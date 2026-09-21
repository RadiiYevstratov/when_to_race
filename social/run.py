"""The daily Instagram job, and the tools for looking at what it decides.

    python -m social.run                        today: build everything, publish nothing
    python -m social.run --publish              today: build everything and post it
    python -m social.run --date 2026-09-22      explain one day's choice
    python -m social.run --replay FROM TO       walk a date range, choosing as it goes
    python -m social.run --status               recent decisions and token health
    python -m social.run --prune                drop old card images

Publishing is opt-in. Every other mode stops before Instagram, which means the
whole pipeline - selection, card, caption, validation - can be exercised against
the real calendar with no credentials and no risk of posting.

Replay runs entirely in memory: it keeps its own history as it walks the days,
so the novelty rules behave exactly as in production without writing a row. It
is how the cadence was tuned, and how a policy change is checked before it ships.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import instagram, policy
from .pipeline import run as run_pipeline
from .repository import (
    connect,
    decided_today,
    load_events,
    load_history,
    prune_media,
    recent,
)
from .selection import Candidate, Decision, PostRecord, decide

# Windows consoles still default to a codepage that cannot hold an en dash, and
# a UnicodeEncodeError while printing a schedule would be a silly way to fail.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def decision_time(day: date, timezone: str = policy.POSTING_TIMEZONE) -> datetime:
    """Noon in the posting timezone, as an absolute instant.

    Never the server's noon: the runner is a GitHub Actions machine in UTC and
    the audience is in Europe. Deriving the instant from a named zone also keeps
    the hour steady across daylight saving, which a fixed UTC offset would not.
    """
    return datetime.combine(day, time(policy.POSTING_HOUR), ZoneInfo(timezone))


def _describe(candidate: Candidate) -> str:
    if candidate.kind == "week_ahead":
        names = ", ".join(e.series_short_name for e in candidate.events[:4])
        return f"week ahead — {names}"
    event = candidate.events[0]
    if candidate.session is None:
        return f"{event.series_short_name} — {event.name}"
    return (
        f"{event.series_short_name} — {event.name} — "
        f"{candidate.session.category_short_name} {candidate.session.display_name}"
    )


def explain(day: date, decision: Decision, timezone: str) -> None:
    print(f"\n=== {day:%A %d %B %Y} · 12:00 {timezone} ===")
    if not decision.should_post:
        print(f"  NO POST — {decision.reason}")
        for candidate in decision.runners_up:
            print(f"    considered: {_describe(candidate):<58} {candidate.score:>4}")
        return

    chosen = decision.chosen
    assert chosen is not None
    print(f"  POST — {chosen.kind} · score {chosen.score}")
    print(f"    {_describe(chosen)}")
    if chosen.session is not None:
        event = chosen.events[0]
        local = chosen.session.starts_at_utc.astimezone(ZoneInfo(event.venue_timezone))
        mine = chosen.session.starts_at_utc.astimezone(ZoneInfo(timezone))
        where = f"{event.venue_name}, {event.venue_country}"
        print(f"    {local:%a %d %b %H:%M} at the circuit · {mine:%H:%M} yours · {where}")
    print("    scoring:")
    for reason in chosen.reasons:
        print(f"      {reason}")
    if decision.runners_up:
        print("    beat:")
        for candidate in decision.runners_up:
            print(f"      {_describe(candidate):<58} {candidate.score:>4}")


def replay(connection, start: date, end: date, timezone: str, verbose: bool) -> None:
    """Walk the calendar day by day, keeping history as we go."""
    window_from = decision_time(start, timezone) - timedelta(days=2)
    window_to = decision_time(end, timezone) + timedelta(days=20)
    events = load_events(connection, window_from, window_to)
    print(f"loaded {len(events)} events between {start} and {end}")

    history: list[PostRecord] = []
    kinds: Counter[str] = Counter()
    posts = 0
    day = start

    while day <= end:
        now = decision_time(day, timezone)
        decision = decide(events, history, now, timezone)

        if verbose:
            explain(day, decision, timezone)

        if decision.should_post and decision.chosen is not None:
            chosen = decision.chosen
            posts += 1
            kinds[chosen.kind] += 1
            event = chosen.events[0] if len(chosen.events) == 1 else None
            history.append(
                PostRecord(
                    decided_at=now,
                    event_id=event.event_id if event else None,
                    session_id=chosen.session.session_id if chosen.session else None,
                    series_code=event.series_code if event else None,
                    post_kind=chosen.kind,
                )
            )
            if not verbose:
                print(f"  {day:%a %d %b}  {chosen.kind:<16} {_describe(chosen):<58} {chosen.score:>4}")
        elif not verbose:
            print(f"  {day:%a %d %b}  {'—':<16}")

        day += timedelta(days=1)

    total_days = (end - start).days + 1
    print(f"\n{posts} posts over {total_days} days ({100 * posts // total_days}% of days)")
    print("by kind: " + ", ".join(f"{k}={v}" for k, v in kinds.most_common()))
    weeks = max(1, total_days / 7)
    print(f"average: {posts / weeks:.1f} posts per week")


def show_run(result, day: date) -> None:
    """Print what the run did, in the shape the brief asked for."""
    print(f"\n=== {day:%A %d %B %Y} · {policy.POSTING_HOUR}:00 {policy.POSTING_TIMEZONE} ===")
    print(f"  outcome: {result.outcome.upper()}")

    if result.outcome == "skipped":
        reason = result.decision.reason if result.decision else (result.error or "")
        print(f"  no post today — {reason}")
        if result.decision:
            for candidate in result.decision.runners_up:
                print(f"    considered: {_describe(candidate):<54} {candidate.score:>4}")
        return

    if result.outcome == "failed":
        print(f"  error: {result.error}")
        return

    the_brief = result.brief
    if the_brief is None:
        return

    print(f"  kind: {result.decision.chosen.kind}   score: {result.decision.chosen.score}")
    print(f"  event: {the_brief.series} — {the_brief.event_name}")
    if the_brief.headline:
        h = the_brief.headline
        print(f"  session: {h.category} {h.name}")
        print(f"  when (reader): {h.viewer_weekday} {h.viewer_date_label}, {h.viewer_time} {h.viewer_zone_label}")
        print(f"  when (circuit): {h.circuit_weekday} {h.circuit_date_label}, {h.circuit_time} local")
    if the_brief.place:
        print(f"  where: {the_brief.place}")

    size = len(result.media_bytes or b"") / 1024
    print(f"\n  media: {size:.0f} KB JPEG 1080x1350")
    print(f"  url:   {result.media_url}")
    print(f"  caption ({result.caption_source}):")
    for line in (result.caption or "").splitlines():
        print(f"    {line}")

    print("\n  checks: event ✓  date ✓  time ✓  caption ✓  media ✓")
    if result.instagram_post_id:
        print(f"  published: {result.instagram_post_id}")
    else:
        print("  publishing: SKIPPED — dry run")


def show_status(connection) -> bool:
    """Print the token's health and the recent decisions. False if it needs a human.

    The return value is what turns this into an alert. The workflow runs it after
    every post, and a failed scheduled run is something GitHub emails the owner
    about - so a token Meta rejects, or one within two weeks of expiring because
    refreshes keep failing, becomes an email rather than an account that quietly
    stopped posting. Not being configured yet is the expected state before setup,
    so that is not a failure.
    """
    healthy = True

    # Read the stored token rather than the environment: after the first run
    # they differ, and the stored one is what tomorrow's post will use.
    try:
        creds = instagram.current(connection, refresh=False)
        print("instagram:", instagram.token_health(creds))
        if creds.is_stale:
            healthy = False
    except instagram.NotConfigured as error:
        print(f"instagram: not configured - {error}")
    else:
        # Ask Meta who the token belongs to. It is the only way to prove the
        # setup works short of posting, and it catches the mistakes that matter:
        # an expired token, the wrong account, a personal rather than a
        # professional one.
        try:
            me = instagram.whoami(creds)
            kind = (me.get("account_type") or "").upper()
            print(f"account:   @{me.get('username')} ({kind or 'type unknown'}), id {me.get('user_id')}")
            if kind and kind not in ("BUSINESS", "MEDIA_CREATOR"):
                print("           WARNING: only Business and Creator accounts can publish")
        except instagram.InstagramError as error:
            print(f"account:   TOKEN REJECTED - {error}")
            healthy = False
    print()
    rows = recent(connection, 15)
    if not rows:
        print("no decisions recorded yet")
        return healthy
    print(f"{'day':<12}{'outcome':<11}{'kind':<17}{'what':<40}{'post'}")
    print("-" * 92)
    for row in rows:
        what = f"{row['series_code'] or ''} {row['event_name'] or ''}".strip() or (
            (row["error_message"] or "")[:38]
        )
        print(
            f"{str(row['decided_for']):<12}{row['outcome']:<11}"
            f"{(row['post_kind'] or '—'):<17}{what[:38]:<40}"
            f"{row['instagram_post_id'] or ''}"
        )
    return healthy


def within_posting_window(now: datetime, timezone: str) -> bool:
    """Is it the afternoon where the audience is?

    The first version tested for the noon hour exactly, on the assumption that
    GitHub's cron runs about on time. It does not: this repository's scheduled
    jobs start one to three hours late, and an exact-hour test would have
    skipped every firing and never posted at all.

    So the window is noon until the cutoff, the workflow fires several times
    across it, and `decided_today` makes the first firing that gets through the
    one that decides - the rest see the day is settled and stop. Daylight saving
    needs no special case: the window is in local time, and the firings are
    spread wide enough to land in it in either season.
    """
    hour = now.astimezone(ZoneInfo(timezone)).hour
    return policy.POSTING_HOUR <= hour < policy.POSTING_CUTOFF_HOUR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m social.run", description=__doc__)
    parser.add_argument("--date", help="explain one day (YYYY-MM-DD)")
    parser.add_argument("--replay", nargs=2, metavar=("FROM", "TO"), help="walk a date range")
    parser.add_argument("--verbose", action="store_true", help="explain every day of a replay")
    parser.add_argument("--publish", action="store_true", help="actually post to Instagram")
    parser.add_argument("--status", action="store_true", help="recent decisions and token health")
    parser.add_argument("--prune", type=int, nargs="?", const=60, metavar="DAYS",
                        help="drop card images older than DAYS (default 60)")
    parser.add_argument("--force", action="store_true",
                        help="publish even if a post already went out today")
    parser.add_argument("--now", help="pretend it is this instant (ISO 8601), for testing")
    parser.add_argument("--check-hour", action="store_true",
                        help="for the cron: act only in the afternoon window, once per day")
    parser.add_argument("--timezone", default=policy.POSTING_TIMEZONE)
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL", "https://ontrackapp.me"))
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )

    with connect() as connection:
        if args.status:
            return 0 if show_status(connection) else 1

        if args.prune is not None:
            print(f"pruned {prune_media(connection, args.prune)} card image(s)")
            return 0

        if args.replay:
            replay(
                connection,
                date.fromisoformat(args.replay[0]),
                date.fromisoformat(args.replay[1]),
                args.timezone,
                args.verbose,
            )
            return 0

        # --- explain one day, without building anything -------------------
        if args.date and not args.publish:
            day = date.fromisoformat(args.date)
            now = decision_time(day, args.timezone)
            events = load_events(connection, now - timedelta(days=2), now + timedelta(days=20))
            history = load_history(connection, now - timedelta(days=30))
            explain(day, decide(events, history, now, args.timezone), args.timezone)
            return 0

        # --- the daily run ------------------------------------------------
        now = (
            datetime.fromisoformat(args.now)
            if args.now
            else datetime.now(tz=ZoneInfo(args.timezone))
        )
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo(args.timezone))

        if args.check_hour:
            local = now.astimezone(ZoneInfo(args.timezone))
            if not within_posting_window(now, args.timezone):
                print(f"{local:%H:%M} {args.timezone} is outside the posting window; nothing to do")
                return 0
            settled = decided_today(connection, local.date())
            if settled and not args.force:
                print(f"{local:%Y-%m-%d} is already settled ({settled}); nothing to do")
                return 0

        result = run_pipeline(
            connection,
            now,
            dry_run=not args.publish,
            site_url=args.site_url,
            timezone_name=args.timezone,
            force=args.force,
        )
        show_run(result, now.astimezone(ZoneInfo(args.timezone)).date())
        return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
