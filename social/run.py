"""What would the account post, and when?

    python -m social.run --date 2026-09-22      one day, explained
    python -m social.run --replay 2026-09-17 2026-12-06

Selection only. Nothing here draws an image, writes a caption or talks to
Instagram - those arrive in later steps behind their own flags. The point of
this stage is to see the cadence the policy produces across a real season before
any of it is built, because a scoring rule that reads sensibly in isolation can
still produce an account that posts four times in a week about one Grand Prix.

Replay runs entirely in memory against the real calendar: it keeps its own
history as it walks the days, so the novelty rules behave exactly as they would
in production without writing a row.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import policy
from .repository import connect, load_events, load_history
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m social.run", description=__doc__)
    parser.add_argument("--date", help="explain one day (YYYY-MM-DD), default today")
    parser.add_argument("--replay", nargs=2, metavar=("FROM", "TO"), help="walk a date range")
    parser.add_argument("--verbose", action="store_true", help="explain every day of a replay")
    parser.add_argument("--timezone", default=policy.POSTING_TIMEZONE)
    args = parser.parse_args(argv)

    with connect() as connection:
        if args.replay:
            start = date.fromisoformat(args.replay[0])
            end = date.fromisoformat(args.replay[1])
            replay(connection, start, end, args.timezone, args.verbose)
            return 0

        day = date.fromisoformat(args.date) if args.date else date.today()
        now = decision_time(day, args.timezone)
        events = load_events(connection, now - timedelta(days=2), now + timedelta(days=20))
        history = load_history(connection, now - timedelta(days=30))
        explain(day, decide(events, history, now, args.timezone), args.timezone)
    return 0


if __name__ == "__main__":
    sys.exit(main())
