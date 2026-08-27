"""Normalize tests.

Two things break this product in the field: a session filed under the wrong
type, and a time converted with the wrong zone. Both are tested here against
the cases that actually occur on the calendar.
"""

import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from scrapers.config import load_series, load_venues
from scrapers.normalize import (
    NormalizeError,
    classify_session_type,
    extract_sequence,
    normalize,
)
from scrapers.records import ParsedSession, build_ics_uid


class ClassificationTests(unittest.TestCase):
    def test_practice_variants(self):
        for name in ("Free Practice 1", "Practice 2", "FP3", "Practice"):
            self.assertEqual(classify_session_type(name), "practice", name)

    def test_qualifying_variants(self):
        for name in ("Qualifying", "Qualifying 1", "Q2", "Hyperpole", "Superpole"):
            self.assertEqual(classify_session_type(name), "qualifying", name)

    def test_indycar_spells_it_qualifications(self):
        """The plural was the gap: a word boundary does not match before an "s"."""
        for name in ("Qualifications", "Qualification", "Qualifying (Firestone Fast 6)"):
            self.assertEqual(classify_session_type(name), "qualifying", name)

    def test_the_build_up_to_a_race_is_not_a_race(self):
        """IndyCar lists a "Pre-Race" ninety minutes before the Indianapolis 500.

        The word "race" is inside it, so the general rule would call it one -
        and a second Indy 500 would appear on the board at an hour nobody goes
        green. The real race must still classify as a race, including the ones
        whose names are unusual.
        """
        for name in ("Pre-Race", "Pre Race Show", "Post-Race", "Post-Race Show"):
            self.assertEqual(classify_session_type(name), "other", name)
        for name in ("Race", "Race 2", "Feature Race", "Superpole Race", "Grand Prix"):
            self.assertEqual(classify_session_type(name), "race", name)

    def test_superpole_race_is_a_race_not_qualifying(self):
        # WorldSBK's Sunday morning race. Getting this wrong hides a race.
        self.assertEqual(classify_session_type("Superpole Race"), "race")

    def test_sprint_qualifying_is_not_sprint_and_not_qualifying(self):
        self.assertEqual(classify_session_type("Sprint Qualifying"), "sprint_qualifying")
        self.assertEqual(classify_session_type("Sprint Shootout"), "sprint_qualifying")
        self.assertEqual(classify_session_type("Sprint"), "sprint")
        self.assertEqual(classify_session_type("Sprint Race"), "sprint")

    def test_rally_shapes(self):
        self.assertEqual(classify_session_type("Shakedown"), "shakedown")
        self.assertEqual(classify_session_type("SS4 Ouninpohja"), "stage")
        self.assertEqual(classify_session_type("Power Stage"), "stage")

    def test_endurance_and_feature_races(self):
        self.assertEqual(classify_session_type("24 Hours of Le Mans"), "race")
        self.assertEqual(classify_session_type("6 Hours of Spa"), "race")
        self.assertEqual(classify_session_type("Feature Race"), "race")

    def test_warmup_and_test(self):
        self.assertEqual(classify_session_type("Warm Up"), "warmup")
        self.assertEqual(classify_session_type("Warm-up"), "warmup")
        self.assertEqual(classify_session_type("Prologue"), "test")
        self.assertEqual(classify_session_type("Preseason Testing"), "test")

    def test_unrecognised_falls_back_to_other(self):
        self.assertEqual(classify_session_type("Drivers' Parade"), "other")

    def test_a_hint_outside_the_vocabulary_is_refused(self):
        with self.assertRaises(NormalizeError):
            classify_session_type("Race", hint="grand_prix")


