"""The fact sheet a post is built from.

One structure, assembled once from the database, and everything downstream -
the card, the caption, the validator - reads only from it. That is the whole
defence against a post that says something untrue: the caption writer is never
given the database, only this, and the validator checks the finished caption
back against the same object.

Nothing here is optional-but-guessed. A field that is unknown stays None and
every consumer omits it rather than inventing a plausible value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from . import policy
from .selection import Candidate, EventFact, SessionFact

# Instagram's own ceiling. Captions are nowhere near it, but a generator that
# runs away should be caught by something other than the API.
CAPTION_LIMIT = 2200


def _local(moment: datetime, zone: str) -> datetime:
    return moment.astimezone(ZoneInfo(zone))


@dataclass(frozen=True)
class SessionLine:
    """One session, in both the circuit's clock and the reader's.

    Each frame carries its own weekday and date, and there is deliberately no
    plain `weekday` to reach for. A NASCAR race at 20:00 on Thursday in Tennessee
    is 02:00 on Friday in Bratislava, and a sentence that takes the day from one
    frame and the clock from the other is wrong in the way a schedule service
    least affords - it reads perfectly and sends someone to the wrong evening.

    The reader's frame is the primary one: this account writes for people in
    central Europe, so "tomorrow" means their tomorrow. The circuit's frame is
    given alongside, and names its own weekday only when the two disagree.
    """

    category: str
    name: str
    session_type: str
    circuit_time: str          # 20:00
    circuit_weekday: str       # Thursday
    circuit_date_label: str    # 17 September
    viewer_time: str           # 02:00
    viewer_weekday: str        # Friday
    viewer_date_label: str     # 18 September
    viewer_zone_label: str     # CEST - the abbreviation on the day, not a guess
    is_headline: bool

    @property
    def crosses_midnight(self) -> bool:
        """Do the circuit and the reader disagree about which day this is?"""
        return self.circuit_date_label != self.viewer_date_label

    @property
    def circuit_stamp(self) -> str:
        """The circuit's clock, carrying its weekday when that differs."""
        if self.crosses_midnight:
            return f"{self.circuit_time} {self.circuit_weekday}"
        return self.circuit_time


@dataclass(frozen=True)
class Brief:
    """Everything true about the post, and nothing else."""

    kind: str                       # today | tomorrow | weekend_preview | week_ahead
    series: str                     # Formula 1
    series_code: str
    event_name: str                 # Azerbaijan Grand Prix
    season: int
    circuit: Optional[str]          # Baku City Circuit
    city: Optional[str]             # Baku
    country: Optional[str]          # AZ
    circuit_timezone: Optional[str]
    viewer_timezone: str

    headline: Optional[SessionLine]          # the session the post leads with
    sessions: tuple[SessionLine, ...] = ()   # the rest of the day or weekend
    classes: tuple[str, ...] = ()            # F1, F2, F3
    other_events: tuple[str, ...] = ()       # for the week-ahead post
    # The days the week-ahead rows fall on, spelled out. The rows abbreviate
    # them ("Thu") for the card, and a writer naturally expands them - which is
    # a true statement the validator has to be able to recognise as one.
    event_weekdays: tuple[str, ...] = ()
    days_away: Optional[int] = None
    accent: tuple[int, int, int] = (238, 240, 241)
    venue_slug: Optional[str] = None
    event_id: Optional[int] = None
    session_id: Optional[int] = None

    # ---- what a caption is allowed to say --------------------------------
    #
    # The validator checks the finished caption against these. Anything
    # resembling a time, a weekday or a year that is not in here is a claim
    # nobody made, and the post is rejected rather than published.

    @property
    def allowed_times(self) -> set[str]:
        times = set()
        for line in self._all_lines():
            times.add(line.circuit_time)
            times.add(line.viewer_time)
        return times

    @property
    def allowed_weekdays(self) -> set[str]:
        days = set(self.event_weekdays)
        for line in self._all_lines():
            days.add(line.viewer_weekday)
            days.add(line.circuit_weekday)
        return days

    @property
    def allowed_dates(self) -> set[str]:
        dates = set()
        for line in self._all_lines():
            dates.add(line.viewer_date_label)
            dates.add(line.circuit_date_label)
        return dates

    def _all_lines(self) -> list[SessionLine]:
        lines = list(self.sessions)
        if self.headline is not None:
            lines.append(self.headline)
        return lines

    @property
    def place(self) -> Optional[str]:
        if self.circuit and self.country:
            return f"{self.circuit}, {self.country}"
        return self.circuit or self.city


def _session_line(session: SessionFact, circuit_zone: str, viewer_zone: str) -> SessionLine:
    circuit = _local(session.starts_at_utc, circuit_zone)
    viewer = _local(session.starts_at_utc, viewer_zone)
    return SessionLine(
        category=session.category_short_name,
        name=session.display_name,
        session_type=session.session_type,
        circuit_time=f"{circuit:%H:%M}",
        circuit_weekday=f"{circuit:%A}",
        circuit_date_label=f"{circuit.day} {circuit:%B}",
        viewer_time=f"{viewer:%H:%M}",
        viewer_weekday=f"{viewer:%A}",
        viewer_date_label=f"{viewer.day} {viewer:%B}",
        # CET in winter, CEST in summer. Printing one of them all year is wrong
        # for half of it, and this is a schedule.
        viewer_zone_label=viewer.strftime("%Z") or "CET",
        is_headline=session.is_headline_class,
    )


