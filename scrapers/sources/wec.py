"""FIA World Endurance Championship.

WEC runs Hypercar and LMGT3 (and LMP2 at Le Mans) to a shared timetable, so the
config models it as a single `wec` category; every session lands on it.

Source: fiawec.com's per-race pages, which embed a schema.org SportsEvent as
JSON-LD with the weekend's sessions as `subEvent`s. There is no session-level
JSON API (the pages are server-rendered), so this parses the JSON-LD - the third
option in the discovery order, structured data in the page. Two stages: the
season page lists the race slugs, then each race page carries its own schedule,
so the source implements `resolve_urls` (see scrapers/sources/base.py).

Two traps this source has to handle, both verified during discovery:

  1. **Bogus offsets.** Every `startDate` is stamped with the CMS server's own
     timezone (CEST/CET), *not* the circuit's - so Fuji's sessions read
     "10:15:00+02:00" when the real time is 10:15 JST. The wall-clock is
     circuit-local and the offset is noise, so the offset is stripped and the
     time handed to normalize as a naive local time for the venue's real IANA
     zone to resolve. (For the European rounds the offset happens to be right;
     for Fuji, Sao Paulo and Austin it is wrong, which is the whole point.)

  2. **No end times.** `endDate` is always null. Practice and qualifying can live
     without one, but a race must carry an end (a 6- or 24-hour race rendered as
     a point in time is the exact failure the schema's end_utc exists to avoid),
     so the race duration is read from the event name: "24 Hours" -> 1440 min,
     "N Hours" -> N*60, and the standard WEC round otherwise -> 360.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable, Optional

from ..config import SeriesConfig, VenueConfig
from ..records import ParsedSession, slugify
from .base import FetchedDocument, register

DEFAULT_BASE_URL = "https://www.fiawec.com"

_LD_JSON = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I
)
_RACE_LINK = re.compile(r"/en/race/([a-z0-9-]+)")
_SPONSOR_PREFIX = re.compile(r"^(totalenergies|rolex|qatar\s+airways)\s+", re.IGNORECASE)

# schema.org location name (slugified) -> venue slug. Circuit names, not cities,
# and deliberately explicit: "24 Heures du Mans" and "Circuit des Ameriques"
# would never resolve by containment.
_VENUE_BY_LOCATION = {
    "imola": "imola",
    "spa-francorchamps": "spa",
    "24-heures-du-mans": "le_mans",
    "interlagos": "interlagos",
    "circuit-des-ameriques": "cota",
    "fuji-speedway": "fuji",
    "barcelona": "barcelona",
    "monza": "monza",
}


class WecSource:
    series_code = "wec"
    detail_level = "full"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    def _season_url(self, season: int) -> str:
        return f"{self.base_url}/en/season/{season}"

    # Two-stage: the season page lists race slugs; each race page has its schedule.
    def resolve_urls(self, season: int, client) -> list[str]:
        html = client.get(self._season_url(season)).body.decode("utf-8", "replace")
        slugs = sorted(set(_RACE_LINK.findall(html)))
        return [
            f"{self.base_url}/en/race/{slug}"
            for slug in slugs
            if slug.endswith(f"-{season}") and "prologue" not in slug  # skip pre-season test
        ]

    def parse(
        self,
        documents: Iterable[FetchedDocument],
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
    ) -> list[ParsedSession]:
        results: list[ParsedSession] = []
        category = series.headline_category.code

        for document in documents:
            event = _sports_event(document.text)
            if event is None:
                continue

            raw_short = _event_short_name(event.get("name", ""), season)
            if not raw_short:
                continue
            event_name = _SPONSOR_PREFIX.sub("", raw_short).strip()
            venue_slug = _venue_for(event.get("location"), venues)
            race_minutes = _race_duration_minutes(raw_short)

            sub_events = event.get("subEvent") or []
            if isinstance(sub_events, dict):
                sub_events = [sub_events]

            for sub in sub_events:
                local_start = _naive_local(sub.get("startDate"))
                if local_start is None:
                    continue
                session_name = _session_name(sub.get("name", ""), raw_short)
                if not session_name:
                    continue
                is_race = session_name.strip().lower() == "race"

                results.append(
                    ParsedSession(
                        series_code=series.code,
                        season=season,
                        event_name=event_name,
                        category_code=category,
                        raw_session_name=session_name,
                        official_name=raw_short if raw_short != event_name else None,
                        venue_slug=venue_slug,
                        # Naive wall-clock: the feed's offset is the CMS server's
                        # zone, not the circuit's, so it is dropped and the
                        # venue's IANA zone resolves the real instant.
                        local_start=local_start,
                        local_timezone=None,
                        duration_minutes=race_minutes if is_race else None,
                        time_status="confirmed",
                        source_url=document.url,
                    )
                )

        return results


def _sports_event(html: str) -> Optional[dict]:
    for block in _LD_JSON.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "SportsEvent":
            return data
    return None


def _event_short_name(name: str, season: int) -> str:
    """"WEC 6 Hours of Fuji 2026" -> "6 Hours of Fuji" (also the subEvent suffix)."""
    text = re.sub(r"^WEC\s+", "", name.strip(), flags=re.IGNORECASE)
    text = re.sub(rf"\s+{season}$", "", text)
    return text.strip()


def _session_name(sub_name: str, event_short: str) -> str:
    """Strip the " - <event>" tail the feed appends to every session name."""
    suffix = f" - {event_short}"
    name = sub_name[: -len(suffix)] if sub_name.endswith(suffix) else sub_name
    return " ".join(name.split())


def _race_duration_minutes(event_short: str) -> int:
    match = re.search(r"(\d+)\s*Hours?", event_short, re.IGNORECASE)
    if match:
        return int(match.group(1)) * 60
    return 360  # the standard WEC round is six hours (e.g. "Lone Star Le Mans")


def _naive_local(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)  # drop the misleading offset


def _venue_for(location, venues: dict[str, VenueConfig]) -> Optional[str]:
    if not isinstance(location, dict):
        return None
    slug = _VENUE_BY_LOCATION.get(slugify(location.get("name", "") or ""))
    return slug if slug in venues else None


@register("wec")
def build(feed_url: Optional[str] = None) -> WecSource:
    # `feed_url` from config/series.toml's source.url is the site base URL.
    return WecSource(base_url=feed_url)
