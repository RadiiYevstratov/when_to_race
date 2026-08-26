/**
 * Every read query, executed against a real database.
 *
 * The unit tests cover logic that can be reasoned about without a server. This
 * covers the part that cannot: whether the SQL the ORM generates is actually
 * accepted by Postgres, and whether it returns the shape the pages destructure.
 *
 * That gap has bitten this project twice already - an ambiguous `id` in a raw
 * fragment that typechecked and then failed at runtime, and an ORM upgrade
 * where nothing in the type system would have shown a change in generated SQL.
 *
 * Skipped when DATABASE_URL is unset, so CI without a database still runs the
 * rest of the suite rather than failing on an absent dependency.
 */

import { test, describe, before, after } from "node:test";
import assert from "node:assert/strict";

const HAS_DB = Boolean(process.env.DATABASE_URL);
const skip = HAS_DB ? false : "DATABASE_URL is not set";

type Queries = typeof import("../lib/queries.ts");
let q: Queries;

describe("read queries execute", { skip }, () => {
  before(async () => {
    q = await import("../lib/queries.ts");
  });

  // An idle pooled socket holds the event loop open and the run never ends.
  after(async () => {
    await q.closeDb();
  });

  const EVERYTHING = { seriesCodes: [], categoryCodes: [] };
  const NARROW = { seriesCodes: ["motogp"], categoryCodes: ["f2"] };

  test("board queries run, filtered and unfiltered", async () => {
    for (const selection of [EVERYTHING, NARROW]) {
      assert.ok(Array.isArray(await q.getLiveSessions(selection)));
      assert.ok(Array.isArray(await q.getUpcomingSessions(selection, 5)));
      assert.ok(Array.isArray(await q.getSessionsInWindow(selection, 7)));
      assert.equal(typeof (await q.hasSessionsAfter(selection)), "boolean");
    }
  });

  test("a session row carries every field the board reads", async () => {
    const [row] = await q.getUpcomingSessions(EVERYTHING, 1);
    if (!row) return; // an empty calendar is legitimate out of season
    for (const field of [
      "id",
      "displayName",
      "sessionType",
      "startsAtUtc",
      "categoryCode",
      "categoryShortName",
      "categoryAccentColor",
      "seriesCode",
      "seriesName",
      "eventSlug",
      "season",
      "venueSlug",
      "venueName",
      "circuitTimezone",
    ]) {
      assert.ok(field in row, `missing ${field}`);
    }
    // The board reads this straight into a style attribute.
    assert.match(row.categoryAccentColor, /^#[0-9A-Fa-f]{6}$/);
  });

  test("season, catalogue and index queries run", async () => {
    const seasons = await q.getPublishedSeasons();
    assert.ok(Array.isArray(seasons));

    const season = seasons[0] ?? new Date().getUTCFullYear();
    assert.ok(Array.isArray(await q.getSeasonEvents(EVERYTHING, season)));
    assert.ok(Array.isArray(await q.getSeasonEvents(NARROW, season)));

    const catalogue = await q.getSeriesCatalogue();
    assert.ok(catalogue.length > 0, "no active series");
    for (const item of catalogue) {
      assert.ok(Array.isArray(item.categories));
    }

    assert.ok(Array.isArray(await q.getRunnableCategoryCodes()));
    assert.ok(Array.isArray(await q.getVisitedVenueSlugs()));
    assert.ok(Array.isArray(await q.getCircuitIndex()));
  });

  test("the calendar feed query runs for both token kinds", async () => {
    assert.ok(Array.isArray(await q.getCalendarSessions([], [])));
    assert.ok(Array.isArray(await q.getCalendarSessions(["f1"], ["moto3"])));
  });

  test("a real weekend loads with its sessions", async () => {
    const [event] = await q.getSeasonEvents(EVERYTHING, (await q.getPublishedSeasons())[0]);
    if (!event) return;

    const weekend = await q.getWeekend(event.seriesCode, event.season, event.slug);
    assert.ok(weekend, `no weekend for ${event.seriesCode}/${event.slug}`);
    assert.ok(weekend.sessions.length > 0);

    const adjacent = await q.getAdjacentEvents(
      event.seriesCode,
      event.season,
      new Date(event.startsAtUtc),
    );
    assert.ok("previous" in adjacent && "next" in adjacent);
  });

  test("a real class and a real circuit load", async () => {
    const [code] = await q.getRunnableCategoryCodes();
    if (code) {
      const category = await q.getCategoryByCode(code);
      assert.ok(category, `${code} runs but has no page`);
      assert.ok(category.sessionCount > 0);
      assert.ok(
        Array.isArray(await q.getVenuesForCategory(code, (await q.getPublishedSeasons())[0])),
      );
    }

    const [slug] = await q.getVisitedVenueSlugs();
    if (slug) {
      const venue = await q.getVenueBySlug(slug);
      assert.ok(venue, `${slug} is raced at but has no page`);
      const events = await q.getEventsAtVenue(slug);
      assert.ok(events.length > 0);
      // The circuit page renders these directly.
      assert.ok(Array.isArray(events[0].classes));
      assert.ok(events[0].classes.length > 0);
    }
  });

  test("unknown identifiers return null rather than throwing", async () => {
    assert.equal(await q.getCategoryByCode("no-such-class"), null);
    assert.equal(await q.getVenueBySlug("no-such-circuit"), null);
    assert.equal(await q.getWeekend("no-such-series", 1999, "no-such-event"), null);
  });

  test("hostile input is parameterised, not interpolated", async () => {
    // If any of these reached Postgres as SQL rather than as a value, the
    // query would error or - far worse - succeed at something unintended.
    const nasty = "'; drop table sessions; --";
    assert.equal(await q.getVenueBySlug(nasty), null);
    assert.equal(await q.getCategoryByCode(nasty), null);
    assert.ok(Array.isArray(await q.getCalendarSessions([nasty], [nasty])));
    assert.ok(
      Array.isArray(
        await q.getSeasonEvents({ seriesCodes: [nasty], categoryCodes: [nasty] }, 2026),
      ),
    );
    // Still standing.
    assert.ok((await q.getSeriesCatalogue()).length > 0);
  });
});
