"""Reading the schedule, and remembering what was said about it.

The only module in the package that knows Postgres exists. Selection stays a
pure function of records so a season can be replayed in memory; this is where
those records come from.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Optional, Sequence

from .selection import EventFact, PostRecord, SessionFact


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. The social job reads the same database the "
            "scrapers write to."
        )
    return url


def connect():
    import psycopg  # imported here so selection stays importable without a driver

    return psycopg.connect(database_url())


# --------------------------------------------------------------------------
# the schedule
# --------------------------------------------------------------------------

_EVENTS_SQL = """
select e.id, s.code, s.short_name, e.season, e.slug, e.name,
       v.name, v.city, v.country_code, v.iana_timezone,
       e.starts_at_utc, e.ends_at_utc
from events e
join series s on s.id = e.series_id
join venues v on v.id = e.venue_id
where e.retired_at is null
  and s.is_active
  and e.ends_at_utc >= %(from)s
  and e.starts_at_utc <= %(to)s
order by e.starts_at_utc
"""

_SESSIONS_SQL = """
select x.event_id, x.id, x.session_type, x.display_name, x.starts_at_utc,
       c.code, c.short_name, c.is_headline
from sessions x
join categories c on c.id = x.category_id
where x.retired_at is null
  and x.event_id = any(%(ids)s)
order by x.starts_at_utc, c.sort_order, x.sequence
"""


def load_events(connection, window_from: datetime, window_to: datetime) -> list[EventFact]:
    """Every event overlapping the window, with its sessions attached.

    Two queries rather than one join: a weekend can carry seventeen sessions and
    fanning the event columns out across all of them, then de-duplicating in
    Python, is more code and more rows for no gain.
    """
    with connection.cursor() as cursor:
        cursor.execute(_EVENTS_SQL, {"from": window_from, "to": window_to})
        rows = cursor.fetchall()
        if not rows:
            return []

        events = {
            row[0]: {
                "event_id": row[0],
                "series_code": row[1],
                "series_short_name": row[2],
                "season": row[3],
                "slug": row[4],
                "name": row[5],
                "venue_name": row[6],
                "venue_city": row[7],
                "venue_country": row[8],
                "venue_timezone": row[9],
                "starts_at_utc": row[10],
                "ends_at_utc": row[11],
                "sessions": [],
            }
            for row in rows
        }

        cursor.execute(_SESSIONS_SQL, {"ids": list(events)})
        for event_id, sid, stype, name, starts, ccode, cshort, headline in cursor.fetchall():
            events[event_id]["sessions"].append(
                SessionFact(
                    session_id=sid,
                    session_type=stype,
                    display_name=name,
                    starts_at_utc=starts,
                    category_code=ccode,
                    category_short_name=cshort,
                    is_headline_class=headline,
                )
            )

    return [
        EventFact(**{**data, "sessions": tuple(data["sessions"])})
        for data in events.values()
    ]


# --------------------------------------------------------------------------
# the history
# --------------------------------------------------------------------------


def load_history(connection, since: datetime) -> list[PostRecord]:
    """Recent decisions, for the rules that stop the account repeating itself.

    Skipped days are excluded: staying quiet about an event is not the same as
    having covered it, and counting it would suppress the post it was waiting
    for.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select decided_at, event_id, session_id, series_code, post_kind
            from social_posts
            where decided_at >= %s and outcome in ('published', 'dry_run')
            order by decided_at
            """,
            (since,),
        )
        return [PostRecord(*row) for row in cursor.fetchall()]


def record(
    connection,
    *,
    decided_for: date,
    outcome: str,
    post_kind: Optional[str] = None,
    event_id: Optional[int] = None,
    session_id: Optional[int] = None,
    series_code: Optional[str] = None,
    category_code: Optional[str] = None,
    event_name: Optional[str] = None,
    session_type: Optional[str] = None,
    session_starts_at_utc: Optional[datetime] = None,
    score: Optional[int] = None,
    reasons: Optional[Sequence[str]] = None,
    caption: Optional[str] = None,
    hashtags: Optional[Sequence[str]] = None,
    media_path: Optional[str] = None,
    media_url: Optional[str] = None,
    instagram_post_id: Optional[str] = None,
    error_message: Optional[str] = None,
) -> int:
    """Write the decision down, whatever it was."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into social_posts (
                decided_for, outcome, post_kind, event_id, session_id, series_code,
                category_code, event_name, session_type, session_starts_at_utc,
                score, reasons, caption, hashtags, media_path, media_url,
                instagram_post_id, error_message
            ) values (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s
            ) returning id
            """,
            (
                decided_for, outcome, post_kind, event_id, session_id, series_code,
                category_code, event_name, session_type, session_starts_at_utc,
                score, json.dumps(list(reasons)) if reasons else None,
                caption, list(hashtags) if hashtags else None, media_path, media_url,
                instagram_post_id, error_message,
            ),
        )
        new_id = cursor.fetchone()[0]
    connection.commit()
    return new_id


def venue_slugs(connection, event_ids: Sequence[int]) -> dict[int, str]:
    """The circuit slug for each event, so the card can draw its outline."""
    if not event_ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select e.id, v.slug from events e
            join venues v on v.id = e.venue_id
            where e.id = any(%s)
            """,
            (list(event_ids),),
        )
        return {row[0]: row[1] for row in cursor.fetchall()}


