"""MotoGP source tests.

Runs the real MotoGP parser against a trimmed capture of the live season-events
API (scrapers/fixtures/motogp_events.json). That fixture is a stored snapshot:
when the API changes shape, these are the tests that go red before a user sees a
wrong time. If one fails, look at the committed fixture before touching the
parser.

The fixture holds three real rounds plus a non-GP TEST entry:
  - Thailand  (finished, ASIA/BANGKOK +07:00, no DST)
  - Aragon    (upcoming, EUROPE/MADRID +02:00, carries a "Baggers" class to drop)
  - Qatar     (upcoming, ASIA/QATAR +03:00, a night race)
"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scrapers.config import load_series, load_session_floors, load_venues
from scrapers.normalize import normalize
from scrapers.pipeline import run_series
from scrapers.repository import InMemoryRepository
from scrapers.snapshots import SnapshotStore
from scrapers.sources.base import FetchedDocument
from scrapers.sources.motogp import MotoGpSource, _clean_event_name, _clean_session_name
from scrapers.validate import validate

SEASON = 2026
FIXTURE = Path(__file__).resolve().parent.parent / "scrapers/fixtures/motogp_events.json"


class FixtureMotoGpSource(MotoGpSource):
    """MotoGP parsing, fixture input - drives the full pipeline offline."""

    def urls(self, season: int) -> list[str]:
        return ["fixture://motogp_events.json"]


class MotoGpParseTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["motogp"]
        self.venues = load_venues()
        body = FIXTURE.read_bytes()
        document = FetchedDocument(url="fixture://motogp_events.json", body=body, content_type="application/json")
        parsed = MotoGpSource().parse([document], self.series, self.venues, SEASON)
        self.events = normalize(parsed, self.series, self.venues)
        self.by_slug = {event.slug: event for event in self.events}

    def _session(self, slug, category, session_type):
        return next(
            s
            for s in self.by_slug[slug].sessions
            if s.category_code == category and s.session_type == session_type
        )

    def test_only_gp_weekends_become_events(self):
        # The VALENCIA TEST entry (kind != "GP") must not become a round.
        self.assertEqual(set(self.by_slug), {"thailand", "aragon", "qatar"})

    def test_all_three_classes_share_the_weekend(self):
        thailand = self.by_slug["thailand"]
        self.assertEqual({s.category_code for s in thailand.sessions}, {"motogp", "moto2", "moto3"})

    def test_the_baggers_class_is_dropped(self):
        # Aragon carries a "Baggers" invitational the schema does not track.
        aragon = self.by_slug["aragon"]
        self.assertEqual({s.category_code for s in aragon.sessions}, {"motogp", "moto2", "moto3"})

    def test_media_entries_are_not_sessions(self):
        names = [s.display_name for e in self.events for s in e.sessions]
        self.assertNotIn("Group Photo", names)
        self.assertNotIn("Pre-Event Press Conference", names)

    def test_offset_stamped_times_convert_to_utc(self):
        # Thailand is +07:00 year-round: 15:00 local -> 08:00 UTC.
        race = self._session("thailand", "motogp", "race")
        self.assertEqual(race.start_utc, datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc))

    def test_a_night_race_in_a_different_offset(self):
        # Qatar is +03:00: a 20:00 local night race -> 17:00 UTC.
        race = self._session("qatar", "motogp", "race")
        self.assertEqual(race.start_utc, datetime(2026, 11, 8, 17, 0, tzinfo=timezone.utc))

    def test_the_sprint_is_classified_despite_its_race_kind(self):
        # "Tissot Sprint" arrives with kind=RACE but must be a sprint, not a race.
        sprint = self._session("thailand", "motogp", "sprint")
        self.assertEqual(sprint.display_name, "Sprint")
        motogp_races = [
            s for s in self.by_slug["thailand"].sessions if s.category_code == "motogp" and s.session_type == "race"
        ]
        self.assertEqual([s.display_name for s in motogp_races], ["Grand Prix"])

    def test_full_session_vocabulary_is_present(self):
        types = {s.session_type for s in self.by_slug["thailand"].sessions if s.category_code == "motogp"}
        self.assertEqual(types, {"practice", "qualifying", "sprint", "warmup", "race"})

    def test_practice_and_qualifying_get_distinct_sequences(self):
        thailand = self.by_slug["thailand"]
        practice = sorted(
            s.sequence for s in thailand.sessions if s.category_code == "motogp" and s.session_type == "practice"
        )
        quali = sorted(
            s.sequence for s in thailand.sessions if s.category_code == "motogp" and s.session_type == "qualifying"
        )
        self.assertEqual(practice, [1, 2, 3])
        self.assertEqual(quali, [1, 2])

    def test_venues_and_rounds_resolve(self):
        self.assertEqual(self.by_slug["thailand"].venue_slug, "buriram")
        self.assertEqual(self.by_slug["aragon"].venue_slug, "aragon")
        self.assertEqual(self.by_slug["qatar"].venue_slug, "lusail")
        self.assertEqual(self.by_slug["thailand"].round_number, 1)
        self.assertEqual(self.by_slug["qatar"].round_number, 20)

    def test_names_are_ascii_and_clean(self):
        for event in self.events:
            for session in event.sessions:
                self.assertTrue(session.display_name.isascii(), session.display_name)
                self.assertNotIn("Nr.", session.display_name)

    def test_every_session_falls_inside_its_event_span(self):
        for event in self.events:
            for session in event.sessions:
                with self.subTest(session=session.display_name):
                    self.assertGreaterEqual(session.start_utc, event.starts_at_utc)
                    self.assertLessEqual(session.start_utc, event.ends_at_utc)

    def test_the_fixture_validates_clean(self):
        floors = load_session_floors()
        issues = validate(self.events, self.series, self.venues, min_sessions_per_event=floors["motogp"])
        self.assertEqual([i for i in issues if i.severity == "error"], [])


class MotoGpHelperTests(unittest.TestCase):
    def test_session_name_cleaning(self):
        self.assertEqual(_clean_session_name("Free Practice Nr. 1"), "Free Practice 1")
        self.assertEqual(_clean_session_name("Qualifying Nr.2"), "Qualifying 2")
        self.assertEqual(_clean_session_name("Tissot Sprint"), "Sprint")
        self.assertEqual(_clean_session_name("Grand Prix"), "Grand Prix")

    def test_event_name_cleaning(self):
        self.assertEqual(_clean_event_name("THAILAND"), "Thailand")
        self.assertEqual(_clean_event_name("SAN MARINO"), "San Marino")
        self.assertEqual(_clean_event_name("USA"), "United States")
        self.assertEqual(_clean_event_name("GERMANY "), "Germany")


class MotoGpPipelineTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["motogp"]
        self.venues = load_venues()
        self.floors = load_session_floors()
        self.repository = InMemoryRepository()
        self.directory = tempfile.TemporaryDirectory()
        self.store = SnapshotStore(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def _run(self, **kwargs):
        return run_series(
            self.series,
            FixtureMotoGpSource(),
            self.venues,
            self.repository,
            SEASON,
            snapshot_store=self.store,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
            session_floors=self.floors,
            **kwargs,
        )

    def test_a_full_run_succeeds(self):
        result = self._run()
        self.assertEqual(result.status, "success", result.error_message)
        self.assertEqual(result.records_found, 60)  # 3 rounds x 20 sessions
        self.assertEqual([i for i in result.issues if i.severity == "error"], [])

    def test_running_twice_changes_nothing_the_second_time(self):
        first = self._run()
        self.assertGreater(first.records_changed, 0)
        second = self._run()
        self.assertEqual(second.status, "success", second.error_message)
        self.assertEqual(second.records_changed, 0)
        self.assertEqual(self.repository.changes, [])


if __name__ == "__main__":
    unittest.main()
