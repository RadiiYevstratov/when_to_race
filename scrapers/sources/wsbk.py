"""WorldSBK: WorldSBK, WorldSSP, WorldSPB and Women's WorldWCR.

All classes share a race weekend and land on the same `event`, which is what
makes the unified weekend view work.

Source: worldsbk.com's own JSON:API backend (`api.wsbk.pulselive.com`). Unlike
MotoGP's single season-list call, this API is two-stage: one call lists the
season's rounds, then sessions are served per round. So this source implements
`resolve_urls` (see scrapers/sources/base.py) - it fetches the rounds index with
the polite client to learn the round codes, then returns the rounds URL plus one
sessions URL per round. `parse` reads everything back from the fetched
documents, correlating each session to its round by the round id the session
carries. (The rounds URL is fetched twice - once to discover codes, once by the
pipeline so it is snapshotted - which is one small request per run.)

Discovery status: see docs/sources.md#worldsbk. Same publisher (Dorna) and the
same personal-use Terms as MotoGP; set live on the same basis.

Shape (JSON:API), trimmed to what this parser reads:

    rounds:   data[] = {id: "2026-ARA", attributes: {name, brief_description,
                        source_id: "ARA", sequence_order, ...},
                        relationships: {circuit: {data: {id: "ARAGO"}}}}
    sessions: data[] = {id: "2026-ARA-SBK-001",
                        attributes: {brief_description: "Race 1",
                                     start_date_utc: "2026-05-30T12:00:00+00:00",
                                     end_date_utc:   "2026-05-30T12:18:00+00:00",
                                     status: "FINISHED"},
                        relationships: {round:    {data: {id: "2026-ARA"}},
                                        category: {data: {id: "SBK"}}}}
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable, Optional

from ..config import SeriesConfig, VenueConfig
from ..records import ParsedSession
from .base import FetchedDocument, register

DEFAULT_BASE_URL = "https://api.wsbk.pulselive.com/wsbk-events/v1"

# API category id -> our category code. YR3EC (the Yamaha R3 one-make cup) is a
# junior support series and is deliberately dropped, like MotoGP's Baggers.
_CATEGORY_MAP = {
    "SBK": "wsbk",
    "SSP": "wssp",
    "SPB": "wspb",
    "WCR": "wcr",
}

# API circuit id -> venue slug. Keyed on the circuit rather than the round code
# so a round renamed by a title sponsor still resolves.
_VENUE_BY_CIRCUIT = {
    "ARAGO": "aragon",
    "PHILL": "phillip_island",
    "CREMO": "cremona",
    "MOST": "most",
    "ESTOR": "estoril",
    "MAGNY": "magny_cours",
    "DONIN": "donington",
    "BALAT": "balaton_park",
    "MISAN": "misano",
    "JEREZ": "jerez",
    "ASSEN": "assen",
    "PORTI": "portimao",
}


class WorldSbkSource:
    series_code = "wsbk"
    detail_level = "full"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    def _rounds_url(self, season: int) -> str:
        return f"{self.base_url}/seasons/{season}/rounds"

    def _sessions_url(self, season: int, round_source_id: str) -> str:
        return f"{self.base_url}/seasons/{season}/rounds/{round_source_id}/sessions"

    # Two-stage discovery: fetch the rounds index, then one sessions URL each.
    def resolve_urls(self, season: int, client) -> list[str]:
        rounds_url = self._rounds_url(season)
        body = client.get(rounds_url).body
        rounds = json.loads(body).get("data", [])
        session_urls = [
            self._sessions_url(season, r["attributes"]["source_id"])
            for r in rounds
            if r.get("attributes", {}).get("source_id")
        ]
        # rounds_url first so parse() has the round metadata; it is fetched again
        # here only so the pipeline snapshots it.
        return [rounds_url] + session_urls

    def parse(
        self,
        documents: Iterable[FetchedDocument],
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
    ) -> list[ParsedSession]:
        rounds_by_id: dict[str, dict] = {}
        session_lists: list[list[dict]] = []

        for document in documents:
            data = json.loads(document.text).get("data", [])
            if not data:
                continue
            kind = data[0].get("type")
            if kind == "rounds":
                for entry in data:
                    rounds_by_id[entry["id"]] = entry
            elif kind == "sessions":
                session_lists.append(data)

        results: list[ParsedSession] = []
        for sessions in session_lists:
            for entry in sessions:
                rels = entry.get("relationships", {})
                round_id = rels.get("round", {}).get("data", {}).get("id")
                round_entry = rounds_by_id.get(round_id)
                if round_entry is None:
                    continue
                category_code = _CATEGORY_MAP.get(rels.get("category", {}).get("data", {}).get("id", ""))
                if category_code is None:
                    continue  # YR3EC and any future untracked class

                attrs = entry.get("attributes", {})
                start = _parse_dt(attrs.get("start_date_utc"))
                if start is None:
                    continue
                end = _parse_dt(attrs.get("end_date_utc"))
                duration = int((end - start).total_seconds() // 60) if end else None

                r_attrs = round_entry.get("attributes", {})
                circuit_id = round_entry.get("relationships", {}).get("circuit", {}).get("data", {}).get("id", "")
                venue_slug = _VENUE_BY_CIRCUIT.get(circuit_id)
                event_name = (r_attrs.get("brief_description") or "").strip()
                if not event_name:
                    continue
                official_name = (r_attrs.get("name") or "").strip() or None
                round_source = r_attrs.get("source_id")

                results.append(
                    ParsedSession(
                        series_code=series.code,
                        season=season,
                        event_name=event_name,
                        category_code=category_code,
                        # "Superpole" arrives padded with trailing spaces.
                        raw_session_name=" ".join((attrs.get("brief_description") or "").split()),
                        official_name=official_name,
                        venue_slug=venue_slug if venue_slug in venues else None,
                        round_number=r_attrs.get("sequence_order"),
                        start_utc=start,
                        end_utc=end,
                        duration_minutes=duration or None,
                        # Times are published without a provisional/confirmed
                        # distinction (status is FINISHED/NOT-STARTED, i.e.
                        # temporal). Treated as confirmed, as for F1 and MotoGP.
                        time_status="confirmed",
                        source_url=(
                            f"https://www.worldsbk.com/en/calendar/event/{season}-{round_source}"
                            if round_source
                            else "https://www.worldsbk.com/en/calendar"
                        ),
                    )
                )

        return results


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse an offset-stamped ISO string into an aware datetime, or None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


@register("wsbk")
def build(feed_url: Optional[str] = None) -> WorldSbkSource:
    # `feed_url` is what the runner passes from config/series.toml's source.url;
    # for this API it is the base URL that resolve_urls builds paths on.
    return WorldSbkSource(base_url=feed_url)
