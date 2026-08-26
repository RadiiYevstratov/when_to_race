/**
 * Read queries.
 *
 * The web app only reads. Everything it needs comes from a small number of
 * joins, so these are written as one shaped row type per view rather than as
 * generic helpers.
 */

import { and, asc, desc, eq, gt, gte, inArray, isNull, lt, lte, or, sql } from "drizzle-orm";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";

import { categories, events, series, sessions, venues } from "./schema.ts";
import { type Selection } from "./selection.ts";

// One pooled client per server instance, cached on globalThis so Next.js dev
// hot-reloads reuse it instead of opening a fresh pool on every edit - which
// otherwise leaks connections until Supabase's session pooler (a hard cap of
// 15 clients) starts rejecting with EMAXCONNSESSION. `max` is deliberately
// small: the pooler is the shared resource, not this process.
const globalForDb = globalThis as unknown as {
  pgClient?: ReturnType<typeof postgres>;
  drizzleDb?: ReturnType<typeof drizzle>;
};

/**
 * Connect on first query rather than on import.
 *
 * `next build` evaluates every route module to collect page data, so throwing
 * at import time made the build itself require database credentials - it failed
 * on any host that does not expose runtime secrets to the build step. Nothing
 * here is needed at build time: every page is force-dynamic and postgres.js
 * opens its sockets lazily anyway. Deferring means a missing DATABASE_URL is
 * reported when a request actually needs the database, which is both the honest
 * moment and the one where the message is useful.
 */
function getDb(): ReturnType<typeof drizzle> {
  if (globalForDb.drizzleDb) return globalForDb.drizzleDb;

  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) {
    throw new Error("DATABASE_URL is not set");
  }

  const client =
    globalForDb.pgClient ?? postgres(connectionString, { prepare: false, max: 3 });
  const instance = drizzle(client);

  if (process.env.NODE_ENV !== "production") {
    globalForDb.pgClient = client;
  }
  globalForDb.drizzleDb = instance;
  return instance;
}

// Exported as a lazy proxy so callers keep using `db.select(...)` unchanged.
// Methods are bound to the real instance, which Drizzle's builders rely on.
export const db = new Proxy({} as ReturnType<typeof drizzle>, {
  get(_target, property) {
    const instance = getDb() as unknown as Record<string | symbol, unknown>;
    const value = instance[property];
    return typeof value === "function" ? value.bind(instance) : value;
  },
});

/** No filter at all: the default, and what most visitors want. */
const EMPTY: Selection = { seriesCodes: [], categoryCodes: [] };

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
  categorySortOrder: number;
  /** The class's own colour, falling back to the championship's. */
  categoryAccentColor: string;
  seriesCode: string;
  seriesName: string;
  seriesShortName: string;
  accentColor: string;
  lastSuccessfulScrape: Date | null;
  eventSlug: string;
  eventName: string;
  officialName: string | null;
  eventStatus: string;
  season: number;
  venueSlug: string;
  venueName: string;
  venueCity: string | null;
  venueCountry: string;
  venueLatitude: number | null;
  venueLongitude: number | null;
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
  categorySortOrder: categories.sortOrder,
  // A class with no colour of its own wears the championship's. Resolved here
  // rather than in the component so every surface inherits identically.
  categoryAccentColor: sql<string>`coalesce(${categories.accentColor}, ${series.accentColor})`,
  seriesCode: series.code,
  seriesName: series.name,
  seriesShortName: series.shortName,
  accentColor: series.accentColor,
  lastSuccessfulScrape: series.lastSuccessfulScrape,
  eventSlug: events.slug,
  eventName: events.name,
  officialName: events.officialName,
  eventStatus: events.status,
  season: events.season,
  venueSlug: venues.slug,
  venueName: venues.name,
  venueCity: venues.city,
  venueCountry: venues.countryCode,
  venueLatitude: venues.latitude,
  venueLongitude: venues.longitude,
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

/**
 * Whole series OR individual categories.
 *
 * The two kinds of token are alternatives, never both: "f1.f2+motogp" means
 * Formula 2 *or* everything in MotoGP, and ANDing them would return nothing.
 * An empty selection filters nothing, which is how "everything" is expressed.
 */
function selectionFilter(selection: Selection) {
  const bySeries =
    selection.seriesCodes.length > 0 ? inArray(series.code, selection.seriesCodes) : undefined;
  const byCategory =
    selection.categoryCodes.length > 0
      ? inArray(categories.code, selection.categoryCodes)
      : undefined;
  if (bySeries && byCategory) return or(bySeries, byCategory);
  return bySeries ?? byCategory;
}

