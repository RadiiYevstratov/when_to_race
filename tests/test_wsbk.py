"""WorldSBK source tests.

Runs the real WorldSBK parser against a trimmed capture of the live JSON:API
(scrapers/fixtures/wsbk_rounds.json + wsbk_sessions_*.json). The fixture is a
stored snapshot: when the API changes shape these go red before a user sees a
wrong time. If one fails, look at the committed fixture before touching the
parser.

Two real rounds are captured:
  - Aragon   (round 6, carries a YR3EC one-make cup that must be dropped)
  - Portimao (round 2, carries the Women's WCR class that must be kept)
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
from scrapers.sources.wsbk import WorldSbkSource
from scrapers.validate import validate

SEASON = 2026
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "scrapers/fixtures"
FIXTURE_FILES = ["wsbk_rounds.json", "wsbk_sessions_ARA.json", "wsbk_sessions_POR.json"]


def _documents():
    return [
        FetchedDocument(
            url=f"fixture://{name}",
            body=(FIXTURE_DIR / name).read_bytes(),
            content_type="application/json",
        )
        for name in FIXTURE_FILES
    ]


class FixtureWorldSbkSource(WorldSbkSource):
    """WorldSBK parsing, fixture input - no network, drives the full pipeline."""

    def resolve_urls(self, season: int, client) -> list[str]:
        return [f"fixture://{name}" for name in FIXTURE_FILES]


class WorldSbkParseTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["wsbk"]
        self.venues = load_venues()
        parsed = WorldSbkSource().parse(_documents(), self.series, self.venues, SEASON)
        self.events = normalize(parsed, self.series, self.venues)
        self.by_slug = {event.slug: event for event in self.events}

    def _session(self, slug, category, name):
        return next(
            s for s in self.by_slug[slug].sessions if s.category_code == category and s.display_name == name
        )

    def test_rounds_become_events(self):
        self.assertEqual(set(self.by_slug), {"aragon", "portimao"})

    def test_untracked_one_make_cup_is_dropped(self):
        # Aragon carries YR3EC (a Yamaha one-make cup) which we do not track.
        self.assertEqual({s.category_code for s in self.by_slug["aragon"].sessions}, {"wsbk", "wssp", "wspb"})

    def test_womens_championship_is_kept(self):
        self.assertIn("wcr", {s.category_code for s in self.by_slug["portimao"].sessions})

    def test_utc_times_are_read_exactly(self):
        race = self._session("aragon", "wsbk", "Race 1")
        self.assertEqual(race.start_utc, datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc))

    def test_superpole_vocabulary_is_classified(self):
        # "Superpole" is qualifying; "Superpole Race" is a race, not qualifying.
        self.assertEqual(self._session("aragon", "wsbk", "Superpole").session_type, "qualifying")
        self.assertEqual(self._session("aragon", "wsbk", "Superpole Race").session_type, "race")

    def test_the_three_sbk_races_get_distinct_sequences(self):
        seqs = sorted(
            s.sequence
            for s in self.by_slug["aragon"].sessions
            if s.category_code == "wsbk" and s.session_type == "race"
        )
        self.assertEqual(seqs, [1, 2, 3])

    def test_padding_is_stripped_from_names(self):
        # "Superpole" arrives padded with trailing spaces in the feed.
        self.assertEqual(self._session("aragon", "wsbk", "Superpole").display_name, "Superpole")

    def test_venues_and_rounds_resolve(self):
        self.assertEqual(self.by_slug["aragon"].venue_slug, "aragon")
        self.assertEqual(self.by_slug["portimao"].venue_slug, "portimao")
        self.assertEqual(self.by_slug["aragon"].round_number, 6)
        self.assertEqual(self.by_slug["portimao"].round_number, 2)

    def test_source_url_points_at_the_event_page(self):
        race = self._session("aragon", "wsbk", "Race 1")
        self.assertEqual(race.source_url, "https://www.worldsbk.com/en/calendar/event/2026-ARA")

    def test_every_session_falls_inside_its_event_span(self):
        for event in self.events:
            for session in event.sessions:
                with self.subTest(session=session.display_name):
                    self.assertGreaterEqual(session.start_utc, event.starts_at_utc)
                    self.assertLessEqual(session.start_utc, event.ends_at_utc)

    def test_the_fixture_validates_clean(self):
        floors = load_session_floors()
        issues = validate(self.events, self.series, self.venues, min_sessions_per_event=floors["wsbk"])
        self.assertEqual([i for i in issues if i.severity == "error"], [])


class WorldSbkPipelineTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["wsbk"]
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
            FixtureWorldSbkSource(),
            self.venues,
            self.repository,
            SEASON,
            snapshot_store=self.store,
            now=datetime(2026, 5, 1, tzinfo=timezone.utc),
            session_floors=self.floors,
            **kwargs,
        )

    def test_a_full_run_succeeds_and_snapshots_each_document(self):
        result = self._run()
        self.assertEqual(result.status, "success", result.error_message)
        self.assertEqual(result.records_found, 48)  # ARA 21 (YR3EC dropped) + POR 27
        self.assertEqual(len(result.snapshots), 3)  # rounds + two sessions docs
        self.assertEqual([i for i in result.issues if i.severity == "error"], [])

    def test_running_twice_changes_nothing_the_second_time(self):
        first = self._run()
        self.assertGreater(first.records_changed, 0)
        second = self._run()
        self.assertEqual(second.records_changed, 0)
        self.assertEqual(self.repository.changes, [])


if __name__ == "__main__":
    unittest.main()