class SequenceTests(unittest.TestCase):
    def test_numbers_are_read_from_known_shapes(self):
        self.assertEqual(extract_sequence("Free Practice 2"), 2)
        self.assertEqual(extract_sequence("FP3"), 3)
        self.assertEqual(extract_sequence("SS12 Ouninpohja"), 12)

    def test_a_number_that_is_not_a_session_number_is_ignored(self):
        # The failure this guards against: "24 Hours of Le Mans" as session 24.
        self.assertIsNone(extract_sequence("24 Hours of Le Mans"))
        self.assertIsNone(extract_sequence("6 Hours of Spa"))
        self.assertIsNone(extract_sequence("Qualifying"))


def _session(name, category, start, venue="monza", **kwargs):
    return ParsedSession(
        series_code="f1",
        season=2026,
        event_name=kwargs.pop("event_name", "Italian Grand Prix"),
        category_code=category,
        raw_session_name=name,
        venue_slug=venue,
        local_start=start,
        **kwargs,
    )


class TimezoneTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["f1"]
        self.venues = load_venues()

    def _one(self, parsed):
        events = normalize(parsed, self.series, self.venues)
        return events[0].sessions[0]

    def test_circuit_local_converts_through_the_iana_zone(self):
        session = self._one([_session("Race", "f1", datetime(2026, 9, 6, 15, 0))])
        self.assertEqual(session.start_utc, datetime(2026, 9, 6, 13, 0, tzinfo=timezone.utc))

    def test_the_same_wall_clock_maps_differently_across_a_dst_boundary(self):
        # Europe/Rome is +02:00 in September and +01:00 in November. A fixed
        # offset would put one of these an hour out.
        summer = self._one([_session("Race", "f1", datetime(2026, 9, 6, 15, 0))])
        winter = self._one(
            [_session("Race", "f1", datetime(2026, 11, 8, 15, 0), event_name="Winter Test")]
        )
        self.assertEqual(summer.start_utc.hour, 13)
        self.assertEqual(winter.start_utc.hour, 14)

    def test_southern_hemisphere_dst_runs_the_other_way(self):
        march = self._one(
            [
                _session(
                    "Race", "f1", datetime(2026, 3, 8, 15, 0),
                    venue="melbourne", event_name="Australian Grand Prix",
                )
            ]
        )
        july = self._one(
            [
                _session(
                    "Race", "f1", datetime(2026, 7, 8, 15, 0),
                    venue="melbourne", event_name="Australian Winter Test",
                )
            ]
        )
        self.assertEqual(march.start_utc, datetime(2026, 3, 8, 4, 0, tzinfo=timezone.utc))  # +11
        self.assertEqual(july.start_utc, datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc))  # +10

    def test_a_zone_that_never_observes_dst(self):
        for month, expected_hour in ((1, 20), (7, 20)):
            session = self._one(
                [
                    _session(
                        "Race", "f1", datetime(2026, month, 15, 13, 0),
                        venue="phoenix", event_name=f"Phoenix {month}",
                    )
                ]
            )
            self.assertEqual(session.start_utc.hour, expected_hour, month)  # MST all year

    def test_non_hour_offset(self):
        session = self._one(
            [_session("Race", "f1", datetime(2026, 10, 4, 15, 0), venue="buddh", event_name="Indian GP")]
        )
        self.assertEqual(session.start_utc, datetime(2026, 10, 4, 9, 30, tzinfo=timezone.utc))

    def test_an_already_absolute_time_is_passed_through(self):
        parsed = ParsedSession(
            series_code="f1",
            season=2026,
            event_name="Australian Grand Prix",
            category_code="f1",
            raw_session_name="Race",
            venue_slug="melbourne",
            start_utc=datetime(2026, 3, 8, 4, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(self._one([parsed]).start_utc, datetime(2026, 3, 8, 4, 0, tzinfo=timezone.utc))

    def test_a_session_ending_before_it_starts_is_refused(self):
        parsed = _session("Race", "f1", datetime(2026, 9, 6, 15, 0))
        parsed.local_end = datetime(2026, 9, 6, 14, 0)
        with self.assertRaises(NormalizeError):
            normalize([parsed], self.series, self.venues)

    def test_a_timezone_override_is_recorded_only_when_it_differs(self):
        same = _session("Race", "f1", datetime(2026, 9, 6, 15, 0))
        same.local_timezone = "Europe/Rome"
        self.assertIsNone(self._one([same]).iana_timezone)

        different = _session("SS1 Border Stage", "f1", datetime(2026, 9, 6, 15, 0))
        different.local_timezone = "Europe/Zurich"
        self.assertEqual(self._one([different]).iana_timezone, "Europe/Zurich")


class GroupingTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["f1"]
        self.venues = load_venues()

    def test_support_series_share_one_event(self):
        parsed = [
            _session("Practice 1", "f1", datetime(2026, 9, 4, 13, 30)),
            _session("Qualifying", "f1", datetime(2026, 9, 5, 16, 0)),
            _session("Race", "f1", datetime(2026, 9, 6, 15, 0)),
            _session("Feature Race", "f2", datetime(2026, 9, 6, 10, 10)),
            _session("Sprint Race", "f3", datetime(2026, 9, 5, 8, 30)),
        ]
        events = normalize(parsed, self.series, self.venues)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events[0].sessions), 5)
        self.assertEqual({s.category_code for s in events[0].sessions}, {"f1", "f2", "f3"})

    def test_event_span_covers_every_session(self):
        parsed = [
            _session("Practice 1", "f1", datetime(2026, 9, 4, 13, 30)),
            _session("Race", "f1", datetime(2026, 9, 6, 15, 0), duration_minutes=120),
        ]
        event = normalize(parsed, self.series, self.venues)[0]
        self.assertEqual(event.starts_at_utc, datetime(2026, 9, 4, 11, 30, tzinfo=timezone.utc))
        self.assertEqual(event.ends_at_utc, datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc))

    def test_sessions_are_ordered_chronologically(self):
        parsed = [
            _session("Race", "f1", datetime(2026, 9, 6, 15, 0)),
            _session("Practice 1", "f1", datetime(2026, 9, 4, 13, 30)),
            _session("Qualifying", "f1", datetime(2026, 9, 5, 16, 0)),
        ]
        event = normalize(parsed, self.series, self.venues)[0]
        self.assertEqual(
            [s.display_name for s in event.sessions], ["Practice 1", "Qualifying", "Race"]
        )

    def test_sequence_is_stable_when_an_earlier_session_is_added(self):
        # A weekend-wide index would renumber the race when FP2 appears, which
        # would orphan the existing row on the next upsert.
        before = normalize(
            [
                _session("Practice 1", "f1", datetime(2026, 9, 4, 13, 30)),
                _session("Race", "f1", datetime(2026, 9, 6, 15, 0)),
            ],
            self.series,
            self.venues,
        )[0]
        after = normalize(
            [
                _session("Practice 1", "f1", datetime(2026, 9, 4, 13, 30)),
                _session("Practice 2", "f1", datetime(2026, 9, 4, 17, 0)),
                _session("Race", "f1", datetime(2026, 9, 6, 15, 0)),
            ],
            self.series,
            self.venues,
        )[0]
        race_before = next(s for s in before.sessions if s.session_type == "race")
        race_after = next(s for s in after.sessions if s.session_type == "race")
        self.assertEqual(race_before.natural_key, race_after.natural_key)

    def test_positional_fallback_when_names_carry_no_numbers(self):
        event = normalize(
            [
                _session("Practice", "f2", datetime(2026, 9, 4, 11, 0)),
                _session("Practice", "f2", datetime(2026, 9, 4, 15, 0)),
            ],
            self.series,
            self.venues,
        )[0]
        self.assertEqual(sorted(s.sequence for s in event.sessions), [1, 2])

    def test_calendar_uid_is_stable_and_unique(self):
        event = normalize(
            [
                _session("Practice 1", "f1", datetime(2026, 9, 4, 13, 30)),
                _session("Practice 1", "f2", datetime(2026, 9, 4, 11, 0)),
            ],
            self.series,
            self.venues,
        )[0]
        uids = [s.ics_uid for s in event.sessions]
        self.assertEqual(len(set(uids)), 2)
        self.assertIn(build_ics_uid("f1", 2026, "italian-grand-prix", "f1", "Practice 1"), uids)

    def test_an_unknown_venue_is_refused_rather_than_guessed(self):
        with self.assertRaises(NormalizeError):
            normalize(
                [_session("Race", "f1", datetime(2026, 9, 6, 15, 0), venue="nowhere")],
                self.series,
                self.venues,
            )

    def test_an_unknown_category_is_refused(self):
        with self.assertRaises(Exception):
            normalize(
                [_session("Race", "motogp", datetime(2026, 9, 6, 15, 0))],
                self.series,
                self.venues,
            )

    def test_one_event_cannot_span_two_venues(self):
        parsed = [
            _session("Practice 1", "f1", datetime(2026, 9, 4, 13, 30), venue="monza"),
            _session("Race", "f1", datetime(2026, 9, 6, 15, 0), venue="imola"),
        ]
        with self.assertRaises(NormalizeError):
            normalize(parsed, self.series, self.venues)


