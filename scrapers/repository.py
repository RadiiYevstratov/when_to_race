"""Persistence boundary.

The pipeline talks to a Repository, never to psycopg directly. That keeps the
whole run testable without a database and makes `--dry-run` a one-line swap.
scrapers/db.py holds the Postgres implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Protocol

from .records import NormalizedEvent
from .sync import ExistingSession, SyncPlan


@dataclass
class AppliedCounts:
    created: int = 0
    updated: int = 0
    retired: int = 0
    revived: int = 0
    changes_logged: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.retired + self.revived


class Repository(Protocol):
    def load_existing_sessions(self, series_code: str, season: int) -> list[ExistingSession]:
        ...

    def start_run(self, series_code: str) -> int:
        ...

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        records_found: int,
        records_changed: int,
        error_message: Optional[str] = None,
    ) -> None:
        ...

    def apply(self, plan: SyncPlan, series_code: str, season: int, run_id: int) -> AppliedCounts:
        ...

    def mark_series_scraped(self, series_code: str, when: datetime) -> None:
        ...

    def record_snapshots(self, run_id: int, snapshots) -> None:
        """Optional. Implementations that do not track snapshots may omit it."""
        ...


@dataclass
class _StoredSession:
    record: ExistingSession
    ics_uid: str


class InMemoryRepository:
    """Reference implementation. Used by the tests and by --dry-run."""

    def __init__(self) -> None:
        self.sessions: dict[tuple[str, int, tuple], _StoredSession] = {}
        self.events: dict[tuple[str, int, str], NormalizedEvent] = {}
        self.changes: list[tuple] = []
        self.runs: list[dict] = []
        self.last_scraped: dict[str, datetime] = {}
        self.snapshots: list[tuple] = []
        self._next_id = 1

    def load_existing_sessions(self, series_code: str, season: int) -> list[ExistingSession]:
        return [
            stored.record
            for (code, year, _), stored in self.sessions.items()
            if code == series_code and year == season
        ]

    def start_run(self, series_code: str) -> int:
        run_id = len(self.runs) + 1
        self.runs.append(
            {
                "id": run_id,
                "series_code": series_code,
                "status": "running",
                "started_at": datetime.now(timezone.utc),
            }
        )
        return run_id

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        records_found: int,
        records_changed: int,
        error_message: Optional[str] = None,
    ) -> None:
        run = self.runs[run_id - 1]
        run.update(
            status=status,
            records_found=records_found,
            records_changed=records_changed,
            error_message=error_message,
            finished_at=datetime.now(timezone.utc),
        )

    def apply(self, plan: SyncPlan, series_code: str, season: int, run_id: int) -> AppliedCounts:
        counts = AppliedCounts()
        now = datetime.now(timezone.utc)

        for event in plan.events:
            self.events[(series_code, season, event.slug)] = event

        for session in plan.creates:
            record = ExistingSession(
                id=self._next_id,
                event_slug=session.event_slug,
                category_code=session.category_code,
                session_type=session.session_type,
                sequence=session.sequence,
                display_name=session.display_name,
                start_utc=session.start_utc,
                end_utc=session.end_utc,
                scheduled_duration_minutes=session.scheduled_duration_minutes,
                time_status=session.time_status,
                start_precision=session.start_precision,
                iana_timezone=session.iana_timezone,
                source_url=session.source_url,
            )
            self._next_id += 1
            self.sessions[(series_code, season, record.key)] = _StoredSession(record, session.ics_uid)
            counts.created += 1

        by_id = {
            stored.record.id: (key, stored)
            for key, stored in self.sessions.items()
            if key[0] == series_code and key[1] == season
        }

        for update in plan.updates:
            entry = by_id.get(update.existing_id)
            if entry is None:
                continue
            key, stored = entry
            for change in update.changes:
                self.changes.append(
                    (update.existing_id, change.field_changed, change.old_value, change.new_value, run_id)
                )
                counts.changes_logged += 1
            record = stored.record
            record.display_name = update.incoming.display_name
            record.start_utc = update.incoming.start_utc
            record.end_utc = update.incoming.end_utc
            record.scheduled_duration_minutes = update.incoming.scheduled_duration_minutes
            record.time_status = update.incoming.time_status
            record.start_precision = update.incoming.start_precision
            record.iana_timezone = update.incoming.iana_timezone
            record.source_url = update.incoming.source_url
            record.retired_at = None
            if update.bumps_ics_sequence:
                record.ics_sequence += 1
            counts.updated += 1

        for item in plan.retire:
            entry = by_id.get(item.id)
            if entry is None:
                continue
            _, stored = entry
            stored.record.retired_at = now
            counts.retired += 1

        for item in plan.revive:
            entry = by_id.get(item.id)
            if entry is None:
                continue
            _, stored = entry
            if stored.record.retired_at is not None:
                stored.record.retired_at = None
                counts.revived += 1

        return counts

    def mark_series_scraped(self, series_code: str, when: datetime) -> None:
        self.last_scraped[series_code] = when

    def record_snapshots(self, run_id: int, snapshots) -> None:
        for snapshot in snapshots:
            self.snapshots.append((run_id, snapshot.url, snapshot.content_hash))
