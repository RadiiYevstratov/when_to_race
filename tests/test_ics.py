"""ICS reader tests.

A feed is the best available source, so this parser has to survive real-world
formatting: folded lines, quoted parameters, three flavours of DTSTART, and
junk it should tolerate rather than choke on.
"""

import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from scrapers.ics import (
    IcsError,
    parse_calendar,
    parse_datetime,
    parse_duration,
    resolve_end,
    split_property,
    unescape_text,
    unfold,
)


class UnfoldTests(unittest.TestCase):
    def test_space_continuation_is_joined(self):
        # One space is the fold marker and is removed; a publisher wanting a
        # space at the fold point emits two, which is what this feed does.
        self.assertEqual(unfold("SUMMARY:Practice\n  1"), ["SUMMARY:Practice 1"])
        self.assertEqual(unfold("SUMMARY:Prac\n tice"), ["SUMMARY:Practice"])

    def test_tab_continuation_is_joined(self):
        self.assertEqual(unfold("SUMMARY:Race\n\tday"), ["SUMMARY:Raceday"])

    def test_crlf_and_lone_cr_both_work(self):
        self.assertEqual(unfold("A:1\r\nB:2"), ["A:1", "B:2"])
        self.assertEqual(unfold("A:1\rB:2"), ["A:1", "B:2"])

    def test_leading_continuation_without_a_previous_line_is_not_dropped(self):
        self.assertEqual(unfold(" orphan"), ["orphan"])


class SplitPropertyTests(unittest.TestCase):
    def test_plain_property(self):
        self.assertEqual(split_property("SUMMARY:Race"), ("SUMMARY", {}, "Race"))

    def test_parameters_are_parsed(self):
        name, params, value = split_property("DTSTART;TZID=Europe/Rome:20260906T150000")
        self.assertEqual(name, "DTSTART")
        self.assertEqual(params, {"TZID": "Europe/Rome"})
        self.assertEqual(value, "20260906T150000")

    def test_colon_inside_a_quoted_parameter_is_not_the_separator(self):
        name, params, value = split_property('ATTENDEE;MEMBER="mailto:a@b.c":mailto:d@e.f')
        self.assertEqual(name, "ATTENDEE")
        self.assertEqual(params["MEMBER"], "mailto:a@b.c")
        self.assertEqual(value, "mailto:d@e.f")

    def test_value_containing_a_colon_survives(self):
        _, _, value = split_property("DESCRIPTION:Starts at 15:00 local")
        self.assertEqual(value, "Starts at 15:00 local")

    def test_missing_separator_raises(self):
        with self.assertRaises(IcsError):
            split_property("BROKEN LINE")


class TextTests(unittest.TestCase):
    def test_escapes(self):
        self.assertEqual(unescape_text(r"Monza\, Italy"), "Monza, Italy")
        self.assertEqual(unescape_text(r"line\nline"), "line\nline")
        self.assertEqual(unescape_text(r"a\;b"), "a;b")
        self.assertEqual(unescape_text(r"back\\slash"), "back\\slash")


class DurationTests(unittest.TestCase):
    def test_hours_and_minutes(self):
        self.assertEqual(parse_duration("PT1H30M"), timedelta(hours=1, minutes=30))

    def test_days_and_weeks(self):
        self.assertEqual(parse_duration("P1D"), timedelta(days=1))
        self.assertEqual(parse_duration("P2W"), timedelta(weeks=2))

    def test_negative(self):
        self.assertEqual(parse_duration("-PT15M"), timedelta(minutes=-15))

    def test_garbage_raises(self):
        for value in ("", "PT", "1H", "P"):
            with self.assertRaises(IcsError):
                parse_duration(value)


