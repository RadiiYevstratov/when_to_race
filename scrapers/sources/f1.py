"""Formula 1, including F2, F3 and F1 Academy.

All four categories share a race weekend and must land on the same `event`, so
this source emits them with different category codes. That is what makes the
unified weekend view possible.

They do not, however, come from one place. The Grand Prix feed carries Formula 1
only; F2 and F3 are read from their own championships' race pages, and each
attends a different subset of the season - 14 rounds and 9 in 2026. So the
parser reads two formats, and then has to decide which Grand Prix each support
session belongs to.

The support pages are the official ones, and that was not the first choice. A
community ICS feed covering both was tried first and turned out to be wrong by
as much as seven hours on individual sessions, in no consistent direction -
close enough to look right on a schedule, far enough to make someone miss a
race. The official pages server-render the same JSON their own timetable draws
from, including an IANA zone and an explicit offset per session, so there is
nothing left to infer.

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

import json
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

# Which championship a support page belongs to. Site knowledge lives here
# rather than in config, which only needs to know the season index to start at.
_SUPPORT_SITES: tuple[tuple[str, str], ...] = (
    ("fiaformula2.com", "f2"),
    ("fiaformula3.com", "f3"),
)

# Round links on a season index: /en/racing/2026/monza
_ROUND_LINK = re.compile(r"/[a-z]{2}/racing/(?P<season>\d{4})/(?P<round>[a-z0-9-]+)")

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


def _naive(value: Optional[str]) -> Optional[datetime]:
    """"2026-09-04T10:00:00" as a naive datetime, to be read in the page's zone."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


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

    # --- fetching --------------------------------------------------------
    def resolve_urls(self, season: int, client) -> list[str]:
        """The Grand Prix feed, plus one page per support round.

        Which rounds a support championship attends changes from season to
        season, so the list is read from its own calendar rather than written
        down here and left to rot.
        """
        urls = [self.feed_url.format(season=season)] if self.feed_url else []

        for index_url in self.extra_urls:
            resolved = index_url.format(season=season)
            try:
                body = client.get(resolved).body.decode("utf-8", errors="replace")
            except Exception as error:  # noqa: BLE001 - one site must not sink the run
                logger.warning("f1: support index %s unavailable: %s", resolved, error)
                continue
            urls.extend(self._round_urls(resolved, body, season))

        return urls

    @staticmethod
    def _round_urls(index_url: str, body: str, season: int) -> list[str]:
        origin = "/".join(index_url.split("/")[:3])
        rounds: list[str] = []
        for match in _ROUND_LINK.finditer(body):
            if match.group("season") != str(season):
                continue
            url = f"{origin}{match.group(0)}"
            if url != index_url and url not in rounds:
                rounds.append(url)
        return rounds

    # --- parsing ---------------------------------------------------------
    def parse(
        self,
        documents: Iterable[FetchedDocument],
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
    ) -> list[ParsedSession]:
        documents = list(documents)
        calendars = [d for d in documents if d.text.lstrip().startswith("BEGIN:VCALENDAR")]
        pages = [d for d in documents if d not in calendars]

        sessions = super().parse(calendars, series, venues, season)
        for document in pages:
            sessions.extend(self._parse_support_page(document, series, season))

        return self._attach_support(sessions, series.headline_category.code)

    @staticmethod
    def _category_for_url(url: str) -> Optional[str]:
        for host, code in _SUPPORT_SITES:
            if host in url:
                return code
        return None

    @staticmethod
    def _embedded_sessions(text: str) -> list[dict]:
        """Pull the timetable out of the server-rendered page.

        The page ships the same JSON its own timetable renders from, escaped
        into the HTML. Bracket-matched rather than regexed: the array contains
        nested objects, and a lazy match would stop at the first inner bracket.
        """
        body = text.replace('\\"', '"').replace("\\u0026", "&")
        # Tolerant of whitespace around the colon: the page ships compact JSON
        # today, but a pretty-printed build should not silently empty the board.
        marker = re.search(r'"meetingSessions"\s*:\s*\[', body)
        if marker is None:
            return []
        start = marker.end() - 1
        depth = 0
        for end in range(start, len(body)):
            if body[end] == "[":
                depth += 1
            elif body[end] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(body[start : end + 1])
                    except json.JSONDecodeError:
                        return []
        return []

    def _parse_support_page(
        self, document: FetchedDocument, series: SeriesConfig, season: int
    ) -> list[ParsedSession]:
        category = self._category_for_url(document.url)
        if category is None:
            logger.warning("f1: %s belongs to no known support site", document.url)
            return []

        entries = self._embedded_sessions(document.text)
        if not entries:
            logger.warning("f1: no timetable found on %s", document.url)
            return []

        # Placeholder only: `_attach_support` replaces it with the Grand Prix
        # this round actually runs alongside.
        round_name = document.url.rstrip("/").rsplit("/", 1)[-1]

        results: list[ParsedSession] = []
        for entry in entries:
            start = entry.get("startTime")
            if not start:
                continue
            name = (entry.get("shortName") or entry.get("session") or "").strip()
            if not name:
                continue

            local_start = _naive(start)
            local_end = _naive(entry.get("endTime"))

            # The published end is occasionally earlier than the published
            # start - F3 at the Red Bull Ring has a sprint race ending the day
            # before it begins. The start is still credible, so only the end is
            # dropped: a session with no end time is already handled everywhere,
            # and correcting the date would be inventing one.
            if local_start and local_end and local_end <= local_start:
                logger.warning(
                    "f1: %s %r ends before it starts (%s -> %s); end discarded",
                    category,
                    name,
                    start,
                    entry.get("endTime"),
                )
                local_end = None

            results.append(
                ParsedSession(
                    series_code=series.code,
                    season=season,
                    event_name=round_name,
                    category_code=category,
                    raw_session_name=name,
                    # Naive local time plus the circuit's own zone, which the
                    # page states outright - no offset arithmetic to get wrong.
                    local_start=local_start,
                    local_end=local_end,
                    local_timezone=entry.get("timezone") or None,
                    sequence_hint=entry.get("sessionNumber") or None,
                    source_url=document.url,
                )
            )
        return results

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