"""What the account thinks is worth saying.

Every number here is an editorial judgement rather than a fact about the sport,
which is why they live in one file away from the logic that applies them. A
Grand Prix outranking a practice session is a choice; so is Formula 1 outranking
WorldSPB. Tuning the account's voice should mean editing this file and rerunning
the replay, not reading the scoring code.

The scores are additive and roughly on a 0-100 scale so a decision can be read
in the log without a calculator: a base for what kind of post it is, then
modifiers for how big the championship is, how soon it runs, and how recently we
last said something similar.
"""

from __future__ import annotations

from datetime import timedelta

# --- what kind of post ----------------------------------------------------
#
# "today" outranks "tomorrow" outranks a preview, because the closer something
# is the more useful saying so becomes. A race outranks everything at the same
# distance.
POST_KINDS = ("today", "tomorrow", "weekend_preview", "week_ahead")

BASE_SCORE: dict[tuple[str, str], int] = {
    # (post kind, session type)
    ("today", "race"): 100,
    ("today", "sprint"): 84,
    ("today", "sprint_qualifying"): 78,
    ("today", "qualifying"): 80,
    ("today", "practice"): 52,
    ("tomorrow", "race"): 88,
    ("tomorrow", "sprint"): 72,
    ("tomorrow", "sprint_qualifying"): 66,
    ("tomorrow", "qualifying"): 68,
    ("tomorrow", "practice"): 44,
}

# A preview is about the weekend rather than one session, so it does not vary by
# session type.
WEEKEND_PREVIEW_SCORE = 66
WEEK_AHEAD_SCORE = 38

# Below this, say nothing.
#
# This number sets the account's volume more than anything else here, and it was
# tuned by replaying the season rather than reasoned about. At 40 the account
# posted 6.6 times a week - with eight championships running, something is
# always happening somewhere, and a low floor says all of it. At 72 it posts
# around four times a week and every post is a race, a qualifying session or the
# weekend they belong to.
SCORE_FLOOR = 72

# --- which championship ---------------------------------------------------
#
# Reach, not merit. WorldSBK racing is no less worth watching than Formula 1;
# there are simply fewer people waiting to hear about it, and an account with
# one post a day has to choose.
SERIES_BONUS: dict[str, int] = {
    "f1": 15,
    "motogp": 12,
    "wec": 7,
    "wsbk": 6,
    "indycar": 6,
    "nascar": 5,
    "imsa": 4,
    "wrc": 4,
}
DEFAULT_SERIES_BONUS = 0

# A weekend running three championships is a bigger weekend. Counted on classes
# rather than series, because F1 + F2 + F3 at Monza genuinely is more to talk
# about than a single-class round.
MULTI_CLASS_BONUS_PER_EXTRA = 3
MULTI_CLASS_BONUS_CAP = 9

# Leading on a support class is weaker news than leading on the premier one. An
# Xfinity race is a race; it is not the race people are waiting for, and without
# this the account led with Trucks and Xfinity most NASCAR weekends purely
# because they run before the Cup race.
SUPPORT_CLASS_PENALTY = 16

# Posting on consecutive days is what turns a schedule account into a feed
# nobody reads. This is the dial that sets cadence: at zero the account posted
# more than six times a week, because with eight championships there is nearly
# always another race to mention. A day's rest has to be outscored, not merely
# tied.
CONSECUTIVE_DAY_PENALTY = 20

# --- not repeating ourselves ---------------------------------------------
#
# The whole reason the history table exists. Without these the account would
# post about the same Grand Prix every day of the week it was approaching,
# because it stays the highest-scoring thing on the calendar throughout.
# Penalties are per *kind* of post, not per event, and the distinction is the
# difference between a working account and a broken one. A race weekend
# legitimately earns a preview on Tuesday and a race-day post on Sunday: those
# say different things. Penalising the event itself suppressed the race - the
# single most important post there is - because the preview had already been
# made. Only saying the same thing twice is the fault.
# Keyed on the session, not the kind. Two "today" posts about the same weekend
# are the same post only if they are about the same session: a Saturday sprint
# and a Sunday race are different news, and a rule that could not tell them
# apart silently suppressed every Grand Prix that followed a sprint.
REPEAT_SAME_SESSION_PENALTY = 90     # this session, said again the same way
REPEAT_SAME_KIND_PENALTY = 34        # same angle, different session, same weekend
REPEAT_EVENT_PENALTY = 12            # a different angle on a weekend already covered
REPEAT_EVENT_RECENT_WINDOW = timedelta(days=9)

# Trailing a race on Saturday and then marking race day on Sunday is not a
# repeat, it is how a schedule account is supposed to behave - and the first
# version of this rule blocked every Grand Prix that had been trailed, which
# silently removed the most valuable post there is.
UPGRADE_TO_TODAY_PENALTY = 10

# However often a weekend deserves revisiting, there is a limit. Three posts is
# a preview, a trail and a race day; a fourth is the account talking to itself.
MAX_POSTS_PER_EVENT = 3
OVER_CAP_PENALTY = 90

# Two Formula 1 posts in a row reads as a Formula 1 account. A gentle nudge
# towards the other championship when both have something on.
SAME_SERIES_RECENT_PENALTY = 12
SAME_SERIES_RECENT_WINDOW = timedelta(days=2)

# The same session, already covered as "tomorrow", should not come back as
# "today" unless nothing else is close. This is a nudge, not a ban: a Grand
# Prix is worth mentioning on the morning of the race even if we trailed it.
REPEAT_SESSION_PENALTY = 25

# --- timing ---------------------------------------------------------------
#
# How far ahead a weekend preview may fire. Exactly two days: a window of two
# to three gave every weekend two chances to be previewed, and with eight
# championships that alone filled most of the calendar.
PREVIEW_MIN_DAYS = 2
PREVIEW_MAX_DAYS = 2

# A "today" post is only worth making while the session is still ahead. Posting
# at noon about a race that started at eleven is worse than saying nothing.
MIN_LEAD_TIME = timedelta(minutes=45)

# Sessions worth building a post around on their own. Practice appears here
# because the first session of a Grand Prix weekend is genuinely the news on a
# Thursday - but it scores low enough that it only wins when nothing else runs.
NOTABLE_SESSION_TYPES = ("race", "sprint", "sprint_qualifying", "qualifying", "practice")

# Only these carry a weekend on their own for the "tomorrow" post. A practice
# session tomorrow is not a reason to post; a race is.
TOMORROW_SESSION_TYPES = ("race", "sprint", "sprint_qualifying", "qualifying")

# The week-ahead post is a Monday habit, and strictly a fallback: it is offered
# only when nothing else clears the floor, rather than competing on score. As a
# competitor it always lost, because a summary of the week is genuinely less
# interesting than any single race in it - which is exactly why it belongs in
# the gap instead of in the race.
WEEK_AHEAD_WEEKDAY = 0  # Monday

# --- where the clock is ---------------------------------------------------
#
# The audience is European and the operator is in Slovakia; the server is in
# neither place and its timezone is not to be trusted. Everything user-facing
# is decided against this zone, and stored in UTC.
POSTING_TIMEZONE = "Europe/Bratislava"
POSTING_HOUR = 12
# The last local hour a scheduled run may still post in. GitHub's cron starts
# this repository's jobs one to three hours late, so "noon" really means "the
# first run at or after noon" - and after this hour a "today" post would be
# arriving too late in the day to be worth making.
POSTING_CUTOFF_HOUR = 18
