"""Seed the reference tables from config/.

Idempotent: run it after every migration and after every config change.
    python -m db.seed
    python -m db.seed --dry-run

Reference data lives in config/*.toml rather than in SQL so that adding a
championship stays a one-file change.
"""

from __future__ import annotations

import argparse
import os
import sys

from scrapers.config import ConfigError, load_series, load_venues


def seed(database_url: str, dry_run: bool = False) -> dict[str, int]:
    series_registry = load_series()
    venues = load_venues()
    counts = {"series": 0, "categories": 0, "venues": 0}

    if dry_run:
        counts["series"] = len(series_registry)
        counts["categories"] = sum(len(item.categories) for item in series_registry.values())
        counts["venues"] = len(venues)
        return counts

    import psycopg

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            for venue in venues.values():
                cursor.execute(
                    """
                    INSERT INTO venues (slug, name, country_code, city, iana_timezone, latitude, longitude)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (slug) DO UPDATE
                       SET name = EXCLUDED.name,
                           country_code = EXCLUDED.country_code,
                           city = EXCLUDED.city,
                           iana_timezone = EXCLUDED.iana_timezone,
                           latitude = EXCLUDED.latitude,
                           longitude = EXCLUDED.longitude,
                           updated_at = now()
                    """,
                    (
                        venue.slug,
                        venue.name,
                        venue.country_code,
                        venue.city,
                        venue.iana_timezone,
                        venue.latitude,
                        venue.longitude,
                    ),
                )
                counts["venues"] += 1

            for series in series_registry.values():
                cursor.execute(
                    """
                    INSERT INTO series (code, name, short_name, accent_color, sort_order)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (code) DO UPDATE
                       SET name = EXCLUDED.name,
                           short_name = EXCLUDED.short_name,
                           accent_color = EXCLUDED.accent_color,
                           sort_order = EXCLUDED.sort_order,
                           updated_at = now()
                    RETURNING id
                    """,
                    (series.code, series.name, series.short_name, series.accent_color, series.sort_order),
                )
                series_id = cursor.fetchone()[0]
                counts["series"] += 1

                for category in series.categories:
                    cursor.execute(
                        """
                        INSERT INTO categories
                            (series_id, code, name, short_name, is_headline, sort_order,
                             accent_color, accent_colors)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (series_id, code) DO UPDATE
                           SET name = EXCLUDED.name,
                               short_name = EXCLUDED.short_name,
                               is_headline = EXCLUDED.is_headline,
                               sort_order = EXCLUDED.sort_order,
                               accent_color = EXCLUDED.accent_color,
                               accent_colors = EXCLUDED.accent_colors,
                               updated_at = now()
                        """,
                        (
                            series_id,
                            category.code,
                            category.name,
                            category.short_name,
                            category.is_headline,
                            category.sort_order,
                            category.accent_color,
                            # NULL rather than an empty string: the check
                            # constraint wants a list or nothing.
                            ",".join(category.accent_colors) or None,
                        ),
                    )
                    counts["categories"] += 1
        connection.commit()

    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m db.seed", description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate config without writing")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args(argv)

    if not args.dry_run and not args.database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    try:
        counts = seed(args.database_url or "", dry_run=args.dry_run)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    verb = "would seed" if args.dry_run else "seeded"
    print(f"{verb} {counts['series']} series, {counts['categories']} categories, {counts['venues']} venues")
    return 0


if __name__ == "__main__":
    sys.exit(main())
