"""NASCAR: Cup, Xfinity and Craftsman Truck.

Source: `https://cf.nascar.com/cacher/{season}/race_list_basic.json`, the feed
behind nascar.com's own schedule. One request carries the whole season for all
three national series, which makes this the cheapest source here to run and the
easiest to reason about - the second option in the discovery order, and by some
distance the best-shaped JSON any of these championships publishes.

    {"series_1": [race, ...],       # Cup
     "series_2": [...],             # Xfinity
     "series_3": [...]}             # Craftsman Truck

    race = {race_id, race_name, track_id, track_name, race_date,
            schedule: [{event_name, start_time_utc, run_type, notes}, ...],
            ... and a great deal about who won it}

**`start_time_utc` really is UTC**, which was checked rather than assumed and is
the one thing that had to be right. nascar.com's schedule page publishes each
race a second time, independently, with an offset-stamped time and a Unix epoch
(`"Event_Time_Est":"2026-07-05T18:00:00-0400","Event_Time_Unix":"1783288800"`).
An epoch cannot be vague about its timezone. Across the 32 races carried by both,
the feed's UTC and the site's epoch agree exactly - every one, on both sides of
the daylight-saving boundary, and at Pacific tracks as well as Eastern ones.

`race_date` is a different matter and is deliberately not used for times. Its
offset from the same race's UTC start is neither the track's nor consistently
Eastern - Las Vegas and Sonoma both come out four hours apart, which is neither -
so whatever convention it follows is not one worth guessing at. Only its date is
read, and only where there is nothing better.

`run_type` types each entry, which spares this parser having to interpret names:

    0  paddock logistics - "Haulers Enter", "Garage Hours", "Driver
       Introductions". Not sessions, and 169 of them would bury the schedule.
    1  practice        2  qualifying        3  race

Everything else in a race object is about the result - `winner_driver_id`,
`pole_winner_speed`, `average_speed`, and a `race_comments` field that is a
written race report naming the winner in its first sentence. None of it is read.
Results are out of scope and a spoiler, and the cheapest place to honour that is
the point the data enters rather than the point it would be displayed.

Two shapes need deciding rather than just parsing:

  **A weekend, not a race.** The three series each run their own race with its
  own sponsored name at one track on one weekend, and this product's unit is the
  weekend. Races are grouped into events by track and ISO week, so a Truck race
  on Friday and a Cup race on Sunday land on one event with the classes side by
  side. Friday, Saturday and Sunday always share an ISO week, which is why that
  is the key.

  **The playoffs have no timetable yet.** The last six weekends of 2026 carry an
  empty `schedule`, because NASCAR publishes those closer to the date. Their
  dates are known, so the race is kept at day precision and marked provisional -
  the board renders it as "--:--" - rather than either inventing a time or
  hiding the championship decider from the calendar.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from ..config import SeriesConfig, VenueConfig
from ..records import ParsedSession
from .base import FetchedDocument, register

logger = logging.getLogger(__name__)

DEFAULT_FEED_URL = "https://cf.nascar.com/cacher/{season}/race_list_basic.json"

# Feed key -> our category code.
_SERIES_KEYS = {
    "series_1": "nascar_cup",
    "series_2": "nascar_xfinity",
    "series_3": "nascar_truck",
}

# run_type -> whether it is a session at all. 0 is paddock logistics.
_RUN_TYPES = {1, 2, 3}

# The weekend is named after this one's race. Cup is the headline in config too;
# it is repeated here because `_event_names` names weekends before it has a
# series config to ask.
_CUP = "nascar_cup"

# The feed's own track_id -> venue slug. Keyed on the id rather than the name
# because a track's name follows its naming rights: Dover has been Dover Downs,
# Dover International and now Dover Motor Speedway, and the id never moved.
_VENUE_BY_TRACK = {
    4: "darlington",
    14: "bristol",
    22: "martinsville",
    26: "richmond",
    39: "chicagoland",
    40: "homestead",
    41: "kansas",
    42: "las_vegas_speedway",
    43: "texas",
    45: "wwtr",
    47: "irp",
    52: "nashville_superspeedway",
    82: "talladega",
    84: "phoenix",
    99: "sonoma",
    103: "dover",
    105: "daytona",
    111: "atlanta",
    123: "indianapolis",
    133: "michigan",
    138: "new_hampshire",
    157: "watkins_glen",
    159: "bowman_gray",
    162: "charlotte",
    175: "rockingham",
    177: "north_wilkesboro",
    198: "pocono",
    206: "iowa",
    214: "cota",
    220: "lime_rock",
    221: "san_diego",
    222: "st_petersburg",
}


class NascarSource:
    series_code = "nascar"
    detail_level = "full"

    def __init__(self, feed_url: Optional[str] = None):
        self.feed_url = feed_url or DEFAULT_FEED_URL

    def urls(self, season: int) -> list[str]:
        return [self.feed_url.format(season=season)]

    def parse(
        self,
        documents: Iterable[FetchedDocument],
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
    ) -> list[ParsedSession]:
        results: list[ParsedSession] = []
        for document in documents:
            try:
                payload = json.loads(document.text)
            except json.JSONDecodeError as error:
                logger.warning("nascar: %s is not JSON: %s", document.url, error)
                continue
            results.extend(self._parse_season(payload, series, venues, season, document.url))
        return results

    def _parse_season(
        self,
        payload: dict,
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
        source_url: str,
    ) -> list[ParsedSession]:
        races = [
            (category_code, race)
            for key, category_code in _SERIES_KEYS.items()
            for race in payload.get(key) or []
        ]
        if not races:
            logger.warning("nascar: %s carries no series lists", source_url)
            return []

        headline = series.headline_category.code
        event_names = _event_names(races, venues)

        results: list[ParsedSession] = []
        for category_code, race in races:
            venue_slug = _VENUE_BY_TRACK.get(race.get("track_id"))
            if venue_slug is None or venue_slug not in venues:
                logger.warning(
                    "nascar: track %s (%r) maps to no known venue; races there dropped",
                    race.get("track_id"),
                    race.get("track_name"),
                )
                continue

            event_name = event_names.get(race.get("race_id"))
            if event_name is None:
                continue

            # The weekend takes its name from the Cup race, which is what it is
            # known by. The support races have their own sponsored names and
            # would each be a plausible-looking wrong answer.
            official_name = (race.get("race_name") or "").strip() if category_code == headline else None

            sessions = [
                entry
                for entry in race.get("schedule") or []
                if entry.get("run_type") in _RUN_TYPES
                and entry.get("start_time_utc")
                and not _postponed(entry)
            ]

            if not sessions:
                placeholder = _placeholder_race(
                    race, series, season, category_code, event_name, venue_slug, official_name, source_url
                )
                if placeholder is not None:
                    results.append(placeholder)
                continue

            for entry in sessions:
                start = _utc(entry.get("start_time_utc"))
                if start is None:
                    continue
                name = " ".join((entry.get("event_name") or "").split())
                if not name:
                    continue

                results.append(
                    ParsedSession(
                        series_code=series.code,
                        season=season,
                        event_name=event_name,
                        category_code=category_code,
                        raw_session_name=name,
                        official_name=official_name,
                        venue_slug=venue_slug,
                        start_utc=start,
                        # No end times in the feed, and no provisional flag - a
                        # published entry is taken as confirmed, as for every
                        # other source that stays silent on it.
                        end_utc=None,
                        time_status="confirmed",
                        source_url=source_url,
                    )
                )

        return results


def _placeholder_race(
    race: dict,
    series: SeriesConfig,
    season: int,
    category_code: str,
    event_name: str,
    venue_slug: str,
    official_name: Optional[str],
    source_url: str,
) -> Optional[ParsedSession]:
    """A race whose timetable has not been published yet.

    The date is known and the time is not, so the date is what gets stored.
    Anchored at local midday so it survives conversion into any viewer's
    timezone, and never displayed - a day-precision session renders as "--:--".
    """
    day = _date_only(race.get("race_date"))
    if day is None:
        return None
    return ParsedSession(
        series_code=series.code,
        season=season,
        event_name=event_name,
        category_code=category_code,
        raw_session_name="Race",
        official_name=official_name,
        venue_slug=venue_slug,
        local_start=datetime(day.year, day.month, day.day, 12, 0),
        time_status="provisional",
        start_precision="day",
        source_url=source_url,
    )


def _event_names(races: list[tuple[str, dict]], venues: dict[str, VenueConfig]) -> dict[int, str]:
    """race_id -> the name of the weekend it belongs to.

    A weekend is one track in one ISO week: the three series run their own races
    across Friday to Sunday, which always share a week, and this product's unit
    is the weekend rather than the individual race.

    A weekend is named after its Cup race, which is what it is known by and what
    anyone would search for - "Coca-Cola 600" rather than "Charlotte, week 21".
    Naming happens after grouping and not before, which is what lets the three
    series share an event while each keeps its own sponsored race name.

    The handful of weekends with no Cup race - the Truck-only rounds at Lime
    Rock and Indianapolis Raceway Park - take the circuit's name instead, and
    the month is added to whichever names would otherwise collide.
    """
    weekends: dict[tuple[str, int, int], list[int]] = {}
    order: list[tuple[str, int, int]] = []
    dates: dict[tuple[str, int, int], datetime] = {}
    headline_race: dict[tuple[str, int, int], str] = {}

    for category_code, race in races:
        venue_slug = _VENUE_BY_TRACK.get(race.get("track_id"))
        race_id = race.get("race_id")
        if venue_slug is None or race_id is None:
            continue
        moment = _weekend_moment(race)
        if moment is None:
            continue
        iso_year, iso_week, _ = moment.isocalendar()
        key = (venue_slug, iso_year, iso_week)
        if key not in weekends:
            weekends[key] = []
            order.append(key)
            dates[key] = moment
        weekends[key].append(race_id)
        if category_code == _CUP and race.get("race_name"):
            headline_race[key] = " ".join(race["race_name"].split())

    chosen = {
        key: headline_race.get(key) or (venues[key[0]].name if key[0] in venues else key[0])
        for key in order
    }
    # Two weekends that would answer to one name are told apart by month, which
    # is how anyone would say it out loud.
    clashing = {
        name for name in chosen.values() if sum(1 for value in chosen.values() if value == name) > 1
    }

    names: dict[int, str] = {}
    for key in order:
        name = chosen[key]
        if name in clashing:
            name = f"{name} ({dates[key]:%B})"
        for race_id in weekends[key]:
            names[race_id] = name
    return names


def _weekend_moment(race: dict) -> Optional[datetime]:
    """When this race's weekend is, for grouping only.

    The race entry's own UTC start if there is one, and the published date
    otherwise. Never a paddock entry: the Bowman Gray haulers arrive six days
    before the race, which would put the weekend in the wrong week.
    """
    for entry in race.get("schedule") or []:
        if entry.get("run_type") == 3:
            start = _utc(entry.get("start_time_utc"))
            if start is not None:
                return start
    day = _date_only(race.get("race_date"))
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc) if day else None


def _postponed(entry: dict) -> bool:
    """A session listed at a time it did not end up running at.

    Charlotte's truck race in May is in the feed three times: twice with
    `notes: "Postponed"` and once with the lap breakdown of the race that
    actually ran. Kept, all three would be three races on one weekend, and the
    validators say so - a duplicate calendar UID, which is the shape that puts
    one race into a subscribed calendar more than once.

    Worth noting that the feed says this outright rather than leaving it to be
    inferred from the order, which is the difference between reading a source
    and guessing at one.
    """
    return "postponed" in (entry.get("notes") or "").strip().lower()


def _utc(value: Optional[str]) -> Optional[datetime]:
    """A UTC timestamp published without an offset on it."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _date_only(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


@register("nascar")
def build(feed_url: Optional[str] = None) -> NascarSource:
    return NascarSource(feed_url=feed_url)
