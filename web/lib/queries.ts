/**
 * Read queries.
 *
 * The web app only reads. Everything it needs comes from a small number of
 * joins, so these are written as one shaped row type per view rather than as
 * generic helpers.
 */

import { and, asc, eq, gte, inArray, isNull, lte, or, sql } from "drizzle-orm";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";

import { categories, events, series, sessions, venues } from "./schema.ts";

const connectionString = process.env.DATABASE_URL;

if (!connectionString) {
  throw new Error("DATABASE_URL is not set");
}

// One pooled client per server instance, cached on globalThis so Next.js dev
// hot-reloads reuse it instead of opening a fresh pool on every edit - which
// otherwise leaks connections until Supabase's session pooler (a hard cap of
// 15 clients) starts rejecting with EMAXCONNSESSION. `max` is deliberately
// small: the pooler is the shared resource, not this process.
const globalForDb = globalThis as unknown as {
  pgClient?: ReturnType<typeof postgres>;
};

const client =
  globalForDb.pgClient ?? postgres(connectionString, { prepare: false, max: 3 });

if (process.env.NODE_ENV !== "production") {
  globalForDb.pgClient = client;
}

export const db = drizzle(client);

export interface SessionRow {
  id: number;
  displayName: string;
  sessionType: string;
  sequence: number;
  startsAtUtc: Date;
  endsAtUtc: Date | null;
  timeStatus: string;
  startsAtPrecision: string;
  status: string;
  icsUid: string;
  icsSequence: number;
  sourceUrl: string | null;
  categoryCode: string;
  categoryShortName: string;
  seriesCode: string;
  seriesShortName: string;
  accentColor: string;
  lastSuccessfulScrape: Date | null;
  eventSlug: string;
  eventName: string;
  season: number;
  venueSlug: string;
  venueName: string;
  venueCity: string | null;
  venueCountry: string;
  circuitTimezone: string;
  sessionTimezone: string | null;
}

const sessionSelection = {
  id: sessions.id,
  displayName: sessions.displayName,
  sessionType: sessions.sessionType,
  sequence: sessions.sequence,
  startsAtUtc: sessions.startsAtUtc,
  endsAtUtc: sessions.endsAtUtc,
  timeStatus: sessions.timeStatus,
  startsAtPrecision: sessions.startsAtPrecision,
  status: sessions.status,
  icsUid: sessions.icsUid,
  icsSequence: sessions.icsSequence,
  sourceUrl: sessions.sourceUrl,
  categoryCode: categories.code,
  categoryShortName: categories.shortName,
  seriesCode: series.code,
  seriesShortName: series.shortName,
  accentColor: series.accentColor,
  lastSuccessfulScrape: series.lastSuccessfulScrape,
  eventSlug: events.slug,
  eventName: events.name,
  season: events.season,
  venueSlug: venues.slug,
  venueName: venues.name,
  venueCity: venues.city,
  venueCountry: venues.countryCode,
  circuitTimezone: venues.ianaTimezone,
  sessionTimezone: sessions.ianaTimezone,
};

function baseQuery() {
  return db
    .select(sessionSelection)
    .from(sessions)
    .innerJoin(events, eq(events.id, sessions.eventId))
    .innerJoin(series, eq(series.id, events.seriesId))
    .innerJoin(categories, eq(categories.id, sessions.categoryId))
    .innerJoin(venues, eq(venues.id, events.venueId));
}

/** Retired rows stay in the table for the audit trail but never render. */
const visible = and(isNull(sessions.retiredAt), isNull(events.retiredAt), eq(series.isActive, true));

function seriesFilter(seriesCodes: string[]) {
  return seriesCodes.length > 0 ? inArray(series.code, seriesCodes) : undefined;
}

/** Anything running right now, by start/end rather than by a stored flag. */
export async function getLiveSessions(seriesCodes: string[] = [], now = new Date()) {
  const moment = now.toISOString();
  return baseQuery()
    .where(
      and(
        visible,
        seriesFilter(seriesCodes),
        lte(sessions.startsAtUtc, now),
        or(
          gte(sessions.endsAtUtc, now),
          and(
            isNull(sessions.endsAtUtc),
            // A source that gives no end time: assume two hours. Written as one
            // sql fragment with an explicit cast, because a raw fragment gives
            // Drizzle no column type to infer the parameter from.
            sql`${sessions.startsAtUtc} + interval '2 hours' >= ${moment}::timestamptz`,
          ),
        ),
      ),
    )
    .orderBy(asc(sessions.startsAtUtc));  
}

