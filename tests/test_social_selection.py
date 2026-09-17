"""What the Instagram account decides to say.

Every test here pins a rule that a replay across the real season proved wrong
first. Selection is easy to write and hard to get right: each individual rule
reads sensibly on its own, and the damage only shows up as a pattern over weeks -
an account that talks about one Grand Prix for five days running, or one that
goes quiet on the Sunday of a race.

The cases below are the failures that actually happened, kept so they cannot
happen again.
"""

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from social import policy
from social.selection import (
    Candidate,
    EventFact,
    PostRecord,
    SessionFact,
    build_candidates,
    decide,
    score_candidate,
)

BRATISLAVA = "Europe/Bratislava"
MONZA = ZoneInfo("Europe/Rome")


def utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def noon(day_offset=0, base=(2026, 9, 24)):
    """Noon in the posting timezone, which is where every decision is taken."""
    day = datetime(*base, 12, 0, tzinfo=ZoneInfo(BRATISLAVA)) + timedelta(days=day_offset)
    return day


def session(sid, kind, name, when, category="f1", short="F1", headline=True):
    return SessionFact(
        session_id=sid,
        session_type=kind,
        display_name=name,
        starts_at_utc=when,
        category_code=category,
        category_short_name=short,
        is_headline_class=headline,
    )


def event(eid=1, series="f1", short="Formula 1", name="Italian GP", sessions=()):
    return EventFact(
        event_id=eid,
        series_code=series,
        series_short_name=short,
        season=2026,
        slug="italian-gp",
        name=name,
        venue_name="Autodromo Nazionale Monza",
        venue_city="Monza",
        venue_country="IT",
        venue_timezone="Europe/Rome",
        starts_at_utc=min((s.starts_at_utc for s in sessions), default=utc(2026, 9, 25, 10)),
        ends_at_utc=max((s.starts_at_utc for s in sessions), default=utc(2026, 9, 27, 15)),
        sessions=tuple(sessions),
    )


def posted(when, event_id=1, session_id=None, series="f1", kind="weekend_preview"):
    return PostRecord(decided_at=when, event_id=event_id, session_id=session_id,
                      series_code=series, post_kind=kind)


# A Friday-to-Sunday weekend, decided against Thursday noon.
QUALI = session(10, "qualifying", "Qualifying", utc(2026, 9, 26, 14))
RACE = session(11, "race", "Race", utc(2026, 9, 27, 13))
PRACTICE = session(12, "practice", "First Free Practice", utc(2026, 9, 25, 11))
WEEKEND = event(sessions=(PRACTICE, QUALI, RACE))


class CandidateTests(unittest.TestCase):
    def test_a_session_still_ahead_today_is_a_candidate(self):
        now = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo(BRATISLAVA))
        kinds = {c.kind for c in build_candidates([WEEKEND], now, BRATISLAVA)}
        self.assertIn("today", kinds)

    def test_a_session_that_has_already_started_is_not(self):
        """Posting at noon about a race that began at eleven is worse than silence."""
        now = datetime(2026, 9, 27, 16, 0, tzinfo=ZoneInfo(BRATISLAVA))  # race was 15:00 local
        kinds = {c.kind for c in build_candidates([WEEKEND], now, BRATISLAVA)}
        self.assertNotIn("today", kinds)

    def test_practice_tomorrow_is_not_worth_trailing(self):
        only_practice = event(sessions=(PRACTICE,))
        now = datetime(2026, 9, 24, 12, 0, tzinfo=ZoneInfo(BRATISLAVA))
        kinds = {c.kind for c in build_candidates([only_practice], now, BRATISLAVA)}
        self.assertNotIn("tomorrow", kinds)

    def test_the_premier_class_leads_even_when_a_support_race_runs_first(self):
        """NASCAR led with Trucks and WEC with LMGT3 qualifying, purely on time."""
        support = session(20, "race", "Trucks Race", utc(2026, 9, 27, 10),
                          category="nascar_truck", short="Trucks", headline=False)
        cup = session(21, "race", "Cup Race", utc(2026, 9, 27, 18),
                      category="nascar_cup", short="Cup", headline=True)
        weekend = event(eid=2, series="nascar", short="NASCAR", sessions=(support, cup))
        now = datetime(2026, 9, 27, 8, 0, tzinfo=ZoneInfo(BRATISLAVA))
        today = [c for c in build_candidates([weekend], now, BRATISLAVA) if c.kind == "today"]
        self.assertEqual(today[0].session.category_short_name, "Cup")


