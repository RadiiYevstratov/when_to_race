"""Normalize stage: source-shaped records in, controlled vocabulary out.

Three jobs:
  1. Map every source's session naming onto the controlled `session_type` list.
  2. Resolve circuit-local times to UTC through the venue's IANA zone.
  3. Group sessions into events and assign stable sequences.

Nothing here knows about a specific website. Everything site-specific belongs
in scrapers/sources/.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from .config import SeriesConfig, VenueConfig
from .records import (
    NormalizedEvent,
    NormalizedSession,
    ParsedSession,
    build_ics_uid,
    ensure_utc,
    slugify,
)


class NormalizeError(Exception):
    pass


# Ordered. First match wins, so the specific patterns must come before the
# general ones: "Superpole Race" is a race, "Superpole" is qualifying, and
# "Sprint Shootout" is sprint qualifying rather than either sprint or qualifying.
_SESSION_TYPE_RULES: tuple[tuple[str, str], ...] = (
    (r"\bshakedown\b", "shakedown"),
    (r"\bsprint\s*(qualifying|quali|shootout)\b", "sprint_qualifying"),
    (r"\bsuperpole\s+race\b", "race"),
    (r"\bsprint\b", "sprint"),
    (r"\bwarm[\s-]*up\b", "warmup"),
    (r"\bpower\s*stage\b", "stage"),
    (r"^ss\s*\d+", "stage"),
    (r"\bstage\b", "stage"),
    (r"\bprologue\b", "test"),
    (r"\b(free\s+practice|practice)\b", "practice"),
    (r"^fp\s*\d*$", "practice"),
    (r"^p\d+$", "practice"),
    (r"\b(qualifying|qualification|quali|hyperpole|superpole)\b", "qualifying"),
    (r"^q\d*$", "qualifying"),
    (r"\b(feature\s+race|race|grand\s+prix)\b", "race"),
    (r"\b\d+\s*(hours?|h|minutes?)\s+of\b", "race"),
    (r"\b(test|testing)\b", "test"),
)

_COMPILED_RULES = tuple((re.compile(pattern, re.IGNORECASE), kind) for pattern, kind in _SESSION_TYPE_RULES)

# Only these shapes yield a sequence number from the name. A loose "first
# integer in the string" rule would read "24 Hours of Le Mans" as session 24.
_SEQUENCE_PATTERNS = (
    re.compile(r"^fp\s*(\d+)", re.IGNORECASE),
    re.compile(r"^p\s*(\d+)$", re.IGNORECASE),
    re.compile(r"^q\s*(\d+)$", re.IGNORECASE),
    re.compile(r"^ss\s*(\d+)", re.IGNORECASE),
    re.compile(r"\b(?:free\s+)?practice\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"\bqualifying\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"\bstage\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"\brace\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"\bday\s+(\d+)\b", re.IGNORECASE),
)


def classify_session_type(raw_name: str, hint: Optional[str] = None) -> str:
    """Map a source's session name onto the controlled vocabulary."""
    if hint:
        from .records import SESSION_TYPES

        if hint not in SESSION_TYPES:
            raise NormalizeError(f"session_type hint {hint!r} is not in the controlled vocabulary")
        return hint

    name = raw_name.strip()
    for pattern, session_type in _COMPILED_RULES:
        if pattern.search(name):
            return session_type
    return "other"


def extract_sequence(raw_name: str) -> Optional[int]:
    for pattern in _SEQUENCE_PATTERNS:
        match = pattern.search(raw_name)
        if match:
            return int(match.group(1))
    return None


def clean_display_name(raw_name: str) -> str:
    """Collapse whitespace. Series-specific naming is preserved on purpose."""
    return re.sub(r"\s+", " ", raw_name).strip()


def _resolve_start(
    parsed: ParsedSession, venue: VenueConfig
) -> tuple[datetime, Optional[datetime], Optional[str]]:
    """Return (start_utc, end_utc, timezone_override)."""
    tz_override = parsed.local_timezone if parsed.local_timezone != venue.iana_timezone else None
    zone_name = parsed.local_timezone or venue.iana_timezone
    zone = ZoneInfo(zone_name)

    if parsed.start_utc is not None:
        start_utc = ensure_utc(parsed.start_utc)
    elif parsed.local_start is not None:
        local = parsed.local_start
        if local.tzinfo is None:
            local = local.replace(tzinfo=zone)
        start_utc = ensure_utc(local)
    else:
        raise NormalizeError(f"session {parsed.raw_session_name!r} has no start time")

    end_utc: Optional[datetime] = None
    if parsed.end_utc is not None:
        end_utc = ensure_utc(parsed.end_utc)
    elif parsed.local_end is not None:
        local_end = parsed.local_end
        if local_end.tzinfo is None:
            local_end = local_end.replace(tzinfo=zone)
        end_utc = ensure_utc(local_end)
    elif parsed.duration_minutes:
        end_utc = start_utc + timedelta(minutes=parsed.duration_minutes)

    if end_utc is not None and end_utc < start_utc:
        raise NormalizeError(
            f"session {parsed.raw_session_name!r} ends before it starts "
            f"({start_utc.isoformat()} -> {end_utc.isoformat()})"
        )
    return start_utc, end_utc, tz_override


