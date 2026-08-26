/**
 * Timezone handling.
 *
 * Everything is stored and transmitted as UTC and converted here, at render
 * time. The one rule that matters: a session is grouped under the day it falls
 * on *in the viewer's timezone*, not the circuit's. A 15:00 race in Melbourne
 * is the previous evening in Los Angeles, and filing it under the wrong day is
 * exactly the confusion this product exists to remove.
 *
 * No date library. Intl has the full IANA database and does the arithmetic
 * correctly across DST boundaries and non-hour offsets.
 */

export type DayKey = string; // "YYYY-MM-DD" in the viewer's zone

export interface HasStart {
  startsAtUtc: string | Date;
}

export interface DayGroup<T> {
  key: DayKey;
  heading: string;
  shortHeading: string;
  items: T[];
}

export function toDate(value: string | Date): Date {
  return value instanceof Date ? value : new Date(value);
}

/** The viewer's zone, or their saved override. */
export function resolveTimeZone(override?: string | null): string {
  if (override && isValidTimeZone(override)) return override;
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function isValidTimeZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

function partsIn(date: Date, timeZone: string): Record<string, string> {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const result: Record<string, string> = {};
  for (const part of formatter.formatToParts(date)) {
    if (part.type !== "literal") result[part.type] = part.value;
  }
  return result;
}

/** Calendar day in the given zone, as YYYY-MM-DD. */
export function dayKey(value: string | Date, timeZone: string): DayKey {
  const parts = partsIn(toDate(value), timeZone);
  return `${parts.year}-${parts.month}-${parts.day}`;
}

/** 24-hour clock time, e.g. "14:30". Hour 24 is midnight in some locales. */
export function formatTime(value: string | Date, timeZone: string, hour12 = false): string {
  const date = toDate(value);
  if (hour12) {
    return new Intl.DateTimeFormat("en-US", {
      timeZone,
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    }).format(date);
  }
  const parts = partsIn(date, timeZone);
  const hour = parts.hour === "24" ? "00" : parts.hour;
  return `${hour}:${parts.minute}`;
}

export function formatDayHeading(key: DayKey, timeZone: string): string {
  const date = new Date(`${key}T12:00:00Z`);
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(date);
}

export function formatShortDay(key: DayKey): string {
  const date = new Date(`${key}T12:00:00Z`);
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(date);
}

/** e.g. "UTC+2", "UTC+5:30". Shown alongside the zone so it is never ambiguous. */
export function offsetLabel(value: string | Date, timeZone: string): string {
  const formatted = new Intl.DateTimeFormat("en-US", {
    timeZone,
    timeZoneName: "shortOffset",
  }).formatToParts(toDate(value));
  const name = formatted.find((part) => part.type === "timeZoneName")?.value ?? "UTC";
  return name.replace("GMT", "UTC") === "UTC" ? "UTC" : name.replace("GMT", "UTC");
}

/**
 * ISO 8601 carrying the offset of the given zone, e.g. "2026-09-06T15:00:00+02:00".
 *
 * Structured data wants the event's own local time. A "Z" timestamp is correct
 * but tells a consumer nothing about which clock the session was scheduled
 * against, and search results show event times in local terms - so the offset
 * is the part that has to survive.
 *
 * hourCycle "h23" rather than hour12:false: some ICU builds render midnight as
 * hour 24 of the previous day, which would move a night session back a day.
 */
export function toLocalIso(value: string | Date, timeZone: string): string {
  const date = toDate(value);

  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });

  const parts: Record<string, string> = {};
  for (const part of formatter.formatToParts(date)) {
    if (part.type !== "literal") parts[part.type] = part.value;
  }

  const local = `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;

  // Read that same wall clock as if it were UTC; the gap to the real instant is
  // the zone's offset at that moment, DST included.
  const offsetMinutes = Math.round((Date.parse(`${local}Z`) - date.getTime()) / 60_000);
  const sign = offsetMinutes < 0 ? "-" : "+";
  const absolute = Math.abs(offsetMinutes);
  const hours = String(Math.floor(absolute / 60)).padStart(2, "0");
  const minutes = String(absolute % 60).padStart(2, "0");

  return `${local}${sign}${hours}:${minutes}`;
}

/**
 * Whole-day difference between the same instant in two zones.
 *
 * Returns +1 when the viewer's calendar day is ahead of the circuit's, -1 when
 * behind, 0 when they agree. This is what the "+1" marker in the UI encodes.
 */
export function dayShift(value: string | Date, viewerZone: string, circuitZone: string): number {
  const viewer = dayKey(value, viewerZone);
  const circuit = dayKey(value, circuitZone);
  if (viewer === circuit) return 0;
  const difference = Date.parse(`${viewer}T00:00:00Z`) - Date.parse(`${circuit}T00:00:00Z`);
  return Math.round(difference / 86_400_000);
}

/** Group chronologically by the viewer's calendar day. */
export function groupByDay<T extends HasStart>(items: T[], timeZone: string): DayGroup<T>[] {
  const buckets = new Map<DayKey, T[]>();
  const sorted = [...items].sort(
    (a, b) => toDate(a.startsAtUtc).getTime() - toDate(b.startsAtUtc).getTime(),
  );

  for (const item of sorted) {
    const key = dayKey(item.startsAtUtc, timeZone);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(item);
    else buckets.set(key, [item]);
  }

  return [...buckets.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, groupItems]) => ({
      key,
      heading: formatDayHeading(key, timeZone),
      shortHeading: formatShortDay(key),
      items: groupItems,
    }));
}

export interface Countdown {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
  totalMs: number;
  isPast: boolean;
}

export function countdown(target: string | Date, from: Date = new Date()): Countdown {
  const totalMs = toDate(target).getTime() - from.getTime();
  const clamped = Math.max(0, totalMs);
  return {
    days: Math.floor(clamped / 86_400_000),
    hours: Math.floor((clamped % 86_400_000) / 3_600_000),
    minutes: Math.floor((clamped % 3_600_000) / 60_000),
    seconds: Math.floor((clamped % 60_000) / 1000),
    totalMs,
    isPast: totalMs <= 0,
  };
}

export function formatCountdown(value: Countdown): string {
  if (value.isPast) return "now";
  if (value.days > 0) return `${value.days}d ${value.hours}h`;
  if (value.hours > 0) return `${value.hours}h ${String(value.minutes).padStart(2, "0")}m`;
  return `${value.minutes}m ${String(value.seconds).padStart(2, "0")}s`;
}

/**
 * How long a session runs when its source never said.
 *
 * Not every organiser publishes an end time - MotoGP publishes none at all for
 * races, and WEC publishes none for practice or qualifying - so something has
 * to be assumed to answer "is this on right now". A single flat guess used to
 * serve that, and two hours was wrong in both directions: it kept a 45-minute
 * Grand Prix marked live for over an hour after the flag, and would have
 * dropped a 6-hour endurance race four hours early.
 *
 * These are medians of the sessions where the end *is* published, measured
 * across every series on the site rather than picked by feel. They err a little
 * long on purpose: showing a session as live shortly after it finished is a
 * smaller failure than hiding one that is still running, which is the entire
 * reason someone opened the page.
 *
 * Endurance racing is the deliberate exception and needs no entry here: WEC
 * publishes a real end for every race, so no race ever falls back to this.
 */
const ASSUMED_MINUTES: Record<string, number> = {
  practice: 60,
  qualifying: 45,
  sprint_qualifying: 45,
  sprint: 45,
  race: 90,
  warmup: 20,
  shakedown: 60,
  stage: 30,
  test: 240,
  other: 60,
};

const FALLBACK_MINUTES = 60;

export function assumedDurationMinutes(sessionType?: string | null): number {
  if (!sessionType) return FALLBACK_MINUTES;
  return ASSUMED_MINUTES[sessionType] ?? FALLBACK_MINUTES;
}

export interface HasSpan {
  startsAtUtc: string | Date;
  endsAtUtc?: string | Date | null;
  sessionType?: string | null;
}

/**
 * When a session finishes, published or assumed.
 *
 * The single place that answers this. It is needed by the board, by the
 * calendar export and by anything asking whether a session is running, and
 * three separate answers is how they drift apart.
 */
export function sessionEnd(session: HasSpan): Date {
  const start = toDate(session.startsAtUtc);
  if (session.endsAtUtc) {
    const end = toDate(session.endsAtUtc);
    // A stored end at or before the start carries no information. Normalisation
    // strips these, but a row written before that rule existed can still exist.
    if (end.getTime() > start.getTime()) return end;
  }
  return new Date(start.getTime() + assumedDurationMinutes(session.sessionType) * 60_000);
}

/** True while the session is running: after the start, before the end. */
export function isLive(
  session: HasSpan & { status?: string },
  now: Date = new Date(),
): boolean {
  if (session.status === "cancelled") return false;
  const start = toDate(session.startsAtUtc).getTime();
  return now.getTime() >= start && now.getTime() <= sessionEnd(session).getTime();
}

/** A series is stale if it has not scraped successfully in 48 hours. */
export const STALE_AFTER_MS = 48 * 3_600_000;

export function isStale(lastSuccessfulScrape: string | Date | null, now: Date = new Date()): boolean {
  if (!lastSuccessfulScrape) return true;
  return now.getTime() - toDate(lastSuccessfulScrape).getTime() > STALE_AFTER_MS;
}
