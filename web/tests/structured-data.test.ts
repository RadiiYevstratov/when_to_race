/**
 * Structured data tests.
 *
 * Markup fails silently: nothing on the page looks wrong, the rich result just
 * never appears, or worse, appears with the wrong time. These cover the two
 * things most likely to go wrong unnoticed - an offset that does not match the
 * circuit's clock, and a claim asserted without the data to back it.
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  breadcrumbJsonLd,
  seasonListJsonLd,
  sportsEventJsonLd,
  websiteJsonLd,
  type StructuredEvent,
  type StructuredSession,
} from "../lib/structured-data.ts";
import { toLocalIso } from "../lib/time.ts";

const MONZA: StructuredEvent = {
  eventName: "Italian GP",
  officialName: "Formula 1 Gran Premio d'Italia 2026",
  season: 2026,
  eventSlug: "italian-gp",
  eventStatus: "scheduled",
  seriesCode: "f1",
  seriesName: "FIA Formula One World Championship",
  seriesShortName: "Formula 1",
  venueName: "Autodromo Nazionale Monza",
  venueCity: "Monza",
  venueCountry: "IT",
  venueLatitude: 45.6156,
  venueLongitude: 9.2811,
  circuitTimezone: "Europe/Rome",
};

// Monza, 6 September 2026, 15:00 CEST (+2) = 13:00 UTC.
const RACE: StructuredSession = {
  displayName: "Race",
  categoryShortName: "F1",
  startsAtUtc: "2026-09-06T13:00:00Z",
  endsAtUtc: "2026-09-06T15:00:00Z",
  status: "scheduled",
};

const PRACTICE: StructuredSession = {
  displayName: "Practice 1",
  categoryShortName: "F1",
  startsAtUtc: "2026-09-04T11:30:00Z",
  endsAtUtc: null,
  status: "scheduled",
};

describe("local ISO timestamps", () => {
  test("carries the circuit's offset, not Z", () => {
    assert.equal(toLocalIso(RACE.startsAtUtc, "Europe/Rome"), "2026-09-06T15:00:00+02:00");
  });

  test("follows daylight saving rather than a fixed offset", () => {
    // Same circuit, February: CET (+1) rather than CEST (+2).
    assert.equal(toLocalIso("2026-02-06T13:00:00Z", "Europe/Rome"), "2026-02-06T14:00:00+01:00");
  });

  test("handles a half-hour zone", () => {
    assert.equal(toLocalIso("2026-03-08T04:00:00Z", "Asia/Kolkata"), "2026-03-08T09:30:00+05:30");
  });

  test("handles a negative offset that crosses the date line backwards", () => {
    // Las Vegas, 22:00 on 21 November local, which is 06:00 UTC on the 22nd.
    assert.equal(
      toLocalIso("2026-11-22T06:00:00Z", "America/Los_Angeles"),
      "2026-11-21T22:00:00-08:00",
    );
  });

  test("midnight stays on its own day", () => {
    // Le Mans runs through midnight; hour 24 of the previous day would move it.
    assert.equal(toLocalIso("2026-06-13T22:00:00Z", "Europe/Paris"), "2026-06-14T00:00:00+02:00");
  });
});

describe("weekend markup", () => {
  const data = sportsEventJsonLd(MONZA, [RACE, PRACTICE], "A description.");

  test("is a SportsEvent spanning the whole weekend", () => {
    assert.equal(data["@type"], "SportsEvent");
    assert.equal(data.name, "Italian GP 2026");
    // Sessions arrive unsorted; the span must still run first start to last end.
    assert.equal(data.startDate, "2026-09-04T13:30:00+02:00");
    assert.equal(data.endDate, "2026-09-06T17:00:00+02:00");
  });

  test("lists every session as a subEvent, in order", () => {
    const subEvents = data.subEvent as Record<string, unknown>[];
    assert.equal(subEvents.length, 2);
    assert.equal(subEvents[0].name, "Italian GP - F1 Practice 1");
    assert.equal(subEvents[1].name, "Italian GP - F1 Race");
  });

  test("leaves a session with no end time open rather than guessing one", () => {
    const subEvents = data.subEvent as Record<string, unknown>[];
    assert.ok(!("endDate" in subEvents[0]), "practice has no known end, so none is claimed");
    assert.equal(subEvents[1].endDate, "2026-09-06T17:00:00+02:00");
  });

  test("locates the circuit precisely", () => {
    const location = data.location as Record<string, unknown>;
    const address = location.address as Record<string, unknown>;
    assert.equal(address.addressLocality, "Monza");
    assert.equal(address.addressCountry, "IT");
    assert.deepEqual(location.geo, {
      "@type": "GeoCoordinates",
      latitude: 45.6156,
      longitude: 9.2811,
    });
  });

  test("omits geo entirely when coordinates are missing", () => {
    const withoutGeo = sportsEventJsonLd(
      { ...MONZA, venueLatitude: null, venueLongitude: null },
      [RACE],
      "A description.",
    );
    const location = withoutGeo.location as Record<string, unknown>;
    assert.ok(!("geo" in location));
  });

  test("carries the official name only when it adds something", () => {
    assert.equal(data.alternateName, "Formula 1 Gran Premio d'Italia 2026");
    const plain = sportsEventJsonLd({ ...MONZA, officialName: "Italian GP" }, [RACE], "d");
    assert.ok(!("alternateName" in plain));
  });

  test("maps a cancelled round to the cancelled status", () => {
    const cancelled = sportsEventJsonLd({ ...MONZA, eventStatus: "cancelled" }, [RACE], "d");
    assert.equal(cancelled.eventStatus, "https://schema.org/EventCancelled");
  });

  test("asserts nothing it cannot know", () => {
    for (const invented of ["offers", "organizer", "performer", "competitor"]) {
      assert.ok(!(invented in data), `${invented} must not be invented`);
    }
  });

  test("survives an event with no sessions at all", () => {
    const empty = sportsEventJsonLd(MONZA, [], "d");
    assert.ok(!("startDate" in empty));
    assert.ok(!("subEvent" in empty));
  });
});

describe("supporting markup", () => {
  test("breadcrumbs are absolute and numbered from one", () => {
    const data = breadcrumbJsonLd([
      { name: "ON TRACK", path: "/" },
      { name: "Season 2026", path: "/calendar?season=2026" },
    ]);
    const items = data.itemListElement as Record<string, unknown>[];
    assert.equal(items[0].position, 1);
    assert.equal(items[1].position, 2);
    assert.ok(String(items[1].item).endsWith("/calendar?season=2026"));
    assert.ok(String(items[0].item).startsWith("http"));
  });

  test("the season list points at real weekend URLs", () => {
    const data = seasonListJsonLd(2026, [
      { name: "Italian GP", seriesCode: "f1", season: 2026, slug: "italian-gp" },
    ]);
    assert.equal(data.numberOfItems, 1);
    const items = data.itemListElement as Record<string, unknown>[];
    assert.ok(String(items[0].url).endsWith("/weekend/f1/2026/italian-gp"));
  });

  test("the site block claims no search feature that does not exist", () => {
    const data = websiteJsonLd("A description.");
    assert.equal(data["@type"], "WebSite");
    assert.ok(!("potentialAction" in data));
  });
});