if __name__ == "__main__":
    unittest.main()


class ImpossibleOverlapTests(unittest.TestCase):
    """Two sessions of one class at the same instant.

    A car cannot be in two places at once, so this is not a schedule - it is a
    schedule with a mistake in it, and the mistake belongs to the source. Which
    of the two times is wrong is not knowable from here, and inventing a
    correction would be worse than saying nothing, so both are kept and both
    are marked provisional.

    This is a general rule rather than a patch for one site: it was written for
    F1 Academy publishing Montreal's two qualifying sessions at an identical
    minute, and it immediately found the same fault in Formula 2.
    """

    def setUp(self):
        self.series = load_series()["f1"]
        self.venues = load_venues()

    def _normalize(self, parsed):
        events = list(normalize(parsed, self.series, self.venues))
        self.assertEqual(len(events), 1)
        return events[0].sessions

    def test_a_clash_is_flagged_and_both_sessions_are_kept(self):
        clash = datetime(2026, 9, 5, 14, 0)
        sessions = self._normalize([
            _session("Qualifying 1", "f1", clash),
            _session("Qualifying 2", "f1", clash),
        ])
        self.assertEqual(len(sessions), 2)
        for item in sessions:
            with self.subTest(item.display_name):
                self.assertEqual(item.time_status, "provisional")

    def test_two_classes_at_one_instant_are_left_alone(self):
        """Different championships sharing a minute is a clash of nothing.

        Support classes are attached to a Grand Prix weekend by date, so two of
        them lining up is ordinary - only one class doing two things at once is
        impossible.
        """
        clash = datetime(2026, 9, 5, 14, 0)
        sessions = self._normalize([
            _session("Qualifying", "f2", clash),
            _session("Qualifying", "f3", clash),
        ])
        self.assertTrue(all(item.time_status == "confirmed" for item in sessions))

    def test_day_precision_anchors_do_not_count_as_a_clash(self):
        """A day-precision time is an anchor for a date, not a claim about a clock.

        A round with no published times gets every session anchored at local
        midday, so several sharing an instant is the design working rather than
        a contradiction - and flagging them would be flagging them twice.
        """
        anchor = datetime(2026, 9, 5, 12, 0)
        sessions = self._normalize([
            _session("Practice", "f2", anchor, start_precision="day", time_status="provisional"),
            _session("Qualifying", "f2", anchor, start_precision="day", time_status="provisional"),
        ])
        self.assertEqual(len(sessions), 2)
        for item in sessions:
            with self.subTest(item.display_name):
                self.assertEqual(item.start_precision, "day")
