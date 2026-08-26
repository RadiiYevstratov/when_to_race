"""IndyCar, the one source parsed straight from markup.

Two things here are worth more than the rest of the suite put together.

The first is the timezone. Every time on indycar.com is published in US Eastern
whatever timezone the circuit is in, so a session at Laguna Seca reads "5:00PM
ET" and starts at 2:00 PM Pacific. Treating that as circuit-local would put
every West Coast session three hours wrong, and it would look entirely
plausible on the board. The conversion is pinned here against the figure printed
in the official weekend-schedule PDF, which states "All times local (Pacific)".

The second is that the source repeats itself in two different ways - once per
broadcaster, and once per round of a doubleheader - and both produce a duplicate
that reads as a real session at a time nothing starts.

The page fixtures are real excerpts, including the template bug that leaks
`False ? disabled` into the markup. They are what turns a site redesign into a
failing test rather than a wrong time on someone's phone.
"""

import unittest
from datetime import datetime, timezone

from scrapers.config import load_series, load_venues
from scrapers.normalize import normalize
from scrapers.sources import get_source
from scrapers.sources.base import FetchedDocument
from scrapers.sources.indycar import IndyCarSource

SEASON = 2026


def entry(when: str, description: str) -> str:
    """One schedule row, with the broadcaster markup the real page carries."""
    return (
        '<div class="schedule-entry"> <div> '
        f'<div class="schedule-time">{when}</div> '
        '<a href="https://www.foxsports.com/live/fs1" class="schedule-network">'
        '<img src="/-/media/IndyCar/Logos/Networks/FS1-Pos.png" alt="FS1" /></a> '
        '<div class="divider"></div> '
        f'<div class="schedule-description">{description}</div> '
        '</div> <div class="schedule-actions"> '
        '<a href="#" class="btn btn-secondary" False ? disabled><p>Highlights</p></a> '
        "</div> </div>"
    )


def page(title: str, days: list[tuple[str, list[tuple[str, str]]]]) -> bytes:
    body = [f"<h1>{title}</h1>", '<div class="schedule-table">']
    for heading, rows in days:
        body.append(f"<h3>{heading}</h3>")
        body.extend(entry(when, what) for when, what in rows)
    body.append("</div>")
    return ("<html><body>" + "".join(body) + "</body></html>").encode()


LAGUNA_SECA = page(
    "INDYCAR Grand Prix of Monterey",
    [
        ("Friday, Sep 4", [("5:00PM ET", "NTT INDYCAR SERIES - Practice 1")]),
        ("Saturday, Sep 5", [("4:30PM ET", "NTT INDYCAR SERIES - Qualifying")]),
        ("Sunday, Sep 6", [("2:30PM ET", "NTT INDYCAR SERIES - Race")]),
    ],
)


class TimezoneTests(unittest.TestCase):
    """The site publishes Eastern for every circuit, and says so on every row."""

    def setUp(self):
        self.series = load_series()["indycar"]
        self.venues = load_venues()
        self.source = get_source("indycar")

    def _sessions(self, *docs: tuple[str, bytes]):
        documents = [FetchedDocument(url=url, body=body) for url, body in docs]
        parsed = self.source.parse(documents, self.series, self.venues, SEASON)
        return {event.slug: event for event in normalize(parsed, self.series, self.venues)}

    LAG = ("https://www.indycar.com/Schedule/2026/Laguna-Seca", LAGUNA_SECA)

    def test_eastern_is_resolved_to_the_instant_the_circuit_races_at(self):
        """5:00PM ET at Laguna Seca is 2:00 PM Pacific, which is 21:00 UTC.

        The official weekend-schedule PDF for this round prints "All times local
        (Pacific)" and lists Practice 1 at 2:00 PM. Both describe one instant,
        and this is that instant.
        """
        event = self._sessions(self.LAG)["laguna-seca"]
        practice = next(s for s in event.sessions if s.display_name == "Practice 1")
        self.assertEqual(practice.start_utc, datetime(2026, 9, 4, 21, 0, tzinfo=timezone.utc))

    def test_the_circuit_keeps_its_own_zone_for_display(self):
        """Eastern is how the source writes times down, not where the race is.

        Handing "ET" to normalize as the session's timezone would make it a
        display override, and a viewer would be told the Pacific race happens in
        Eastern. The venue's zone has to survive the conversion.
        """
        event = self._sessions(self.LAG)["laguna-seca"]
        self.assertEqual(self.venues[event.venue_slug].iana_timezone, "America/Los_Angeles")
        self.assertTrue(all(s.iana_timezone is None for s in event.sessions))

    def test_a_label_that_is_not_eastern_is_not_read_as_eastern(self):
        body = page("Test", [("Friday, Sep 4", [("5:00PM PT", "NTT INDYCAR SERIES - Practice 1")])])
        event = self._sessions(("https://www.indycar.com/Schedule/2026/Laguna-Seca", body))
        practice = next(iter(event.values())).sessions[0]
        self.assertEqual(practice.start_utc, datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc))

    def test_an_unknown_label_is_dropped_rather_than_assumed(self):
        body = page("Test", [("Friday, Sep 4", [("5:00PM XYZ", "NTT INDYCAR SERIES - Practice 1")])])
        documents = [FetchedDocument(url="https://www.indycar.com/Schedule/2026/Laguna-Seca", body=body)]
        self.assertEqual(self.source.parse(documents, self.series, self.venues, SEASON), [])