def store_media(
    connection,
    record_id: int,
    data: bytes,
    media_type: str = "image/jpeg",
    media_url: Optional[str] = None,
) -> None:
    """Attach the rendered card to its record.

    The bytes go in the database because Instagram fetches media from a URL and
    the site can serve it from here - no object store, no extra credential. The
    URL is stored next to them so the row says where its own image was served
    from, rather than leaving that to be reconstructed later.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            update social_posts
               set media_bytes = %s, media_type = %s,
                   media_url = coalesce(%s, media_url)
             where id = %s
            """,
            (data, media_type, media_url, record_id),
        )
    connection.commit()


def load_media(connection, record_id: int) -> Optional[tuple[bytes, str]]:
    """The card for a record, for the route that serves it."""
    with connection.cursor() as cursor:
        cursor.execute(
            "select media_bytes, media_type from social_posts where id = %s", (record_id,)
        )
        row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    return bytes(row[0]), row[1]


def recent(connection, limit: int = 20) -> list[dict]:
    """The last few decisions, for the status command and the admin page."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select id, decided_for, decided_at, outcome, post_kind, series_code,
                   event_name, score, instagram_post_id, error_message,
                   media_bytes is not null as has_media
            from social_posts
            order by decided_at desc
            limit %s
            """,
            (limit,),
        )
        columns = [c.name for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def prune_media(connection, days: int = 60) -> int:
    """Drop the bytes of cards old enough that nothing will ask for them."""
    with connection.cursor() as cursor:
        cursor.execute("select prune_social_media(make_interval(days => %s))", (days,))
        pruned = cursor.fetchone()[0]
    connection.commit()
    return pruned


_ACCENT_SQL = """
select coalesce(c.accent_color, s.accent_color)
from series s
left join categories c on c.series_id = s.id and c.code = %(category)s
where s.code = %(series)s
limit 1
"""


def accent_colour(
    connection, series_code: str, category_code: Optional[str] = None
) -> Optional[tuple[int, int, int]]:
    """The colour this class is drawn in, resolved exactly as the site does it.

    `coalesce(category, series)` is the same rule the board uses: a headline
    class has no colour of its own because its series colour is already correct,
    and a support class overrides it. Reading it from the database rather than
    hard-coding a table here means a colour changed on the site changes on the
    card too, without a second place to forget.
    """
    with connection.cursor() as cursor:
        cursor.execute(_ACCENT_SQL, {"series": series_code, "category": category_code})
        row = cursor.fetchone()

    if not row or not row[0]:
        return None
    text = row[0].lstrip("#")
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def load_credential(connection, name: str) -> Optional[tuple[str, datetime]]:
    """The stored secret and the moment it was issued, if there is one."""
    with connection.cursor() as cursor:
        cursor.execute(
            "select value, issued_at from social_credentials where name = %s", (name,)
        )
        row = cursor.fetchone()
    return (row[0], row[1]) if row else None


def store_credential(
    connection, name: str, value: str, issued_at: Optional[datetime] = None
) -> None:
    """Write the current secret back.

    Called after every refresh. The token Meta returns is a new string, and a
    job that refreshes without saving has done nothing at all.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into social_credentials (name, value, issued_at, updated_at)
            values (%s, %s, coalesce(%s, now()), now())
            on conflict (name) do update
               set value = excluded.value,
                   issued_at = excluded.issued_at,
                   updated_at = now()
            """,
            (name, value, issued_at),
        )
    connection.commit()


def already_published(connection, day: date) -> bool:
    """Has a live post already gone out for this local day?"""
    with connection.cursor() as cursor:
        cursor.execute(
            "select 1 from social_posts where decided_for = %s and outcome = 'published'",
            (day,),
        )
        return cursor.fetchone() is not None
