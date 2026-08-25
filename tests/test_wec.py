"""WEC source tests.

Runs the real WEC parser against trimmed captures of fiawec.com race pages
(scrapers/fixtures/wec_*.html - each is a minimal page carrying the real
schema.org JSON-LD). These are stored snapshots: when the site changes shape
they go red before a user sees a wrong time.

Three rounds are captured for what each exercises:
  - Fuji    - the bogus-offset trap (+02:00 stamped on a JST wall-clock)
  - Le Mans - the 24-hour race (end time, multi-day span) and its 12 sessions
  - Monza   - a plain European round
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
from scrapers.sources.wec import WecSource, _race_duration_minutes
from scrapers.validate import validate

SEASON = 2026
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "scrapers/fixtures"
FIXTURES = {
    "wec_fuji.html": "https://www.fiawec.com/en/race/6-hours-of-fuji-2026",
    "wec_le_mans.html": "https://www.fiawec.com/en/race/24-hours-of-le-mans-2026",
    "wec_monza.html": "https://www.fiawec.com/en/race/6-hours-of-monza-2026",
}


def _documents():
    return [
        FetchedDocument(url=url, body=(FIXTURE_DIR / name).read_bytes(), content_type="text/html")
        for name, url in FIXTURES.items()
    ]


class FixtureWecSource(WecSource):
    """WEC parsing, fixture input - no network, drives the full pipeline."""

    def resolve_urls(self, season: int, client) -> list[str]:
        return [f"fixture://{name}" for name in FIXTURES]


class WecParseTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["wec"]
        self.venues = load_venues()
        parsed = WecSource().parse(_documents(), self.series, self.venues, SEASON)
        self.events = normalize(parsed, self.series, self.venues)
        self.by_slug = {event.slug: event for event in self.events}

    def _race(self, slug):
        return next(s for s in self.by_slug[slug].sessions if s.session_type == "race")

    def test_rounds_and_venues_resolve(self):
        self.assertEqual(
            {slug: e.venue_slug for slug, e in self.by_slug.items()},
            {"6-hours-of-fuji": "fuji", "24-hours-of-le-mans": "le_mans", "6-hours-of-monza": "monza"},
        )

    def test_the_bogus_offset_is_ignored_and_the_venue_zone_applied(self):
        # Fuji's feed stamps 11:00+02:00, but the circuit is JST: 11:00 JST -> 02:00 UTC.
        self.assertEqual(self._race("6-hours-of-fuji").start_utc, datetime(2026, 9, 27, 2, 0, tzinfo=timezone.utc))

    def test_a_european_round_still_resolves_correctly(self):
        # Monza in November is CET: 11:00 local -> 10:00 UTC.
        self.assertEqual(self._race("6-hours-of-monza").start_utc, datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc))

    def test_the_24_hour_race_spans_a_day_with_an_end_time(self):
        race = self._race("24-hours-of-le-mans")
        self.assertEqual(race.start_utc, datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc))
        self.assertEqual(race.end_utc, datetime(2026, 6, 14, 14, 0, tzinfo=timezone.utc))
        self.assertEqual((race.end_utc - race.start_utc).total_seconds() / 3600, 24)

    def test_six_hour_races_carry_a_six_hour_end(self):
        race = self._race("6-hours-of-monza")
        self.assertEqual((race.end_utc - race.start_utc).total_seconds() / 3600, 6)

    def test_the_session_suffix_is_stripped_from_names(self):
        names = {s.display_name for s in self.by_slug["6-hours-of-fuji"].sessions}
        self.assertIn("Free Practice 1", names)
        self.assertIn("Race", names)
        self.assertNotIn("Race - 6 Hours of Fuji", names)

    def test_le_mans_has_its_full_session_set(self):
        le_mans = self.by_slug["24-hours-of-le-mans"]
        self.assertEqual(len(le_mans.sessions), 12)
        self.assertEqual(
            sorted(set(s.session_type for s in le_mans.sessions)),
            ["practice", "qualifying", "race", "warmup"],
        )

    def test_all_sessions_are_the_single_wec_category(self):
        self.assertEqual(
            {s.category_code for e in self.events for s in e.sessions},
            {"wec"},
        )

    def test_qualifying_and_hyperpole_get_distinct_sequences(self):
        # Fuji has Qualifying/Hyperpole for each of LMGT3 and HYPERCAR - four
        # sessions of type qualifying that must not collide on the natural key.
        seqs = sorted(
            s.sequence for s in self.by_slug["6-hours-of-fuji"].sessions if s.session_type == "qualifying"
        )
        self.assertEqual(seqs, [1, 2, 3, 4])

    def test_event_names_drop_the_sponsor_prefix(self):
        # Monza has none; check the parser at least keeps a clean place name.
        self.assertEqual(self.by_slug["6-hours-of-monza"].name, "6 Hours of Monza")

    def test_the_fixtures_validate_clean(self):
        floors = load_session_floors()
        issues = validate(self.events, self.series, self.venues, min_sessions_per_event=floors["wec"])
        self.assertEqual([i for i in issues if i.severity == "error"], [])


class WecHelperTests(unittest.TestCase):
    def test_race_duration_from_event_name(self):
        self.assertEqual(_race_duration_minutes("24 Hours of Le Mans"), 1440)
        self.assertEqual(_race_duration_minutes("6 Hours of Fuji"), 360)
        self.assertEqual(_race_duration_minutes("Lone Star Le Mans"), 360)  # no hours -> WEC standard


class WecPipelineTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["wec"]
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
            FixtureWecSource(),
            self.venues,
            self.repository,
            SEASON,
            snapshot_store=self.store,
            now=datetime(2026, 3, 1, tzinfo=timezone.utc),
            session_floors=self.floors,
            **kwargs,
        )

    def test_a_full_run_succeeds_and_snapshots_each_race_page(self):
        result = self._run()
        self.assertEqual(result.status, "success", result.error_message)
        self.assertEqual(result.records_found, 28)  # Fuji 8 + Le Mans 12 + Monza 8
        self.assertEqual(len(result.snapshots), 3)
        self.assertEqual([i for i in result.issues if i.severity == "error"], [])

    def test_running_twice_changes_nothing_the_second_time(self):
        first = self._run()
        self.assertGreater(first.records_changed, 0)
        second = self._run()
        self.assertEqual(second.records_changed, 0)
        self.assertEqual(self.repository.changes, [])


if __name__ == "__main__":
    unittest.main()
