"""Pipeline orchestration.

fetch -> snapshot -> parse -> normalize -> validate -> upsert

Every stage's output is inspectable, and a failure at any stage leaves the
database exactly as it was.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .config import SeriesConfig, VenueConfig, load_session_floors
from .http import FetchError, HttpClient
from .normalize import NormalizeError, normalize
from .records import NormalizedEvent
from .repository import AppliedCounts, Repository
from .snapshots import SnapshotRecord, SnapshotStore
from .sources.base import FetchedDocument, Source
from .sources.fixture import FIXTURE_SCHEME, read_fixture
from .sync import GuardTripped, SyncPlan, apply_guards, diff_sessions
from .validate import ValidationError, ValidationIssue, raise_for_errors, validate

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    series_code: str
    season: int
    status: str  # success | failed | aborted_guard
    records_found: int = 0
    records_changed: int = 0
    issues: list[ValidationIssue] = field(default_factory=list)
    snapshots: list[SnapshotRecord] = field(default_factory=list)
    events: list[NormalizedEvent] = field(default_factory=list)
    plan: Optional[SyncPlan] = None
    counts: Optional[AppliedCounts] = None
    error_message: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "success"


def fetch_documents(
    source: Source,
    season: int,
    *,
    client: Optional[HttpClient] = None,
    snapshot_store: Optional[SnapshotStore] = None,
    series_code: str = "",
    run_started: Optional[datetime] = None,
) -> tuple[list[FetchedDocument], list[SnapshotRecord]]:
    """Fetch every URL the source needs and snapshot the raw bodies first."""
    documents: list[FetchedDocument] = []
    records: list[SnapshotRecord] = []
    started = run_started or datetime.now(timezone.utc)

    # Most sources know their URLs up front. Some (e.g. an API that lists rounds
    # and then serves sessions per round) must fetch an index first to know the
    # rest. Such a source implements resolve_urls(season, client) and gets the
    # polite client to do that discovery fetch; every returned URL is then
    # fetched and snapshotted here exactly as a static list would be.
    resolver = getattr(source, "resolve_urls", None)
    if resolver is not None:
        if client is None:
            client = HttpClient()
        source_urls = resolver(season, client)
    else:
        source_urls = source.urls(season)

    for url in source_urls:
        if url.startswith(FIXTURE_SCHEME):
            body = read_fixture(url)
            content_type = "text/calendar"
        else:
            if client is None:
                client = HttpClient()
            response = client.get(url)
            body = response.body
            content_type = response.content_type

        if snapshot_store is not None:
            records.append(
                snapshot_store.write(series_code or source.series_code, started, url, body, content_type)
            )
        documents.append(FetchedDocument(url=url, body=body, content_type=content_type))

    return documents, records


def run_series(
    series: SeriesConfig,
    source: Source,
    venues: dict[str, VenueConfig],
    repository: Repository,
    season: int,
    *,
    client: Optional[HttpClient] = None,
    snapshot_store: Optional[SnapshotStore] = None,
    now: Optional[datetime] = None,
    threshold: float = 0.30,
    dry_run: bool = False,
    session_floors: Optional[dict[str, int]] = None,
) -> PipelineResult:
    moment = now or datetime.now(timezone.utc)
    result = PipelineResult(series_code=series.code, season=season, status="failed")
    run_id = repository.start_run(series.code)

    try:
        documents, snapshots = fetch_documents(
            source,
            season,
            client=client,
            snapshot_store=snapshot_store,
            series_code=series.code,
            run_started=moment,
        )
        result.snapshots = snapshots

        recorder = getattr(repository, "record_snapshots", None)
        if recorder is not None and snapshots:
            recorder(run_id, snapshots)

        parsed = source.parse(documents, series, venues, season)
        result.records_found = len(parsed)

        events = normalize(parsed, series, venues, detail_level=getattr(source, "detail_level", "full"))
        result.events = events

        floors = session_floors if session_floors is not None else load_session_floors()
        issues = validate(events, series, venues, min_sessions_per_event=floors.get(series.code, 1))
        result.issues = issues
        raise_for_errors(issues)

        existing = repository.load_existing_sessions(series.code, season)
        plan = diff_sessions(existing, events)
        result.plan = plan

        apply_guards(plan, existing, records_found=result.records_found, now=moment, threshold=threshold)

        if dry_run:
            result.status = "success"
            result.records_changed = plan.records_changed
            repository.finish_run(
                run_id,
                status="success",
                records_found=result.records_found,
                records_changed=plan.records_changed,
            )
            return result

        counts = repository.apply(plan, series.code, season, run_id)
        result.counts = counts
        result.records_changed = counts.total
        result.status = "success"
        repository.finish_run(
            run_id,
            status="success",
            records_found=result.records_found,
            records_changed=counts.total,
        )
        repository.mark_series_scraped(series.code, moment)

    except GuardTripped as exc:
        result.status = "aborted_guard"
        result.error_message = str(exc)
        logger.error("%s: guard tripped: %s", series.code, exc)
        repository.finish_run(
            run_id,
            status="aborted_guard",
            records_found=result.records_found,
            records_changed=0,
            error_message=str(exc),
        )
    except (FetchError, NormalizeError, ValidationError, FileNotFoundError, ValueError) as exc:
        result.status = "failed"
        result.error_message = str(exc)
        logger.error("%s: run failed: %s", series.code, exc)
        repository.finish_run(
            run_id,
            status="failed",
            records_found=result.records_found,
            records_changed=0,
            error_message=str(exc),
        )

    return result
