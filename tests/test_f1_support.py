"""Attaching F2 and F3 to the Grand Prix they run at.

The support championships come from their own websites, in a different format
from the Grand Prix feed, and name their rounds differently. These tests pin the
rule that resolves the difference: a support session belongs to the Grand Prix
whose weekend it runs inside, decided on time rather than on the round's name.

The Spanish case is the reason that rule exists. From 2026 the season visits
Spain twice, Barcelona and Madrid, and a round called "Spanish" could be either
- two names a fortnight and a thousand kilometres apart that slugify the same.

The page fixtures are real excerpts, escaping included. They are what turns a
site redesign into a failing test rather than a wrong time on someone's phone.
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scrapers.config import load_series, load_venues
from scrapers.normalize import classify_session_type, normalize
from scrapers.sources import get_source
from scrapers.sources.base import FetchedDocument
from scrapers.sources.f1 import FormulaOneSource, _CATEGORY_PATTERNS

SEASON = 2026
FIXTURES = Path(__file__).resolve().parent.parent / "scrapers/fixtures"


def calendar(*entries: str) -> bytes:
    body = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", *entries, "END:VCALENDAR"])
    return body.encode("utf-8")


def entry(summary: str, start: str, end: str, location: str) -> str:
    return "\r\n".join(
        [
            "BEGIN:VEVENT",
            f"SUMMARY:{summary}",
            f"DTSTART:{start}",
            f"DTEND:{end}",
            f"LOCATION:{location}",
            "END:VEVENT",
        ]
    )


def page(sessions: list[dict]) -> bytes:
    """A support round page, with the payload escaped the way the real one is."""
    # Compact separators, as the real page ships it.
    blob = json.dumps(
        {"race": {"meetingSessions": sessions}}, separators=(",", ":")
    ).replace('"', '\\"')
    return f'<html><body><script>window.__D__ = "{blob}";</script></body></html>'.encode()


def session(name: str, start: str, end: str, number: int = 0, zone: str = "Europe/Madrid") -> dict:
    return {
        "session": name,
        "shortName": name,
        "startTime": start,
        "endTime": end,
        "sessionNumber": number,
        "timezone": zone,
        "gmtOffset": "+02:00",
    }


# Two Spanish rounds a fortnight apart: Barcelona in June, Madrid in September.
GRAND_PRIX = calendar(
    entry("\U0001F1EA\U0001F1F8 Spanish GP: Practice 1", "20260612T103000Z", "20260612T113000Z", "Barcelona"),
    entry("\U0001F1EA\U0001F1F8 Spanish GP: Race", "20260614T130000Z", "20260614T150000Z", "Barcelona"),
    entry("\U0001F1EA\U0001F1F8 Madrid GP: Practice 1", "20260911T103000Z", "20260911T113000Z", "Madrid"),
    entry("\U0001F1EA\U0001F1F8 Madrid GP: Race", "20260913T130000Z", "20260913T150000Z", "Madrid"),
    entry("\U0001F1F2\U0001F1E8 Monaco GP: Practice 1", "20260605T113000Z", "20260605T123000Z", "Monaco"),
    entry("\U0001F1F2\U0001F1E8 Monaco GP: Race", "20260607T130000Z", "20260607T150000Z", "Monaco"),
)

# Both Spanish rounds are just "barcelona" and "madrid" in the URL; the round
# name is never what decides which weekend a session lands on.
F2_BARCELONA = page([
    session("Practice", "2026-06-12T10:30:00", "2026-06-12T11:15:00"),
    session("Feature Race", "2026-06-14T09:00:00", "2026-06-14T10:00:00", 2),
])
F2_MADRID = page([
    session("Feature Race", "2026-09-13T09:00:00", "2026-09-13T10:00:00", 2),
])
F3_MONACO = page([
    # Monaco runs Formula 3 on the Thursday, before Formula 1 has turned a wheel.
    session("Practice", "2026-06-04T11:25:00", "2026-06-04T12:10:00", zone="Europe/Monaco"),
])
ORPHAN = page([
    session("Feature Race", "2026-02-14T09:00:00", "2026-02-14T10:00:00", 2),
])


class SupportAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["f1"]
        self.venues = load_venues()
        self.source = get_source("f1", feed_url="https://example.invalid/f1.ics")

    def _events(self, *docs: tuple[str, bytes]):
        documents = [FetchedDocument(url=url, body=body) for url, body in docs]
        parsed = self.source.parse(documents, self.series, self.venues, SEASON)
        return {event.slug: event for event in normalize(parsed, self.series, self.venues)}

    def _categories(self, event):
        return {s.category_code for s in event.sessions}

    ICS = ("https://example.invalid/f1.ics", GRAND_PRIX)
    F2_BCN = ("https://www.fiaformula2.com/en/racing/2026/barcelona", F2_BARCELONA)
    F2_MAD = ("https://www.fiaformula2.com/en/racing/2026/madrid", F2_MADRID)
    F3_MON = ("https://www.fiaformula3.com/en/racing/2026/monte-carlo", F3_MONACO)

    def test_two_rounds_in_the_same_country_stay_on_their_own_weekends(self):
        events = self._events(self.ICS, self.F2_BCN, self.F2_MAD)
        self.assertEqual(events["spanish-gp"].venue_slug, "barcelona")
        self.assertEqual(events["madrid-gp"].venue_slug, "madrid")
        self.assertEqual(
            [s.display_name for s in events["spanish-gp"].sessions if s.category_code == "f2"],
            ["Practice", "Feature Race"],
        )
        self.assertEqual(
            [s.display_name for s in events["madrid-gp"].sessions if s.category_code == "f2"],
            ["Feature Race"],
        )

    def test_support_sessions_join_the_grand_prix_weekend(self):
        events = self._events(self.ICS, self.F2_BCN)
        self.assertEqual(self._categories(events["spanish-gp"]), {"f1", "f2"})

    def test_a_thursday_session_still_belongs_to_the_weekend(self):
        events = self._events(self.ICS, self.F3_MON)
        self.assertIn("f3", self._categories(events["monaco-gp"]))

    def test_a_round_with_no_grand_prix_is_dropped(self):
        events = self._events(
            self.ICS, ("https://www.fiaformula2.com/en/racing/2026/sakhir", ORPHAN)
        )
        self.assertEqual(set(events), {"spanish-gp", "madrid-gp", "monaco-gp"})

    def test_support_alone_produces_nothing_rather_than_a_half_event(self):
        events = self._events(self.F2_BCN)
        self.assertEqual(events, {})

    def test_the_grand_prix_owns_the_venue(self):
        events = self._events(self.ICS, self.F2_BCN)
        for s in events["spanish-gp"].sessions:
            self.assertEqual(events["spanish-gp"].venue_slug, "barcelona", s.category_code)


class SupportPageTests(unittest.TestCase):
    """Reading the timetable out of a real page."""

    def _sessions(self, name):
        return FormulaOneSource._embedded_sessions((FIXTURES / name).read_text(encoding="utf-8"))

    def test_the_f2_timetable_matches_the_published_one(self):
        got = {s["shortName"]: (s["startTime"], s["endTime"]) for s in self._sessions("f2_round_monza.html")}
        self.assertEqual(got["Practice"], ("2026-09-04T10:00:00", "2026-09-04T10:45:00"))
        self.assertEqual(got["Qualifying"], ("2026-09-04T14:55:00", "2026-09-04T15:25:00"))
        self.assertEqual(got["Sprint Race"], ("2026-09-05T14:15:00", "2026-09-05T15:05:00"))
        self.assertEqual(got["Feature Race"], ("2026-09-06T09:45:00", "2026-09-06T10:50:00"))

    def test_f3_keeps_both_qualifying_sessions(self):
        """A source that merged them into one would lose a session outright."""
        got = [s["shortName"] for s in self._sessions("f3_round_monza.html")]
        self.assertEqual(got, ["Practice", "Qualifying A", "Qualifying B", "Sprint Race", "Feature Race"])

    def test_the_two_qualifying_sessions_get_distinct_sequences(self):
        # They share a category and a session type, so the upsert key separates
        # them on sequence alone - collapse that and one silently overwrites the
        # other.
        quali = [s for s in self._sessions("f3_round_monza.html") if s["shortName"].startswith("Qualifying")]
        self.assertEqual([s["sessionNumber"] for s in quali], [1, 2])

    def test_the_circuit_zone_is_taken_from_the_page(self):
        for s in self._sessions("f2_round_monza.html"):
            self.assertEqual(s["timezone"], "Europe/Rome")

    def test_a_page_without_a_timetable_yields_nothing(self):
        self.assertEqual(FormulaOneSource._embedded_sessions("<html>nothing here</html>"), [])

    def test_an_end_before_its_start_is_discarded_not_corrected(self):
        """F3 at the Red Bull Ring publishes a sprint ending the day before it
        starts. The start is credible; inventing the end would not be."""
        source = get_source("f1", feed_url="https://example.invalid/f1.ics")
        broken = page([session("Sprint Race", "2026-06-27T10:05:00", "2026-06-26T10:50:00", 1)])
        document = FetchedDocument(
            url="https://www.fiaformula3.com/en/racing/2026/spielberg", body=broken
        )
        parsed = source._parse_support_page(document, load_series()["f1"], SEASON)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].local_start, datetime(2026, 6, 27, 10, 5))
        self.assertIsNone(parsed[0].local_end)

    def test_the_category_comes_from_the_site(self):
        self.assertEqual(
            FormulaOneSource._category_for_url("https://www.fiaformula2.com/en/racing/2026/monza"), "f2"
        )
        self.assertEqual(
            FormulaOneSource._category_for_url("https://www.fiaformula3.com/en/racing/2026/monza"), "f3"
        )
        self.assertIsNone(FormulaOneSource._category_for_url("https://example.invalid/x"))


class SessionNamingTests(unittest.TestCase):
    def test_the_published_names_classify_correctly(self):
        self.assertEqual(classify_session_type("Practice"), "practice")
        self.assertEqual(classify_session_type("Qualifying A"), "qualifying")
        self.assertEqual(classify_session_type("Sprint Race"), "sprint")
        self.assertEqual(classify_session_type("Feature Race"), "race")

    def test_a_hyphenated_academy_is_not_read_as_formula_one(self):
        """It matches the plain "f1" pattern otherwise, silently and wrongly."""
        for summary in ("F1-ACADEMY: FP1 (Chinese)", "F1 ACADEMY: FP1 (Chinese)"):
            got = next((c for p, c in _CATEGORY_PATTERNS if p.search(summary)), None)
            self.assertEqual(got, "f1a", summary)


class SupportSourceConfigTests(unittest.TestCase):
    def test_the_support_calendars_are_configured(self):
        """A silent loss of these would look like a working F1-only site."""
        joined = " ".join(load_series()["f1"].source.extra_urls)
        for expected in ("fiaformula2.com", "fiaformula3.com"):
            self.assertIn(expected, joined)

    def test_the_season_index_is_templated(self):
        for url in load_series()["f1"].source.extra_urls:
            self.assertIn("{season}", url)

    def test_round_links_are_read_off_a_season_index(self):
        body = """
          <a href="/en/racing/2026/monza">Monza</a>
          <a href="/en/racing/2026/monza">Monza again</a>
          <a href="/en/racing/2025/monza">last year</a>
          <a href="/en/racing/2026/spa-francorchamps">Spa</a>
        """
        got = FormulaOneSource._round_urls(
            "https://www.fiaformula2.com/en/racing/2026", body, SEASON
        )
        self.assertEqual(
            got,
            [
                "https://www.fiaformula2.com/en/racing/2026/monza",
                "https://www.fiaformula2.com/en/racing/2026/spa-francorchamps",
            ],
        )


if __name__ == "__main__":
    unittest.main()