class DateTimeTests(unittest.TestCase):
    def test_tzid_attaches_the_zone(self):
        result = parse_datetime("20260906T150000", {"TZID": "Europe/Rome"})
        self.assertEqual(result.value, datetime(2026, 9, 6, 15, 0, tzinfo=ZoneInfo("Europe/Rome")))
        self.assertFalse(result.is_utc)

    def test_trailing_z_is_utc(self):
        result = parse_datetime("20260308T040000Z", {})
        self.assertTrue(result.is_utc)
        self.assertEqual(result.value, datetime(2026, 3, 8, 4, 0, tzinfo=timezone.utc))

    def test_z_wins_over_a_contradictory_tzid(self):
        result = parse_datetime("20260308T040000Z", {"TZID": "Europe/Rome"})
        self.assertEqual(result.value.utcoffset(), timezone.utc.utcoffset(None))
        self.assertIsNone(result.tzid)

    def test_date_only_is_kept_as_a_date(self):
        result = parse_datetime("20260905", {"VALUE": "DATE"})
        self.assertTrue(result.is_date_only)
        self.assertEqual(result.value, date(2026, 9, 5))

    def test_floating_time_stays_naive(self):
        result = parse_datetime("20260906T150000", {})
        self.assertIsNone(result.value.tzinfo)

    def test_unknown_tzid_raises(self):
        with self.assertRaises(IcsError):
            parse_datetime("20260906T150000", {"TZID": "Mars/Olympus"})


class CalendarTests(unittest.TestCase):
    FEED = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:one\r\n"
        "SUMMARY:FORMULA 1 GRAN PREMIO D'ITALIA 2026 - Practice\r\n"
        "  1\r\n"
        "LOCATION:Autodromo Nazionale Monza\\, Monza\\, Italy\r\n"
        "DTSTART;TZID=Europe/Rome:20260904T133000\r\n"
        "DTEND;TZID=Europe/Rome:20260904T143000\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:two\r\n"
        "SUMMARY:Race\r\n"
        "DTSTART;TZID=Europe/Rome:20260906T150000\r\n"
        "DURATION:PT2H\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    def test_events_are_extracted_in_order(self):
        events = parse_calendar(self.FEED)
        self.assertEqual([event.uid for event in events], ["one", "two"])

    def test_folded_summary_is_rejoined_and_text_unescaped(self):
        first = parse_calendar(self.FEED)[0]
        self.assertEqual(first.summary, "FORMULA 1 GRAN PREMIO D'ITALIA 2026 - Practice 1")
        self.assertEqual(first.get("LOCATION"), "Autodromo Nazionale Monza, Monza, Italy")

    def test_duration_resolves_an_end_time(self):
        second = parse_calendar(self.FEED)[1]
        self.assertEqual(
            resolve_end(second),
            datetime(2026, 9, 6, 17, 0, tzinfo=ZoneInfo("Europe/Rome")),
        )

    def test_junk_lines_are_tolerated(self):
        feed = self.FEED.replace("VERSION:2.0\r\n", "VERSION:2.0\r\nTHIS IS NOT A PROPERTY\r\n")
        self.assertEqual(len(parse_calendar(feed)), 2)

    def test_unterminated_event_raises(self):
        with self.assertRaises(IcsError):
            parse_calendar("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nEND:VCALENDAR\n")

    def test_nested_valarm_properties_stay_out_of_the_event(self):
        # Real feeds attach a reminder to each session. Its DESCRIPTION must not
        # overwrite the event's, and its TRIGGER must not appear at all.
        feed = (
            "BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:one\r\n"
            "SUMMARY:Italian GP: Race\r\n"
            "DESCRIPTION:Round 16\r\n"
            "DTSTART:20260906T130000Z\r\n"
            "BEGIN:VALARM\r\n"
            "ACTION:DISPLAY\r\n"
            "DESCRIPTION:Race starts in 15 minutes!\r\n"
            "TRIGGER:-PT15M\r\n"
            "END:VALARM\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        events = parse_calendar(feed)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].get("DESCRIPTION"), "Round 16")
        self.assertIsNone(events[0].get("TRIGGER"))
        self.assertIsNone(events[0].get("ACTION"))

    def test_empty_feed_returns_nothing_rather_than_raising(self):
        self.assertEqual(parse_calendar("BEGIN:VCALENDAR\nEND:VCALENDAR\n"), [])


if __name__ == "__main__":
    unittest.main()