def _assign_sequences(sessions: list[tuple[ParsedSession, str]]) -> dict[int, int]:
    """Sequence is the ordinal within (category, session_type), not within the
    weekend.

    The brief describes sequence as weekend ordering, but the upsert natural key
    includes it, and a weekend-wide index renumbers every later session whenever
    one is inserted - which would orphan rows and spam schedule_changes. Ordinal
    within (category, type) is stable under insertion. Display order comes from
    starts_at_utc, so nothing is lost. See docs/data-model-review.md.
    """
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, (parsed, session_type) in enumerate(sessions):
        groups[(parsed.category_code, session_type)].append(index)

    assigned: dict[int, int] = {}
    for indices in groups.values():
        proposed: list[Optional[int]] = []
        for index in indices:
            parsed, _ = sessions[index]
            proposed.append(parsed.sequence_hint or extract_sequence(parsed.raw_session_name))

        usable = [value for value in proposed if value is not None]
        # Fall back to positional numbering if the names are incomplete or
        # collide - a half-derived, half-positional group would be worse.
        if len(usable) != len(indices) or len(set(usable)) != len(usable):
            for ordinal, index in enumerate(indices, start=1):
                assigned[index] = ordinal
        else:
            for index, value in zip(indices, proposed):
                assigned[index] = int(value)  # type: ignore[arg-type]
    return assigned


def normalize(
    parsed_sessions: Iterable[ParsedSession],
    series: SeriesConfig,
    venues: dict[str, VenueConfig],
    detail_level: str = "full",
) -> list[NormalizedEvent]:
    """Group parsed sessions into events with UTC times and stable keys."""
    by_event: dict[tuple[str, int, str], list[ParsedSession]] = defaultdict(list)
    for parsed in parsed_sessions:
        if parsed.series_code != series.code:
            raise NormalizeError(
                f"parser returned series {parsed.series_code!r} while running {series.code!r}"
            )
        series.category(parsed.category_code)  # raises if the code is unknown
        by_event[(parsed.series_code, parsed.season, parsed.event_name)].append(parsed)

    events: list[NormalizedEvent] = []
    used_slugs: dict[tuple[str, int], set[str]] = defaultdict(set)

    for (series_code, season, event_name), group in by_event.items():
        venue_slugs = {item.venue_slug for item in group if item.venue_slug}
        if not venue_slugs:
            raise NormalizeError(f"event {event_name!r} has no venue")
        if len(venue_slugs) > 1:
            raise NormalizeError(f"event {event_name!r} maps to multiple venues: {sorted(venue_slugs)}")
        venue_slug = venue_slugs.pop()
        if venue_slug not in venues:
            raise NormalizeError(f"unknown venue slug {venue_slug!r} for event {event_name!r}")
        venue = venues[venue_slug]

        slug = slugify(event_name)
        if slug in used_slugs[(series_code, season)]:
            round_number = next((item.round_number for item in group if item.round_number), None)
            slug = f"{slug}-{round_number}" if round_number else f"{slug}-{venue_slug}"
        used_slugs[(series_code, season)].add(slug)

        # Resolve to UTC before sorting. A feed can mix TZID-qualified,
        # UTC-stamped and floating times in one file, and those cannot be
        # compared to each other until they are all absolute.
        resolved = [
            (
                item,
                classify_session_type(item.raw_session_name, item.session_type_hint),
                *_resolve_start(item, venue),
            )
            for item in group
        ]
        resolved.sort(key=lambda entry: (entry[2], entry[0].raw_session_name))

        classified = [(item, session_type) for item, session_type, _, _, _ in resolved]
        sequences = _assign_sequences(classified)

        normalized_sessions: list[NormalizedSession] = []
        for index, (parsed, session_type, start_utc, end_utc, tz_override) in enumerate(resolved):
            display_name = clean_display_name(parsed.raw_session_name)
            normalized_sessions.append(
                NormalizedSession(
                    series_code=series_code,
                    season=season,
                    event_slug=slug,
                    category_code=parsed.category_code,
                    session_type=session_type,
                    display_name=display_name,
                    sequence=sequences[index],
                    start_utc=start_utc,
                    end_utc=end_utc,
                    scheduled_duration_minutes=parsed.duration_minutes,
                    time_status=parsed.time_status,
                    start_precision=parsed.start_precision,
                    iana_timezone=tz_override,
                    ics_uid=build_ics_uid(series_code, season, slug, parsed.category_code, display_name),
                    source_url=parsed.source_url,
                )
            )

        starts = [session.start_utc for session in normalized_sessions]
        ends = [session.end_utc or session.start_utc for session in normalized_sessions]
        first = next((item for item in group if item.official_name), None)
        round_number = next((item.round_number for item in group if item.round_number is not None), None)
        source_url = next((item.source_url for item in group if item.source_url), None)

        events.append(
            NormalizedEvent(
                series_code=series_code,
                season=season,
                slug=slug,
                name=event_name,
                official_name=first.official_name if first else None,
                venue_slug=venue_slug,
                round_number=round_number,
                starts_at_utc=min(starts),
                ends_at_utc=max(ends),
                detail_level=detail_level,
                source_url=source_url,
                sessions=sorted(normalized_sessions, key=lambda s: (s.start_utc, s.sequence)),
            )
        )

    events.sort(key=lambda event: (event.season, event.starts_at_utc))
    return events
