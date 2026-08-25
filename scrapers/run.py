"""python -m scrapers.run --series f1

Deliberately a plain CLI with no platform coupling: the same command runs under
a systemd timer on a VPS and under a GitHub Actions cron. It reads DATABASE_URL
from the environment and writes nothing but the database and the snapshot
directory.

Exit codes:
  0  every requested series succeeded
  1  at least one series failed
  2  bad invocation (unknown series, unimplemented adapter, missing config)

One dead source never blocks the others: failures are recorded and the loop
continues.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from .config import ConfigError, load_series, load_session_floors, load_venues
from .pipeline import PipelineResult, run_series
from .repository import InMemoryRepository, Repository
from .snapshots import SnapshotStore
from .sources import get_source, registered_adapters

logger = logging.getLogger("scrapers.run")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scrapers.run", description=__doc__)
    parser.add_argument("--series", required=True, help="series code, comma-separated, or 'all'")
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--source", help="override the adapter (e.g. 'fixture')")
    parser.add_argument("--dry-run", action="store_true", help="plan only; never writes")
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="run a series whose source endpoint has not been confirmed by discovery",
    )
    parser.add_argument("--threshold", type=float, default=0.30, help="change guard ratio")
    parser.add_argument("--snapshot-dir", help="where to write raw responses")
    parser.add_argument("--log-level", default="INFO")
    return parser


def resolve_series_codes(requested: str, known: dict) -> list[str]:
    """Expand the --series argument into codes to run.

    "all" means every series that can actually run - those whose source has been
    verified by discovery. A series still awaiting discovery is skipped silently
    rather than counted as a failure, because "all" is what the scheduled job
    calls: if unimplemented series failed the run, the cron would report red on
    every execution and a genuine breakage would be lost in the noise. Asking for
    one by name (--series wrc) still reports the unverified error, which is where
    that message is useful.
    """
    if requested.strip().lower() == "all":
        runnable = [code for code, series in known.items() if series.source.is_verified]
        return sorted(runnable, key=lambda code: known[code].sort_order)
    codes = [code.strip() for code in requested.split(",") if code.strip()]
    unknown = [code for code in codes if code not in known]
    if unknown:
        raise ConfigError(f"unknown series: {', '.join(unknown)}. Known: {', '.join(sorted(known))}")
    return codes


def make_repository(dry_run: bool) -> Repository:
    if dry_run:
        return InMemoryRepository()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ConfigError("DATABASE_URL is not set (use --dry-run to plan without a database)")
    from .db import PostgresRepository  # imported here so --dry-run needs no driver

    return PostgresRepository(database_url)


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )

    try:
        series_registry = load_series()
        venues = load_venues()
        floors = load_session_floors()
        codes = resolve_series_codes(args.series, series_registry)
        repository = make_repository(args.dry_run)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2

    store = SnapshotStore(args.snapshot_dir) if args.snapshot_dir else SnapshotStore()
    results: list[PipelineResult] = []
    failures = 0

    for code in codes:
        series = series_registry[code]
        adapter = args.source or series.source.adapter

        if not args.source and not series.source.is_verified and not args.allow_unverified:
            logger.error(
                "%s: source is unverified. Do discovery first (%s), then set source.status "
                "to 'live' in config/series.toml. Use --allow-unverified to override, or "
                "--source fixture to exercise the pipeline.",
                code,
                series.source.discovery_notes or "docs/sources.md",
            )
            failures += 1
            continue

        try:
            source = get_source(adapter, feed_url=series.source.url) if adapter != "fixture" else get_source(adapter)
        except KeyError:
            logger.error(
                "%s: no adapter %r yet. Registered: %s. This series is still awaiting "
                "discovery; see docs/sources.md.",
                code,
                adapter,
                ", ".join(registered_adapters()),
            )
            failures += 1
            continue
        except TypeError as exc:
            logger.error("%s: adapter %r rejected its arguments: %s", code, adapter, exc)
            failures += 1
            continue

        logger.info("%s: starting (season %s, adapter %s)", code, args.season, adapter)
        result = run_series(
            series,
            source,
            venues,
            repository,
            args.season,
            snapshot_store=store,
            threshold=args.threshold,
            dry_run=args.dry_run,
            session_floors=floors,
        )
        results.append(result)

        if result.ok:
            logger.info(
                "%s: %s sessions found, %s changed%s",
                code,
                result.records_found,
                result.records_changed,
                " (dry run, nothing written)" if args.dry_run else "",
            )
            store.prune(code)
        else:
            failures += 1
            logger.error("%s: %s - %s", code, result.status, result.error_message)

        for issue in result.issues:
            logger.warning("%s: %s", code, issue)

    succeeded = sum(1 for result in results if result.ok)
    logger.info("done: %s of %s series succeeded", succeeded, len(codes))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
