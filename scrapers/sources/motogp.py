"""MotoGP, including Moto2 and Moto3 (and MotoE when it appears on a calendar).

All classes share a race weekend and must land on the same `event`, so this
source emits them from one response with different category codes. That is what
makes the unified weekend view possible.

Source: the site's own internal JSON API (the top structured option after an
official ICS feed). One request returns the whole season with every session for
every class already embedded, so the two-step "list then fetch each event" dance
is unnecessary - `broadcasts` is populated on the season-list response itself.

Discovery status: see docs/sources.md#motogp. The endpoint and parsing are
verified against scrapers/fixtures/motogp_events.json, but the source is held at
status = "unverified" in config/series.toml pending a Terms-of-Use decision
(personal-use-only clause), so the runner will not scrape it live without
--allow-unverified. Flip to "live" once that call is made.

Shape of one event (trimmed to what this parser reads):

    {
      "kind": "GP",                       # SPORT/TEST/GP; only GP is a round
      "name": "PT GRAND PRIX OF THAILAND",
      "additional_name": "THAILAND",      # the clean place label
      "sequence": 1,                       # round number
      "time_zone": "ASIA/BANGKOK",
      "circuit": {"name": "Chang International Circuit", "city": "...", ...},
      "broadcasts": [
        {
          "name": "Free Practice Nr. 1",
          "type": "SESSION",               # MEDIA entries (press, shows) are dropped
          "kind": "PRACTICE",
          "category": {"name": "Moto3"},   # MotoGP/Moto2/Moto3/MotoE, or Baggers etc.
          "date_start": "2026-02-27T09:00:00+0700",   # offset-stamped local time
          "date_end":   "2026-02-27T09:35:00+0700",
          "status": "FINISHED"             # FINISHED/NOT-STARTED - temporal, not confidence
        },
        ...
      ]
    }
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable, Optional

from ..config import SeriesConfig, VenueConfig
from ..records import ParsedSession, slugify
from .base import FetchedDocument, register

DEFAULT_FEED_URL = "https://api.motogp.pulselive.com/motogp/v1/events?seasonYear={season}"

# The API's class names mapped onto our category codes. Anything not in here -
# most notably "Baggers", an invitational that appears at a handful of rounds -
# is dropped rather than forced into a class it does not belong to.
_CATEGORY_MAP = {
    "MotoGP": "motogp",
    "Moto2": "moto2",
    "Moto3": "moto3",
    "MotoE": "motoe",
}

# additional_name is already a clean place label; .title() handles the rest.
# Only genuine exceptions belong here.
_EVENT_NAME_FIXUPS = {
    "USA": "United States",
}


def _clean_session_name(name: str) -> str:
    """Tidy the API's session labels without changing what they mean.

    "Free Practice Nr. 1" -> "Free Practice 1", "Qualifying Nr.2" -> "Qualifying
    2", "Tissot Sprint" -> "Sprint". The numbering matters: normalize derives a
    stable per-(category, type) sequence from "... 1"/"... 2", and "Nr." sits
    between the word and the digit where the sequence patterns cannot see it.
    """
    text = name.strip()
    text = re.sub(r"\bNr\.?\s*", "", text)          # drop the "Nr." infix
    text = re.sub(r"^Tissot\s+", "", text)          # sprint sponsor
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _clean_event_name(additional_name: str) -> str:
    place = (additional_name or "").strip()
    if place.upper() in _EVENT_NAME_FIXUPS:
        return _EVENT_NAME_FIXUPS[place.upper()]
    return place.title()


class MotoGpSource:
    """Parses the MotoGP season-events JSON into ParsedSession records."""

    series_code = "motogp"
    detail_level = "full"

    # circuit name (as slugified by records.slugify) -> venue slug. Keyed on the
    # normalized token so accents and punctuation in the feed cannot cause a
    # miss. City fallbacks cover a circuit being renamed by a new title sponsor.
    venue_by_circuit = {
        "chang-international-circuit": "buriram",
        "autodromo-internacional-de-goiania-ayrton-senna": "goiania",
        "circuit-of-the-americas": "cota",
        "circuito-de-jerez-angel-nieto": "jerez",
        "le-mans": "le_mans",
        "circuit-de-barcelona-catalunya": "barcelona",
        "autodromo-internazionale-del-mugello": "mugello",
        "balaton-park": "balaton_park",
        "creditas-autodrom-brno": "brno",
        "tt-circuit-assen": "assen",
        "sachsenring": "sachsenring",
        "silverstone-circuit": "silverstone",
        "motorland-aragon": "aragon",
        "misano-world-circuit-marco-simoncelli": "misano",
        "red-bull-ring-spielberg": "red_bull_ring",
        "mobility-resort-motegi": "motegi",
        "pertamina-mandalika-international-circuit": "mandalika",
        "phillip-island": "phillip_island",
        "petronas-sepang-international-circuit": "sepang",
        "lusail-international-circuit": "lusail",
        "autodromo-internacional-do-algarve": "portimao",
        "circuit-ricardo-tormo": "valencia",
    }
    venue_by_city = {
        "buriram": "buriram",
        "goiania": "goiania",
        "austin": "cota",
        "jerez de la frontera": "jerez",
        "le mans": "le_mans",
        "montmelo": "barcelona",
        "scarperia": "mugello",
        "brno": "brno",
        "assen": "assen",
        "spielberg": "red_bull_ring",
        "motegi": "motegi",
        "sepang": "sepang",
        "cheste": "valencia",
    }

    def __init__(self, feed_url: Optional[str] = None):
        self.feed_url = feed_url or DEFAULT_FEED_URL

    def urls(self, season: int) -> list[str]:
        return [self.feed_url.format(season=season)]

    def _venue_for(self, circuit: dict, venues: dict[str, VenueConfig]) -> Optional[str]:
        name_token = slugify(circuit.get("name", "") or "")
        slug = self.venue_by_circuit.get(name_token)
        if slug is None:
            city = (circuit.get("city") or "").strip().lower()
            slug = self.venue_by_city.get(city)
        # Never guess: an unmapped circuit surfaces as a normalize error rather
        # than sending sessions to the wrong circuit and the wrong timezone.
        return slug if slug in venues else None

    def parse(
        self,
        documents: Iterable[FetchedDocument],
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
    ) -> list[ParsedSession]:
        results: list[ParsedSession] = []

        for document in documents:
            events = json.loads(document.text)
            if isinstance(events, dict):  # some deployments wrap the list
                events = events.get("events") or events.get("data") or []

            for event in events:
                if event.get("kind") != "GP":
                    continue  # SPORT/TEST/PRESENTATION are not race weekends

                event_name = _clean_event_name(event.get("additional_name", ""))
                if not event_name:
                    continue
                official_name = (event.get("name") or "").strip() or None
                venue_slug = self._venue_for(event.get("circuit") or {}, venues)
                round_number = event.get("sequence")

                for entry in event.get("broadcasts", []):
                    if entry.get("type") != "SESSION":
                        continue  # press conferences, shows, group photos
                    category_code = _CATEGORY_MAP.get((entry.get("category") or {}).get("name", ""))
                    if category_code is None:
                        continue  # Baggers and any future non-tracked class

                    start = _parse_dt(entry.get("date_start"))
                    if start is None:
                        continue
                    end = _parse_dt(entry.get("date_end"))
                    duration = int((end - start).total_seconds() // 60) if end else None

                    results.append(
                        ParsedSession(
                            series_code=series.code,
                            season=season,
                            event_name=event_name,
                            category_code=category_code,
                            raw_session_name=_clean_session_name(entry.get("name", "")),
                            official_name=official_name,
                            venue_slug=venue_slug,
                            round_number=round_number,
                            start_utc=start,
                            end_utc=end,
                            duration_minutes=duration or None,
                            # The API does not distinguish provisional from
                            # confirmed times (status is FINISHED/NOT-STARTED,
                            # which is temporal). Like the F1 feed, everything is
                            # treated as confirmed. See docs/sources.md.
                            time_status="confirmed",
                            source_url="https://www.motogp.com/en/calendar",
                        )
                    )

        return results


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse an offset-stamped ISO string ("...+0700" or "...+07:00").

    The offset makes the instant unambiguous, so the result is timezone-aware
    and flows straight through normalize as start_utc without needing the venue's
    IANA zone.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


@register("motogp")
def build(feed_url: Optional[str] = None) -> MotoGpSource:
    return MotoGpSource(feed_url=feed_url)
