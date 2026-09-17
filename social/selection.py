"""Deciding what, if anything, to post today.

Pure functions over plain records: the schedule comes in, a decision comes out,
and nothing here touches a database or a clock of its own. That is deliberate -
the interesting behaviour of this module is what it does across a whole season,
and replaying a season is only cheap if selection is a function.

The shape of the problem is set by the sport rather than by us. Motorsport runs
in weekend clusters with three to five dead days between them, so on most days
the honest answer is nothing. Every rule below exists to keep the account from
filling that silence with something it has already said.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from . import policy


@dataclass(frozen=True)
class SessionFact:
    """One session, as the selector needs it."""

    session_id: int
    session_type: str
    display_name: str
    starts_at_utc: datetime
    category_code: str
    category_short_name: str
    # True for the class the weekend is named after. Without it a post about
    # NASCAR at Bristol leads with the Trucks race because it runs first, and
    # a WEC weekend leads with LMGT3 qualifying rather than the race.
    is_headline_class: bool = True


@dataclass(frozen=True)
class EventFact:
    """One race weekend, with every session on it."""

    event_id: int
    series_code: str
    series_short_name: str
    season: int
    slug: str
    name: str
    venue_name: str
    venue_city: Optional[str]
    venue_country: str
    venue_timezone: str
    starts_at_utc: datetime
    ends_at_utc: datetime
    sessions: tuple[SessionFact, ...] = ()

    @property
    def class_count(self) -> int:
        return len({session.category_code for session in self.sessions})


@dataclass(frozen=True)
class PostRecord:
    """Something the account already said."""

    decided_at: datetime
    event_id: Optional[int]
    session_id: Optional[int]
    series_code: Optional[str]
    post_kind: Optional[str]


@dataclass
class Candidate:
    kind: str
    events: tuple[EventFact, ...]
    session: Optional[SessionFact]
    score: int
    reasons: list[str] = field(default_factory=list)

    @property
    def event(self) -> Optional[EventFact]:
        """The one event this is about, where there is one."""
        return self.events[0] if len(self.events) == 1 else None

    def note(self, points: int, why: str) -> None:
        """Record a scoring step so a decision can be explained later."""
        self.score += points
        self.reasons.append(f"{points:+d} {why}")


@dataclass
class Decision:
    """What the day came to, and what it beat."""

    should_post: bool
    chosen: Optional[Candidate]
    runners_up: list[Candidate]
    reason: str


# --------------------------------------------------------------------------
# building candidates
# --------------------------------------------------------------------------


def _local_date(moment: datetime, timezone: str) -> date:
    return moment.astimezone(ZoneInfo(timezone)).date()


def _sessions_on(event: EventFact, day: date, timezone: str) -> list[SessionFact]:
    return [s for s in event.sessions if _local_date(s.starts_at_utc, timezone) == day]


def _headline(sessions: Sequence[SessionFact]) -> Optional[SessionFact]:
    """The session a post about this day should lead with.

    Ordered by what a reader came for rather than by what runs first: a race day
    with practice on it is a race day, and the premier class outranks its
    support races even when they run earlier.
    """
    if not sessions:
        return None
    rank = {kind: index for index, kind in enumerate(policy.NOTABLE_SESSION_TYPES)}
    return min(
        sessions,
        key=lambda s: (
            rank.get(s.session_type, len(rank)),
            0 if s.is_headline_class else 1,
            s.starts_at_utc,
        ),
    )


def build_candidates(
    events: Sequence[EventFact],
    now: datetime,
    timezone: str = policy.POSTING_TIMEZONE,
) -> list[Candidate]:
    """Every post that could reasonably be made at `now`, unscored."""
    today = _local_date(now, timezone)
    tomorrow = today + timedelta(days=1)
    candidates: list[Candidate] = []

    for event in events:
        # --- today: something still ahead of us on this calendar day --------
        later_today = [
            s
            for s in _sessions_on(event, today, timezone)
            if s.starts_at_utc - now >= policy.MIN_LEAD_TIME
            and s.session_type in policy.NOTABLE_SESSION_TYPES
        ]
        headline = _headline(later_today)
        if headline is not None:
            candidates.append(Candidate("today", (event,), headline, 0))

        # --- tomorrow: worth trailing only for the sessions people plan around
        due_tomorrow = [
            s
            for s in _sessions_on(event, tomorrow, timezone)
            if s.session_type in policy.TOMORROW_SESSION_TYPES
        ]
        headline = _headline(due_tomorrow)
        if headline is not None:
            candidates.append(Candidate("tomorrow", (event,), headline, 0))

        # --- preview: the weekend starts in a couple of days ----------------
        if event.sessions:
            first = min(s.starts_at_utc for s in event.sessions)
            days_away = (_local_date(first, timezone) - today).days
            if policy.PREVIEW_MIN_DAYS <= days_away <= policy.PREVIEW_MAX_DAYS:
                candidates.append(Candidate("weekend_preview", (event,), None, 0))

    return candidates


def build_fallback(
    events: Sequence[EventFact],
    now: datetime,
    timezone: str = policy.POSTING_TIMEZONE,
) -> Optional[Candidate]:
    """The Monday look-ahead, offered only when nothing else qualifies.

    Deliberately not a competitor. Scored against the races it sits beside it
    always lost, which is correct - a summary of the week is less interesting
    than any single race in it. Its place is the gap, not the contest.
    """
    today = _local_date(now, timezone)
    if today.weekday() != policy.WEEK_AHEAD_WEEKDAY:
        return None

    week_end = today + timedelta(days=7)
    in_week = tuple(
        event
        for event in events
        if any(today <= _local_date(s.starts_at_utc, timezone) < week_end for s in event.sessions)
    )
    if not in_week:
        return None
    return Candidate("week_ahead", in_week, None, 0)


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------


def score_candidate(
    candidate: Candidate,
    history: Sequence[PostRecord],
    now: datetime,
) -> Candidate:
    """Apply the policy, recording each step so the result can be explained."""
    candidate.score = 0
    candidate.reasons = []

    # --- what kind of post it is -------------------------------------------
    if candidate.kind == "week_ahead":
        candidate.note(policy.WEEK_AHEAD_SCORE, f"week ahead ({len(candidate.events)} rounds)")
    elif candidate.kind == "weekend_preview":
        candidate.note(policy.WEEKEND_PREVIEW_SCORE, "weekend preview")
    else:
        session_type = candidate.session.session_type if candidate.session else "other"
        base = policy.BASE_SCORE.get((candidate.kind, session_type))
        if base is None:
            # Not a combination worth posting on its own.
            candidate.note(0, f"{candidate.kind} {session_type} is not a post")
            return candidate
        candidate.note(base, f"{candidate.kind}: {session_type}")

    # --- which championship ------------------------------------------------
    if candidate.kind == "week_ahead":
        best = max(
            (policy.SERIES_BONUS.get(e.series_code, policy.DEFAULT_SERIES_BONUS) for e in candidate.events),
            default=0,
        )
        if best:
            candidate.note(best, "biggest championship in the week")
    else:
        event = candidate.events[0]
        bonus = policy.SERIES_BONUS.get(event.series_code, policy.DEFAULT_SERIES_BONUS)
        if bonus:
            candidate.note(bonus, f"{event.series_short_name} reach")

        # --- a weekend with more on it ------------------------------------
        extra = max(0, event.class_count - 1)
        if extra:
            bonus = min(extra * policy.MULTI_CLASS_BONUS_PER_EXTRA, policy.MULTI_CLASS_BONUS_CAP)
            candidate.note(bonus, f"{event.class_count} classes on the weekend")

        # --- leading on a support class -----------------------------------
        if candidate.session is not None and not candidate.session.is_headline_class:
            candidate.note(
                -policy.SUPPORT_CLASS_PENALTY,
                f"{candidate.session.category_short_name} is a support class",
            )

    # --- have we said this already -----------------------------------------
    _apply_novelty(candidate, history, now)
    return candidate


def _apply_novelty(candidate: Candidate, history: Sequence[PostRecord], now: datetime) -> None:
    """Penalise saying the same thing twice.

    Without this the selector picks one Grand Prix and talks about nothing else
    for a week, because a big weekend stays the highest-scoring item on the
    calendar the whole time it is approaching.
    """
    if candidate.kind == "week_ahead":
        # A weekly habit is allowed to be a habit, but not twice in a week.
        recent = [
            p for p in history
            if p.post_kind == "week_ahead" and now - p.decided_at < timedelta(days=6)
        ]
        if recent:
            candidate.note(-policy.REPEAT_EVENT_RECENT_PENALTY, "already did a week ahead")
        return

    event = candidate.events[0]
    recent = [
        p for p in history
        if p.event_id == event.event_id
        and now - p.decided_at < policy.REPEAT_EVENT_RECENT_WINDOW
    ]

    # Three tiers, narrowest first. The same session said twice is the real
    # fault; the same angle on a different session is weaker news; a different
    # angle on the same weekend is the account working as intended.
    session_id = candidate.session.session_id if candidate.session else None
    same_session = [p for p in recent if session_id is not None and p.session_id == session_id]
    if same_session:
        # Trailing it yesterday and marking the day today is the intended
        # behaviour, not a repeat. Saying it the same way twice is not.
        upgrading = candidate.kind == "today" and all(p.post_kind == "tomorrow" for p in same_session)
        if upgrading:
            candidate.note(-policy.UPGRADE_TO_TODAY_PENALTY, "trailed yesterday; today is race day")
        else:
            candidate.note(-policy.REPEAT_SAME_SESSION_PENALTY, "already posted about this session")
    elif any(p.post_kind == candidate.kind for p in recent):
        candidate.note(-policy.REPEAT_SAME_KIND_PENALTY, f"already posted a {candidate.kind} for this weekend")
    elif recent:
        candidate.note(-policy.REPEAT_EVENT_PENALTY, f"{len(recent)} post(s) about this weekend already")

    # Race day for a premier class is the one post a schedule account exists to
    # make, so the volume rules do not get to suppress it. Both of them tried:
    # the rest-day penalty dropped WorldSBK's Sunday race because Saturday's had
    # been covered, and the per-weekend cap dropped the season finale at Abu
    # Dhabi because the weekend had already earned three posts. Repetition is
    # still caught above - saying the same thing about the same session twice is
    # a different rule, and it still applies.
    race_day = (
        candidate.kind == "today"
        and candidate.session is not None
        and candidate.session.session_type == "race"
        and candidate.session.is_headline_class
    )
    if race_day:
        return

    if len(recent) >= policy.MAX_POSTS_PER_EVENT:
        candidate.note(-policy.OVER_CAP_PENALTY, f"{len(recent)} posts is enough for one weekend")

    if any(now - p.decided_at < timedelta(days=1, hours=1) for p in history):
        candidate.note(-policy.CONSECUTIVE_DAY_PENALTY, "posted yesterday")

    same_series = [
        p for p in history
        if p.series_code == event.series_code
        and now - p.decided_at < policy.SAME_SERIES_RECENT_WINDOW
        and p.event_id != event.event_id
    ]
    if same_series:
        candidate.note(-policy.SAME_SERIES_RECENT_PENALTY, f"{event.series_short_name} posted recently")


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------


def decide(
    events: Sequence[EventFact],
    history: Sequence[PostRecord],
    now: datetime,
    timezone: str = policy.POSTING_TIMEZONE,
) -> Decision:
    """What to post at `now`, or nothing."""
    candidates = [
        score_candidate(c, history, now)
        for c in build_candidates(events, now, timezone)
    ]
    if not candidates:
        fallback = build_fallback(events, now, timezone)
        if fallback is not None:
            fallback = score_candidate(fallback, history, now)
            if fallback.score > 0:
                return Decision(True, fallback, [], "quiet week; week ahead")
        return Decision(False, None, [], "nothing on the calendar to talk about")

    ranked = sorted(candidates, key=_ranking_key, reverse=True)
    best = ranked[0]

    if best.score >= policy.SCORE_FLOOR:
        return Decision(True, best, ranked[1:4], f"scored {best.score}")

    # Nothing worth a post of its own. Monday gets a look-ahead instead.
    fallback = build_fallback(events, now, timezone)
    if fallback is not None:
        fallback = score_candidate(fallback, history, now)
        if fallback.score > 0:
            return Decision(True, fallback, ranked[:3], "nothing else qualified; week ahead")

    return Decision(
        False,
        None,
        ranked[:3],
        f"best candidate scored {best.score}, floor is {policy.SCORE_FLOOR}",
    )


def _ranking_key(candidate: Candidate) -> tuple:
    """Score first; then the sooner thing; then a stable tiebreak.

    The stable tail matters more than it looks: without it two equal candidates
    swap places between runs and the account's choices stop being reproducible,
    which makes a bad decision impossible to investigate.
    """
    when = candidate.session.starts_at_utc if candidate.session else candidate.events[0].starts_at_utc
    return (candidate.score, -when.timestamp(), -candidate.events[0].event_id)
