/**
 * Calendar export.
 *
 * The subscribable feed is the reason to get UID and SEQUENCE exactly right: a
 * calendar client matches on UID and only accepts an update when SEQUENCE has
 * increased. Get either wrong and a rescheduled session appears twice on
 * someone's phone instead of moving.
 */

// The selection format is shared with the board's filter, so it lives in
// selection.ts. Re-exported here because this module's callers have always
// found it at this address.
export { parseSelection } from "./selection.ts";

export interface CalendarSession {
  icsUid: string;
  icsSequence: number;
  displayName: string;
  seriesShortName: string;
  categoryShortName: string;
  eventName: string;
  venueName: string;
  startsAtUtc: string | Date;
  endsAtUtc?: string | Date | null;
  status?: string;
  timeStatus?: string;
  sourceUrl?: string | null;
}

export interface CalendarOptions {
  calendarName: string;
  /** Overridden in tests so output is deterministic. */
  now?: Date;
  productId?: string;
}

const DEFAULT_PRODUCT_ID = "-//motorsport-schedule//EN";
const DEFAULT_DURATION_MS = 2 * 3_600_000;

function stamp(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
}

export function escapeText(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r?\n/g, "\\n");
}

/**
 * Fold to 75 octets per RFC 5545. Counts bytes, not characters - a circuit name
 * with an accent is multi-byte and a naive character count breaks the line in
 * the wrong place.
 */
export function foldLine(line: string): string {
  const encoder = new TextEncoder();
  if (encoder.encode(line).length <= 75) return line;

  const output: string[] = [];
  let current = "";
  let currentBytes = 0;
  let limit = 75;

  for (const character of line) {
    const size = encoder.encode(character).length;
    if (currentBytes + size > limit) {
      output.push(current);
      current = character;
      currentBytes = size;
      limit = 74; // continuation lines carry a leading space
    } else {
      current += character;
      currentBytes += size;
    }
  }
  output.push(current);
  return output.join("\r\n ");
}

function statusLine(session: CalendarSession): string | null {
  if (session.status === "cancelled") return "STATUS:CANCELLED";
  if (session.timeStatus && session.timeStatus !== "confirmed") return "STATUS:TENTATIVE";
  return "STATUS:CONFIRMED";
}

export function buildEvent(session: CalendarSession, now: Date): string[] {
  const start = session.startsAtUtc;
  const end =
    session.endsAtUtc ??
    new Date(
      (start instanceof Date ? start : new Date(start)).getTime() + DEFAULT_DURATION_MS,
    );

  const summary = `${session.categoryShortName}: ${session.displayName} - ${session.eventName}`;
  const provisional =
    session.timeStatus && session.timeStatus !== "confirmed"
      ? "Time is provisional; confirm with the official source."
      : "";
  const description = [provisional, session.sourceUrl ?? ""].filter(Boolean).join(" ");

  const lines = [
    "BEGIN:VEVENT",
    `UID:${session.icsUid}`,
    `SEQUENCE:${session.icsSequence}`,
    `DTSTAMP:${stamp(now)}`,
    `DTSTART:${stamp(start)}`,
    `DTEND:${stamp(end)}`,
    `SUMMARY:${escapeText(summary)}`,
    `LOCATION:${escapeText(session.venueName)}`,
  ];

  if (description) lines.push(`DESCRIPTION:${escapeText(description)}`);
  if (session.sourceUrl) lines.push(`URL:${session.sourceUrl}`);

  const status = statusLine(session);
  if (status) lines.push(status);

  lines.push("END:VEVENT");
  return lines;
}

export function buildCalendar(sessions: CalendarSession[], options: CalendarOptions): string {
  const now = options.now ?? new Date();
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    `PRODID:${options.productId ?? DEFAULT_PRODUCT_ID}`,
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    `X-WR-CALNAME:${escapeText(options.calendarName)}`,
    "X-PUBLISHED-TTL:PT6H",
    "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
  ];

  for (const session of sessions) {
    lines.push(...buildEvent(session, now));
  }
  lines.push("END:VCALENDAR");

  return lines.map(foldLine).join("\r\n") + "\r\n";
}

/**
 * Selection tokens for /api/calendar/[selection].ics
 *   all            every series
 *   f1             one series
 *   f1+motogp      several
 *   f1.f1          a single category within a series
 */
