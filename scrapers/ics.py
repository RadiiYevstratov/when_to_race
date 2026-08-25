"""A small RFC 5545 reader.

An official ICS feed is the best possible source for this product: structured,
timezone-aware and stable. That makes this module load-bearing, so it is written
against the spec rather than against one publisher's output, and it is
stdlib-only so it can be tested without installing anything.

Supported: line unfolding, property parameters (quoted and unquoted), VEVENT
extraction, DTSTART/DTEND with TZID / UTC / DATE forms, DURATION, text
unescaping. Not supported: RRULE, VALARM, VTIMEZONE definitions (we resolve
TZID against the IANA database instead, which is what publishers mean anyway).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class IcsError(Exception):
    pass


@dataclass
class IcsDateTime:
    """A DTSTART/DTEND value, keeping the distinction the feed made."""

    value: datetime | date
    tzid: Optional[str] = None
    is_date_only: bool = False
    is_utc: bool = False


@dataclass
class IcsEvent:
    properties: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, dict[str, str]] = field(default_factory=dict)
    dtstart: Optional[IcsDateTime] = None
    dtend: Optional[IcsDateTime] = None
    duration: Optional[timedelta] = None

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self.properties.get(name.upper(), default)

    @property
    def summary(self) -> str:
        return self.get("SUMMARY", "") or ""

    @property
    def uid(self) -> Optional[str]:
        return self.get("UID")


def unfold(text: str) -> list[str]:
    """Undo RFC 5545 line folding.

    A continuation line starts with a single space or tab, which is stripped.
    Handles CRLF, LF and lone CR line endings, because publishers emit all three.
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw_line in normalised.split("\n"):
        if raw_line[:1] in (" ", "\t"):
            # RFC 5545 folding: the first space or tab is the marker, not content.
            if lines:
                lines[-1] += raw_line[1:]
            else:
                lines.append(raw_line[1:])
        else:
            lines.append(raw_line)
    return [line for line in lines if line.strip()]


def split_property(line: str) -> tuple[str, dict[str, str], str]:
    """Split `NAME;PARAM=VAL;P2="a:b":VALUE` into (name, params, value).

    The value starts at the first colon that is not inside a quoted parameter.
    """
    in_quotes = False
    for index, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
        elif char == ":" and not in_quotes:
            head, value = line[:index], line[index + 1 :]
            break
    else:
        raise IcsError(f"content line has no value separator: {line!r}")

    segments: list[str] = []
    current = ""
    in_quotes = False
    for char in head:
        if char == '"':
            in_quotes = not in_quotes
            current += char
        elif char == ";" and not in_quotes:
            segments.append(current)
            current = ""
        else:
            current += char
    segments.append(current)

    name = segments[0].upper()
    params: dict[str, str] = {}
    for segment in segments[1:]:
        if "=" not in segment:
            continue
        key, _, param_value = segment.partition("=")
        params[key.strip().upper()] = param_value.strip().strip('"')
    return name, params, value


_TEXT_ESCAPES = {"n": "\n", "N": "\n", ",": ",", ";": ";", "\\": "\\"}


def unescape_text(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            nxt = value[index + 1]
            result.append(_TEXT_ESCAPES.get(nxt, nxt))
            index += 2
        else:
            result.append(char)
            index += 1
    return "".join(result)


_DURATION_RE = re.compile(
    r"^(?P<sign>[+-])?P"
    r"(?:(?P<weeks>\d+)W)?"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_duration(value: str) -> timedelta:
    match = _DURATION_RE.match(value.strip())
    if not match or value.strip() in ("P", "PT"):
        raise IcsError(f"unparseable DURATION: {value!r}")
    parts = {key: int(val) for key, val in match.groupdict().items() if val and key != "sign"}
    if not parts:
        raise IcsError(f"unparseable DURATION: {value!r}")
    delta = timedelta(
        weeks=parts.get("weeks", 0),
        days=parts.get("days", 0),
        hours=parts.get("hours", 0),
        minutes=parts.get("minutes", 0),
        seconds=parts.get("seconds", 0),
    )
    return -delta if match.group("sign") == "-" else delta


def parse_datetime(value: str, params: dict[str, str]) -> IcsDateTime:
    """Parse a DATE-TIME or DATE value, honouring TZID and the trailing Z."""
    raw = value.strip()
    tzid = params.get("TZID")

    if params.get("VALUE", "").upper() == "DATE" or (len(raw) == 8 and "T" not in raw):
        try:
            parsed_date = datetime.strptime(raw, "%Y%m%d").date()
        except ValueError as exc:
            raise IcsError(f"unparseable DATE: {value!r}") from exc
        return IcsDateTime(value=parsed_date, tzid=tzid, is_date_only=True)

    is_utc = raw.endswith("Z")
    stamp = raw[:-1] if is_utc else raw
    try:
        naive = datetime.strptime(stamp, "%Y%m%dT%H%M%S")
    except ValueError:
        try:
            naive = datetime.strptime(stamp, "%Y%m%dT%H%M")
        except ValueError as exc:
            raise IcsError(f"unparseable DATE-TIME: {value!r}") from exc

    if is_utc:
        if tzid:
            # A Z suffix means UTC; a TZID alongside it is a publisher bug. The
            # Z wins, but the caller should know the feed is inconsistent.
            tzid = None
        return IcsDateTime(value=naive.replace(tzinfo=timezone.utc), tzid=None, is_utc=True)

    if tzid:
        try:
            zone = ZoneInfo(tzid)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise IcsError(f"unknown TZID {tzid!r}") from exc
        return IcsDateTime(value=naive.replace(tzinfo=zone), tzid=tzid)

    # Floating time: no zone information at all. Left naive on purpose so the
    # normalize stage is forced to attach the venue's zone.
    return IcsDateTime(value=naive, tzid=None)


def parse_calendar(text: str) -> list[IcsEvent]:
    """Return every VEVENT in the feed, in document order."""
    events: list[IcsEvent] = []
    current: Optional[IcsEvent] = None
    nested_depth = 0

    for line in unfold(text):
        try:
            name, params, value = split_property(line)
        except IcsError:
            continue  # tolerate junk lines rather than losing the whole feed

        if name == "BEGIN" and value.upper() == "VEVENT":
            current = IcsEvent()
            nested_depth = 0
            continue
        if name == "END" and value.upper() == "VEVENT":
            if current is not None:
                events.append(current)
            current = None
            nested_depth = 0
            continue
        if current is None:
            continue

        # A VEVENT can contain sub-components - VALARM in practice. Their
        # properties belong to the alarm, not the session: an alarm's
        # DESCRIPTION would otherwise overwrite the event's.
        if name == "BEGIN":
            nested_depth += 1
            continue
        if name == "END":
            nested_depth = max(0, nested_depth - 1)
            continue
        if nested_depth > 0:
            continue

        current.parameters[name] = params
        if name == "DTSTART":
            current.dtstart = parse_datetime(value, params)
        elif name == "DTEND":
            current.dtend = parse_datetime(value, params)
        elif name == "DURATION":
            current.duration = parse_duration(value)
        else:
            current.properties[name] = unescape_text(value)

    if current is not None:
        raise IcsError("feed ended inside a VEVENT")
    return events


def resolve_end(event: IcsEvent) -> Optional[datetime | date]:
    """DTEND if present, otherwise DTSTART + DURATION, otherwise None."""
    if event.dtend is not None:
        return event.dtend.value
    if event.duration is not None and event.dtstart is not None:
        start = event.dtstart.value
        if isinstance(start, datetime):
            return start + event.duration
        return start + event.duration
    return None