"""NTT IndyCar Series.

Source: indycar.com's own schedule pages. The season page lists the rounds and
each round page carries its weekend timetable, so this is two-stage and
implements ``resolve_urls`` (see scrapers/sources/base.py).

This is the first source here that is **plain HTML** - the last resort in the
discovery order. There is nothing better to fall back to: the site is
server-rendered end to end, so there is no internal JSON API to read, no
`__NEXT_DATA__`, no JSON-LD, and no calendar feed. What it does have is a
consistent markup shape, which is what this parses:

    <div class="schedule-table">
      <h3>Friday, Aug 28</h3>
      <div class="schedule-entry">
        <div class="schedule-time">6:00PM ET</div>
        <div class="schedule-description">NTT INDYCAR SERIES - Practice</div>

Being brittle by nature, it fails loudly rather than quietly: a round page that
yields no sessions is logged, and the validation floor turns a site redesign
into a failed run instead of a silently empty calendar.

**The timezone is the important part, and it is not the circuit's.** Every time
on the site is published in US Eastern regardless of where the race is - Portland
practice reads "5:30PM ET". That is unusual enough to be worth stating twice,
because treating it as circuit-local would put every West Coast session three
hours wrong. Verified against the official weekend-schedule PDF for Laguna Seca,
which prints "All times local (Pacific)" and lists Practice 1 at 2:00 PM against
the site's 5:00PM ET - the same instant.

So this adapter resolves Eastern to an absolute UTC instant itself, rather than
handing normalize a naive local time. Sources are otherwise meant to leave
timezones alone, and the distinction matters: reading a stamp the source itself
states is parsing, while deciding what zone a *circuit* is in is normalize's job
with the venue registry, and that stays where it belongs. Passing "ET" through as
`local_timezone` would be actively wrong - normalize reads that as a display
override, and every Portland session would then be shown to a viewer in Eastern.

Three source quirks, all found by reading the whole season rather than one page:

  1. **A session can be listed twice, once per broadcaster.** Indianapolis 500
     practice appears at 12:00PM on FS2 and again at 4:00PM on FS1 - one session
     running from noon, two television windows. Both stored would put a second
     "Practice 1" on the board at an hour nothing starts.

  2. **A doubleheader is published as two rounds sharing one weekend.** Milwaukee
     Race 1 and Race 2 have their own pages, each listing some of the same
     sessions - qualifying appears on both. They are one weekend at one track.

  3. **The day headings carry no year.** "Friday, Aug 28" is all there is, so the
     year comes from the season being scraped - and is then checked against the
     weekday the heading names, which is a free integrity test on both the year
     and the page's freshness.

Indy NXT is configured as a category but is not published here: its own site
lists no session times at all, and on indycar.com its sessions appear only in
the per-round PDFs. A category with no source is left empty rather than filled
from a worse one.
"""

from __future__ import annotations

import calendar
import logging
import re
from datetime import datetime
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from ..config import SeriesConfig, VenueConfig
from ..records import ParsedSession
from .base import FetchedDocument, register

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULE_URL = "https://www.indycar.com/Schedule"
_BASE = "https://www.indycar.com"

# Round links on the season page, e.g. /Schedule/2026/Mid-Ohio. The season is
# matched rather than assumed: the page also links previous years.
_ROUND_LINK = re.compile(r'href="(/Schedule/(?P<season>\d{4})/[A-Za-z0-9\-]+)"')

# A day heading, a time, or a description. Matched together and in document
# order, because the day a session belongs to is the last heading above it.
_TOKEN = re.compile(
    r"<h3[^>]*>(?P<day>.*?)</h3>"
    r'|<div class="schedule-time">(?P<time>.*?)</div>'
    r'|<div class="schedule-description">(?P<desc>.*?)</div>',
    re.S,
)
_TABLE = re.compile(r'<div class="schedule-table">(.*)', re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_TAG = re.compile(r"<[^>]+>")

# "Friday, Aug 28" and "6:00PM ET".
_DAY = re.compile(r"^(?P<weekday>[A-Za-z]+),\s*(?P<month>[A-Za-z]+)\s+(?P<dom>\d{1,2})$")
_TIME = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<meridiem>AM|PM)\s*(?P<zone>[A-Z]{2,3})$", re.I)

# The site publishes in Eastern everywhere, but the label is read rather than
# assumed - if a page ever says CT, this must not silently treat it as ET.
_ZONES = {
    "ET": "America/New_York",
    "CT": "America/Chicago",
    "MT": "America/Denver",
    "PT": "America/Los_Angeles",
    "AKT": "America/Anchorage",
    "HT": "Pacific/Honolulu",
}

_MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_abbr) if name}
_MONTHS.update({name.lower(): number for number, name in enumerate(calendar.month_name) if name})
_WEEKDAYS = {name.lower(): number for number, name in enumerate(calendar.day_name)}

# Round token -> venue slug. Keyed on the URL token because it is the one part
# of a round that a title sponsor cannot rename: the page heading for Barber is
# "Children's of Alabama Indy Grand Prix", which names neither the circuit nor
# the city.
_VENUE_BY_ROUND = {
    "st-petersburg": "st_petersburg",
    "phoenix": "phoenix",
    "arlington": "arlington",
    "barber": "barber",
    "long-beach": "long_beach",
    "indianapolis": "indianapolis",
    "indianapolis-500": "indianapolis",
    "detroit": "detroit",
    "wwtr": "wwtr",
    "road-america": "road_america",
    "mid-ohio": "mid_ohio",
    "laguna-seca": "laguna_seca",
    "nashville": "nashville_superspeedway",
    "portland": "portland",
    "markham": "markham",
    "washington-dc": "washington_dc",
    "milwaukee": "milwaukee",
}

# The class a schedule row belongs to, from the prefix the site puts before the
# session name. Rows with no prefix are IndyCar's own; see `_split_description`.
_CLASS_PREFIXES = {
    "ntt indycar series": "indycar",
    "indycar": "indycar",
    "indy nxt by firestone": "indynxt",
    "indy nxt": "indynxt",
}

# A doubleheader is two championship rounds on one weekend at one track, and the
# site gives each its own page listing overlapping sessions. Both fold into one
# event, which is what a weekend view is for.
_DOUBLEHEADER = re.compile(r"-race\d+$", re.I)


class IndyCarSource:
    series_code = "indycar"
    detail_level = "full"

    def __init__(self, schedule_url: Optional[str] = None):
        self.schedule_url = (schedule_url or DEFAULT_SCHEDULE_URL).rstrip("/")

    def resolve_urls(self, season: int, client) -> list[str]:
        """The season page lists the rounds; each round page holds a timetable."""
        try:
            body = client.get(self.schedule_url).body.decode("utf-8", errors="replace")
        except Exception as error:  # noqa: BLE001 - reported, not raised
            logger.warning("indycar: schedule index %s unavailable: %s", self.schedule_url, error)
            return []

        paths: list[str] = []
        for match in _ROUND_LINK.finditer(body):
            if int(match.group("season")) != season:
                continue
            path = match.group(1)
            if path not in paths:
                paths.append(path)

        if not paths:
            # The index only ever carries the current season, so this is the
            # normal answer for a past or future year rather than a failure.
            logger.warning("indycar: no %s rounds linked from %s", season, self.schedule_url)
        return [_BASE + path for path in paths]

    def parse(
        self,
        documents: Iterable[FetchedDocument],
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
    ) -> list[ParsedSession]:
        # Collapsing happens across the whole season rather than per page,
        # because the two things it has to catch differ only in where the
        # duplicate comes from: one session listed twice on a page for two
        # broadcasters, and one session listed on both pages of a doubleheader.
        # Keyed by event, day, class and name, and the earliest time wins.
        earliest: dict[tuple[str, str, str, str], ParsedSession] = {}
        order: list[tuple[str, str, str, str]] = []

        for document in documents:
            self._parse_round(document, series, venues, season, earliest, order)
        return [earliest[key] for key in order]

    def _parse_round(
        self,
        document: FetchedDocument,
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
        earliest: dict[tuple[str, str, str, str], ParsedSession],
        order: list[tuple[str, str, str, str]],
    ) -> None:
        token = document.url.rstrip("/").rsplit("/", 1)[-1].lower()
        # Both Milwaukee pages become one event named for the weekend, not for
        # either race.
        event_name = _DOUBLEHEADER.sub("", token)
        venue_slug = _VENUE_BY_ROUND.get(event_name)
        if venue_slug is None or venue_slug not in venues:
            logger.warning("indycar: round %s maps to no known venue; sessions dropped", token)
            return

        official_name = None
        heading = _H1.search(document.text)
        if heading:
            official_name = _clean(heading.group(1)) or None

        rows = _schedule_rows(document.text)
        if not rows:
            logger.warning("indycar: no schedule found on %s", document.url)
            return

        for day_text, time_text, description in rows:
            category_code, name = _split_description(description)
            if category_code is None or not name:
                continue

            day = _parse_day(day_text, season)
            if day is None:
                logger.warning(
                    "indycar: %s heading %r is not a %s date; sessions under it dropped",
                    token,
                    day_text,
                    season,
                )
                continue

            start = _parse_start(day, time_text)
            if start is None:
                logger.warning("indycar: %s has an unreadable time %r for %r", token, time_text, name)
                continue

            key = (event_name, day.isoformat(), category_code, name.lower())
            existing = earliest.get(key)
            if existing is not None:
                if start < existing.start_utc:
                    existing.start_utc = start
                continue

            session = ParsedSession(
                series_code=series.code,
                season=season,
                event_name=event_name,
                category_code=category_code,
                raw_session_name=name,
                official_name=official_name,
                venue_slug=venue_slug,
                start_utc=start,
                # No end times anywhere on the site, and no way to tell a
                # confirmed time from a provisional one - so, as for every other
                # source that stays silent on it, these are taken as confirmed.
                end_utc=None,
                time_status="confirmed",
                source_url=document.url,
            )
            earliest[key] = session
            order.append(key)


