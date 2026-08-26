"""NASCAR: Cup, Xfinity and Trucks, from one request.

The feed is the best-shaped of any championship here, so most of what these
tests pin is judgement rather than parsing:

  - three series race at one track on one weekend, and this product's unit is
    the weekend rather than the race;
  - the feed carries the winner of every race, and none of it may be read;
  - a race that was rained off is still in the feed at the time it did not run.

The one thing that is pure parsing is also the one thing that would be worst to
get wrong, so it is pinned twice: `start_time_utc` is UTC, verified during
discovery against the Unix epochs nascar.com publishes separately.
"""

import json
import unittest
from datetime import datetime, timezone

from scrapers.config import load_series, load_venues
from scrapers.normalize import normalize
from scrapers.sources import get_source
from scrapers.sources.base import FetchedDocument

SEASON = 2026
FEED_URL = "https://cf.nascar.com/cacher/2026/race_list_basic.json"

# Daytona is track 105, Charlotte 162, Lime Rock 220.
DAYTONA = 105
CHARLOTTE = 162
LIME_ROCK = 220


def session(name: str, start: str, run_type: int, notes: str = "") -> dict:
    return {
        "event_name": name,
        "notes": notes,
        "start_time_utc": start,
        "run_type": run_type,
    }


def race(
    race_id: int,
    name: str,
    track_id: int,
    race_date: str,
    schedule: list[dict],
    winner: str = "",
) -> dict:
    """A race object with the result fields the real feed carries."""
    return {
        "race_id": race_id,
        "race_name": name,
        "track_id": track_id,
        "track_name": "track",
        "race_date": race_date,
        "schedule": schedule,
        # None of the below may reach a stored session.
        "winner_driver_id": 4070 if winner else 0,
        "race_comments": f"{winner} won the {name}." if winner else "",
        "average_speed": 142.5,
        "pole_winner_speed": 181.9,
    }


def feed(cup=(), xfinity=(), truck=()) -> bytes:
    payload = {"series_1": list(cup), "series_2": list(xfinity), "series_3": list(truck)}
    return json.dumps(payload).encode()


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["nascar"]
        self.venues = load_venues()
        self.source = get_source("nascar")

    def _events(self, body: bytes):
        documents = [FetchedDocument(url=FEED_URL, body=body)]
        parsed = self.source.parse(documents, self.series, self.venues, SEASON)
        return {event.slug: event for event in normalize(parsed, self.series, self.venues)}

    def test_the_published_time_is_utc(self):
        """No offset is written on it, and it is not local either.

        Verified during discovery against the Unix epochs nascar.com publishes
        for the same races - 32 of them, agreeing exactly, on both sides of the
        daylight-saving boundary.
        """
        body = feed(cup=[
            race(1, "DAYTONA 500", DAYTONA, "2026-02-15T14:30:00", [
                session("Race", "2026-02-15T18:30:00", 3),
            ]),
        ])
        event = self._events(body)["daytona-500"]
        self.assertEqual(
            event.sessions[0].start_utc, datetime(2026, 2, 15, 18, 30, tzinfo=timezone.utc)
        )

    def test_paddock_logistics_are_not_sessions(self):
        """run_type 0 is haulers arriving and garages opening.

        There are 169 of them across a season, and on the board they would bury
        the racing they exist to support.
        """
        body = feed(cup=[
            race(1, "DAYTONA 500", DAYTONA, "2026-02-15T14:30:00", [
                session("Haulers Enter", "2026-02-09T13:00:00", 0),
                session("Garage Hours", "2026-02-14T15:30:00", 0),
                session("Driver Introductions", "2026-02-15T18:20:00", 0),
                session("Practice", "2026-02-13T15:00:00", 1),
                session("Race", "2026-02-15T18:30:00", 3),
            ]),
        ])
        event = self._events(body)["daytona-500"]
        self.assertEqual([s.display_name for s in event.sessions], ["Practice", "Race"])

    def test_the_run_type_decides_what_a_session_is(self):
        body = feed(cup=[
            race(1, "DAYTONA 500", DAYTONA, "2026-02-15T14:30:00", [
                session("Practice", "2026-02-13T15:00:00", 1),
                session("Qualifying (Impound)", "2026-02-13T17:00:00", 2),
                session("Race", "2026-02-15T18:30:00", 3),
            ]),
        ])
        event = self._events(body)["daytona-500"]
        self.assertEqual(
            [s.session_type for s in event.sessions], ["practice", "qualifying", "race"]
        )

    def test_the_winner_never_enters_the_pipeline(self):
        """Every race object carries a written race report naming the winner.

        Reading it and then declining to display it would leave it one careless
        template away from the board, which is the one thing this product
        promises never to show.
        """
        body = feed(cup=[
            race(1, "DAYTONA 500", DAYTONA, "2026-02-15T14:30:00", [
                session("Race", "2026-02-15T18:30:00", 3),
            ], winner="W. Byron"),
        ])
        event = self._events(body)["daytona-500"]
        self.assertNotIn("Byron", repr(vars(event.sessions[0])))
        self.assertNotIn("Byron", repr(event.official_name))

    def test_a_postponed_running_is_dropped(self):
        """Charlotte's truck race is in the feed three times.

        Twice with notes saying "Postponed", once with the race that actually
        ran. All three kept would be three races on one weekend, and one race in
        a subscribed calendar three times. The feed says which is which rather
        than leaving it to be guessed from the order.
        """
        body = feed(truck=[
            race(3, "North Carolina Education Lottery 200", CHARLOTTE, "2026-05-23T19:00:00", [
                session("Race", "2026-05-22T23:00:00", 3, notes="Postponed"),
                session("Race", "2026-05-24T01:00:00", 3, notes="Postponed"),
                session("Race", "2026-05-24T14:00:00", 3, notes="Stages 30/60/134 Laps"),
            ]),
        ])
        event = next(iter(self._events(body).values()))
        races = [s for s in event.sessions if s.session_type == "race"]
        self.assertEqual(len(races), 1)
        self.assertEqual(races[0].start_utc, datetime(2026, 5, 24, 14, 0, tzinfo=timezone.utc))


