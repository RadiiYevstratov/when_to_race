"""Pipeline, fetch-layer, snapshot and config tests.

The end-to-end cases run the real F1 parser against the committed fixture. That
fixture is a stored snapshot: when a source redesigns its feed, these are the
tests that go red before a user sees a wrong time.
"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scrapers.config import (
    ConfigError,
    load_series,
    load_session_floors,
    load_venues,
)
from scrapers.http import (
    FetchError,
    HttpClient,
    RateLimiter,
    Response,
    RobotsDisallowed,
    backoff_delay,
    should_retry,
)
from scrapers.pipeline import run_series
from scrapers.repository import InMemoryRepository
from scrapers.snapshots import SnapshotStore, content_hash
from scrapers.sources import get_source, registered_adapters
from scrapers.validate import ValidationIssue, raise_for_errors, validate

SEASON = 2026


class ConfigTests(unittest.TestCase):
    def test_registries_load(self):
        series = load_series()
        venues = load_venues()
        self.assertIn("f1", series)
        self.assertGreaterEqual(len(series), 8)
        self.assertGreater(len(venues), 40)

    def test_every_series_has_exactly_one_headline_category(self):
        for code, series in load_series().items():
            with self.subTest(series=code):
                self.assertTrue(series.categories)
                self.assertIsNotNone(series.headline_category)

    def test_f1_carries_its_support_categories(self):
        codes = {category.code for category in load_series()["f1"].categories}
        self.assertEqual(codes, {"f1", "f2", "f3", "f1a"})

    def test_a_class_that_shares_a_weekend_has_its_own_colour(self):
        """Four championships on one weekend, all painted the series red, said
        nothing about which row was which."""
        categories = {c.code: c for c in load_series()["f1"].categories}
        self.assertEqual(categories["f2"].accent_color, "#0096D6")
        self.assertEqual(categories["f3"].accent_color, "#E35205")

    def test_a_headline_class_inherits_rather_than_repeats(self):
        # Formula 1 within Formula 1 has no separate identity to state, and
        # copying the value would mean changing a series colour in two places.
        for code, series in load_series().items():
            with self.subTest(series=code):
                self.assertIsNone(series.headline_category.accent_color)

    def test_every_declared_class_colour_is_a_hex_triplet(self):
        for code, series in load_series().items():
            for category in series.categories:
                if category.accent_color is None:
                    continue
                with self.subTest(series=code, category=category.code):
                    self.assertRegex(category.accent_color, r"^#[0-9A-Fa-f]{6}$")

    def test_a_malformed_class_colour_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "series.toml"
            path.write_text(
                """
