"""Validate stage. Hard constraints on normalized output, before it touches the
database.

Everything here is a check that a broken parser would fail and a real calendar
would pass. Each failure carries the offending record so a 3am alert is
actionable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from .config import SeriesConfig, VenueConfig
from .records import (
    SESSION_TYPES,
    TIME_PRECISIONS,
    TIME_STATUSES,
    NormalizedEvent,
)

# A session may legitimately fall a little outside its season year: the Bahrain
# test runs in February, and some championships schedule a December round.
SEASON_WINDOW_BEFORE = timedelta(days=75)
SEASON_WINDOW_AFTER = timedelta(days=75)


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    code: str
    message: str
    event_slug: Optional[str] = None
    session_uid: Optional[str] = None

    def __str__(self) -> str:  # pragma: no cover - formatting only
        where = self.event_slug or "-"
        return f"[{self.severity}] {self.code} ({where}): {self.message}"


class ValidationError(Exception):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("; ".join(str(issue) for issue in issues))


def validate(
    events: Iterable[NormalizedEvent],
    series: SeriesConfig,
    venues: dict[str, VenueConfig],
    min_sessions_per_event: int = 1,
) -> list[ValidationIssue]:
    """Return every issue found. Errors mean do not write; warnings mean write
    and log."""
    issues: list[ValidationIssue] = []
    events = list(events)

    seen_event_keys: set[tuple] = set()
    seen_uids: set[str] = set()

    for event in events:
        if event.natural_key in seen_event_keys:
            issues.append(
                ValidationIssue(
                    "error",
                    "duplicate_event",
                    f"two events share the natural key {event.natural_key}",
                    event.slug,
                )
            )
        seen_event_keys.add(event.natural_key)

        if event.venue_slug not in venues:
            issues.append(
                ValidationIssue("error", "unknown_venue", f"venue {event.venue_slug!r} is not in the registry", event.slug)
            )

        if event.detail_level not in ("full", "partial"):
            issues.append(
                ValidationIssue("error", "bad_detail_level", f"detail_level {event.detail_level!r}", event.slug)
            )

        if not event.sessions:
            issues.append(ValidationIssue("error", "empty_event", "event has no sessions", event.slug))
            continue

        if len(event.sessions) < min_sessions_per_event:
            severity = "warning" if event.detail_level == "partial" else "error"
            issues.append(
                ValidationIssue(
                    severity,
                    "session_floor",
                    f"{len(event.sessions)} sessions, floor for {series.code} is {min_sessions_per_event}",
                    event.slug,
                )
            )

        season_start = datetime(event.season, 1, 1, tzinfo=timezone.utc) - SEASON_WINDOW_BEFORE
        season_end = datetime(event.season, 12, 31, 23, 59, tzinfo=timezone.utc) + SEASON_WINDOW_AFTER

        seen_session_keys: set[tuple] = set()
        for session in event.sessions:
            if session.session_type not in SESSION_TYPES:
                issues.append(
                    ValidationIssue(
                        "error",
                        "bad_session_type",
                        f"{session.session_type!r} is outside the controlled vocabulary",
                        event.slug,
                        session.ics_uid,
                    )
                )
            if session.time_status not in TIME_STATUSES:
                issues.append(
                    ValidationIssue("error", "bad_time_status", f"{session.time_status!r}", event.slug, session.ics_uid)
                )
            if session.start_precision not in TIME_PRECISIONS:
                issues.append(
                    ValidationIssue(
                        "error", "bad_precision", f"{session.start_precision!r}", event.slug, session.ics_uid
                    )
                )

            try:
                series.category(session.category_code)
            except Exception:  # noqa: BLE001 - config raises its own type
                issues.append(
                    ValidationIssue(
                        "error",
                        "unknown_category",
                        f"category {session.category_code!r} is not registered for {series.code}",
                        event.slug,
                        session.ics_uid,
                    )
                )

            if session.start_utc.tzinfo is None:
                issues.append(
                    ValidationIssue("error", "naive_datetime", "start_utc is naive", event.slug, session.ics_uid)
                )
            elif not (season_start <= session.start_utc <= season_end):
                issues.append(
                    ValidationIssue(
                        "error",
                        "start_outside_season",
                        f"{session.start_utc.isoformat()} is outside the {event.season} window",
                        event.slug,
                        session.ics_uid,
                    )
                )

            if session.end_utc is not None and session.end_utc < session.start_utc:
                issues.append(
                    ValidationIssue("error", "end_before_start", session.display_name, event.slug, session.ics_uid)
                )

            # Endurance rounds must carry an end time; a 24-hour race rendered
            # as a point in time is the whole failure mode this product exists
            # to avoid.
            if (
                session.session_type == "race"
                and session.scheduled_duration_minutes
                and session.scheduled_duration_minutes >= 180
                and session.end_utc is None
            ):
                issues.append(
                    ValidationIssue(
                        "error",
                        "missing_end_for_long_race",
                        f"{session.display_name} runs {session.scheduled_duration_minutes} min with no end time",
                        event.slug,
                        session.ics_uid,
                    )
                )

            key = (session.category_code, session.session_type, session.sequence)
            if key in seen_session_keys:
                issues.append(
                    ValidationIssue(
                        "error",
                        "duplicate_session_key",
                        f"two sessions share (category, type, sequence) = {key}",
                        event.slug,
                        session.ics_uid,
                    )
                )
            seen_session_keys.add(key)

            if session.ics_uid in seen_uids:
                issues.append(
                    ValidationIssue(
                        "error",
                        "duplicate_uid",
                        f"calendar UID {session.ics_uid} is not unique",
                        event.slug,
                        session.ics_uid,
                    )
                )
            seen_uids.add(session.ics_uid)

            if not (event.starts_at_utc <= session.start_utc <= event.ends_at_utc):
                issues.append(
                    ValidationIssue(
                        "error",
                        "session_outside_event",
                        f"{session.display_name} starts outside its event span",
                        event.slug,
                        session.ics_uid,
                    )
                )

    return issues


def raise_for_errors(issues: list[ValidationIssue]) -> None:
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise ValidationError(errors)