class WeekendTests(unittest.TestCase):
    """Three championships, one track, one weekend, one event."""

    def setUp(self):
        self.series = load_series()["nascar"]
        self.venues = load_venues()
        self.source = get_source("nascar")

    def _events(self, body: bytes):
        documents = [FetchedDocument(url=FEED_URL, body=body)]
        parsed = self.source.parse(documents, self.series, self.venues, SEASON)
        return {event.slug: event for event in normalize(parsed, self.series, self.venues)}

    def test_the_three_series_share_one_weekend(self):
        """Friday, Saturday and Sunday are always the same ISO week.

        Which is why the week is the key: the Trucks race on Friday and Cup on
        Sunday, and they are one weekend at one track however the championships
        count them.
        """
        body = feed(
            cup=[race(1, "DAYTONA 500", DAYTONA, "2026-02-15T14:30:00", [
                session("Race", "2026-02-15T18:30:00", 3),
            ])],
            xfinity=[race(2, "Beef It's What's For Dinner 300", DAYTONA, "2026-02-14T17:00:00", [
                session("Race", "2026-02-14T22:00:00", 3),
            ])],
            truck=[race(3, "Fresh From Florida 250", DAYTONA, "2026-02-13T19:30:00", [
                session("Race", "2026-02-14T00:30:00", 3),
            ])],
        )
        events = self._events(body)
        self.assertEqual(len(events), 1)
        event = events["daytona-500"]
        self.assertEqual(
            {s.category_code for s in event.sessions},
            {"nascar_cup", "nascar_xfinity", "nascar_truck"},
        )

    def test_the_weekend_is_named_after_its_cup_race(self):
        """"DAYTONA 500", not "Daytona, week 7" and not the support race either.

        The three series each have their own sponsored name for their own race,
        and two of the three would be a plausible-looking wrong answer.
        """
        body = feed(
            cup=[race(1, "DAYTONA 500", DAYTONA, "2026-02-15T14:30:00", [
                session("Race", "2026-02-15T18:30:00", 3),
            ])],
            truck=[race(3, "Fresh From Florida 250", DAYTONA, "2026-02-13T19:30:00", [
                session("Race", "2026-02-14T00:30:00", 3),
            ])],
        )
        event = self._events(body)["daytona-500"]
        self.assertEqual(event.name, "DAYTONA 500")
        self.assertEqual(event.official_name, "DAYTONA 500")

    def test_a_weekend_with_no_cup_race_is_named_after_the_circuit(self):
        """Lime Rock and Indianapolis Raceway Park are Truck-only rounds."""
        body = feed(truck=[
            race(9, "Crayon 200", LIME_ROCK, "2026-07-11T13:00:00", [
                session("Practice", "2026-07-11T13:00:00", 1),
                session("Race", "2026-07-11T17:30:00", 3),
            ]),
        ])
        event = next(iter(self._events(body).values()))
        self.assertEqual(event.name, "Lime Rock Park")

    def test_two_weekends_that_share_a_name_are_told_apart_by_month(self):
        """Richmond runs the "Cook Out 400" twice in one season."""
        body = feed(cup=[
            race(1, "Cook Out 400", 26, "2026-03-27T19:30:00", [
                session("Race", "2026-03-27T23:30:00", 3),
            ]),
            race(2, "Cook Out 400", 26, "2026-08-14T19:30:00", [
                session("Race", "2026-08-14T23:30:00", 3),
            ]),
        ])
        events = self._events(body)
        self.assertEqual(len(events), 2)
        self.assertEqual(
            sorted(event.name for event in events.values()),
            ["Cook Out 400 (August)", "Cook Out 400 (March)"],
        )

    def test_a_race_with_no_timetable_keeps_its_day(self):
        """The playoffs have dates but no published times until much later.

        Storing a time would invent one and dropping the race would hide the
        championship decider, so the date is kept and the clock is not.
        """
        body = feed(cup=[
            race(1, "NASCAR Championship Race", 40, "2026-11-08T15:00:00", []),
        ])
        event = next(iter(self._events(body).values()))
        entry = event.sessions[0]
        self.assertEqual(entry.display_name, "Race")
        self.assertEqual(entry.start_precision, "day")
        self.assertEqual(entry.time_status, "provisional")
        # Anchored at local midday, which for Homestead in November is UTC-5.
        self.assertEqual(entry.start_utc, datetime(2026, 11, 8, 17, 0, tzinfo=timezone.utc))

    def test_an_unknown_track_is_dropped_rather_than_guessed(self):
        body = feed(cup=[
            race(1, "Somewhere New 400", 999, "2026-11-08T15:00:00", [
                session("Race", "2026-11-08T20:00:00", 3),
            ]),
        ])
        self.assertEqual(self._events(body), {})

    def test_a_body_that_is_not_the_feed_yields_nothing(self):
        documents = [FetchedDocument(url=FEED_URL, body=b"<html>maintenance</html>")]
        self.assertEqual(self.source.parse(documents, self.series, self.venues, SEASON), [])


class ConfigTests(unittest.TestCase):
    def test_the_series_is_wired_to_this_adapter(self):
        series = load_series()["nascar"]
        self.assertEqual(series.source.adapter, "nascar")
        self.assertEqual(series.source.status, "live")
        self.assertIn("{season}", series.source.url)

    def test_the_season_is_templated_into_the_url(self):
        source = get_source("nascar", feed_url=load_series()["nascar"].source.url)
        self.assertEqual(
            source.urls(2026), ["https://cf.nascar.com/cacher/2026/race_list_basic.json"]
        )

    def test_every_track_maps_to_a_venue_that_exists(self):
        """A venue slug with no entry is a session at no timezone at all."""
        from scrapers.sources.nascar import _VENUE_BY_TRACK

        venues = load_venues()
        for track_id, slug in _VENUE_BY_TRACK.items():
            with self.subTest(track=track_id):
                self.assertIn(slug, venues)

    def test_every_configured_category_is_reachable_from_the_feed(self):
        from scrapers.sources.nascar import _SERIES_KEYS

        configured = {category.code for category in load_series()["nascar"].categories}
        self.assertEqual(set(_SERIES_KEYS.values()), configured)
