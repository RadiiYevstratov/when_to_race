/**
 * Frontend logic tests. Run with:
 *   node --experimental-strip-types --test web/tests/
 *
 * These cover the two things that would silently give users wrong information:
 * a session grouped under the wrong day, and a calendar export that duplicates
 * instead of updating.
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  countdown,
  dayKey,
  dayShift,
  formatCountdown,
  formatTime,
  groupByDay,
  isLive,
  isStale,
  isValidTimeZone,
  offsetLabel,
  resolveTimeZone,
} from "../lib/time.ts";

import { buildCalendar, escapeText, foldLine, parseSelection } from "../lib/ics.ts";

// Melbourne, 8 March 2026, 15:00 AEDT (+11) = 04:00 UTC.
const MELBOURNE_RACE = "2026-03-08T04:00:00Z";
// Monza, 6 September 2026, 15:00 CEST (+2) = 13:00 UTC.
const MONZA_RACE = "2026-09-06T13:00:00Z";
// Las Vegas, 21 November 2026, 22:00 PST (-8) = 06:00 UTC on the 22nd.
const VEGAS_RACE = "2026-11-22T06:00:00Z";

describe("day grouping", () => {
  test("groups under the viewer's calendar day, not the circuit's", () => {
    assert.equal(dayKey(MELBOURNE_RACE, "Australia/Melbourne"), "2026-03-08");
    assert.equal(dayKey(MELBOURNE_RACE, "America/Los_Angeles"), "2026-03-07");
    assert.equal(dayKey(MELBOURNE_RACE, "Europe/Bratislava"), "2026-03-08");
  });

  test("a late-night race is the next day in Europe", () => {
    assert.equal(dayKey(VEGAS_RACE, "America/Los_Angeles"), "2026-11-21");
    assert.equal(dayKey(VEGAS_RACE, "Europe/Bratislava"), "2026-11-22");
  });

  test("dayShift reports the offset the UI marks with +1 / -1", () => {
    assert.equal(dayShift(MELBOURNE_RACE, "America/Los_Angeles", "Australia/Melbourne"), -1);
    assert.equal(dayShift(VEGAS_RACE, "Europe/Bratislava", "America/Los_Angeles"), 1);
    assert.equal(dayShift(MONZA_RACE, "Europe/Bratislava", "Europe/Rome"), 0);
  });

  test("groups are chronological and headings match the viewer's day", () => {
    const sessions = [
      { startsAtUtc: MONZA_RACE, name: "Race" },
      { startsAtUtc: "2026-09-04T11:30:00Z", name: "Practice 1" },
      { startsAtUtc: "2026-09-05T14:00:00Z", name: "Qualifying" },
    ];
    const groups = groupByDay(sessions, "Europe/Bratislava");
    assert.deepEqual(
      groups.map((group) => group.key),
      ["2026-09-04", "2026-09-05", "2026-09-06"],
    );
    assert.equal(groups[0].items[0].name, "Practice 1");
    assert.match(groups[2].heading, /Sunday/);
  });

  test("a session that crosses midnight for the viewer lands in the later group", () => {
    const groups = groupByDay(
      [{ startsAtUtc: VEGAS_RACE }, { startsAtUtc: "2026-11-21T04:00:00Z" }],
      "Europe/Bratislava",
    );
    assert.deepEqual(
      groups.map((group) => group.key),
      ["2026-11-21", "2026-11-22"],
    );
  });
});

describe("time formatting", () => {
  test("24-hour clock in the viewer's zone", () => {
    assert.equal(formatTime(MONZA_RACE, "Europe/Bratislava"), "15:00");
    assert.equal(formatTime(MONZA_RACE, "Europe/London"), "14:00");
    assert.equal(formatTime(MONZA_RACE, "UTC"), "13:00");
  });

  test("midnight is 00:00, never 24:00", () => {
    assert.equal(formatTime("2026-09-06T22:00:00Z", "Europe/Rome"), "00:00");
  });

  test("non-hour offsets survive", () => {
    assert.equal(formatTime("2026-10-04T09:30:00Z", "Asia/Kolkata"), "15:00");
    assert.equal(formatTime("2026-10-04T09:30:00Z", "Australia/Adelaide"), "20:00");
  });

  test("offset labels are shown so the zone is never ambiguous", () => {
    assert.equal(offsetLabel(MONZA_RACE, "Europe/Bratislava"), "UTC+2");
    assert.equal(offsetLabel("2026-01-06T13:00:00Z", "Europe/Bratislava"), "UTC+1");
    assert.equal(offsetLabel(MONZA_RACE, "Asia/Kolkata"), "UTC+5:30");
  });

  test("a zone that does not observe DST reads the same all year", () => {
    assert.equal(offsetLabel("2026-01-15T20:00:00Z", "America/Phoenix"), "UTC-7");
    assert.equal(offsetLabel("2026-07-15T20:00:00Z", "America/Phoenix"), "UTC-7");
  });
});

describe("timezone resolution", () => {
  test("a valid override wins", () => {
    assert.equal(resolveTimeZone("Asia/Tokyo"), "Asia/Tokyo");
  });

  test("an invalid override falls back rather than throwing", () => {
    assert.ok(isValidTimeZone(resolveTimeZone("Mars/Olympus")));
    assert.ok(isValidTimeZone(resolveTimeZone(null)));
  });
});

describe("live and staleness", () => {
  const session = { startsAtUtc: MONZA_RACE, endsAtUtc: "2026-09-06T15:00:00Z" };

  test("live only between start and end", () => {
    assert.equal(isLive(session, new Date("2026-09-06T14:00:00Z")), true);
    assert.equal(isLive(session, new Date("2026-09-06T12:59:00Z")), false);
    assert.equal(isLive(session, new Date("2026-09-06T15:01:00Z")), false);
  });

  test("a cancelled session is never live", () => {
    assert.equal(
      isLive({ ...session, status: "cancelled" }, new Date("2026-09-06T14:00:00Z")),
      false,
    );
  });

  test("staleness trips after 48 hours", () => {
    const now = new Date("2026-09-06T00:00:00Z");
    assert.equal(isStale("2026-09-05T12:00:00Z", now), false);
    assert.equal(isStale("2026-09-03T00:00:00Z", now), true);
    assert.equal(isStale(null, now), true);
  });
});

describe("countdown", () => {
  test("counts down and then reads as now", () => {
    const now = new Date("2026-09-06T10:00:00Z");
    assert.equal(formatCountdown(countdown(MONZA_RACE, now)), "3h 00m");
    assert.equal(formatCountdown(countdown("2026-09-06T09:00:00Z", now)), "now");
    assert.equal(formatCountdown(countdown("2026-09-09T10:00:00Z", now)), "3d 0h");
  });

  test("seconds appear inside the final hour", () => {
    const value = countdown("2026-09-06T10:05:30Z", new Date("2026-09-06T10:00:00Z"));
    assert.equal(formatCountdown(value), "5m 30s");
  });
});

describe("calendar export", () => {
  const session = {
    icsUid: "f1-2026-gran-premio-d-italia-f1-race@motorsport-schedule",
    icsSequence: 0,
    displayName: "Race",
    seriesShortName: "Formula 1",
    categoryShortName: "F1",
    eventName: "Gran Premio d'Italia",
    venueName: "Autodromo Nazionale Monza, Monza",
    startsAtUtc: MONZA_RACE,
    endsAtUtc: "2026-09-06T15:00:00Z",
  };
  const now = new Date("2026-08-01T00:00:00Z");

  test("produces a well-formed calendar", () => {
    const output = buildCalendar([session], { calendarName: "Formula 1", now });
    assert.ok(output.startsWith("BEGIN:VCALENDAR\r\n"));
    assert.ok(output.endsWith("END:VCALENDAR\r\n"));
    assert.ok(output.includes("DTSTART:20260906T130000Z"));
    assert.ok(output.includes("DTEND:20260906T150000Z"));
    assert.equal(output.split("\r\n").filter((line) => line === "BEGIN:VEVENT").length, 1);
  });

  test("UID is stable and SEQUENCE carries through, so updates replace rather than duplicate", () => {
    const first = buildCalendar([session], { calendarName: "F1", now });
    const moved = buildCalendar(
      [{ ...session, icsSequence: 1, startsAtUtc: "2026-09-06T12:00:00Z" }],
      { calendarName: "F1", now },
    );
    const uid = `UID:${session.icsUid}`;
    assert.ok(first.includes(uid) && moved.includes(uid));
    assert.ok(first.includes("SEQUENCE:0"));
    assert.ok(moved.includes("SEQUENCE:1"));
  });

  test("provisional times are marked TENTATIVE and say so in the description", () => {
    const output = buildCalendar([{ ...session, timeStatus: "provisional" }], {
      calendarName: "F1",
      now,
    });
    assert.ok(output.includes("STATUS:TENTATIVE"));
    assert.ok(output.includes("provisional"));
  });

  test("a cancelled session exports as cancelled", () => {
    const output = buildCalendar([{ ...session, status: "cancelled" }], {
      calendarName: "F1",
      now,
    });
    assert.ok(output.includes("STATUS:CANCELLED"));
  });

  test("a session with no end time still gets one", () => {
    const output = buildCalendar([{ ...session, endsAtUtc: null }], {
      calendarName: "F1",
      now,
    });
    assert.ok(output.includes("DTEND:20260906T150000Z"));
  });

  test("text is escaped", () => {
    assert.equal(escapeText("Monza, Italy"), "Monza\\, Italy");
    assert.equal(escapeText("a;b"), "a\\;b");
    assert.equal(escapeText("line\nline"), "line\\nline");
  });

  test("long lines fold at 75 octets and count bytes, not characters", () => {
    const folded = foldLine(`SUMMARY:${"é".repeat(100)}`);
    const lines = folded.split("\r\n");
    assert.ok(lines.length > 1);
    for (const line of lines) {
      assert.ok(new TextEncoder().encode(line).length <= 75, `line too long: ${line.length}`);
    }
    assert.ok(lines.slice(1).every((line) => line.startsWith(" ")));
  });

  test("no line in a real calendar exceeds the limit", () => {
    const output = buildCalendar(
      [{ ...session, eventName: "Gran Premio d'Italia ".repeat(6) }],
      { calendarName: "Everything", now },
    );
    for (const line of output.split("\r\n")) {
      assert.ok(new TextEncoder().encode(line).length <= 75);
    }
  });
});

describe("calendar selection tokens", () => {
  test("all series", () => {
    assert.deepEqual(parseSelection("all.ics"), { seriesCodes: [], categoryCodes: [] });
    assert.deepEqual(parseSelection(""), { seriesCodes: [], categoryCodes: [] });
  });

  test("one and several series", () => {
    assert.deepEqual(parseSelection("f1.ics"), { seriesCodes: ["f1"], categoryCodes: [] });
    assert.deepEqual(parseSelection("f1+motogp.ics"), {
      seriesCodes: ["f1", "motogp"],
      categoryCodes: [],
    });
  });

  test("a single category within a series", () => {
    assert.deepEqual(parseSelection("f1.f2+motogp.ics"), {
      seriesCodes: ["motogp"],
      categoryCodes: ["f2"],
    });
  });
});
