"""Formula 1, including F2, F3 and F1 Academy.

All four categories share a race weekend and must land on the same `event`, so
this source emits them with different category codes. That is what makes the
unified weekend view possible.

They do not, however, come from one feed. The Grand Prix feed carries Formula 1
only; F2, F3 and F1 Academy are published separately, in a different summary
shape, and each attends a different subset of the season - 14 rounds, 9 and 6
respectively in 2026. So the parser reads two dialects, and then has to decide
which Grand Prix each support session belongs to.

That decision is made on time, not on names, and the difference matters. The
support feeds name their rounds "Australian", "USA", "Zandvoort", "Spanish" -
which do not match the Grand Prix names, collide with each other (2026 has two
Spanish rounds, Barcelona and Madrid), and would put "USA" on the United States
GP when the feed actually means Miami. A session that runs inside a Grand Prix
weekend belongs to it, and that is checkable rather than guessable.

Discovery status: UNVERIFIED. No endpoint has been confirmed - see
docs/sources.md#formula-1 for the procedure and for what to record. Set
`source.url` and `source.status = "live"` in config/series.toml once it is done.
The parsing below is exercised against scrapers/fixtures/f1_sample.ics, so the
shape it expects is explicit and checkable rather than assumed.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ..config import SeriesConfig, VenueConfig
from ..ics import IcsEvent
from ..records import ParsedSession
from .base import FetchedDocument, register
from .ics_source import IcsSource

logger = logging.getLogger(__name__)

# Ordered: "F1 ACADEMY" must be tested before "F1", or Academy sessions land in
# the F1 category and silently double the Grand Prix schedule. The separator is
# a character class rather than \s* because the feed writes "F1-ACADEMY", and a
# whitespace-only separator misses that - silently, because the entry then
# matches the plain "f1" alternative on the line below.
_CATEGORY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(f1[\s-]*academy|formula\s*1[\s-]*academy)\b", re.IGNORECASE), "f1a"),
    (re.compile(r"\b(formula\s*3|f3)\b", re.IGNORECASE), "f3"),
    (re.compile(r"\b(formula\s*2|f2)\b", re.IGNORECASE), "f2"),
    (re.compile(r"\b(formula\s*(1|one)|f1|grand\s*prix|gran\s*premio|gp)\b", re.IGNORECASE), "f1"),
)

_CATEGORY_PREFIX = re.compile(
    r"^\s*(fia\s+)?(f1[\s-]*academy|formula\s*1[\s-]*academy|formula\s*3|formula\s*2|"
    r"formula\s*(1|one)|f3|f2|f1)\b[\s:–—-]*",
    re.IGNORECASE,
)

# The support feeds write "F2: Feature (Italian)" - category, session, then the
# round in brackets. Nothing like the Grand Prix feed's "Italian GP: Race", and
# splitting it on ": " like that one would yield an event called "F2".
_SUPPORT_SUMMARY = re.compile(
    r"^\s*(?:f1[\s-]*academy|formula\s*1[\s-]*academy|f2|f3|formula\s*[23])\s*:\s*"
    r"(?P<session>.+?)\s*\((?P<round>[^)]+)\)\s*$",
    re.IGNORECASE,
)

# How far a support session may sit from a Grand Prix and still count as part of
# it. Three days rather than one because Monaco runs Formula 3 on the Thursday,
# before Formula 1 has turned a wheel - with a tighter window that practice
# missed its weekend by five minutes.
_SUPPORT_MAX_GAP = timedelta(days=3)


@dataclass
class _Weekend:
    """A Grand Prix, as a span of time to test support sessions against."""

    event_name: str
    start: datetime
    end: datetime
    venue_slug: Optional[str]
    round_number: Optional[int]

    def gap_to(self, when: datetime) -> timedelta:
        if self.start <= when <= self.end:
            return timedelta(0)
        return min(abs(when - self.start), abs(when - self.end))


# Sponsor noise that appears in official event titles. Removed from `name`,
# preserved in `official_name`.
_SPONSOR_NOISE = re.compile(
    r"\b(pirelli|rolex|heineken|aramco|qatar\s+airways|msc\s+cruises|lenovo|"
    r"louis\s+vuitton|stc|gulf\s+air|crypto\.com|aws)\b",
    re.IGNORECASE,
)


def strip_decoration(value: str) -> str:
    """Remove emoji and other pictographs from a feed's display strings.

    Some feeds decorate every entry - flags on the event, a wrench on practice,
    a chequered flag on the race. Useful in a calendar app, noise in a database:
    it would end up in display_name, in the slug, and in the calendar UID.
    Category "So" covers pictographs and regional-indicator flag letters;
    "Cf" and the variation selectors cover the invisible modifiers that follow
    them.
    """
    cleaned = "".join(
        char
        for char in value
        if unicodedata.category(char) not in ("So", "Cf") and char not in ("\ufe0f", "\ufe0e")
    )
    return re.sub(r"\s{2,}", " ", cleaned).strip()


class FormulaOneSource(IcsSource):
    series_code = "f1"

    # Free-text locations from the source mapped onto the venue registry.
    # Site-specific knowledge belongs here, never in normalize.
    venue_aliases = {
        "bahrain": "sakhir",
        "sakhir": "sakhir",
        "saudi arabia": "jeddah",
        "jeddah": "jeddah",
        "australia": "melbourne",
        "albert park": "melbourne",
        "melbourne": "melbourne",
        "japan": "suzuka",
        "suzuka": "suzuka",
        "china": "shanghai",
        "shanghai": "shanghai",
        "miami": "miami",
        "emilia-romagna": "imola",
        "emilia romagna": "imola",
        "imola": "imola",
        "monaco": "monaco",
        "monte carlo": "monaco",
        "canada": "montreal",
        "montreal": "montreal",
        "barcelona": "barcelona",
        "catalunya": "barcelona",
        # Spain has two rounds from 2026: Barcelona and the new Madrid circuit.
        # "spain" alone is ambiguous, so it is deliberately not an alias.
        "madrid": "madrid",
        "madring": "madrid",
        "austria": "red_bull_ring",
        "spielberg": "red_bull_ring",
        "great britain": "silverstone",
        "british": "silverstone",
        "silverstone": "silverstone",
        "hungary": "hungaroring",
        "budapest": "hungaroring",
        "belgium": "spa",
        "spa-francorchamps": "spa",
        "netherlands": "zandvoort",
        "zandvoort": "zandvoort",
        "italy": "monza",
        "italia": "monza",
        "monza": "monza",
        "azerbaijan": "baku",
        "baku": "baku",
        "singapore": "singapore",
        "united states": "cota",
        "austin": "cota",
        "circuit of the americas": "cota",
        "mexico": "mexico_city",
        "brazil": "interlagos",
        "sao paulo": "interlagos",
        "são paulo": "interlagos",
        "interlagos": "interlagos",
        "las vegas": "las_vegas",
        "qatar": "lusail",
        "lusail": "lusail",
        "abu dhabi": "yas_marina",
        "yas marina": "yas_marina",
    }

    def category_for(self, summary: str, series: SeriesConfig) -> Optional[str]:
        for pattern, code in _CATEGORY_PATTERNS:
            if pattern.search(summary):
                return code
        # An entry we cannot attribute is dropped rather than guessed into F1.
        return None

    def split_summary(self, summary: str) -> tuple[str, str]:
        text = strip_decoration(summary)

        # A support entry names its round in brackets. That name is provisional:
        # `parse` replaces it with the Grand Prix this session actually runs at.
        support = _SUPPORT_SUMMARY.match(text)
        if support:
            return support.group("round").strip(), support.group("session").strip()

        for separator in (" - ", " – ", " — ", ": "):
            if separator in text:
                head, _, tail = text.rpartition(separator)
                return head.strip(), tail.strip()
        return text, text

    def clean_event_name(self, event_name: str, season: int) -> str:
        text = _CATEGORY_PREFIX.sub("", strip_decoration(event_name))
        text = _SPONSOR_NOISE.sub("", text)
        text = text.replace(str(season), "")
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip(" -–—:")

    # --- attaching the support championships ------------------------------
    def parse(
        self,
        documents: Iterable[FetchedDocument],
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
    ) -> list[ParsedSession]:
        sessions = super().parse(documents, series, venues, season)
        return self._attach_support(sessions, series.headline_category.code)

    def _attach_support(
        self, sessions: list[ParsedSession], headline: str
    ) -> list[ParsedSession]:
        """Re-file every support session onto the Grand Prix it runs at."""
        grands_prix = [item for item in sessions if item.category_code == headline]
        support = [item for item in sessions if item.category_code != headline]
        if not support:
            return sessions

        weekends = self._weekends(grands_prix)
        if not weekends:
            # Without the Grand Prix feed there is nothing to attach to, and a
            # support session on its own would invent a half-empty event under
            # a name like "Australian". Drop them and let the session-count
            # floor fail the run, which is the honest signal.
            logger.warning(
                "f1: %d support sessions dropped - no Grand Prix weekends parsed",
                len(support),
            )
            return grands_prix

        attached: list[ParsedSession] = []
        unplaced = 0
        for item in support:
            weekend = self._weekend_for(item, weekends)
            if weekend is None:
                unplaced += 1
                continue
            attached.append(
                replace(
                    item,
                    event_name=weekend.event_name,
                    venue_slug=weekend.venue_slug,
                    round_number=weekend.round_number,
                    # The Grand Prix owns the event's sponsor-laden title; a
                    # support entry has no business setting it.
                    official_name=None,
                )
            )

        if unplaced:
            logger.warning(
                "f1: %d support sessions did not fall within %d days of any "
                "Grand Prix and were dropped",
                unplaced,
                _SUPPORT_MAX_GAP.days,
            )

        return grands_prix + attached

    @staticmethod
    def _weekends(grands_prix: list[ParsedSession]) -> list[_Weekend]:
        """One span per Grand Prix, from its own sessions.

        Only absolute times are used. A date-only entry - a feed publishing the
        day but not the hour - would stretch a weekend across midnight in an
        arbitrary zone and pull in neighbouring sessions.
        """
        spans: dict[str, _Weekend] = {}
        for item in grands_prix:
            if item.start_utc is None:
                continue
            end = item.end_utc or item.start_utc
            existing = spans.get(item.event_name)
            if existing is None:
                spans[item.event_name] = _Weekend(
                    event_name=item.event_name,
                    start=item.start_utc,
                    end=end,
                    venue_slug=item.venue_slug,
                    round_number=item.round_number,
                )
                continue
            existing.start = min(existing.start, item.start_utc)
            existing.end = max(existing.end, end)
            if existing.venue_slug is None:
                existing.venue_slug = item.venue_slug
            if existing.round_number is None:
                existing.round_number = item.round_number
        return list(spans.values())

    @staticmethod
    def _match_instant(session: ParsedSession) -> Optional[datetime]:
        """The instant to test a session against a weekend span.

        A date-only entry has no absolute time, only a naive local date. Reading
        that as UTC is wrong by at most the circuit's offset - hours, against a
        window measured in days - so it still lands on the right weekend, and
        refusing to place it would discard precisely the sessions whose times
        the organiser has not published yet.
        """
        if session.start_utc is not None:
            return session.start_utc
        if session.local_start is not None:
            return session.local_start.replace(tzinfo=timezone.utc)
        return None

    @classmethod
    def _weekend_for(
        cls, session: ParsedSession, weekends: list[_Weekend]
    ) -> Optional[_Weekend]:
        """The nearest Grand Prix, or None rather than a guess."""
        when = cls._match_instant(session)
        if when is None:
            return None
        nearest = min(weekends, key=lambda weekend: weekend.gap_to(when))
        if nearest.gap_to(when) > _SUPPORT_MAX_GAP:
            return None
        return nearest

    def round_for(self, event: IcsEvent) -> Optional[int]:
        for field in (event.get("DESCRIPTION", ""), event.summary):
            match = re.search(r"\bround\s*(\d{1,2})\b", field or "", re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    def skip(self, event: IcsEvent) -> bool:
        if not event.summary.strip():
            return True
        summary = event.summary.lower()
        # Feeds routinely carry non-session entries. Keeping them would inflate
        # session counts and defeat the validation floor.
        return any(word in summary for word in ("tickets", "fan zone", "concert", "paddock club"))


@register("f1")
def build(
    feed_url: Optional[str] = None, extra_urls: Iterable[str] = ()
) -> FormulaOneSource:
    return FormulaOneSource(feed_url=feed_url, extra_urls=extra_urls)