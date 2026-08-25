/**
 * Drizzle schema for the read side.
 *
 * db/migrations/0001_init.sql is the single source of truth. This file mirrors
 * it; it does not define it. If the two ever disagree, the SQL is right.
 */

import {
  boolean,
  doublePrecision,
  index,
  integer,
  pgEnum,
  pgTable,
  serial,
  text,
  timestamp,
  uniqueIndex,
} from "drizzle-orm/pg-core";

export const eventStatus = pgEnum("event_status", [
  "scheduled",
  "in_progress",
  "completed",
  "cancelled",
  "postponed",
]);

export const sessionStatus = pgEnum("session_status", [
  "scheduled",
  "live",
  "finished",
  "cancelled",
  "delayed",
]);

export const sessionType = pgEnum("session_type", [
  "practice",
  "qualifying",
  "sprint_qualifying",
  "sprint",
  "race",
  "warmup",
  "shakedown",
  "stage",
  "test",
  "other",
]);

export const timeStatus = pgEnum("time_status", ["confirmed", "provisional", "tbc"]);
export const timePrecision = pgEnum("time_precision", ["exact", "hour", "day"]);

export const series = pgTable("series", {
  id: serial("id").primaryKey(),
  code: text("code").notNull().unique(),
  name: text("name").notNull(),
  shortName: text("short_name").notNull(),
  accentColor: text("accent_color").notNull(),
  sortOrder: integer("sort_order").notNull().default(100),
  isActive: boolean("is_active").notNull().default(true),
  lastSuccessfulScrape: timestamp("last_successful_scrape", { withTimezone: true }),
});

export const categories = pgTable(
  "categories",
  {
    id: serial("id").primaryKey(),
    seriesId: integer("series_id")
      .notNull()
      .references(() => series.id),
    code: text("code").notNull(),
    name: text("name").notNull(),
    shortName: text("short_name").notNull(),
    isHeadline: boolean("is_headline").notNull().default(false),
    sortOrder: integer("sort_order").notNull().default(100),
  },
  (table) => ({
    seriesCode: uniqueIndex("categories_series_code").on(table.seriesId, table.code),
  }),
);

export const venues = pgTable("venues", {
  id: serial("id").primaryKey(),
  slug: text("slug").notNull().unique(),
  name: text("name").notNull(),
  countryCode: text("country_code").notNull(),
  city: text("city"),
  ianaTimezone: text("iana_timezone").notNull(),
  latitude: doublePrecision("latitude"),
  longitude: doublePrecision("longitude"),
});

export const events = pgTable(
  "events",
  {
    id: serial("id").primaryKey(),
    seriesId: integer("series_id")
      .notNull()
      .references(() => series.id),
    season: integer("season").notNull(),
    roundNumber: integer("round_number"),
    slug: text("slug").notNull(),
    name: text("name").notNull(),
    officialName: text("official_name"),
    venueId: integer("venue_id")
      .notNull()
      .references(() => venues.id),
    startsAtUtc: timestamp("starts_at_utc", { withTimezone: true }).notNull(),
    endsAtUtc: timestamp("ends_at_utc", { withTimezone: true }).notNull(),
    status: eventStatus("status").notNull().default("scheduled"),
    detailLevel: text("detail_level").notNull().default("full"),
    sourceUrl: text("source_url"),
    lastSeenAt: timestamp("last_seen_at", { withTimezone: true }).notNull(),
    retiredAt: timestamp("retired_at", { withTimezone: true }),
  },
  (table) => ({
    naturalKey: uniqueIndex("events_natural_key").on(table.seriesId, table.season, table.slug),
    upcoming: index("events_upcoming").on(table.startsAtUtc),
  }),
);

export const sessions = pgTable(
  "sessions",
  {
    id: serial("id").primaryKey(),
    eventId: integer("event_id")
      .notNull()
      .references(() => events.id),
    categoryId: integer("category_id")
      .notNull()
      .references(() => categories.id),
    sessionType: sessionType("session_type").notNull(),
    displayName: text("display_name").notNull(),
    sequence: integer("sequence").notNull(),
    startsAtUtc: timestamp("starts_at_utc", { withTimezone: true }).notNull(),
    endsAtUtc: timestamp("ends_at_utc", { withTimezone: true }),
    scheduledDurationMinutes: integer("scheduled_duration_minutes"),
    timeStatus: timeStatus("time_status").notNull().default("confirmed"),
    startsAtPrecision: timePrecision("starts_at_precision").notNull().default("exact"),
    status: sessionStatus("status").notNull().default("scheduled"),
    ianaTimezone: text("iana_timezone"),
    icsUid: text("ics_uid").notNull(),
    icsSequence: integer("ics_sequence").notNull().default(0),
    sourceUrl: text("source_url"),
    lastSeenAt: timestamp("last_seen_at", { withTimezone: true }).notNull(),
    retiredAt: timestamp("retired_at", { withTimezone: true }),
  },
  (table) => ({
    naturalKey: uniqueIndex("sessions_natural_key").on(
      table.eventId,
      table.categoryId,
      table.sessionType,
      table.sequence,
    ),
    startsAt: index("sessions_starts_at").on(table.startsAtUtc),
  }),
);

export const scrapeRuns = pgTable("scrape_runs", {
  id: serial("id").primaryKey(),
  seriesId: integer("series_id")
    .notNull()
    .references(() => series.id),
  startedAt: timestamp("started_at", { withTimezone: true }).notNull(),
  finishedAt: timestamp("finished_at", { withTimezone: true }),
  status: text("status").notNull(),
  recordsFound: integer("records_found").notNull().default(0),
  recordsChanged: integer("records_changed").notNull().default(0),
  errorMessage: text("error_message"),
});