export async function getUpcomingSessions(
  seriesCodes: string[] = [],
  limit = 40,
  now = new Date(),
) {
  return baseQuery()
    .where(and(visible, seriesFilter(seriesCodes), gte(sessions.startsAtUtc, now)))
    .orderBy(asc(sessions.startsAtUtc))
    .limit(limit);
}

/**
 * Everything happening in the next `days`, which is what "this weekend" means
 * in practice - a fixed Friday-to-Sunday window would miss Thursday rally
 * shakedowns and Saturday-night ovals.
 */
export async function getSessionsInWindow(
  seriesCodes: string[] = [],
  days = 5,
  now = new Date(),
) {
  const until = new Date(now.getTime() + days * 86_400_000);
  return baseQuery()
    .where(
      and(
        visible,
        seriesFilter(seriesCodes),
        gte(sessions.startsAtUtc, new Date(now.getTime() - 6 * 3_600_000)),
        lte(sessions.startsAtUtc, until),
      ),
    )
    .orderBy(asc(sessions.startsAtUtc));
}

/**
 * Is there any visible session starting after `when`? Used by the home page to
 * decide whether a "Load more" control has anything left to reveal.
 */
export async function hasSessionsAfter(
  seriesCodes: string[] = [],
  when = new Date(),
) {
  const rows = await baseQuery()
    .where(and(visible, seriesFilter(seriesCodes), gte(sessions.startsAtUtc, when)))
    .limit(1);
  return rows.length > 0;
}

export async function getWeekend(seriesCode: string, season: number, slug: string) {
  const rows = await baseQuery()
    .where(
      and(
        isNull(sessions.retiredAt),
        isNull(events.retiredAt),
        eq(series.code, seriesCode),
        eq(events.season, season),
        eq(events.slug, slug),
      ),
    )
    .orderBy(asc(sessions.startsAtUtc), asc(categories.sortOrder), asc(sessions.sequence));

  if (rows.length === 0) return null;
  return { event: rows[0], sessions: rows };
}

export async function getSeasonEvents(seriesCodes: string[] = [], season: number) {
  return db
    .select({
      id: events.id,
      slug: events.slug,
      name: events.name,
      roundNumber: events.roundNumber,
      season: events.season,
      startsAtUtc: events.startsAtUtc,
      endsAtUtc: events.endsAtUtc,
      status: events.status,
      detailLevel: events.detailLevel,
      seriesCode: series.code,
      seriesShortName: series.shortName,
      accentColor: series.accentColor,
      venueName: venues.name,
      venueCountry: venues.countryCode,
      circuitTimezone: venues.ianaTimezone,
    })
    .from(events)
    .innerJoin(series, eq(series.id, events.seriesId))
    .innerJoin(venues, eq(venues.id, events.venueId))
    .where(
      and(
        isNull(events.retiredAt),
        eq(events.season, season),
        seriesCodes.length > 0 ? inArray(series.code, seriesCodes) : undefined,
      ),
    )
    .orderBy(asc(events.startsAtUtc));
}

export async function getAllSeries() {
  return db
    .select({
      code: series.code,
      name: series.name,
      shortName: series.shortName,
      accentColor: series.accentColor,
      lastSuccessfulScrape: series.lastSuccessfulScrape,
    })
    .from(series)
    .where(eq(series.isActive, true))
    .orderBy(asc(series.sortOrder));
}

/** Sessions for the calendar feed: upcoming only, plus a short look-back. */
export async function getCalendarSessions(
  seriesCodes: string[],
  categoryCodes: string[],
  now = new Date(),
) {
  const from = new Date(now.getTime() - 7 * 86_400_000);

  // "f1.f2+motogp" means the F2 category *or* everything in MotoGP. The two
  // token kinds are alternatives; ANDing them would return nothing.
  const bySeries = seriesCodes.length > 0 ? inArray(series.code, seriesCodes) : undefined;
  const byCategory = categoryCodes.length > 0 ? inArray(categories.code, categoryCodes) : undefined;
  const selection = bySeries && byCategory ? or(bySeries, byCategory) : (bySeries ?? byCategory);

  return baseQuery()
    .where(and(visible, gte(sessions.startsAtUtc, from), selection))
    .orderBy(asc(sessions.startsAtUtc));
}
