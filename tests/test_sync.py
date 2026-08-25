"""Sync and guard tests.

These encode the brief's non-negotiable reliability rules. If any of them ever
goes red, the scraper is capable of destroying a working calendar.
"""

import unittest
from datetime import datetime, timedelta, timezone

from scrapers.config import load_series, load_venues
from scrapers.normalize import normalize
from scrapers.records import ParsedSession
from scrapers.repository import InMemoryRepository
from scrapers.sync import (
    ExistingSession,
    GuardTripped,
    apply_guards,
    diff_sessions,
    guard_change_threshold,
    guard_not_empty,
)

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def parsed(name, category, start, event="Italian Grand Prix"):
    return ParsedSession(
        series_code="f1",
        season=2026,
        event_name=event,
        category_code=category,
        raw_session_name=name,
        venue_slug="monza",
        local_start=start,
    )


def weekend(race_hour=15):
    return [
        parsed("Practice 1", "f1", datetime(2026, 9, 4, 13, 30)),
        parsed("Practice 2", "f1", datetime(2026, 9, 4, 17, 0)),
        parsed("Practice 3", "f1", datetime(2026, 9, 5, 12, 30)),
        parsed("Qualifying", "f1", datetime(2026, 9, 5, 16, 0)),
        parsed("Race", "f1", datetime(2026, 9, 6, race_hour, 0)),
    ]


class DiffTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["f1"]
        self.venues = load_venues()
        self.events = normalize(weekend(), self.series, self.venues)

    def test_first_run_creates_everything(self):
        plan = diff_sessions([], self.events)
        self.assertEqual(len(plan.creates), 5)
        self.assertEqual(plan.updates, [])
        self.assertEqual(plan.retire, [])

    def test_second_identical_run_is_a_noop(self):
        repository = InMemoryRepository()
        repository.apply(diff_sessions([], self.events), "f1", 2026, run_id=1)

        existing = repository.load_existing_sessions("f1", 2026)
        second = diff_sessions(existing, self.events)

        self.assertTrue(second.is_noop, f"unexpected changes: {second.creates} {second.updates}")
        self.assertEqual(len(second.unchanged), 5)
        self.assertEqual(repository.changes, [])

    def test_a_moved_session_produces_one_audit_row_and_bumps_the_calendar(self):
        repository = InMemoryRepository()
        repository.apply(diff_sessions([], self.events), "f1", 2026, run_id=1)

        moved = normalize(weekend(race_hour=14), self.series, self.venues)
        existing = repository.load_existing_sessions("f1", 2026)
        plan = diff_sessions(existing, moved)

        self.assertEqual(len(plan.updates), 1)
        update = plan.updates[0]
        self.assertEqual([change.field_changed for change in update.changes], ["start_utc"])
        self.assertTrue(update.bumps_ics_sequence)

        repository.apply(plan, "f1", 2026, run_id=2)
        self.assertEqual(len(repository.changes), 1)
        session = next(
            stored.record for stored in repository.sessions.values() if stored.record.session_type == "race"
        )
        self.assertEqual(session.ics_sequence, 1)

    def test_a_cosmetic_change_does_not_notify_subscribers(self):
        repository = InMemoryRepository()
        repository.apply(diff_sessions([], self.events), "f1", 2026, run_id=1)

        for event in self.events:
            for session in event.sessions:
                session.source_url = "https://example.test/new-path"

        plan = diff_sessions(repository.load_existing_sessions("f1", 2026), self.events)
        self.assertEqual(len(plan.updates), 5)
        self.assertFalse(any(update.bumps_ics_sequence for update in plan.updates))

    def test_a_session_missing_from_the_feed_is_retired_not_deleted(self):
        repository = InMemoryRepository()
        repository.apply(diff_sessions([], self.events), "f1", 2026, run_id=1)

        shorter = normalize(weekend()[:4], self.series, self.venues)
        plan = diff_sessions(repository.load_existing_sessions("f1", 2026), shorter)

        self.assertEqual(len(plan.retire), 1)
        self.assertEqual(plan.retire[0].session_type, "race")

        repository.apply(plan, "f1", 2026, run_id=2)
        self.assertEqual(len(repository.sessions), 5)  # still there, just retired

    def test_a_returning_session_is_revived(self):
        repository = InMemoryRepository()
        repository.apply(diff_sessions([], self.events), "f1", 2026, run_id=1)
        shorter = normalize(weekend()[:4], self.series, self.venues)
        repository.apply(diff_sessions(repository.load_existing_sessions("f1", 2026), shorter), "f1", 2026, 2)

        plan = diff_sessions(repository.load_existing_sessions("f1", 2026), self.events)
        self.assertEqual(len(plan.revive), 1)
        repository.apply(plan, "f1", 2026, run_id=3)
        self.assertTrue(all(stored.record.retired_at is None for stored in repository.sessions.values()))


def existing_sessions(count, *, start=datetime(2026, 9, 6, tzinfo=timezone.utc)):
    return [
        ExistingSession(
            id=index,
            event_slug="italian-grand-prix",
            category_code="f1",
            session_type="practice",
            sequence=index,
            display_name=f"Practice {index}",
            start_utc=start + timedelta(days=index),
        )
        for index in range(1, count + 1)
    ]


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["f1"]
        self.venues = load_venues()

    def test_an_empty_response_is_a_failed_run_not_an_empty_calendar(self):
        plan = diff_sessions(existing_sessions(20), [])
        with self.assertRaises(GuardTripped):
            guard_not_empty(plan, records_found=0)

    def test_a_seventy_percent_change_aborts(self):
        existing = existing_sessions(20)
        events = normalize(weekend(), self.series, self.venues)  # nothing matches
        plan = diff_sessions(existing, events)
        # every existing session would be retired: 100% of the upcoming set
        with self.assertRaises(GuardTripped) as caught:
            guard_change_threshold(plan, existing, now=NOW)
        self.assertGreater(caught.exception.ratio, 0.7)

    def test_a_small_change_passes(self):
        existing = existing_sessions(20)
        plan = diff_sessions(existing, [])
        plan.retire = plan.retire[:5]  # 5/20 = 25%
        guard_change_threshold(plan, existing, now=NOW)

    def test_the_guard_stands_down_below_the_baseline(self):
        existing = existing_sessions(4)
        plan = diff_sessions(existing, [])
        guard_change_threshold(plan, existing, now=NOW)  # must not raise

    def test_past_sessions_do_not_count_towards_the_ratio(self):
        past = existing_sessions(20, start=datetime(2020, 1, 1, tzinfo=timezone.utc))
        plan = diff_sessions(past, [])
        guard_change_threshold(plan, past, now=NOW)  # all retirements are historical

    def test_apply_guards_runs_both_checks(self):
        existing = existing_sessions(20)
        plan = diff_sessions(existing, [])
        with self.assertRaises(GuardTripped):
            apply_guards(plan, existing, records_found=0, now=NOW)

    def test_a_tripped_guard_leaves_the_repository_untouched(self):
        repository = InMemoryRepository()
        events = normalize(weekend(), self.series, self.venues)
        repository.apply(diff_sessions([], events), "f1", 2026, run_id=1)
        before = {key: stored.record.start_utc for key, stored in repository.sessions.items()}

        existing = repository.load_existing_sessions("f1", 2026)
        plan = diff_sessions(existing, [])
        try:
            apply_guards(plan, existing, records_found=0, now=NOW)
        except GuardTripped:
            pass
        after = {key: stored.record.start_utc for key, stored in repository.sessions.items()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