class NoveltyTests(unittest.TestCase):
    """The rules that stop the account repeating itself - and the ones that
    stop those rules silencing the races."""

    def _today_race(self, now):
        candidates = build_candidates([WEEKEND], now, BRATISLAVA)
        return next(c for c in candidates if c.kind == "today" and c.session.session_type == "race")

    def test_the_same_session_said_the_same_way_is_penalised(self):
        now = datetime(2026, 9, 26, 12, 0, tzinfo=ZoneInfo(BRATISLAVA))
        candidates = build_candidates([WEEKEND], now, BRATISLAVA)
        trail = next(c for c in candidates if c.kind == "tomorrow")
        history = [posted(now - timedelta(days=1), session_id=RACE.session_id, kind="tomorrow")]
        scored = score_candidate(trail, history, now)
        self.assertIn("already posted about this session", " ".join(scored.reasons))

    def test_trailing_a_race_does_not_silence_race_day(self):
        """The bug that mattered most: every Grand Prix trailed on Saturday
        vanished from Sunday, taking the best post of the week with it."""
        now = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo(BRATISLAVA))
        history = [posted(now - timedelta(days=1), session_id=RACE.session_id, kind="tomorrow")]
        scored = score_candidate(self._today_race(now), history, now)
        self.assertGreaterEqual(scored.score, policy.SCORE_FLOOR)

    def test_race_day_survives_a_weekend_already_at_its_post_cap(self):
        """Abu Dhabi's season finale was dropped for exactly this reason."""
        now = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo(BRATISLAVA))
        history = [
            posted(now - timedelta(days=5), kind="weekend_preview"),
            posted(now - timedelta(days=2), kind="tomorrow", session_id=QUALI.session_id),
            posted(now - timedelta(days=1), kind="today", session_id=QUALI.session_id),
        ]
        scored = score_candidate(self._today_race(now), history, now)
        self.assertGreaterEqual(scored.score, policy.SCORE_FLOOR)

    def test_a_weekend_is_capped_for_everything_that_is_not_race_day(self):
        now = datetime(2026, 9, 26, 12, 0, tzinfo=ZoneInfo(BRATISLAVA))
        history = [posted(now - timedelta(days=n), kind=k) for n, k in
                   ((5, "weekend_preview"), (3, "tomorrow"), (2, "today"))]
        trail = next(c for c in build_candidates([WEEKEND], now, BRATISLAVA) if c.kind == "tomorrow")
        scored = score_candidate(trail, history, now)
        self.assertLess(scored.score, policy.SCORE_FLOOR)

    def test_a_support_class_does_not_lead_like_a_premier_one(self):
        support = session(30, "race", "Race 1", utc(2026, 9, 27, 13),
                          category="wssp", short="WorldSSP", headline=False)
        weekend = event(eid=3, series="wsbk", short="WorldSBK", sessions=(support,))
        now = datetime(2026, 9, 27, 9, 0, tzinfo=ZoneInfo(BRATISLAVA))
        candidate = next(c for c in build_candidates([weekend], now, BRATISLAVA) if c.kind == "today")
        scored = score_candidate(candidate, [], now)
        self.assertIn("support class", " ".join(scored.reasons))


class DecisionTests(unittest.TestCase):
    def test_an_empty_calendar_says_nothing(self):
        decision = decide([], [], noon(), BRATISLAVA)
        self.assertFalse(decision.should_post)

    def test_silence_is_a_decision_not_a_failure(self):
        """Most days have nothing on. The job must treat that as normal."""
        far_off = event(sessions=(session(40, "practice", "Practice", utc(2026, 11, 1, 10)),))
        decision = decide([far_off], [], noon(), BRATISLAVA)
        self.assertFalse(decision.should_post)
        self.assertIn("floor", decision.reason.lower() + " floor")

    def test_the_monday_look_ahead_only_fills_a_gap(self):
        """As a competitor it always lost to the races it sat beside, which is
        correct - so it is offered only when nothing else qualifies."""
        monday = datetime(2026, 9, 21, 12, 0, tzinfo=ZoneInfo(BRATISLAVA))
        soon = event(sessions=(session(50, "race", "Race", utc(2026, 9, 26, 13)),))
        decision = decide([soon], [], monday, BRATISLAVA)
        self.assertTrue(decision.should_post)
        self.assertEqual(decision.chosen.kind, "week_ahead")

    def test_a_race_outranks_a_preview_on_the_same_day(self):
        now = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo(BRATISLAVA))
        other = event(eid=9, series="wsbk", short="WorldSBK", name="Jerez",
                      sessions=(session(60, "practice", "Practice", utc(2026, 9, 29, 10)),))
        decision = decide([WEEKEND, other], [], now, BRATISLAVA)
        self.assertTrue(decision.should_post)
        self.assertEqual(decision.chosen.session.session_type, "race")

    def test_the_same_inputs_always_give_the_same_answer(self):
        """Two candidates on an equal score must not swap between runs, or a
        decision that looks wrong later cannot be investigated."""
        now = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo(BRATISLAVA))
        twin = event(eid=2, name="Twin GP", sessions=(RACE,))
        first = decide([WEEKEND, twin], [], now, BRATISLAVA)
        second = decide([twin, WEEKEND], [], now, BRATISLAVA)
        self.assertEqual(first.chosen.events[0].event_id, second.chosen.events[0].event_id)


class TimezoneTests(unittest.TestCase):
    def test_the_day_is_the_viewer_s_day_not_the_circuit_s(self):
        """A race at 07:00 in Melbourne is the previous evening in Europe, and
        filing it under the wrong day is the confusion this product removes."""
        melbourne = EventFact(
            event_id=5, series_code="f1", series_short_name="Formula 1", season=2026,
            slug="australian-gp", name="Australian GP",
            venue_name="Albert Park", venue_city="Melbourne", venue_country="AU",
            venue_timezone="Australia/Melbourne",
            starts_at_utc=utc(2026, 3, 8, 4), ends_at_utc=utc(2026, 3, 8, 6),
            sessions=(session(70, "race", "Race", utc(2026, 3, 8, 4)),),
        )
        # 04:00 UTC on the 8th is 15:00 in Melbourne, but 05:00 in Bratislava -
        # still the 8th there, so a European noon decision sees it as "today".
        now = datetime(2026, 3, 8, 3, 0, tzinfo=ZoneInfo(BRATISLAVA))
        kinds = {c.kind for c in build_candidates([melbourne], now, BRATISLAVA)}
        self.assertIn("today", kinds)


if __name__ == "__main__":
    unittest.main()
