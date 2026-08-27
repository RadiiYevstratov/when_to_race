"""IMSA: the WeatherTech SportsCar Championship and the Michelin Pilot Challenge.

Source: imsa.com's own event pages, discovered through the site's WordPress REST
API. Two stages, so this implements ``resolve_urls`` (see
scrapers/sources/base.py): `/wp-json/wp/v2/schedule` lists every event as a post
with a link, and each event page carries its weekend timetable.

The API lists events but does not carry their sessions - `content` comes back
empty and `meta` is bare - so the timetable is read from the page markup, the
fourth option in the discovery order. There is no session-level API to prefer:
the only other namespace the site exposes is `rapi/v1/allresults`, which is
results and therefore out of scope here entirely.

What the page gives is better than most:

    <div class="day-event-header">Friday, June 26, 2026</div>
    <div class="day-event-details-container">
      <div class='event-time'>11:25 AM to 12:55 PM ET</div>
      <div class='event-name'>Practice 1 - WeatherTech Championship</div>

Dates carry their year, and **every session has an end time** - which puts this
alongside WEC and WorldSBK rather than with the other American sources, and
matters most for the endurance rounds a generic duration would badly misjudge.

**Times are US Eastern for every circuit**, as at IndyCar, and this was verified
rather than assumed. IMSA and IndyCar share the Long Beach street circuit on one
weekend, and two championships cannot be on one track at the same time. Reading
IMSA's times as Eastern, its nine sessions there interleave with IndyCar's with
no overlap at all; reading them as Pacific puts three of them on top of IndyCar
sessions, including the Grand Prix of Long Beach running during IndyCar
qualifying. IndyCar's own times at that weekend are Eastern, checked separately
against an official schedule PDF. So the label is the truth and the adapter
resolves it to an absolute instant here, for the reasons set out in indycar.py.

Naming the class is the part that needs care, because the page says it three
different ways:

    "Practice 1 - WeatherTech Championship"   the class after the session
    "WeatherTech Championship Qualifying"     the class before it
    "Sahlen's Six Hours of The Glen"          neither

The third is the problem: a named race says nothing about which championship it
belongs to, and a weekend has two of them - at Watkins Glen the Six Hours is the
WeatherTech race and the "LP Building Solutions 120" is the Pilot Challenge's.
Guessing from the distance would be guessing. The page answers it elsewhere,
though: the broadcast schedule lists the same races with their championship's
logo beside them, so the class is read from there and matched back by name. Only
the class is taken from the broadcast section - never the times, which differ by
a few minutes because coverage starts before the session does.

IMSA's weekends also carry Porsche Carrera Cup, Lamborghini Super Trofeo,
Mazda MX-5 Cup, Mustang Challenge and VP Racing SportsCar Challenge. They are
real championships and none of them is configured here, so their sessions are
dropped rather than filed under a class they do not belong to.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from ..config import SeriesConfig, VenueConfig
from ..records import ParsedSession
from .base import FetchedDocument, register

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://www.imsa.com/wp-json/wp/v2/schedule"
_API_PAGES = 3  # 214 posts at 100 a page, and the count only grows slowly

# The event schedule. Matched together and in document order, because the day a
# session belongs to is the last heading above it.
_TOKEN = re.compile(
    r'<div class="day-event-header">(?P<day>.*?)</div>'
    r"|<div class='event-time'>(?P<time>.*?)</div>\s*<div class='event-name'>(?P<name>.*?)</div>",
    re.S,
)

# The broadcast schedule, which is where a named race admits its championship.
_BROADCAST = re.compile(r'<div class="race-event-item">(.*?)</div>\s*</div>', re.S)
_IMAGES = re.compile(r'src="([^"]+)"')
_TAG = re.compile(r"<[^>]+>")

_TIME = re.compile(
    r"^(?P<h1>\d{1,2}):(?P<m1>\d{2})\s*(?P<ap1>AM|PM)\s*to\s*"
    r"(?P<h2>\d{1,2}):(?P<m2>\d{2})\s*(?P<ap2>AM|PM)\s*(?P<zone>[A-Z]{2,3})$",
    re.I,
)

_ZONES = {
    "ET": "America/New_York",
    "CT": "America/Chicago",
    "MT": "America/Denver",
    "PT": "America/Los_Angeles",
}

# How the page names a championship -> our category code. Written as the site
# writes it; the site's own shorthand is not our config's.
_CLASSES = {
    "weathertech championship": "imsa_wtsc",
    "weathertech sportscar championship": "imsa_wtsc",
    "michelin pilot challenge": "imsa_mpc",
    "imsa michelin pilot challenge": "imsa_mpc",
}

# Championship logo filename -> category code, for the broadcast lookup.
_CLASS_LOGOS = {
    "weathertech_championship": "imsa_wtsc",
    "michelinpc": "imsa_mpc",
}

# A phrase in the event's title -> venue slug. Titles are "2026 Watkins Glen
# International" or "2026 Rolex 24 At DAYTONA", so a name match alone does not
# reach - the race is often more famous than the circuit it is held at.
_VENUE_BY_TITLE = {
    "daytona": "daytona",
    "sebring": "sebring",
    "long beach": "long_beach",
    "laguna seca": "laguna_seca",
    "detroit": "detroit",
    "watkins glen": "watkins_glen",
    "canadian tire": "mosport",
    "mosport": "mosport",
    "road america": "road_america",
    "virginia international": "vir",
    "indianapolis": "indianapolis",
    "road atlanta": "road_atlanta",
    "mid-ohio": "mid_ohio",
    "thermal": "thermal_club",
    "sonoma": "sonoma",
    "circuit of the americas": "cota",
    "st. petersburg": "st_petersburg",
}


class ImsaSource:
    series_code = "imsa"
    detail_level = "full"

    def __init__(self, api_url: Optional[str] = None):
        self.api_url = (api_url or DEFAULT_API_URL).rstrip("/")

    def resolve_urls(self, season: int, client) -> list[str]:
        """Every event page for the season, from the site's own post list."""
        links: list[str] = []
        for page in range(1, _API_PAGES + 1):
            url = f"{self.api_url}?per_page=100&page={page}"
            try:
                body = client.get(url).body
            except Exception as error:  # noqa: BLE001 - reported, not raised
                logger.warning("imsa: event index %s unavailable: %s", url, error)
                break

            try:
                posts = json.loads(body)
            except json.JSONDecodeError:
                logger.warning("imsa: event index %s is not JSON", url)
                break
            if not posts:
                break

            for post in posts:
                title = _clean((post.get("title") or {}).get("rendered", ""))
                slug = post.get("slug") or ""
                link = post.get("link")
                # The season appears in the title of every event, and in most
                # slugs. Both are checked because Sebring's slug puts the year
                # in the middle of the race name instead.
                if link and (str(season) in title or str(season) in slug):
                    if link not in links:
                        links.append(link)

        if not links:
            logger.warning("imsa: no %s events found via %s", season, self.api_url)
        return links

    def parse(
        self,
        documents: Iterable[FetchedDocument],
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
    ) -> list[ParsedSession]:
        results: list[ParsedSession] = []
        for document in documents:
            results.extend(self._parse_event(document, series, venues, season))
        return results

    def _parse_event(
        self,
        document: FetchedDocument,
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
    ) -> list[ParsedSession]:
        text = document.text
        title = _title(text)
        if not title:
            logger.warning("imsa: %s has no title", document.url)
            return []

        event_name = _strip_season(title, season)
        venue_slug = _venue_for(title)
        if venue_slug is None or venue_slug not in venues:
            logger.warning("imsa: %r maps to no known venue; sessions dropped", title)
            return []

        by_broadcast = _classes_by_broadcast(text)
        results: list[ParsedSession] = []

        for day_text, time_text, raw_name in _schedule_rows(text):
            category_code, name = _split_name(raw_name, by_broadcast)
            if category_code is None:
                continue  # a championship this project does not carry

            day = _parse_day(day_text)
            if day is None:
                logger.warning("imsa: %s heading %r is not a date", event_name, day_text)
                continue
            if day.year != season:
                continue  # an event page kept up from another year

            span = _parse_span(day, time_text)
            if span is None:
                logger.warning("imsa: %s has an unreadable time %r for %r", event_name, time_text, name)
                continue
            start, end = span

            results.append(
                ParsedSession(
                    series_code=series.code,
                    season=season,
                    event_name=event_name,
                    category_code=category_code,
                    raw_session_name=name,
                    venue_slug=venue_slug,
                    start_utc=start,
                    end_utc=end,
                    # No provisional marker anywhere on the site; a published
                    # session is taken as confirmed, as for every other source
                    # that stays silent on it.
                    time_status="confirmed",
                    source_url=document.url,
                )
            )

        return results


