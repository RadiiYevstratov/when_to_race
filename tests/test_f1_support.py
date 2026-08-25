"""Attaching F2, F3 and F1 Academy to the Grand Prix they run at.

The support championships come from a different publisher than the Grand Prix
feed, in a different summary shape, and name their rounds differently. These
tests pin the rule that resolves the difference: a support session belongs to
the Grand Prix whose weekend it runs inside, decided on time rather than on the
round's name.

The Spanish case is the reason that rule exists. From 2026 the season visits
Spain twice, Barcelona and Madrid, and the support feed calls one round
"Spanish" and the other "Spanish Grand Prix" - two names that both slugify to
`spanish-gp` and would collapse a fortnight apart onto one weekend.
"""

import unittest
from datetime import datetime, timezone

from scrapers.config import load_series, load_venues
from scrapers.normalize import classify_session_type, normalize
from scrapers.sources import get_source
from scrapers.sources.base import FetchedDocument
from scrapers.sources.f1 import _CATEGORY_PATTERNS

SEASON = 2026


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


# Two Spanish rounds a fortnight apart: Barcelona in June, Madrid in September.
GRAND_PRIX = calendar(
    entry("\U0001F1EA\U0001F1F8 Spanish GP: Practice 1", "20260612T103000Z", "20260612T113000Z", "Barcelona"),
    entry("\U0001F1EA\U0001F1F8 Spanish GP: Race", "20260614T130000Z", "20260614T150000Z", "Barcelona"),
    entry("\U0001F1EA\U0001F1F8 Madrid GP: Practice 1", "20260911T103000Z", "20260911T113000Z", "Madrid"),
    entry("\U0001F1EA\U0001F1F8 Madrid GP: Race", "20260913T130000Z", "20260913T150000Z", "Madrid"),
    entry("\U0001F1F2\U0001F1E8 Monaco GP: Practice 1", "20260605T113000Z", "20260605T123000Z", "Monaco"),
    entry("\U0001F1F2\U0001F1E8 Monaco GP: Race", "20260607T130000Z", "20260607T150000Z", "Monaco"),
)

# The support feed calls both Spanish rounds by near-identical names, and runs
# Monaco practice on the Thursday, before Formula 1 has turned a wheel.
SUPPORT = calendar(
    entry("F2: Practice (Spanish)", "20260612T083000Z", "20260612T091500Z", "Barcelona"),
    entry("F2: Feature (Spanish)", "20260614T090000Z", "20260614T100000Z", "Barcelona"),
    entry("F2: Feature (Spanish Grand Prix)", "20260913T090000Z", "20260913T100000Z", "Madrid"),
    entry("F3: Practice (Monaco)", "20260604T112500Z", "20260604T121000Z", "Monaco"),
    entry("F1-ACADEMY: FP1 (Spanish)", "20260612T070000Z", "20260612T074000Z", "Barcelona"),
)

# A support round with no Grand Prix anywhere near it.
ORPHAN = calendar(
    entry("F2: Feature (Sakhir)", "20260214T090000Z", "20260214T100000Z", "Sakhir"),
)


class SupportAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.series = load_series()["f1"]
        self.venues = load_venues()
        self.source = get_source("f1", feed_url="https://example.invalid/f1.ics")

    def _events(self, *bodies: bytes):
        documents = [
            FetchedDocument(url=f"https://example.invalid/{index}.ics", body=body)
            for index, body in enumerate(bodies)
        ]
        parsed = self.source.parse(documents, self.series, self.venues, SEASON)
        return {event.slug: event for event in normalize(parsed, self.series, self.venues)}

    def _categories(self, event):
        return {session.category_code for session in event.sessions}

    # --- the rule ---------------------------------------------------------
    def test_two_rounds_named_alike_stay_on_their_own_weekends(self):
        events = self._events(GRAND_PRIX, SUPPORT)

        barcelona = events["spanish-gp"]
        madrid = events["madrid-gp"]
        self.assertEqual(barcelona.venue_slug, "barcelona")
        self.assertEqual(madrid.venue_slug, "madrid")

        # Both feed rounds are called "Spanish"; only the June one is Barcelona.
        self.assertEqual(
            [session.display_name for session in barcelona.sessions if session.category_code == "f2"],
            ["Practice", "Feature"],
        )
        self.assertEqual(
            [session.display_name for session in madrid.sessions if session.category_code == "f2"],
            ["Feature"],
        )

    def test_support_sessions_join_the_grand_prix_weekend(self):
        events = self._events(GRAND_PRIX, SUPPORT)
        self.assertEqual(self._categories(events["spanish-gp"]), {"f1", "f2", "f1a"})
        self.assertEqual(self._categories(events["madrid-gp"]), {"f1", "f2"})

    def test_a_thursday_session_still_belongs_to_the_weekend(self):
        """Monaco runs Formula 3 on the Thursday, outside the Formula 1 span."""
        events = self._events(GRAND_PRIX, SUPPORT)
        self.assertIn("f3", self._categories(events["monaco-gp"]))

    def test_a_support_round_with_no_grand_prix_is_dropped(self):
        events = self._events(GRAND_PRIX, ORPHAN)
        slugs = set(events)
        self.assertNotIn("sakhir", slugs)
        self.assertEqual(slugs, {"spanish-gp", "madrid-gp", "monaco-gp"})

    def test_support_alone_produces_nothing_rather_than_a_half_event(self):
        """Without the Grand Prix feed there is nothing to attach to."""
        events = self._events(SUPPORT)
        self.assertEqual(events, {})

    def test_the_grand_prix_keeps_ownership_of_the_weekend(self):
        events = self._events(GRAND_PRIX, SUPPORT)
        barcelona = events["spanish-gp"]
        # Venue and round come from the Grand Prix, never from a support entry.
        self.assertEqual(
            {session.category_code: barcelona.venue_slug for session in barcelona.sessions},
            {"f1": "barcelona", "f2": "barcelona", "f1a": "barcelona"},
        )


class SupportDialectTests(unittest.TestCase):
    """The support feed's summaries look nothing like the Grand Prix feed's."""

    def setUp(self):
        self.source = get_source("f1", feed_url="https://example.invalid/f1.ics")

    def test_the_round_is_read_from_the_brackets(self):
        self.assertEqual(
            self.source.split_summary("F2: Feature (Italian)"), ("Italian", "Feature")
        )
        self.assertEqual(
            self.source.split_summary("F1-ACADEMY: Race 1 (British)"), ("British", "Race 1")
        )

    def test_the_grand_prix_dialect_still_splits_on_the_separator(self):
        self.assertEqual(
            self.source.split_summary("\U0001F1EE\U0001F1F9 Italian GP: Race"),
            ("Italian GP", "Race"),
        )

    def test_a_hyphenated_academy_is_not_read_as_formula_one(self):
        """It matches the plain "f1" pattern otherwise, silently and wrongly."""
        for summary in ("F1-ACADEMY: FP1 (Chinese)", "F1 ACADEMY: FP1 (Chinese)"):
            got = next((code for pattern, code in _CATEGORY_PATTERNS if pattern.search(summary)), None)
            self.assertEqual(got, "f1a", summary)

    def test_the_feature_is_a_race(self):
        """F2 and F3 name their main race "Feature", usually with no "race"."""
        self.assertEqual(classify_session_type("Feature"), "race")
        self.assertEqual(classify_session_type("Feature Race"), "race")
        # The sprint must not be swept up by it.
        self.assertEqual(classify_session_type("Sprint"), "sprint")


class SupportFeedConfigTests(unittest.TestCase):
    def test_every_configured_feed_is_fetched(self):
        series = load_series()["f1"]
        source = get_source(
            "f1", feed_url=series.source.url, extra_urls=series.source.extra_urls
        )
        urls = source.urls(SEASON)
        self.assertEqual(urls[0], series.source.url)
        self.assertEqual(len(urls), 1 + len(series.source.extra_urls))

    def test_the_support_feeds_are_configured(self):
        """A silent loss of these would look like a working F1-only site."""
        series = load_series()["f1"]
        joined = " ".join(series.source.extra_urls)
        for expected in ("f2", "f3", "f1-academy"):
            self.assertIn(expected, joined)


if __name__ == "__main__":
    unittest.main()
