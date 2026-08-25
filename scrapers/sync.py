"""Turns "what we have" plus "what we just scraped" into a plan.

Kept deliberately free of any database access so the reliability rules in the
brief are unit-testable: an empty response and a wildly-different response must
both abort without mutating anything, and running the same scrape twice must
produce zero changes.

scrapers/db.py executes a plan. This module decides what the plan is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from .records import NormalizedEvent, NormalizedSession

# Fields compared between an existing row and an incoming record. Anything not
# in this list (ids, timestamps, bookkeeping) never counts as a change.
TRACKED_SESSION_FIELDS = (
    "display_name",
    "start_utc",
    "end_utc",
    "scheduled_duration_minutes",
    "time_status",
    "start_precision",
    "status",
    "iana_timezone",
    "source_url",
)

# Only these fields are worth an audit row and an ics_sequence bump. A tweak to
# a source URL should not push a notification to every subscribed calendar.
NOTIFIABLE_FIELDS = ("start_utc", "end_utc", "status", "time_status", "display_name")


class GuardTripped(Exception):
    """Raised when a run would change more than the threshold allows."""

    def __init__(self, message: str, *, ratio: float = 0.0, affected: int = 0, baseline: int = 0):
        super().__init__(message)
        self.ratio = ratio
        self.affected = affected
        self.baseline = baseline


@dataclass
class ExistingSession:
    """A session already in the database, flattened for comparison."""

    id: int
    event_slug: str
    category_code: str
    session_type: str
    sequence: int
    display_name: str
    start_utc: datetime
    end_utc: Optional[datetime] = None
    scheduled_duration_minutes: Optional[int] = None
    time_status: str = "confirmed"
    start_precision: str = "exact"
    status: str = "scheduled"
    iana_timezone: Optional[str] = None
    source_url: Optional[str] = None
    ics_sequence: int = 0
    retired_at: Optional[datetime] = None

    @property
    def key(self) -> tuple:
        return (self.event_slug, self.category_code, self.session_type, self.sequence)


@dataclass
class FieldChange:
    field_changed: str
    old_value: Optional[str]
    new_value: Optional[str]


@dataclass
class SessionUpdate:
    existing_id: int
    incoming: NormalizedSession
    changes: list[FieldChange]

    @property
    def bumps_ics_sequence(self) -> bool:
        return any(change.field_changed in NOTIFIABLE_FIELDS for change in self.changes)


@dataclass
class SyncPlan:
    events: list[NormalizedEvent] = field(default_factory=list)
    creates: list[NormalizedSession] = field(default_factory=list)
    updates: list[SessionUpdate] = field(default_factory=list)
    unchanged: list[int] = field(default_factory=list)
    retire: list[ExistingSession] = field(default_factory=list)
    revive: list[ExistingSession] = field(default_factory=list)

    @property
    def records_changed(self) -> int:
        return len(self.creates) + len(self.updates) + len(self.retire) + len(self.revive)

    @property
    def is_noop(self) -> bool:
        return self.records_changed == 0


def _stringify(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _incoming_value(session: NormalizedSession, field_name: str):
    if field_name == "status":
        return "scheduled"  # sources give schedule, not live state
    return getattr(session, field_name)


def diff_sessions(
    existing: Iterable[ExistingSession],
    incoming_events: Iterable[NormalizedEvent],
) -> SyncPlan:
    """Match on natural key and record what differs."""
    incoming_events = list(incoming_events)
    existing_by_key = {item.key: item for item in existing}
    seen_keys: set[tuple] = set()

    plan = SyncPlan(events=incoming_events)

    for event in incoming_events:
        for session in event.sessions:
            key = (event.slug, session.category_code, session.session_type, session.sequence)
            seen_keys.add(key)
            current = existing_by_key.get(key)

            if current is None:
                plan.creates.append(session)
                continue

            changes: list[FieldChange] = []
            for field_name in TRACKED_SESSION_FIELDS:
                old = _stringify(getattr(current, field_name))
                new = _stringify(_incoming_value(session, field_name))
                if old != new:
                    changes.append(FieldChange(field_name, old, new))

            if current.retired_at is not None:
                plan.revive.append(current)

            if changes:
                plan.updates.append(SessionUpdate(current.id, session, changes))
            elif current.retired_at is None:
                plan.unchanged.append(current.id)

    for key, item in existing_by_key.items():
        if key not in seen_keys and item.retired_at is None:
            plan.retire.append(item)

    return plan


def guard_not_empty(plan: SyncPlan, *, records_found: int) -> None:
    """Reliability rule 1: a run that returns nothing is a failed run.

    Never an empty calendar - the existing data stays exactly as it is.
    """
    if records_found == 0:
        raise GuardTripped("scrape returned zero records; refusing to touch existing data")


def guard_change_threshold(
    plan: SyncPlan,
    existing: Iterable[ExistingSession],
    *,
    now: Optional[datetime] = None,
    threshold: float = 0.30,
    min_baseline: int = 10,
) -> None:
    """Reliability rule 2: abort if the run would modify or retire more than
    `threshold` of a series' upcoming sessions.

    Only upcoming sessions count. Past sessions get their status settled after
    the fact and would otherwise drown out the signal. Below `min_baseline`
    upcoming sessions the ratio is too noisy to act on - a season with 4 known
    sessions trips at a single reschedule - so the guard stands down and the
    caller relies on validation instead.
    """
    moment = now or datetime.now(timezone.utc)
    upcoming = [item for item in existing if item.retired_at is None and item.start_utc >= moment]
    baseline = len(upcoming)
    if baseline < min_baseline:
        return

    upcoming_ids = {item.id for item in upcoming}
    affected = {update.existing_id for update in plan.updates if update.existing_id in upcoming_ids}
    affected |= {item.id for item in plan.retire if item.id in upcoming_ids}

    ratio = len(affected) / baseline
    if ratio > threshold:
        raise GuardTripped(
            f"run would change {len(affected)}/{baseline} upcoming sessions "
            f"({ratio:.0%} > {threshold:.0%}); aborting for manual review",
            ratio=ratio,
            affected=len(affected),
            baseline=baseline,
        )


def apply_guards(
    plan: SyncPlan,
    existing: Iterable[ExistingSession],
    *,
    records_found: int,
    now: Optional[datetime] = None,
    threshold: float = 0.30,
    min_baseline: int = 10,
) -> None:
    existing = list(existing)
    guard_not_empty(plan, records_found=records_found)
    guard_change_threshold(
        plan, existing, now=now, threshold=threshold, min_baseline=min_baseline
    )
