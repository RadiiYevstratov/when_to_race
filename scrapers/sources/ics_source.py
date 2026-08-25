"""Generic ICS-feed source.

An official iCal feed is the top of the discovery preference order in the brief,
so the common work lives here and a series only supplies the parts that are
actually series-specific: how a SUMMARY splits into event and session, which
category a line belongs to, and how LOCATION maps to a venue.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

from ..config import SeriesConfig, VenueConfig
from ..ics import IcsEvent, parse_calendar, resolve_end
from ..records import ParsedSession
from .base import FetchedDocument, resolve_venue


class IcsSource:
    """Subclass and override the hooks. `feed_url` comes from config."""

    series_code: str = ""
    detail_level: str = "full"
    venue_aliases: dict[str, str] = {}

    def __init__(
        self,
        feed_url: Optional[str] = None,
        extra_urls: Iterable[str] = (),
    ):
        self.feed_url = feed_url
        self.extra_urls = tuple(extra_urls)

    # --- fetch ------------------------------------------------------------
    def urls(self, season: int) -> list[str]:
        if not self.feed_url:
            raise ValueError(
                f"{self.series_code}: no feed URL configured. Run discovery first "
                f"and set source.url in config/series.toml (see docs/sources.md)."
            )
        feeds = [self.feed_url, *self.extra_urls]
        return [url.format(season=season) for url in feeds]

    # --- hooks ------------------------------------------------------------
    def split_summary(self, summary: str) -> tuple[str, str]:
        """Return (event_name, session_name). Default: split on the last ' - '."""
        if " - " in summary:
            head, _, tail = summary.rpartition(" - ")
            return head.strip(), tail.strip()
        return summary.strip(), summary.strip()

    def category_for(self, summary: str, series: SeriesConfig) -> Optional[str]:
        """Which category this line belongs to. Default: the headline category."""
        return series.headline_category.code

    def clean_event_name(self, event_name: str, season: int) -> str:
        return event_name.replace(str(season), "").strip(" -–—")

    def official_name_for(self, raw_event_name: str, season: int) -> Optional[str]:
        """The sponsor-laden title, kept only when it differs from the clean one."""
        cleaned = self.clean_event_name(raw_event_name, season)
        raw = raw_event_name.strip()
        return raw if raw and raw != cleaned else None

    def venue_for(self, event: IcsEvent, venues: dict[str, VenueConfig]) -> Optional[str]:
        location = event.get("LOCATION", "") or ""
        slug = resolve_venue(location, venues, self.venue_aliases)
        if slug is None:
            slug = resolve_venue(event.summary, venues, self.venue_aliases)
        return slug

    def round_for(self, event: IcsEvent) -> Optional[int]:
        return None

    def skip(self, event: IcsEvent) -> bool:
        """Drop non-session entries some feeds include (TV shows, ticket sales)."""
        return not event.summary.strip()

    # --- parse ------------------------------------------------------------
    def parse(
        self,
        documents: Iterable[FetchedDocument],
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
    ) -> list[ParsedSession]:
        results: list[ParsedSession] = []

        for document in documents:
            for entry in parse_calendar(document.text):
                if self.skip(entry) or entry.dtstart is None:
                    continue

                raw_head, session_name = self.split_summary(entry.summary)
                event_name = self.clean_event_name(raw_head, season)
                official_name = self.official_name_for(raw_head, season)
                category = self.category_for(entry.summary, series)
                if category is None:
                    continue

                venue_slug = self.venue_for(entry, venues)
                start_value = entry.dtstart.value
                end_value = resolve_end(entry)

                # A DATE-only entry means the organiser has published the day
                # but not the time. Surfacing that honestly matters more than
                # showing a confident 00:00.
                if entry.dtstart.is_date_only or isinstance(start_value, date) and not isinstance(start_value, datetime):
                    local_start = datetime(start_value.year, start_value.month, start_value.day)
                    parsed = ParsedSession(
                        series_code=series.code,
                        season=season,
                        event_name=event_name,
                        category_code=category,
                        raw_session_name=session_name,
                        official_name=official_name,
                        venue_slug=venue_slug,
                        local_start=local_start,
                        time_status="provisional",
                        start_precision="day",
                        round_number=self.round_for(entry),
                        source_url=entry.get("URL") or document.url,
                    )
                    results.append(parsed)
                    continue

                assert isinstance(start_value, datetime)
                is_absolute = start_value.tzinfo is not None
                end_datetime = end_value if isinstance(end_value, datetime) else None

                duration_minutes: Optional[int] = None
                if end_datetime is not None:
                    duration_minutes = int((end_datetime - start_value).total_seconds() // 60) or None

                results.append(
                    ParsedSession(
                        series_code=series.code,
                        season=season,
                        event_name=event_name,
                        category_code=category,
                        raw_session_name=session_name,
                        official_name=official_name,
                        venue_slug=venue_slug,
                        start_utc=start_value if is_absolute else None,
                        local_start=None if is_absolute else start_value,
                        local_timezone=entry.dtstart.tzid,
                        end_utc=end_datetime if is_absolute else None,
                        local_end=None if is_absolute else end_datetime,
                        duration_minutes=duration_minutes,
                        time_status=self.time_status_for(entry),
                        round_number=self.round_for(entry),
                        source_url=entry.get("URL") or document.url,
                    )
                )

        return results

    def time_status_for(self, event: IcsEvent) -> str:
        status = (event.get("STATUS", "") or "").upper()
        if status == "TENTATIVE":
            return "provisional"
        summary = event.summary.lower()
        if "tbc" in summary or "tbd" in summary:
            return "tbc"
        return "confirmed"