/** Anything running right now, by start/end rather than by a stored flag. */
export async function getLiveSessions(
  selection: Selection = EMPTY,
  now = new Date(),
) {
  const moment = now.toISOString();
  return baseQuery()
    .where(
      and(
        visible,
        selectionFilter(selection),
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
  selection: Selection = EMPTY,
  limit = 40,
  now = new Date(),
) {
  return baseQuery()
    .where(and(visible, selectionFilter(selection), gte(sessions.startsAtUtc, now)))
    .orderBy(asc(sessions.startsAtUtc))
    .limit(limit);
}

/**
 * Everything happening in the next `days`, which is what "this weekend" means
 * in practice - a fixed Friday-to-Sunday window would miss Thursday rally
 * shakedowns and Saturday-night ovals.
 */
export async function getSessionsInWindow(
  selection: Selection = EMPTY,
  days = 5,
  now = new Date(),
) {
  const until = new Date(now.getTime() + days * 86_400_000);
  return baseQuery()
    .where(
      and(
        visible,
        selectionFilter(selection),
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
  selection: Selection = EMPTY,
  when = new Date(),
) {
  const rows = await baseQuery()
    .where(and(visible, selectionFilter(selection), gte(sessions.startsAtUtc, when)))
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

export async function getSeasonEvents(selection: Selection = EMPTY, season: number) {
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
      venueSlug: venues.slug,
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
        seasonSelectionFilter(selection),
      ),
    )
    .orderBy(asc(events.startsAtUtc));
}

/**
 * One class, by its own code.
 *
 * Returns null for a code that exists but has never run - MotoE and
 * WorldSSP300 are seeded and discontinued, and a page for one would be an
 * empty schedule under a confident heading.
 */
export async function getCategoryByCode(code: string) {
  const rows = await db
    .select({
      code: categories.code,
      name: categories.name,
      shortName: categories.shortName,
      isHeadline: categories.isHeadline,
      accentColor: sql<string>`coalesce(${categories.accentColor}, ${series.accentColor})`,
      seriesCode: series.code,
      seriesName: series.name,
      seriesShortName: series.shortName,
      lastSuccessfulScrape: series.lastSuccessfulScrape,
      sessionCount: sql<number>`count(${sessions.id})`.mapWith(Number),
    })
    .from(categories)
    .innerJoin(series, eq(series.id, categories.seriesId))
    .leftJoin(
      sessions,
      and(eq(sessions.categoryId, categories.id), isNull(sessions.retiredAt)),
    )
    .where(and(eq(categories.code, code), eq(series.isActive, true)))
    .groupBy(
      categories.code,
      categories.name,
      categories.shortName,
      categories.isHeadline,
      categories.accentColor,
      series.code,
      series.name,
      series.shortName,
      series.accentColor,
      series.lastSuccessfulScrape,
    )
    .limit(1);

  const row = rows[0];
  return row && row.sessionCount > 0 ? row : null;
}

/** Every class that has run, for the sitemap and for cross-links. */
export async function getRunnableCategoryCodes(): Promise<string[]> {
  const rows = await db
    .selectDistinct({ code: categories.code })
    .from(categories)
    .innerJoin(series, eq(series.id, categories.seriesId))
    .innerJoin(
      sessions,
      and(eq(sessions.categoryId, categories.id), isNull(sessions.retiredAt)),
    )
    .where(eq(series.isActive, true))
    .orderBy(asc(categories.code));
  return rows.map((row) => row.code);
}

/**
 * One circuit, and whether anything is scheduled there.
 *
 * A venue with no visible event gets no page: the registry holds circuits that
 * no championship currently visits, and a page for one would say nothing.
 */
export async function getVenueBySlug(slug: string) {
  const rows = await db
    .select({
      slug: venues.slug,
      name: venues.name,
      city: venues.city,
      countryCode: venues.countryCode,
      ianaTimezone: venues.ianaTimezone,
      latitude: venues.latitude,
      longitude: venues.longitude,
      eventCount: sql<number>`count(${events.id})`.mapWith(Number),
    })
    .from(venues)
    .leftJoin(events, and(eq(events.venueId, venues.id), isNull(events.retiredAt)))
    .where(eq(venues.slug, slug))
    .groupBy(
      venues.slug,
      venues.name,
      venues.city,
      venues.countryCode,
      venues.ianaTimezone,
      venues.latitude,
      venues.longitude,
    )
    .limit(1);

  const row = rows[0];
  return row && row.eventCount > 0 ? row : null;
}

/**
 * Every circuit that has a round, with who races there.
 *
 * Ordered by name rather than by date: this is an index someone scans looking
 * for a place they know, not a schedule.
 */
export async function getCircuitIndex() {
  const rows = await db
    .select({
      slug: venues.slug,
      name: venues.name,
      city: venues.city,
      countryCode: venues.countryCode,
      seriesCode: series.code,
      seriesShortName: series.shortName,
      accentColor: series.accentColor,
      seriesSortOrder: series.sortOrder,
      nextStart: sql<Date | null>`min(${events.startsAtUtc})`,
    })
    .from(venues)
    .innerJoin(events, and(eq(events.venueId, venues.id), isNull(events.retiredAt)))
    .innerJoin(series, and(eq(series.id, events.seriesId), eq(series.isActive, true)))
    .groupBy(
      venues.slug,
      venues.name,
      venues.city,
      venues.countryCode,
      series.code,
      series.shortName,
      series.accentColor,
      series.sortOrder,
    )
    .orderBy(asc(venues.name), asc(series.sortOrder));

  const grouped = new Map<
    string,
    {
      slug: string;
      name: string;
      city: string | null;
      countryCode: string;
      series: { code: string; shortName: string; accentColor: string }[];
    }
  >();

  for (const row of rows) {
    let circuit = grouped.get(row.slug);
    if (!circuit) {
      circuit = {
        slug: row.slug,
        name: row.name,
        city: row.city,
        countryCode: row.countryCode,
        series: [],
      };
      grouped.set(row.slug, circuit);
    }
    circuit.series.push({
      code: row.seriesCode,
      shortName: row.seriesShortName,
      accentColor: row.accentColor,
    });
  }

  return [...grouped.values()];
}

/** Every circuit something actually races at, for the sitemap. */
export async function getVisitedVenueSlugs(): Promise<string[]> {
  const rows = await db
    .selectDistinct({ slug: venues.slug })
    .from(venues)
    .innerJoin(events, and(eq(events.venueId, venues.id), isNull(events.retiredAt)))
    .orderBy(asc(venues.slug));
  return rows.map((row) => row.slug);
}

/**
 * Every round at one circuit, whichever championship it belongs to.
 *
 * The point of a circuit page: someone searching "Monza session times" wants
 * the weekend, not one series' slice of it.
 */
export async function getEventsAtVenue(slug: string) {
  return db
    .select({
      slug: events.slug,
      name: events.name,
      season: events.season,
      roundNumber: events.roundNumber,
      startsAtUtc: events.startsAtUtc,
      endsAtUtc: events.endsAtUtc,
      status: events.status,
      seriesCode: series.code,
      seriesShortName: series.shortName,
      accentColor: series.accentColor,
    })
    .from(events)
    .innerJoin(series, eq(series.id, events.seriesId))
    .innerJoin(venues, eq(venues.id, events.venueId))
    .where(and(isNull(events.retiredAt), eq(venues.slug, slug), eq(series.isActive, true)))
    .orderBy(asc(events.startsAtUtc));
}

/** The circuits one class visits in a season, in calendar order. */
export async function getVenuesForCategory(code: string, season: number) {
  return db
    .selectDistinctOn([events.startsAtUtc], {
      venueSlug: venues.slug,
      venueName: venues.name,
      venueCountry: venues.countryCode,
      eventSlug: events.slug,
      eventName: events.name,
      seriesCode: series.code,
      season: events.season,
      startsAtUtc: events.startsAtUtc,
    })
    .from(sessions)
    .innerJoin(categories, eq(categories.id, sessions.categoryId))
    .innerJoin(events, eq(events.id, sessions.eventId))
    .innerJoin(series, eq(series.id, events.seriesId))
    .innerJoin(venues, eq(venues.id, events.venueId))
    .where(
      and(
        isNull(sessions.retiredAt),
        isNull(events.retiredAt),
        eq(categories.code, code),
        eq(events.season, season),
      ),
    )
    .orderBy(asc(events.startsAtUtc));
}

/** Every season that has published rounds, newest first. */
export async function getPublishedSeasons(): Promise<number[]> {
  const rows = await db
    .selectDistinct({ season: events.season })
    .from(events)
    .where(isNull(events.retiredAt))
    .orderBy(asc(events.season));
  return rows.map((row) => row.season).sort((a, b) => b - a);
}

/**
 * The rounds either side of this one, within the same series and season.
 *
 * Partly navigation and partly reach: without these, a weekend page is only
 * linked from the season calendar, so a crawler has to go back to the top of
 * the site between every round. Adjacent links let it walk the season.
 */
export async function getAdjacentEvents(
  seriesCode: string,
  season: number,
  startsAtUtc: Date,
) {
  const selection = {
    slug: events.slug,
    name: events.name,
    season: events.season,
    seriesCode: series.code,
    startsAtUtc: events.startsAtUtc,
  };

  const base = and(isNull(events.retiredAt), eq(series.code, seriesCode), eq(events.season, season));

  const [previous, next] = await Promise.all([
    db
      .select(selection)
      .from(events)
      .innerJoin(series, eq(series.id, events.seriesId))
      .where(and(base, lt(events.startsAtUtc, startsAtUtc)))
      .orderBy(desc(events.startsAtUtc))
      .limit(1),
    db
      .select(selection)
      .from(events)
      .innerJoin(series, eq(series.id, events.seriesId))
      .where(and(base, gt(events.startsAtUtc, startsAtUtc)))
      .orderBy(asc(events.startsAtUtc))
      .limit(1),
  ]);

  return { previous: previous[0] ?? null, next: next[0] ?? null };
}

/**
 * The same selection, applied to a query that lists events rather than
 * sessions.
 *
 * Categories live on sessions, so a category filter becomes "this event has at
 * least one visible session in one of these categories". The subquery is
 * written as literal SQL with qualified names: Drizzle renders an interpolated
 * column inside a raw fragment as a bare name, and `id` is ambiguous across the
 * four tables joined here.
 */
function seasonSelectionFilter(selection: Selection) {
  const bySeries =
    selection.seriesCodes.length > 0 ? inArray(series.code, selection.seriesCodes) : undefined;

  if (selection.categoryCodes.length === 0) return bySeries;

  const codes = sql.join(
    selection.categoryCodes.map((code) => sql`${code}`),
    sql`, `,
  );
  const byCategory = sql`exists (
    select 1 from sessions s2
    join categories c2 on c2.id = s2.category_id
    where s2.event_id = events.id
      and s2.retired_at is null
      and c2.code in (${codes})
  )`;

  return bySeries ? or(bySeries, byCategory) : byCategory;
}

/**
 * Every series with the categories under it, for the header's filter.
 *
 * `sessionCount` is what tells a category apart from a placeholder: MotoE and
 * WorldSSP300 are seeded but no longer run, and a chip that always yields an
 * empty board reads as a broken filter rather than a discontinued class.
 */
export async function getSeriesCatalogue() {
  const rows = await db
    .select({
      seriesCode: series.code,
      seriesShortName: series.shortName,
      accentColor: series.accentColor,
      lastSuccessfulScrape: series.lastSuccessfulScrape,
      seriesSortOrder: series.sortOrder,
      categoryCode: categories.code,
      categoryShortName: categories.shortName,
      categorySortOrder: categories.sortOrder,
      categoryAccentColor: sql<string>`coalesce(${categories.accentColor}, ${series.accentColor})`,
      sessionCount: sql<number>`count(${sessions.id})`.mapWith(Number),
    })
    .from(series)
    .innerJoin(categories, eq(categories.seriesId, series.id))
    .leftJoin(
      sessions,
      and(eq(sessions.categoryId, categories.id), isNull(sessions.retiredAt)),
    )
    .where(eq(series.isActive, true))
    .groupBy(
      series.code,
      series.shortName,
      series.accentColor,
      series.lastSuccessfulScrape,
      series.sortOrder,
      categories.code,
      categories.shortName,
      categories.sortOrder,
      categories.accentColor,
    )
    .orderBy(asc(series.sortOrder), asc(categories.sortOrder));

  const grouped = new Map<
    string,
    {
      code: string;
      shortName: string;
      accentColor: string;
      lastSuccessfulScrape: Date | null;
      categories: {
        code: string;
        shortName: string;
        accentColor: string;
        sessionCount: number;
      }[];
    }
  >();

  for (const row of rows) {
    let group = grouped.get(row.seriesCode);
    if (!group) {
      group = {
        code: row.seriesCode,
        shortName: row.seriesShortName,
        accentColor: row.accentColor,
        lastSuccessfulScrape: row.lastSuccessfulScrape,
        categories: [],
      };
      grouped.set(row.seriesCode, group);
    }
    group.categories.push({
      code: row.categoryCode,
      shortName: row.categoryShortName,
      accentColor: row.categoryAccentColor,
      sessionCount: row.sessionCount,
    });
  }

  return [...grouped.values()];
}

/** Sessions for the calendar feed: upcoming only, plus a short look-back. */
export async function getCalendarSessions(
  seriesCodes: string[],
  categoryCodes: string[],
  now = new Date(),
) {
  const from = new Date(now.getTime() - 7 * 86_400_000);
  return baseQuery()
    .where(
      and(
        visible,
        gte(sessions.startsAtUtc, from),
        selectionFilter({ seriesCodes, categoryCodes }),
      ),
    )
    .orderBy(asc(sessions.startsAtUtc));
}