[[series]]
code = "f1"
name = "Formula One"
short_name = "F1"
accent_color = "#E8112D"
[series.source]
adapter = "f1"
[[series.categories]]
code = "f1"
name = "Formula One"
short_name = "F1"
is_headline = true
[[series.categories]]
code = "f2"
name = "Formula 2"
short_name = "F2"
accent_color = "blue"
""",
                encoding="utf-8",
            )
            load_series.cache_clear()
            with self.assertRaises(ConfigError):
                load_series(directory)
            load_series.cache_clear()

    def test_no_venue_is_configured_with_utc(self):
        # A UTC "circuit-local" zone is always a data-entry mistake.
        for slug, venue in load_venues().items():
            with self.subTest(venue=slug):
                self.assertNotIn(venue.iana_timezone.upper(), ("UTC", "GMT"))

    def test_session_floors_cover_every_series(self):
        floors = load_session_floors()
        for code in load_series():
            with self.subTest(series=code):
                self.assertIn(code, floors)

    def test_a_floor_for_an_unknown_series_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "series.toml"
            path.write_text(
                '[[series]]\ncode = "f1"\nname = "n"\nshort_name = "s"\n'
                'accent_color = "#000000"\nsort_order = 1\n'
                '[[series.categories]]\ncode = "f1"\nname = "n"\nshort_name = "s"\n'
                "[validation.min_sessions_per_event]\nnope = 3\n"
            )
            with self.assertRaises(ConfigError):
                load_session_floors(directory)


class SourceRegistryTests(unittest.TestCase):
    def test_adapters_self_register(self):
        self.assertIn("f1", registered_adapters())
        self.assertIn("fixture", registered_adapters())
        self.assertIn("motogp", registered_adapters())
        self.assertIn("wsbk", registered_adapters())
        self.assertIn("wec", registered_adapters())

    def test_an_unknown_adapter_names_what_is_available(self):
        with self.assertRaises(KeyError) as caught:
            get_source("does-not-exist")
        self.assertIn("registered", str(caught.exception))

    def test_unimplemented_series_are_honest_about_it(self):
        # Better to report "no adapter yet" than to ship a stub that silently
        # returns nothing and looks like an empty calendar.
        for code in ("wrc", "imsa", "indycar", "nascar"):
            with self.subTest(series=code):
                self.assertNotIn(code, registered_adapters())


class ResolveSeriesTests(unittest.TestCase):
    """--series all is what the scheduled job runs, so it must stay green."""

    def test_all_covers_every_verified_series(self):
        from scrapers.run import resolve_series_codes

        registry = load_series()
        codes = resolve_series_codes("all", registry)
        expected = {code for code, series in registry.items() if series.source.is_verified}
        self.assertEqual(set(codes), expected)

    def test_all_skips_series_still_awaiting_discovery(self):
        # Otherwise every scheduled run exits non-zero and a real breakage is
        # lost among the permanent failures.
        from scrapers.run import resolve_series_codes

        registry = load_series()
        codes = resolve_series_codes("all", registry)
        for code, series in registry.items():
            if not series.source.is_verified:
                with self.subTest(series=code):
                    self.assertNotIn(code, codes)

    def test_naming_an_unverified_series_still_selects_it(self):
        # The unverified error is useful when it was asked for by name.
        from scrapers.run import resolve_series_codes

        registry = load_series()
        unverified = next(
            (code for code, s in registry.items() if not s.source.is_verified), None
        )
        if unverified is None:
            self.skipTest("every series is verified")
        self.assertEqual(resolve_series_codes(unverified, registry), [unverified])


class RateLimitTests(unittest.TestCase):
    def test_first_request_to_a_host_is_immediate(self):
        limiter = RateLimiter(min_interval=2.0, clock=lambda: 100.0)
        self.assertEqual(limiter.delay_for("example.test"), 0.0)

    def test_a_second_request_waits_out_the_interval(self):
        now = [100.0]
        limiter = RateLimiter(min_interval=2.0, clock=lambda: now[0])
        limiter.record("example.test")
        now[0] = 100.5
        self.assertAlmostEqual(limiter.delay_for("example.test"), 1.5)
        now[0] = 103.0
        self.assertEqual(limiter.delay_for("example.test"), 0.0)

    def test_hosts_are_limited_independently(self):
        limiter = RateLimiter(min_interval=2.0, clock=lambda: 100.0)
        limiter.record("a.test")
        self.assertEqual(limiter.delay_for("b.test"), 0.0)


class RetryTests(unittest.TestCase):
    def test_backoff_is_exponential(self):
        self.assertEqual([backoff_delay(n) for n in (1, 2, 3)], [2.0, 4.0, 8.0])

    def test_retryable_statuses(self):
        self.assertTrue(should_retry(503, attempt=1))
        self.assertTrue(should_retry(429, attempt=1))
        self.assertTrue(should_retry(None, attempt=1))
        self.assertFalse(should_retry(404, attempt=1))

    def test_attempts_are_capped_at_three(self):
        self.assertFalse(should_retry(503, attempt=3, max_attempts=3))


class HttpClientTests(unittest.TestCase):
    def test_a_transient_failure_is_retried_then_succeeds(self):
        calls = []
        slept = []

        def transport(url):
            calls.append(url)
            if len(calls) < 3:
                return Response(url=url, status=503, body=b"")
            return Response(url=url, status=200, body=b"ok", content_type="text/calendar")

        client = HttpClient(
            transport=transport,
            sleep=slept.append,
            respect_robots=False,
            rate_limiter=RateLimiter(min_interval=0.0),
        )
        response = client.get("https://example.test/feed.ics")

        self.assertEqual(response.body, b"ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(slept, [2.0, 4.0])

    def test_repeat_requests_to_one_host_are_spaced_out(self):
        slept = []
        client = HttpClient(
            transport=lambda url: Response(url=url, status=200, body=b"ok"),
            sleep=slept.append,
            respect_robots=False,
        )
        client.get("https://example.test/a.ics")
        client.get("https://example.test/b.ics")
        self.assertEqual(len(slept), 1)
        self.assertGreater(slept[0], 1.5)  # one request per host per 2 seconds

    def test_a_permanent_failure_is_not_retried(self):
        calls = []

        def transport(url):
            calls.append(url)
            return Response(url=url, status=404, body=b"")

        client = HttpClient(
            transport=transport,
            sleep=lambda _: None,
            respect_robots=False,
            rate_limiter=RateLimiter(min_interval=0.0),
        )
        with self.assertRaises(FetchError):
            client.get("https://example.test/missing.ics")
        self.assertEqual(len(calls), 1)

    def test_giving_up_after_three_attempts(self):
        calls = []

        def transport(url):
            calls.append(url)
            return Response(url=url, status=500, body=b"")

        client = HttpClient(
            transport=transport,
            sleep=lambda _: None,
            respect_robots=False,
            rate_limiter=RateLimiter(min_interval=0.0),
        )
        with self.assertRaises(FetchError):
            client.get("https://example.test/feed.ics")
        self.assertEqual(len(calls), 3)

    def test_robots_disallow_is_respected(self):
        def transport(url):
            if url.endswith("/robots.txt"):
                body = b"User-agent: *\nDisallow: /calendar/\n"
                return Response(url=url, status=200, body=body, content_type="text/plain")
            return Response(url=url, status=200, body=b"data")

        client = HttpClient(transport=transport, sleep=lambda _: None)
        with self.assertRaises(RobotsDisallowed):
            client.get("https://example.test/calendar/f1.ics")
        self.assertEqual(client.get("https://example.test/public.ics").body, b"data")

    def test_a_missing_robots_file_means_no_restriction(self):
        def transport(url):
            if url.endswith("/robots.txt"):
                return Response(url=url, status=404, body=b"")
            return Response(url=url, status=200, body=b"data")

        client = HttpClient(transport=transport, sleep=lambda _: None)
        self.assertEqual(client.get("https://example.test/feed.ics").body, b"data")


class SnapshotTests(unittest.TestCase):
    def test_body_is_written_and_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(directory)
            record = store.write(
                "f1", datetime(2026, 6, 1, tzinfo=timezone.utc), "https://x.test/f.ics", b"BEGIN", "text/calendar"
            )
            self.assertEqual(record.content_hash, content_hash(b"BEGIN"))
            self.assertTrue(Path(record.storage_path).exists())
            self.assertTrue(record.storage_path.endswith(".ics"))

    def test_only_the_configured_number_of_runs_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(directory, runs_kept=2)
            for day in (1, 2, 3, 4):
                store.write(
                    "f1", datetime(2026, 6, day, tzinfo=timezone.utc), "https://x.test/f.ics", b"body", "text/calendar"
                )
            removed = store.prune("f1")
            remaining = sorted(p.name for p in (Path(directory) / "f1").iterdir())
            self.assertEqual(len(removed), 2)
            self.assertEqual(remaining, ["20260603T000000Z", "20260604T000000Z"])


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["f1"]
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
            get_source("fixture"),
            self.venues,
            self.repository,
            SEASON,
            snapshot_store=self.store,
            now=datetime(2026, 1, 15, tzinfo=timezone.utc),
            session_floors=self.floors,
            **kwargs,
        )

    def test_a_full_run_succeeds(self):
        result = self._run()
        self.assertEqual(result.status, "success", result.error_message)
        self.assertEqual([issue for issue in result.issues if issue.severity == "error"], [])

    def test_the_ticket_entry_is_not_treated_as_a_session(self):
        result = self._run()
        names = [session.display_name for event in result.events for session in event.sessions]
        self.assertNotIn("Tickets on sale", names)

    def test_two_weekends_are_recognised(self):
        result = self._run()
        self.assertEqual({event.slug for event in result.events}, {"gran-premio-d-italia", "australian-grand-prix"})

    def test_support_series_land_on_the_headline_weekend(self):
        result = self._run()
        monza = next(event for event in result.events if event.slug == "gran-premio-d-italia")
        self.assertEqual({session.category_code for session in monza.sessions}, {"f1", "f2", "f3", "f1a"})
        self.assertEqual(monza.round_number, 16)

    def test_times_are_converted_from_circuit_local(self):
        result = self._run()
        monza = next(event for event in result.events if event.slug == "gran-premio-d-italia")
        race = next(
            session
            for session in monza.sessions
            if session.category_code == "f1" and session.session_type == "race"
        )
        self.assertEqual(race.start_utc, datetime(2026, 9, 6, 13, 0, tzinfo=timezone.utc))

    def test_a_utc_stamped_entry_is_read_as_utc(self):
        result = self._run()
        melbourne = next(event for event in result.events if event.slug == "australian-grand-prix")
        race = next(session for session in melbourne.sessions if session.session_type == "race")
        self.assertEqual(race.start_utc, datetime(2026, 3, 8, 4, 0, tzinfo=timezone.utc))

    def test_the_sprint_weekend_is_classified_correctly(self):
        result = self._run()
        melbourne = next(event for event in result.events if event.slug == "australian-grand-prix")
        types = {session.display_name: session.session_type for session in melbourne.sessions}
        self.assertEqual(types["Sprint Qualifying"], "sprint_qualifying")
        self.assertEqual(types["Sprint"], "sprint")
        self.assertEqual(types["Qualifying"], "qualifying")

    def test_a_date_only_entry_is_flagged_rather_than_shown_as_midnight(self):
        result = self._run()
        monza = next(event for event in result.events if event.slug == "gran-premio-d-italia")
        academy = next(session for session in monza.sessions if session.category_code == "f1a")
        self.assertEqual(academy.start_precision, "day")
        self.assertEqual(academy.time_status, "provisional")

    def test_duration_only_entries_get_an_end_time(self):
        result = self._run()
        monza = next(event for event in result.events if event.slug == "gran-premio-d-italia")
        fp2 = next(session for session in monza.sessions if session.display_name == "Practice 2")
        self.assertEqual(fp2.end_utc, datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc))

    def test_every_session_falls_inside_its_event_span(self):
        result = self._run()
        for event in result.events:
            for session in event.sessions:
                with self.subTest(session=session.display_name):
                    self.assertGreaterEqual(session.start_utc, event.starts_at_utc)
                    self.assertLessEqual(session.start_utc, event.ends_at_utc)

    def test_running_twice_changes_nothing_the_second_time(self):
        first = self._run()
        self.assertGreater(first.records_changed, 0)

        second = self._run()
        self.assertEqual(second.status, "success", second.error_message)
        self.assertEqual(second.records_changed, 0)
        self.assertEqual(self.repository.changes, [])

    def test_a_dry_run_writes_nothing(self):
        result = self._run(dry_run=True)
        self.assertEqual(result.status, "success")
        self.assertEqual(self.repository.sessions, {})

    def test_the_raw_response_is_snapshotted_before_parsing(self):
        result = self._run()
        self.assertEqual(len(result.snapshots), 1)
        self.assertTrue(Path(result.snapshots[0].storage_path).exists())

    def test_snapshots_are_linked_to_the_run(self):
        self._run()
        self.assertEqual(len(self.repository.snapshots), 1)
        run_id, url, digest = self.repository.snapshots[0]
        self.assertEqual(run_id, 1)
        self.assertTrue(url.startswith("fixture://"))
        self.assertEqual(len(digest), 64)

    def test_the_run_is_logged(self):
        self._run()
        self.assertEqual(self.repository.runs[0]["status"], "success")
        self.assertEqual(self.repository.runs[0]["records_found"], 19)

    def test_the_series_staleness_marker_is_updated(self):
        self._run()
        self.assertIn("f1", self.repository.last_scraped)


class RealFeedShapeTests(unittest.TestCase):
    """Parses a capture of a real published F1 ICS feed.

    This is the test that catches the feed changing shape. If it goes red, look
    at the committed fixture before touching the parser.
    """

    def setUp(self):
        from scrapers.sources.base import FetchedDocument
        from scrapers.sources.f1 import FormulaOneSource, strip_decoration

        self.strip_decoration = strip_decoration
        self.series = load_series()["f1"]
        self.venues = load_venues()
        body = (Path(__file__).resolve().parent.parent / "scrapers/fixtures/f1_ical_feed.ics").read_bytes()
        document = FetchedDocument(url="fixture://f1_ical_feed.ics", body=body, content_type="text/calendar")
        parsed = FormulaOneSource().parse([document], self.series, self.venues, SEASON)
        from scrapers.normalize import normalize

        self.events = normalize(parsed, self.series, self.venues)

    def test_emoji_are_stripped_from_names(self):
        self.assertEqual(self.strip_decoration("🇮🇹 Italian GP"), "Italian GP")
        self.assertEqual(self.strip_decoration("🏎️ Ferrari Car Launch"), "Ferrari Car Launch")
        for event in self.events:
            self.assertTrue(event.name.isascii(), event.name)
            for session in event.sessions:
                self.assertTrue(session.display_name.isascii(), session.display_name)

    def test_non_session_entries_are_dropped(self):
        names = [event.name for event in self.events]
        self.assertNotIn("Ferrari Car Launch", names)
        self.assertNotIn("Pre-season Testing 2026 #1", names)

    def test_practice_ordinals_come_out_chronological(self):
        monza = next(event for event in self.events if event.slug == "italian-gp")
        practices = [s for s in monza.sessions if s.session_type == "practice"]
        self.assertEqual([s.sequence for s in practices], [1, 2, 3])
        self.assertEqual(practices[0].display_name, "First Free Practice")

    def test_sprint_weekend_is_classified(self):
        china = next(event for event in self.events if event.slug == "chinese-gp")
        types = {s.session_type for s in china.sessions}
        self.assertIn("sprint", types)
        self.assertIn("sprint_qualifying", types)

    def test_two_spanish_rounds_resolve_to_different_venues(self):
        # From 2026 Spain has both Barcelona and Madrid. A "spain" venue alias
        # would silently send one to the wrong circuit and the wrong timezone.
        venues = {event.slug: event.venue_slug for event in self.events}
        self.assertEqual(venues["spanish-gp"], "madrid")
        self.assertEqual(venues["barcelona-gp"], "barcelona")

    def test_utc_stamped_times_are_preserved_exactly(self):
        monza = next(event for event in self.events if event.slug == "italian-gp")
        race = next(s for s in monza.sessions if s.session_type == "race")
        self.assertEqual(race.start_utc, datetime(2026, 9, 6, 13, 0, tzinfo=timezone.utc))


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["f1"]
        self.venues = load_venues()
        source = get_source("fixture")
        from scrapers.normalize import normalize
        from scrapers.sources.base import FetchedDocument
        from scrapers.sources.fixture import read_fixture

        url = source.urls(SEASON)[0]
        documents = [FetchedDocument(url=url, body=read_fixture(url), content_type="text/calendar")]
        self.events = normalize(source.parse(documents, self.series, self.venues, SEASON), self.series, self.venues)

    def test_the_fixture_is_clean(self):
        issues = validate(self.events, self.series, self.venues, min_sessions_per_event=5)
        self.assertEqual([issue for issue in issues if issue.severity == "error"], [])

    def test_a_thin_weekend_trips_the_session_floor(self):
        event = self.events[0]
        event.sessions = event.sessions[:1]
        issues = validate([event], self.series, self.venues, min_sessions_per_event=5)
        self.assertIn("session_floor", [issue.code for issue in issues])

    def test_a_partial_rally_downgrades_the_floor_to_a_warning(self):
        event = self.events[0]
        event.sessions = event.sessions[:1]
        event.detail_level = "partial"
        issues = validate([event], self.series, self.venues, min_sessions_per_event=5)
        floor = next(issue for issue in issues if issue.code == "session_floor")
        self.assertEqual(floor.severity, "warning")

    def test_a_time_far_outside_the_season_is_an_error(self):
        event = self.events[0]
        event.sessions[0].start_utc = datetime(2031, 5, 1, tzinfo=timezone.utc)
        issues = validate(self.events, self.series, self.venues)
        self.assertIn("start_outside_season", [issue.code for issue in issues])

    def test_duplicate_natural_keys_are_errors(self):
        event = self.events[0]
        first = event.sessions[0]
        clone = type(first)(**{**first.__dict__})
        clone.ics_uid = first.ics_uid + "-clone"
        event.sessions.append(clone)
        issues = validate([event], self.series, self.venues)
        self.assertIn("duplicate_session_key", [issue.code for issue in issues])

    def test_raise_for_errors_ignores_warnings(self):
        raise_for_errors([ValidationIssue("warning", "x", "just a warning")])


if __name__ == "__main__":
    unittest.main()