def _clean(value: str) -> str:
    text = _TAG.sub(" ", value)
    for entity, character in (
        ("&#8211;", "-"),
        ("&#038;", "&"),
        ("&amp;", "&"),
        ("&#8217;", "'"),
        ("&rsquo;", "'"),
        ("&nbsp;", " "),
    ):
        text = text.replace(entity, character)
    return " ".join(text.split())


def _title(text: str) -> str:
    match = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
    if not match:
        return ""
    # "2026 Watkins Glen International | IMSA"
    return _clean(match.group(1)).split("|")[0].strip()


def _strip_season(title: str, season: int) -> str:
    """"2026 Rolex 24 At DAYTONA" -> "Rolex 24 At DAYTONA".

    The season is already in the URL a weekend is reached by, so repeating it in
    the name puts it on the page twice.
    """
    return re.sub(rf"^{season}\s+", "", title).strip() or title


def _venue_for(title: str) -> Optional[str]:
    needle = title.lower()
    for phrase, slug in _VENUE_BY_TITLE.items():
        if phrase in needle:
            return slug
    return None


def _schedule_rows(text: str) -> list[tuple[str, str, str]]:
    """(day heading, time span, session name) for the event schedule."""
    rows: list[tuple[str, str, str]] = []
    day = ""
    for token in _TOKEN.finditer(text):
        if token.group("day") is not None:
            day = _clean(token.group("day"))
        elif day:
            rows.append((day, _clean(token.group("time")), _clean(token.group("name"))))
    return rows


