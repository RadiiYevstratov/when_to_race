"""Record types passed between pipeline stages.

parse   -> ParsedSession   (loose, source-shaped, times still local)
normalize -> NormalizedSession (controlled vocabulary, times in UTC)
group   -> NormalizedEvent  (a weekend, with its sessions)

These are plain dataclasses rather than Pydantic models. See
docs/data-model-review.md, "Deviation 1" for the reasoning and for how to swap
them back if you'd rather keep Pydantic.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# Controlled vocabulary. A source's own naming must never leak into this.
SESSION_TYPES = (
    "practice",
    "qualifying",
    "sprint_qualifying",
    "sprint",
    "race",
    "warmup",
    "shakedown",
    "stage",
    "test",
    "other",
)

TIME_STATUSES = ("confirmed", "provisional", "tbc")
TIME_PRECISIONS = ("exact", "hour", "day")


def slugify(value: str) -> str:
    """ASCII slug. Used for event slugs and calendar UIDs, so it must be stable."""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
    return cleaned.strip("-")


@dataclass
class ParsedSession:
    """Output of a source-specific parser. Times may still be local and naive.

    Exactly one of (local_start + local_timezone) or start_utc must be provided.
    """

    series_code: str
    season: int
    event_name: str
    category_code: str
    raw_session_name: str

    venue_slug: Optional[str] = None
    official_name: Optional[str] = None
    round_number: Optional[int] = None

    # Either a naive local time...
    local_start: Optional[datetime] = None
    local_end: Optional[datetime] = None
    local_timezone: Optional[str] = None  # overrides the venue's zone if set
    # ...or an already-absolute time (an ICS feed with UTC stamps, say).
    start_utc: Optional[datetime] = None
    end_utc: Optional[datetime] = None

    duration_minutes: Optional[int] = None
    time_status: str = "confirmed"
    start_precision: str = "exact"
    session_type_hint: Optional[str] = None  # source told us outright
    sequence_hint: Optional[int] = None
    source_url: Optional[str] = None


@dataclass
class NormalizedSession:
    series_code: str
    season: int
    event_slug: str
    category_code: str
    session_type: str
    display_name: str
    sequence: int
    start_utc: datetime
    end_utc: Optional[datetime]
    scheduled_duration_minutes: Optional[int]
    time_status: str
    start_precision: str
    iana_timezone: Optional[str]  # only when it differs from the venue's
    ics_uid: str
    source_url: Optional[str] = None

    @property
    def natural_key(self) -> tuple:
        return (
            self.series_code,
            self.season,
            self.event_slug,
            self.category_code,
            self.session_type,
            self.sequence,
        )


@dataclass
class NormalizedEvent:
    series_code: str
    season: int
    slug: str
    name: str
    official_name: Optional[str]
    venue_slug: str
    round_number: Optional[int]
    starts_at_utc: datetime
    ends_at_utc: datetime
    detail_level: str = "full"
    source_url: Optional[str] = None
    sessions: list[NormalizedSession] = field(default_factory=list)

    @property
    def natural_key(self) -> tuple:
        return (self.series_code, self.season, self.slug)


def build_ics_uid(
    series_code: str, season: int, event_slug: str, category_code: str, display_name: str
) -> str:
    """Stable calendar UID.

    Deliberately keyed on display_name rather than on `sequence`. A subscribed
    calendar identifies an event by UID; if the UID changed whenever a source
    renumbered its sessions, every subscriber would get a duplicate instead of
    an update. Display names ("Free Practice 1") survive renumbering.
    """
    parts = [series_code, str(season), event_slug, category_code, slugify(display_name)]
    return "-".join(parts) + "@motorsport-schedule"


def ensure_utc(value: datetime) -> datetime:
    """Reject naive datetimes and normalise to UTC. Called at every boundary."""
    if value.tzinfo is None:
        raise ValueError(f"naive datetime reached a UTC boundary: {value!r}")
    return value.astimezone(timezone.utc)
