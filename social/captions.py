"""Writing the caption, and refusing to publish it when it says something new.

Two halves, and the second matters more. Generation asks Claude for a few
sentences given only the brief; validation reads the finished text back against
that same brief and rejects anything containing a time, a weekday, a year or a
result that nobody put there. A generator can be persuaded to embellish. A
validator that only knows the facts cannot be.

There is always a caption. If the API key is absent, the request fails, or the
model writes something that does not survive validation, a composed caption is
used instead - built from the brief by string formatting, so it cannot be wrong.
The account keeps working when Anthropic is down, which for a daily job that
nobody watches is the difference between a quiet day and a broken one.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from .brief import CAPTION_LIMIT, Brief, hashtags

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5"

# One short caption a day: the token cost is a rounding error either way, so the
# choice is made on quality rather than price. Effort is held low because this
# is three sentences from a fact sheet, not a reasoning problem.
EFFORT = "low"
MAX_TOKENS = 700
TIMEOUT_SECONDS = 45

SYSTEM = """You write captions for ON TRACK, a motorsport schedule service.

You are given a fact sheet. Write a short Instagram caption about it.

Absolute rules:
- Use ONLY facts from the sheet. Never add a time, date, driver, team, result,
  standing, weather, lap count, or any other detail that is not written there.
- Never mention results, winners, championship positions or who is favourite.
  This account publishes schedules and must not spoil a race anyone recorded.
- If something is missing from the sheet, leave it out. Do not guess.
- Never invent a nickname for a circuit or a round.
- Never say sessions overlap, clash, or run at the same time unless the sheet
  gives times that show it. Two events starting on the same day is not that.
- A weekday belongs to the clock it is written next to. The sheet gives the
  reader's day and time and the circuit's day and time separately; never pair
  one frame's weekday with the other frame's time.

Style:
- Two or three short paragraphs. Around 40 to 70 words in total.
- Direct and useful. A reader should come away knowing what is on and when.
- Vary the opening. Do not begin every caption the same way.
- At most two emoji, and only where they earn their place. Often none is right.
- No hashtags - they are added separately.
- No hype, no clickbait, no "buckle up", no "get ready", no rhetorical questions.
- Do not sign off with a call to action; one is appended separately.