def _classes_by_broadcast(text: str) -> dict[str, str]:
    """Session name -> category, learned from the broadcast schedule's logos.

    A named race - "Sahlen's Six Hours of The Glen" - says nothing about which
    championship it belongs to, and a weekend has one for each. The broadcast
    listing puts the championship's logo next to the same race, which is the
    page answering the question somewhere else on itself.

    Only the class is taken from here. The times are not: broadcast coverage
    starts a few minutes before the session does, and using those would move
    every named race a little earlier than it runs.
    """
    found: dict[str, str] = {}
    for block in _BROADCAST.finditer(text):
        chunk = block.group(1)
        category_code = None
        for image in _IMAGES.findall(chunk):
            filename = image.rsplit("/", 1)[-1].lower()
            for marker, code in _CLASS_LOGOS.items():
                if marker in filename:
                    category_code = code
                    break
            if category_code:
                break
        if category_code is None:
            continue

        label = _clean(chunk.split("race-logos")[-1] if "race-logos" in chunk else chunk)
        # The label trails a broadcast note - "(Available Globally)" - and opens
        # with the leftovers of the attribute the split cut through.
        label = re.sub(r"^[\">\s]+", "", label)
        label = re.sub(r"\s*\([^)]*\)\s*$", "", label).strip()
        if label:
            found.setdefault(label.lower(), category_code)
    return found


def _split_name(raw_name: str, by_broadcast: dict[str, str]) -> tuple[Optional[str], str]:
    """The class this row belongs to, and the session name without it."""
    head, separator, tail = raw_name.rpartition(" - ")
    if separator and tail.strip().lower() in _CLASSES:
        return _CLASSES[tail.strip().lower()], head.strip()

    lowered = raw_name.lower()
    for phrase, code in _CLASSES.items():
        if lowered.startswith(phrase):
            return code, raw_name[len(phrase) :].strip() or raw_name

    # A named race. The broadcast listing is the only thing on the page that
    # says whose it is, and if it does not say, this stays unclassified rather
    # than being filed under a guess.
    code = by_broadcast.get(lowered)
    if code is not None:
        return code, raw_name
    return None, ""


def _parse_day(text: str):
    """"Friday, June 26, 2026" - and this source states its year, unlike IndyCar."""
    try:
        return datetime.strptime(text, "%A, %B %d, %Y").date()
    except ValueError:
        return None


def _parse_span(day, text: str) -> Optional[tuple[datetime, datetime]]:
    """"11:25 AM to 12:55 PM ET" on a given day, as two absolute instants."""
    match = _TIME.match(text)
    if not match:
        return None
    zone_name = _ZONES.get(match.group("zone").upper())
    if zone_name is None:
        return None
    zone = ZoneInfo(zone_name)

    def at(hour: str, minute: str, meridiem: str) -> datetime:
        value = int(hour) % 12
        if meridiem.upper() == "PM":
            value += 12
        return datetime(day.year, day.month, day.day, value, int(minute), tzinfo=zone)

    start = at(match.group("h1"), match.group("m1"), match.group("ap1"))
    end = at(match.group("h2"), match.group("m2"), match.group("ap2"))
    if end <= start:
        # An endurance race runs past midnight, and the Rolex 24 runs past the
        # next one. The page prints only a clock, so the day is inferred - a
        # session that ends before it starts ended on a later date.
        end += timedelta(days=1)
    utc = ZoneInfo("UTC")
    return start.astimezone(utc), end.astimezone(utc)


@register("imsa")
def build(feed_url: Optional[str] = None) -> ImsaSource:
    # `feed_url` is what the runner passes from config/series.toml's source.url;
    # here it is the WordPress post list the event pages are discovered from.
    return ImsaSource(api_url=feed_url)
