"""Take a series off the site without deleting anything.

Written for one specific situation: a source that turned out not to permit
automated collection after its data had already been published. Setting the
series to `status = "unverified"` in config stops the next scrape, but it does
nothing about what is already in the database and on the board.

    python -m tools.retire_series --series indycar,nascar --season 2026
    python -m tools.retire_series --series indycar --season 2026 --dry-run

Soft, and reversible in the ordinary way. Every web query filters on
`retired_at IS NULL`, so a retired event and its sessions vanish from the board,
the calendar feed and the sitemap while staying in the database with their audit
history intact. Bringing them back is the normal scrape:

    python -m scrapers.run --series indycar --season 2026 --allow-unverified

because the event and session upserts both clear `retired_at` on anything they
see again. Nothing here needs undoing by hand.
"""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_SEASON = 2026


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.retire_series", description=__doc__)
    parser.add_argument("--series", required=True, help="series code, or several comma-separated")
    parser.add_argument("--season", type=int, default=DEFAULT_SEASON)
    parser.add_argument("--dry-run", action="store_true", help="count what would be retired")
    return parser


def retire(database_url: str, codes: list[str], season: int, dry_run: bool) -> dict[str, tuple[int, int]]:
    import psycopg

    counts: dict[str, tuple[int, int]] = {}
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        for code in codes:
            cursor.execute("SELECT id FROM series WHERE code = %s", (code,))
            row = cursor.fetchone()
            if row is None:
                raise SystemExit(f"unknown series: {code}")
            series_id = row[0]

            cursor.execute(
                """
                SELECT count(*) FROM events
                 WHERE series_id = %s AND season = %s AND retired_at IS NULL
                """,
                (series_id, season),
            )
            events = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT count(*) FROM sessions s
                  JOIN events e ON e.id = s.event_id
                 WHERE e.series_id = %s AND e.season = %s AND s.retired_at IS NULL
                """,
                (series_id, season),
            )
            sessions = cursor.fetchone()[0]
            counts[code] = (events, sessions)

            if dry_run:
                continue

            # Sessions first: an event with live sessions under it would be a
            # weekend page listing races that are no longer meant to be there.
            cursor.execute(
                """
                UPDATE sessions s
                   SET retired_at = now(), updated_at = now()
                  FROM events e
                 WHERE e.id = s.event_id
                   AND e.series_id = %s AND e.season = %s AND s.retired_at IS NULL
                """,
                (series_id, season),
            )
            cursor.execute(
                """
                UPDATE events SET retired_at = now(), updated_at = now()
                 WHERE series_id = %s AND season = %s AND retired_at IS NULL
                """,
                (series_id, season),
            )
        if not dry_run:
            connection.commit()
    return counts


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    codes = [code.strip() for code in args.series.split(",") if code.strip()]
    counts = retire(database_url, codes, args.season, args.dry_run)

    verb = "would retire" if args.dry_run else "retired"
    for code, (events, sessions) in counts.items():
        print(f"{code}: {verb} {events} events and {sessions} sessions for {args.season}")
    if args.dry_run:
        print("(dry run, nothing written)")
    else:
        print("Reverse with: python -m scrapers.run --series <code> --season "
              f"{args.season} --allow-unverified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