Write only the caption text."""

CALL_TO_ACTION = "Full schedule in your timezone at ontrackapp.me"

# Anything that would make this a results account rather than a schedule one.
_SPOILER = re.compile(
    r"\b(won|wins|winner|victory|victorious|podium|championship lead|title race|"
    r"beat|beaten|defeated|fastest lap|pole position secured|standings)\b",
    re.IGNORECASE,
)

_TIME = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_WEEKDAY = re.compile(
    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", re.IGNORECASE
)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_PLACEHOLDER = re.compile(r"\{[a-z_]+\}|\bTODO\b|\bTBD\b|lorem ipsum", re.IGNORECASE)


@dataclass
class CaptionResult:
    text: str
    source: str            # "model" or "composed"
    tags: list[str]


class ValidationError(Exception):
    """The caption said something the brief does not support."""


# --------------------------------------------------------------------------
# the fact sheet the model is given
# --------------------------------------------------------------------------


def fact_sheet(brief: Brief) -> str:
    """The brief as text. The model sees this and nothing else."""
    lines = [
        f"Post type: {brief.kind}",
        f"Championship: {brief.series}",
        f"Event: {brief.event_name}",
        f"Season: {brief.season}",
    ]
    if brief.circuit:
        lines.append(f"Circuit: {brief.circuit}")
    if brief.city and brief.country:
        lines.append(f"Location: {brief.city}, {brief.country}")
    if brief.classes:
        lines.append(f"Classes racing: {', '.join(brief.classes)}")
    if brief.days_away is not None and brief.kind == "weekend_preview":
        lines.append(f"Days until the weekend starts: {brief.days_away}")

    if brief.headline:
        h = brief.headline
        lines += [
            "",
            "Main session:",
            f"  {h.category} {h.name}",
            f"  For the reader: {h.viewer_weekday} {h.viewer_date_label}, "
            f"{h.viewer_time} central European time",
            f"  At the circuit: {h.circuit_weekday} {h.circuit_date_label}, "
            f"{h.circuit_time} local time",
        ]
        if h.crosses_midnight:
            lines.append(
                "  NOTE: these are different days. If you name a weekday, it must "
                "be the reader's, and it must go with the reader's time."
            )

    if brief.sessions:
        lines += ["", "Also scheduled (all times central European):"]
        lines += [
            f"  {s.category} {s.name} - {s.viewer_weekday} {s.viewer_time}"
            for s in brief.sessions
        ]

    if brief.other_events:
        # Each row is the day an event's first session falls on - usually
        # practice - and nothing more. Without saying so, the first real caption
        # read three Friday rows as "a full Friday of overlapping action".
        lines += [
            "",
            "This week (the day each event's first session is on - usually",
            "practice, not the race; no times are known here):",
        ] + [f"  {row}" for row in brief.other_events]

    if brief.headline or brief.sessions:
        lines += [
            "",
            "The reader is in central Europe. Times at the circuit and the reader's",
            "time are both given above where they differ; use whichever reads better,",
            "and say which is which.",
        ]
    else:
        # With no clock times there is nothing to disambiguate. Asked to "say
        # which is which" anyway, the first real caption added a sentence
        # explaining that its weekdays were central European weekdays.
        lines += [
            "",
            "The days above are the reader's days. There are no times to explain,",
            "so do not mention timezones at all.",
        ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# generation
# --------------------------------------------------------------------------


def generate(brief: Brief) -> CaptionResult:
    """A caption for this brief. Never raises - there is always a fallback."""
    tags = hashtags(brief)

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            text = _from_model(brief)
            body = _assemble(text, tags)
            validate(body, brief)
            return CaptionResult(body, "model", tags)
        except ValidationError as error:
            logger.warning("caption from model rejected (%s); composing instead", error)
        except Exception as error:  # noqa: BLE001 - the day's post must not die here
            logger.warning("caption generation failed (%s); composing instead", error)
    else:
        logger.info("ANTHROPIC_API_KEY is not set; composing the caption")

    body = _assemble(compose(brief), tags)
    validate(body, brief)  # the composed caption is checked too, on principle
    return CaptionResult(body, "composed", tags)


def _from_model(brief: Brief) -> str:
    import anthropic

    client = anthropic.Anthropic(timeout=TIMEOUT_SECONDS)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": fact_sheet(brief)}],
    )

    if response.stop_reason == "refusal":
        raise ValidationError("the model declined to write this caption")

    text = "".join(block.text for block in response.content if block.type == "text")
    if not text.strip():
        raise ValidationError("the model returned no text")
    return text.strip()


def _assemble(body: str, tags: list[str]) -> str:
    return f"{body.strip()}\n\n{CALL_TO_ACTION}\n\n{' '.join(tags)}"


# --------------------------------------------------------------------------
# the fallback, which cannot be wrong
# --------------------------------------------------------------------------


def compose(brief: Brief) -> str:
    """A caption built from the brief by formatting.

    Plainer than the model's, and never incorrect. Used when there is no API
    key, when the call fails, and when what came back did not survive
    validation.
    """
    if brief.kind == "week_ahead":
        rows = "\n".join(brief.other_events[:5])
        return f"The week ahead in motorsport.\n\n{rows}"

    where = brief.place or ""
    head = brief.headline

    if head is None:
        opening = f"The {brief.event_name} weekend is next for {brief.series}."
        if where:
            opening += f" It runs at {where}."
        if brief.sessions:
            first = brief.sessions[0]
            opening += (
                f"\n\nFirst on track: {first.category} {first.name}, "
                f"{first.viewer_weekday} at {first.viewer_time} central European time."
            )
        return opening

    # Everything below is in the reader's frame, because "today" and "tomorrow"
    # are. The circuit's own clock follows in brackets, and says which day it is
    # there whenever that is not the same day.
    when = {
        "today": "today",
        "tomorrow": f"tomorrow, {head.viewer_weekday},",
    }.get(brief.kind, f"on {head.viewer_weekday} {head.viewer_date_label},")

    lines = [f"{brief.series} — {brief.event_name}.", ""]
    lines.append(
        f"{head.category} {head.name} is {when} at {head.viewer_time} central European "
        f"time ({head.circuit_stamp} at the circuit)."
    )
    if where:
        lines.append(f"Round held at {where}.")
    if brief.sessions:
        also = ", ".join(f"{s.category} {s.name} at {s.viewer_time}" for s in brief.sessions[:3])
        lines.append(f"Also that day, same timezone: {also}.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def validate(caption: str, brief: Brief) -> None:
    """Refuse a caption that states anything the brief does not.

    Deliberately mechanical. Every clock time, weekday and year in the text is
    matched against the set the brief allows; anything else is a claim that
    arrived from somewhere other than the database, and the post does not go
    out. It is the only reason a language model is safe to have in this loop.
    """
    if not caption.strip():
        raise ValidationError("the caption is empty")

    if len(caption) > CAPTION_LIMIT:
        raise ValidationError(f"caption is {len(caption)} characters, limit is {CAPTION_LIMIT}")

    if _PLACEHOLDER.search(caption):
        raise ValidationError("the caption contains an unfilled placeholder")

    spoiler = _SPOILER.search(caption)
    if spoiler:
        raise ValidationError(f"the caption mentions a result: {spoiler.group(0)!r}")

    allowed_times = brief.allowed_times
    for match in _TIME.finditer(caption):
        if match.group(0) not in allowed_times:
            raise ValidationError(f"time {match.group(0)!r} is not in the brief")

    allowed_days = {d.lower() for d in brief.allowed_weekdays}
    for match in _WEEKDAY.finditer(caption):
        if match.group(0).lower() not in allowed_days:
            raise ValidationError(f"weekday {match.group(0)!r} is not in the brief")

    for match in _YEAR.finditer(caption):
        if match.group(0) != str(brief.season):
            raise ValidationError(f"year {match.group(0)!r} is not the season in the brief")

    # The event has to actually be named, or the post is about nothing.
    if brief.kind != "week_ahead":
        subject = brief.event_name.lower()
        shortened = subject.replace("grand prix", "gp")
        text = caption.lower()
        if subject not in text and shortened not in text and brief.series.lower() not in text:
            raise ValidationError("the caption never names the event or the championship")
