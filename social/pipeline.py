"""One day's run, start to finish.

    decide -> brief -> card -> caption -> validate -> store -> publish -> record

Two properties matter more than the steps. First, every exit writes a row: a
published post, a dry run, a quiet day and a failure all end in `social_posts`,
so the log answers what happened on any date rather than only when things went
well. Second, publishing is the last thing that happens and it happens once -
the media is stored and the caption validated before Instagram is contacted at
all, and a unique index on the day makes a double publish impossible even if
the job is run twice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from . import brief as brief_module
from . import captions, instagram, policy
from .cards import CardContent, render, to_jpeg
from .repository import (
    accent_colour,
    already_published,
    load_events,
    load_history,
    record,
    store_media,
    venue_slugs,
)
from .selection import Decision, decide

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    outcome: str                       # published | dry_run | skipped | failed
    decision: Optional[Decision] = None
    brief: Optional[brief_module.Brief] = None
    caption: Optional[str] = None
    caption_source: Optional[str] = None
    media_bytes: Optional[bytes] = None
    media_url: Optional[str] = None
    instagram_post_id: Optional[str] = None
    error: Optional[str] = None
    record_id: Optional[int] = None

    @property
    def ok(self) -> bool:
        return self.outcome in ("published", "dry_run", "skipped")


def run(
    connection,
    now: datetime,
    *,
    dry_run: bool = True,
    site_url: str = "https://ontrackapp.me",
    timezone_name: str = policy.POSTING_TIMEZONE,
    force: bool = False,
) -> RunResult:
    """Decide and, unless this is a dry run, publish."""
    from zoneinfo import ZoneInfo

    today = now.astimezone(ZoneInfo(timezone_name)).date()

    # --- has today already gone out? --------------------------------------
    #
    # Checked before anything is generated, so a re-run costs nothing and
    # cannot produce a second post. The unique index is the real guarantee;
    # this is the polite version of it.
    if not dry_run and not force and already_published(connection, today):
        logger.info("a post has already been published for %s", today)
        return RunResult("skipped", error=None)

    # --- choose ------------------------------------------------------------
    try:
        events = load_events(connection, now - timedelta(days=2), now + timedelta(days=21))
        history = load_history(connection, now - timedelta(days=30))
    except Exception as error:  # noqa: BLE001
        logger.exception("could not read the schedule")
        return _fail(connection, today, f"schedule unavailable: {error}")

    decision = decide(events, history, now, timezone_name)

    if not decision.should_post or decision.chosen is None:
        logger.info("no post today: %s", decision.reason)
        record_id = record(
            connection, decided_for=today, outcome="skipped", error_message=decision.reason
        )
        return RunResult("skipped", decision=decision, record_id=record_id)

    candidate = decision.chosen

    # --- assemble the facts -------------------------------------------------
    try:
        slugs = venue_slugs(connection, [e.event_id for e in candidate.events])
        # The class's own colour, not the championship's: the site paints an F2
        # session blue and an F3 session orange inside the same Grand Prix
        # weekend, and a card that ignored that would not look like the product.
        accent = accent_colour(
            connection,
            candidate.events[0].series_code,
            candidate.session.category_code if candidate.session else None,
        )
        the_brief = brief_module.build(candidate, now, timezone_name, accent)
        event = candidate.events[0] if len(candidate.events) == 1 else None
        if event is not None:
            the_brief = _with_venue(the_brief, slugs.get(event.event_id))
    except Exception as error:  # noqa: BLE001
        logger.exception("could not build the brief")
        return _fail(connection, today, f"brief failed: {error}", decision)

    # --- draw --------------------------------------------------------------
    try:
        media = to_jpeg(render(_card_for(the_brief)))
        _check_media(media)
    except Exception as error:  # noqa: BLE001
        logger.exception("could not draw the card")
        return _fail(connection, today, f"media failed: {error}", decision, the_brief)

    # --- write and check ---------------------------------------------------
    try:
        caption = captions.generate(the_brief)
    except Exception as error:  # noqa: BLE001
        logger.exception("could not write a caption")
        return _fail(connection, today, f"caption failed: {error}", decision, the_brief)

    result = RunResult(
        "dry_run" if dry_run else "published",
        decision=decision,
        brief=the_brief,
        caption=caption.text,
        caption_source=caption.source,
        media_bytes=media,
    )

    # --- record before publishing -----------------------------------------
    #
    # The row exists, and the card is served from it, before Instagram is asked
    # to fetch anything. Doing it the other way round would mean publishing
    # something the site cannot show.
    record_id = record(
        connection,
        decided_for=today,
        outcome="dry_run" if dry_run else "failed",  # promoted on success
        post_kind=candidate.kind,
        event_id=the_brief.event_id,
        session_id=the_brief.session_id,
        series_code=the_brief.series_code,
        event_name=the_brief.event_name,
        session_type=the_brief.headline.session_type if the_brief.headline else None,
        session_starts_at_utc=None,
        score=candidate.score,
        reasons=candidate.reasons,
        caption=caption.text,
        hashtags=caption.tags,
        error_message=None if dry_run else "publishing not attempted yet",
    )
    result.record_id = record_id

    # The URL is derived from the row's own id, so it cannot point anywhere else,
    # and it is written down beside the bytes it serves.
    media_url = f"{site_url.rstrip('/')}/api/social/card/{record_id}.jpg"
    store_media(connection, record_id, media, media_url=media_url)
    result.media_url = media_url

    if dry_run:
        logger.info("dry run complete; nothing was published")
        return result

    # --- publish -----------------------------------------------------------
    #
    # The token is resolved here rather than inside publish() so that a refresh
    # happens once per run, on the way to a real post, and never during a dry
    # run that was not supposed to touch Meta at all.
    try:
        credentials = instagram.current(connection)
        post_id = instagram.publish(media_url, caption.text, credentials)
    except instagram.NotConfigured as error:
        logger.warning("not publishing: %s", error)
        _update(connection, record_id, outcome="dry_run", error=str(error))
        result.outcome = "dry_run"
        result.error = str(error)
        return result
    except Exception as error:  # noqa: BLE001
        logger.exception("publishing failed")
        _update(connection, record_id, outcome="failed", error=str(error))
        result.outcome = "failed"
        result.error = str(error)
        return result

    _update(
        connection,
        record_id,
        outcome="published",
        instagram_post_id=post_id,
        error=None,
        published=True,
    )
    result.instagram_post_id = post_id
    logger.info("published %s for %s", post_id, today)
    return result


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _with_venue(the_brief: brief_module.Brief, slug: Optional[str]) -> brief_module.Brief:
    from dataclasses import replace

    return replace(the_brief, venue_slug=slug)


# ON TRACK's own ink rather than any championship's colour, for the one post
# kind that belongs to none of them.
WEEK_AHEAD_ACCENT = (238, 240, 241)

_KICKER = {
    "today": "Today",
    "tomorrow": "Tomorrow",
    "weekend_preview": "This weekend",
    "week_ahead": "The week ahead",
}


def _card_for(the_brief: brief_module.Brief) -> CardContent:
    """The card, in the reader's frame.

    The kicker already says "today" or "tomorrow" to someone in central Europe,
    so the date and the start time have to be theirs, or the card contradicts
    itself. The circuit's own clock gets a row of its own - labelled with the
    city, so there is no question which is which - and only when it differs. A
    Monza race at 15:00 for a reader who is also at 15:00 does not need telling
    twice.
    """
    head = the_brief.headline
    fields: list[tuple[str, str]] = []

    if head is not None:
        fields.append(("date", f"{head.viewer_weekday} {head.viewer_date_label}"))
        fields.append(("start", f"{head.viewer_time} {head.viewer_zone_label}"))
        if head.circuit_time != head.viewer_time:
            label = f"at {the_brief.city}" if the_brief.city else "at the circuit"
            fields.append((label, head.circuit_stamp))

    if the_brief.place:
        fields.append(("where", the_brief.place))

    return CardContent(
        kicker=_KICKER.get(the_brief.kind, "On track"),
        # A week-ahead post covers several championships. Labelling it with
        # whichever one scored highest - and painting it that series' colour -
        # told the feed it was a Formula 1 post.
        series="Motorsport" if the_brief.kind == "week_ahead" else the_brief.series,
        title=the_brief.event_name,
        subtitle=f"{head.category} {head.name}" if head else None,
        accent=WEEK_AHEAD_ACCENT if the_brief.kind == "week_ahead" else the_brief.accent,
        fields=tuple(fields),
        venue_slug=the_brief.venue_slug,
        lines=the_brief.other_events or _session_lines(the_brief),
        # The week-ahead list needs no heading: the kicker already says
        # "The week ahead" directly above it.
        lines_label=(
            None
            if the_brief.other_events
            else (f"Also on {head.viewer_weekday}" if head else None)
        ),
    )


def _session_lines(the_brief: brief_module.Brief) -> tuple[str, ...]:
    """The rest of the day, for a card whose circuit has no traced outline.

    Most ovals do not have one, and without it the middle of the card is simply
    empty. Filling it with the day's running order is better than filling it with
    decoration: it is the thing the account exists to publish.
    """
    return tuple(
        f"{line.viewer_time}  {line.category} {line.name}"
        for line in the_brief.sessions[:5]
    )


def _check_media(data: bytes) -> None:
    """The card has to be something Instagram will actually take."""
    import io

    from PIL import Image

    if not data:
        raise ValueError("the card is empty")
    if len(data) > 8 * 1024 * 1024:
        raise ValueError(f"the card is {len(data) // 1024}KB; Instagram's limit is 8MB")

    image = Image.open(io.BytesIO(data))
    if image.format != "JPEG":
        raise ValueError(f"the card is {image.format}; Instagram accepts JPEG only")

    width, height = image.size
    if not 320 <= width <= 1440:
        raise ValueError(f"width {width} is outside Instagram's 320-1440 range")

    ratio = width / height
    if not 0.8 - 1e-6 <= ratio <= 1.91 + 1e-6:
        raise ValueError(f"aspect ratio {ratio:.2f} is outside Instagram's 4:5 to 1.91:1")


def _fail(
    connection,
    today: date,
    message: str,
    decision: Optional[Decision] = None,
    the_brief: Optional[brief_module.Brief] = None,
) -> RunResult:
    try:
        record_id = record(
            connection, decided_for=today, outcome="failed", error_message=message
        )
    except Exception:  # noqa: BLE001 - a failure to log a failure must not raise
        logger.exception("could not even record the failure")
        record_id = None
    return RunResult("failed", decision=decision, brief=the_brief, error=message, record_id=record_id)


def _update(connection, record_id: int, *, published: bool = False, **fields) -> None:
    """Change an existing row.

    `published_at` is set only on a real publish. Stamping it on every update
    would put a publication time on rows that never went out, which is exactly
    the kind of quietly wrong log entry this table exists to avoid.
    """
    sets, values = [], []
    for column, value in fields.items():
        column = {"error": "error_message"}.get(column, column)
        sets.append(f"{column} = %s")
        values.append(value)
    if published:
        sets.append("published_at = now()")
    if not sets:
        return
    values.append(record_id)
    with connection.cursor() as cursor:
        cursor.execute(
            f"update social_posts set {', '.join(sets)} where id = %s", values
        )
    connection.commit()