# Colours match the class accents the site uses, so a post and the page look
# like one product. Resolved by the repository where the database is reachable;
# this is the fallback for the series-level colour.
_SERIES_ACCENT: dict[str, tuple[int, int, int]] = {
    "f1": (232, 17, 45),
    "motogp": (135, 66, 211),
    "wsbk": (254, 0, 0),
    "wec": (46, 158, 91),
    "indycar": (12, 124, 140),
    "nascar": (176, 138, 0),
    "imsa": (122, 79, 191),
    "wrc": (200, 106, 0),
}


def build(
    candidate: Candidate,
    now: datetime,
    viewer_zone: str = policy.POSTING_TIMEZONE,
    accent: Optional[tuple[int, int, int]] = None,
) -> Brief:
    """Turn a chosen candidate into the only facts the post may state."""
    if candidate.kind == "week_ahead":
        return _week_ahead_brief(candidate, now, viewer_zone)

    event: EventFact = candidate.events[0]
    circuit_zone = event.venue_timezone

    headline = (
        _session_line(candidate.session, circuit_zone, viewer_zone)
        if candidate.session is not None
        else None
    )

    # For a preview, the weekend's own running order is the story; for a
    # session post, the rest of that day is useful context and the rest of the
    # weekend is noise.
    if candidate.kind == "weekend_preview":
        chosen = sorted(event.sessions, key=lambda s: s.starts_at_utc)[:6]
    elif candidate.session is not None:
        day = _local(candidate.session.starts_at_utc, viewer_zone).date()
        chosen = [
            s for s in sorted(event.sessions, key=lambda s: s.starts_at_utc)
            if _local(s.starts_at_utc, viewer_zone).date() == day
            and s.session_id != candidate.session.session_id
        ][:4]
    else:
        chosen = []

    first = min((s.starts_at_utc for s in event.sessions), default=None)
    days_away = (
        (_local(first, viewer_zone).date() - _local(now, viewer_zone).date()).days
        if first else None
    )

    return Brief(
        kind=candidate.kind,
        series=event.series_short_name,
        series_code=event.series_code,
        event_name=event.name,
        season=event.season,
        circuit=event.venue_name,
        city=event.venue_city,
        country=event.venue_country,
        circuit_timezone=circuit_zone,
        viewer_timezone=viewer_zone,
        headline=headline,
        sessions=tuple(_session_line(s, circuit_zone, viewer_zone) for s in chosen),
        classes=tuple(
            dict.fromkeys(
                s.category_short_name
                for s in sorted(event.sessions, key=lambda s: s.starts_at_utc)
            )
        ),
        days_away=days_away,
        accent=accent or _SERIES_ACCENT.get(event.series_code, (238, 240, 241)),
        venue_slug=None,  # filled by the repository, which knows the venue slug
        event_id=event.event_id,
        session_id=candidate.session.session_id if candidate.session else None,
    )


def _week_ahead_brief(candidate: Candidate, now: datetime, viewer_zone: str) -> Brief:
    """The Monday look-ahead: several events, no single session."""
    lines: list[str] = []
    weekdays: list[str] = []
    for event in sorted(candidate.events, key=lambda e: e.starts_at_utc)[:5]:
        first = min((s.starts_at_utc for s in event.sessions), default=None)
        if first is None:
            continue
        local = _local(first, viewer_zone)
        lines.append(f"{local:%a} · {event.series_short_name} · {event.name}")
        weekdays.append(f"{local:%A}")

    leading = max(
        candidate.events,
        key=lambda e: policy.SERIES_BONUS.get(e.series_code, 0),
    )
    return Brief(
        kind="week_ahead",
        series=leading.series_short_name,
        series_code=leading.series_code,
        event_name="This week in motorsport",
        season=leading.season,
        circuit=None,
        city=None,
        country=None,
        circuit_timezone=None,
        viewer_timezone=viewer_zone,
        headline=None,
        sessions=(),
        classes=tuple(dict.fromkeys(e.series_short_name for e in candidate.events)),
        other_events=tuple(lines),
        event_weekdays=tuple(dict.fromkeys(weekdays)),
        accent=_SERIES_ACCENT.get(leading.series_code, (238, 240, 241)),
        event_id=None,
        session_id=None,
    )


# --------------------------------------------------------------------------
# hashtags
# --------------------------------------------------------------------------

_SERIES_TAGS: dict[str, tuple[str, ...]] = {
    "f1": ("F1", "Formula1"),
    "motogp": ("MotoGP",),
    "wsbk": ("WorldSBK",),
    "wec": ("WEC", "Endurance"),
    "indycar": ("IndyCar",),
    "nascar": ("NASCAR",),
    "imsa": ("IMSA",),
    "wrc": ("WRC",),
}


def hashtags(brief: Brief, limit: int = 7) -> list[str]:
    """Tags derived from the event, not a fixed block stapled to every post.

    Built in code rather than asked of a model: they are a mechanical function
    of the series, the round and the circuit, and paying for a model to invent
    them would only introduce a way for them to be wrong.
    """
    tags: list[str] = []

    def add(value: Optional[str]) -> None:
        if not value:
            return
        cleaned = "".join(ch for ch in value.title() if ch.isalnum())
        if cleaned and cleaned not in tags:
            tags.append(cleaned)

    for tag in _SERIES_TAGS.get(brief.series_code, ()):
        add(tag)

    if brief.kind != "week_ahead":
        add(brief.event_name.replace("Grand Prix", "GP"))
        add(brief.city)
        add(brief.circuit)

    add("Motorsport")
    add("RaceWeekend" if brief.kind == "weekend_preview" else "OnTrack")
    return [f"#{t}" for t in tags[:limit]]