class DuplicateTests(unittest.TestCase):
    """The same session, published twice, in two different ways."""

    def setUp(self):
        self.series = load_series()["indycar"]
        self.venues = load_venues()
        self.source = get_source("indycar")

    def _events(self, *docs: tuple[str, bytes]):
        documents = [FetchedDocument(url=url, body=body) for url, body in docs]
        parsed = self.source.parse(documents, self.series, self.venues, SEASON)
        return {event.slug: event for event in normalize(parsed, self.series, self.venues)}

    def test_a_session_listed_once_per_broadcaster_starts_once(self):
        """Indianapolis 500 practice runs from noon; 4:00 PM is when it changes channel.

        Two rows, one session. The later one is a television window, and stored
        as a session it would be a second practice at an hour nothing begins.
        """
        body = page(
            "110th Running of the Indianapolis 500",
            [
                (
                    "Tuesday, May 12",
                    [
                        ("12:00PM ET", "NTT INDYCAR SERIES - Practice 1"),
                        ("4:00PM ET", "NTT INDYCAR SERIES - Practice 1"),
                    ],
                ),
                ("Sunday, May 24", [("12:30PM ET", "NTT INDYCAR SERIES - Race")]),
            ],
        )
        event = self._events(("https://www.indycar.com/Schedule/2026/Indianapolis-500", body))
        sessions = next(iter(event.values())).sessions
        practices = [s for s in sessions if s.display_name == "Practice 1"]
        self.assertEqual(len(practices), 1)
        self.assertEqual(practices[0].start_utc, datetime(2026, 5, 12, 16, 0, tzinfo=timezone.utc))

    def test_a_doubleheader_is_one_weekend_and_not_two(self):
        """Milwaukee publishes two rounds that share a track, a weekend and sessions.

        Qualifying appears on both pages. Two events would split one weekend in
        half and show the shared sessions twice, which is also the shape that
        makes two calendar entries out of one race.
        """
        race_one = page(
            "Snap-on Makers and Fixers 250",
            [
                ("Friday, Aug 28", [("6:00PM ET", "NTT INDYCAR SERIES - Practice")]),
                (
                    "Saturday, Aug 29",
                    [
                        ("11:00AM ET", "NTT INDYCAR SERIES - Qualifying"),
                        ("2:30PM ET", "NTT INDYCAR SERIES - Race 1"),
                    ],
                ),
                ("Sunday, Aug 30", [("1:00PM ET", "NTT INDYCAR SERIES - Race 2")]),
            ],
        )
        race_two = page(
            "Snap-on Milwaukee Mile 250",
            [
                ("Saturday, Aug 29", [("11:00AM ET", "NTT INDYCAR SERIES - Qualifying")]),
                (
                    "Sunday, Aug 30",
                    [
                        ("10:15AM ET", "NTT INDYCAR SERIES - Warmup"),
                        ("1:00PM ET", "NTT INDYCAR SERIES - Race 2"),
                    ],
                ),
            ],
        )
        events = self._events(
            ("https://www.indycar.com/Schedule/2026/Milwaukee-Race1", race_one),
            ("https://www.indycar.com/Schedule/2026/Milwaukee-Race2", race_two),
        )
        self.assertEqual(len(events), 1)
        sessions = next(iter(events.values())).sessions
        self.assertEqual(
            [s.display_name for s in sessions],
            ["Practice", "Qualifying", "Race 1", "Warmup", "Race 2"],
        )
        # Both races survive as distinct sessions; only the repeats collapse.
        self.assertEqual(len([s for s in sessions if s.session_type == "race"]), 2)


