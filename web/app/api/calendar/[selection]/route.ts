/**
 * Subscribable calendar feed.
 *
 * GET /api/calendar/f1.ics
 * GET /api/calendar/f1+motogp.ics
 * GET /api/calendar/all.ics
 *
 * Subscribed as webcal://, this is what makes a rescheduled session move in
 * someone's phone calendar instead of appearing twice. That depends entirely on
 * stable UIDs and an incrementing SEQUENCE, both of which come from the
 * database rather than being derived here.
 */

import { NextResponse } from "next/server";

import { buildCalendar, parseSelection, type CalendarSession } from "../../../../lib/ics.ts";
import { getCalendarSessions } from "../../../../lib/queries.ts";

export const dynamic = "force-dynamic";

const CACHE_SECONDS = 1800; // calendars move slowly; clients poll aggressively

function calendarName(seriesCodes: string[], categoryCodes: string[]): string {
  const parts = [...seriesCodes, ...categoryCodes];
  if (parts.length === 0) return "Motorsport - all series";
  return `Motorsport - ${parts.map((code) => code.toUpperCase()).join(", ")}`;
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ selection: string }> },
) {
  const { selection } = await params;
  const { seriesCodes, categoryCodes } = parseSelection(selection);

  // Guard against a pathological request enumerating the whole database.
  if (seriesCodes.length + categoryCodes.length > 20) {
    return new NextResponse("Too many series in one selection", { status: 400 });
  }

  // A selection that named something, none of which survived parsing, is a
  // mistake rather than a request for everything. Silently widening it would
  // subscribe someone to ten championships because they mistyped one - and a
  // calendar subscription is checked once and then trusted for a season.
  const asked = decodeURIComponent(selection).replace(/\.ics$/i, "").trim();
  const wantsEverything = asked === "" || asked.toLowerCase() === "all";
  if (!wantsEverything && seriesCodes.length + categoryCodes.length === 0) {
    return new NextResponse(
      "Unrecognised selection. Use a series code, a series.class code, or 'all'.",
      { status: 400 },
    );
  }

  let rows;
  try {
    rows = await getCalendarSessions(seriesCodes, categoryCodes);
  } catch (error) {
    console.error("calendar feed failed", error);
    return new NextResponse("Calendar temporarily unavailable", { status: 503 });
  }

  if (rows.length === 0 && (seriesCodes.length > 0 || categoryCodes.length > 0)) {
    return new NextResponse("No sessions for that selection", { status: 404 });
  }

  const sessions: CalendarSession[] = rows.map((row) => ({
    icsUid: row.icsUid,
    icsSequence: row.icsSequence,
    displayName: row.displayName,
    // Without this a session whose source gave no end time gets the generic
    // assumed length rather than the one for its kind - a 90-minute race
    // arriving in someone's calendar as an hour.
    sessionType: row.sessionType,
    seriesCode: row.seriesCode,
    seriesShortName: row.seriesShortName,
    categoryShortName: row.categoryShortName,
    eventName: row.eventName,
    venueName: [row.venueName, row.venueCity].filter(Boolean).join(", "),
    startsAtUtc: row.startsAtUtc,
    endsAtUtc: row.endsAtUtc,
    status: row.status,
    timeStatus: row.timeStatus,
    sourceUrl: row.sourceUrl,
  }));

  const body = buildCalendar(sessions, {
    calendarName: calendarName(seriesCodes, categoryCodes),
  });

  return new NextResponse(body, {
    status: 200,
    headers: {
      "Content-Type": "text/calendar; charset=utf-8",
      "Content-Disposition": `inline; filename="${selection.replace(/[^a-z0-9+._-]/gi, "") || "motorsport"}"`,
      "Cache-Control": `public, max-age=${CACHE_SECONDS}, s-maxage=${CACHE_SECONDS}`,
    },
  });
}