def _clean(value: str) -> str:
    """Tag-stripped, entity-decoded, whitespace-collapsed text."""
    text = _TAG.sub(" ", value)
    for entity, character in (
        ("&amp;", "&"),
        ("&#39;", "'"),
        ("&rsquo;", "'"),
        ("&quot;", '"'),
        ("&nbsp;", " "),
        ("&ndash;", "-"),
        ("&mdash;", "-"),
    ):
        text = text.replace(entity, character)
    return " ".join(text.split())


def _schedule_rows(text: str) -> list[tuple[str, str, str]]:
    """(day heading, time, description) for every entry on a round page."""
    table = _TABLE.search(text)
    if not table:
        return []

    rows: list[tuple[str, str, str]] = []
    day = ""
    pending: Optional[str] = None
    for token in _TOKEN.finditer(table.group(1)):
        if token.group("day") is not None:
            day = _clean(token.group("day"))
        elif token.group("time") is not None:
            pending = _clean(token.group("time"))
        elif token.group("desc") is not None:
            if pending is not None and day:
                rows.append((day, pending, _clean(token.group("desc"))))
            pending = None
    return rows


def _split_description(description: str) -> tuple[Optional[str], str]:
    """The class and session name in "NTT INDYCAR SERIES - Practice 1".

    An entry with no prefix is kept only when its name reads as a session on its
    own. Most of them are IndyCar's, written without the prefix - Phoenix
    publishes a bare "Practice 1" - but the schedule also carries things that are
    not sessions at all, and at Indianapolis those include a hot dog race. An
    entry has to either name its class or be recognisably a session; naming
    neither is not enough to put a chip on the board.
    """
    head, separator, tail = description.partition(" - ")
    if separator:
        category_code = _CLASS_PREFIXES.get(head.strip().lower())
        if category_code is not None:
            return category_code, tail.strip()

    if re.match(r"^(practice|qualif|race|warm|final practice|fast friday)", description.strip(), re.I):
        return "indycar", description.strip()
    return None, ""


def _parse_day(text: str, season: int):
    """The date a heading like "Friday, Aug 28" names, in the season given.

    The weekday is the check that makes borrowing the year safe: if the date
    does not fall on the day the page says it does, the assumption is wrong or
    the page is stale, and either way it is not something to publish.
    """
    match = _DAY.match(text)
    if not match:
        return None
    month = _MONTHS.get(match.group("month").lower())
    weekday = _WEEKDAYS.get(match.group("weekday").lower())
    if month is None or weekday is None:
        return None
    try:
        day = datetime(season, month, int(match.group("dom"))).date()
    except ValueError:
        return None
    return day if day.weekday() == weekday else None


def _parse_start(day, text: str) -> Optional[datetime]:
    """"6:00PM ET" on a given day, as an absolute instant."""
    match = _TIME.match(text)
    if not match:
        return None
    zone_name = _ZONES.get(match.group("zone").upper())
    if zone_name is None:
        return None

    hour = int(match.group("hour")) % 12
    if match.group("meridiem").upper() == "PM":
        hour += 12
    local = datetime(day.year, day.month, day.day, hour, int(match.group("minute")))
    return local.replace(tzinfo=ZoneInfo(zone_name)).astimezone(ZoneInfo("UTC"))


@register("indycar")
def build(feed_url: Optional[str] = None) -> IndyCarSource:
    # `feed_url` is what the runner passes from config/series.toml's source.url;
    # here it is the season index the rounds are discovered from.
    return IndyCarSource(schedule_url=feed_url)