class ScheduleRowTests(unittest.TestCase):
    """Reading a row, and deciding whether it is a session at all."""

    def setUp(self):
        self.series = load_series()["indycar"]
        self.venues = load_venues()
        self.source = get_source("indycar")

    def _parse(self, url: str, body: bytes):
        return self.source.parse(
            [FetchedDocument(url=url, body=body)], self.series, self.venues, SEASON
        )

    def test_an_unprefixed_row_that_reads_as_a_session_is_kept(self):
        """Phoenix publishes a bare "Practice 1" with no championship in front."""
        body = page("Good Ranchers 250", [("Friday, Mar 6", [("10:00AM ET", "Practice 1")])])
        parsed = self._parse("https://www.indycar.com/Schedule/2026/Phoenix", body)
        self.assertEqual([p.raw_session_name for p in parsed], ["Practice 1"])
        self.assertEqual(parsed[0].category_code, "indycar")

    def test_an_unprefixed_row_that_is_not_a_session_is_dropped(self):
        """The Indianapolis 500 timetable includes a hot dog race.

        An entry has to either name its championship or read as a session. The
        Oscar Mayer Wienie 500 does neither, and it is not motorsport.
        """
        body = page(
            "110th Running of the Indianapolis 500",
            [
                (
                    "Friday, May 22",
                    [
                        ("2:00PM ET", "Oscar Mayer Wienie 500"),
                        ("2:30PM ET", "NTT INDYCAR SERIES - Pit Stop Competition"),
                    ],
                )
            ],
        )
        parsed = self._parse("https://www.indycar.com/Schedule/2026/Indianapolis-500", body)
        self.assertEqual([p.raw_session_name for p in parsed], ["Pit Stop Competition"])

    def test_a_heading_on_the_wrong_weekday_is_refused(self):
        """The year is borrowed from the season, so the weekday has to agree.

        "Friday, Sep 4" is a Friday in 2026. If the page and the season disagree
        about that, either the assumption is wrong or the page is stale, and
        neither is something to publish.
        """
        body = page("Test", [("Monday, Sep 4", [("5:00PM ET", "NTT INDYCAR SERIES - Practice 1")])])
        self.assertEqual(self._parse("https://www.indycar.com/Schedule/2026/Laguna-Seca", body), [])

    def test_a_round_at_an_unknown_venue_is_dropped_rather_than_guessed(self):
        body = page("Test", [("Friday, Sep 4", [("5:00PM ET", "NTT INDYCAR SERIES - Practice 1")])])
        self.assertEqual(self._parse("https://www.indycar.com/Schedule/2026/Somewhere-New", body), [])

    def test_a_page_with_no_timetable_yields_nothing(self):
        body = b"<html><body><h1>Round</h1><p>Tickets on sale</p></body></html>"
        self.assertEqual(self._parse("https://www.indycar.com/Schedule/2026/Phoenix", body), [])

    def test_the_sponsored_title_is_kept_as_the_official_name(self):
        """The slug comes from the URL because the title changes with the sponsor.

        Barber's page is headed "Children's of Alabama Indy Grand Prix", which
        names neither the circuit nor the city - so a slug built from it would
        move the event every time the sponsorship does.
        """
        body = page(
            "Children&#39;s of Alabama Indy Grand Prix",
            [("Friday, Mar 27", [("3:30PM ET", "NTT INDYCAR SERIES - Practice 1")])],
        )
        parsed = self._parse("https://www.indycar.com/Schedule/2026/Barber", body)
        self.assertEqual(parsed[0].official_name, "Children's of Alabama Indy Grand Prix")
        self.assertEqual(parsed[0].event_name, "barber")
        self.assertEqual(parsed[0].venue_slug, "barber")


class RoundDiscoveryTests(unittest.TestCase):
    def test_only_the_requested_season_is_fetched(self):
        index = (
            '<a href="/Schedule/2026/Phoenix">Phoenix</a>'
            '<a href="/Schedule/2026/Barber">Barber</a>'
            '<a href="/Schedule/2025/Phoenix">last year</a>'
            '<a href="/Schedule/2026/Phoenix">Phoenix again</a>'
        ).encode()

        class _Client:
            def get(self, url):
                return type("R", (), {"body": index})()

        urls = IndyCarSource().resolve_urls(2026, _Client())
        self.assertEqual(
            urls,
            [
                "https://www.indycar.com/Schedule/2026/Phoenix",
                "https://www.indycar.com/Schedule/2026/Barber",
            ],
        )

    def test_an_unreachable_index_is_reported_rather_than_raised(self):
        class _Client:
            def get(self, url):
                raise OSError("connection reset")

        self.assertEqual(IndyCarSource().resolve_urls(2026, _Client()), [])


class ConfigTests(unittest.TestCase):
    def test_the_series_is_wired_to_this_adapter(self):
        series = load_series()["indycar"]
        self.assertEqual(series.source.adapter, "indycar")
        self.assertEqual(series.source.status, "live")
        self.assertTrue(series.source.url.startswith("https://www.indycar.com/"))

    def test_every_round_maps_to_a_venue_that_exists(self):
        """A venue slug with no entry is a session at no timezone at all."""
        from scrapers.sources.indycar import _VENUE_BY_ROUND

        venues = load_venues()
        for round_token, slug in _VENUE_BY_ROUND.items():
            with self.subTest(round=round_token):
                self.assertIn(slug, venues)
