/**
 * JSON-LD for search engines.
 *
 * This is the one place where the product's whole value - machine-readable
 * facts about when things happen and where - can be handed to a search engine
 * directly rather than left to be inferred from rendered text. A weekend page
 * describes itself as a SportsEvent whose subEvents are the individual
 * sessions, which is what lets a result show "Qualifying, Sat 15:00" instead of
 * a bare link.
 *
 * Two rules hold throughout:
 *
 *   - Nothing is asserted that is not known. No organizer, no offers, no
 *     performers. A confident wrong claim in structured data is worse than a
 *     missing one, because it is repeated by anything that consumes it.
 *   - Times carry the circuit's own offset, not "Z". See toLocalIso.
 *
 * Builders are pure and take plain rows so they can be tested without a
 * database or a renderer.
 */

import { SITE_URL } from "./site.ts";
import { toDate, toLocalIso } from "./time.ts";

/** Only the fields the markup needs, so tests can build a row by hand. */
export interface StructuredSession {
  displayName: string;
  categoryShortName: string;
  startsAtUtc: string | Date;
  endsAtUtc: string | Date | null;
  status: string;
}

export interface StructuredEvent {
  eventName: string;
  officialName?: string | null;
  season: number;
  eventSlug: string;
  eventStatus: string;
  seriesCode: string;
  seriesName: string;
  seriesShortName: string;
  venueName: string;
  venueCity: string | null;
  venueCountry: string;
  venueLatitude?: number | null;
  venueLongitude?: number | null;
  circuitTimezone: string;
}

type Json = Record<string, unknown>;

const STATUS_URLS: Record<string, string> = {
  scheduled: "https://schema.org/EventScheduled",
  cancelled: "https://schema.org/EventCancelled",
  postponed: "https://schema.org/EventPostponed",
  rescheduled: "https://schema.org/EventRescheduled",
};

function eventStatusUrl(status: string): string {
  return STATUS_URLS[status] ?? STATUS_URLS.scheduled;
}

/**
 * The canonical URL for a season.
 *
 * The current season lives at /calendar with no query, because that is the URL
 * people link to and the one the page declares as canonical. Archived seasons
 * carry the parameter. Breadcrumbs and the sitemap both come through here so
 * they cannot point somewhere the page disowns.
 */
export function seasonPath(season: number, currentSeason: number): string {
  return season === currentSeason ? "/calendar" : `/calendar?season=${season}`;
}

export function weekendPath(event: {
  seriesCode: string;
  season: number;
  eventSlug: string;
}): string {
  return `/weekend/${event.seriesCode}/${event.season}/${event.eventSlug}`;
}

/**
 * The circuit, as a Place.
 *
 * Coordinates are included because every venue has them and they disambiguate
 * circuits that share a city name with something else entirely - "Phillip
 * Island" is a town before it is a race track.
 */
function place(event: StructuredEvent): Json {
  const value: Json = {
    "@type": "Place",
    name: event.venueName,
    address: {
      "@type": "PostalAddress",
      ...(event.venueCity ? { addressLocality: event.venueCity } : {}),
      addressCountry: event.venueCountry,
    },
  };

  if (typeof event.venueLatitude === "number" && typeof event.venueLongitude === "number") {
    value.geo = {
      "@type": "GeoCoordinates",
      latitude: event.venueLatitude,
      longitude: event.venueLongitude,
    };
  }

  return value;
}

/**
 * A single session as a subEvent.
 *
 * Sessions with no end time are left open rather than given a guessed one. The
 * board assumes two hours when it needs to draw something, but a guess written
 * into structured data would be republished as fact.
 */
function subEvent(
  session: StructuredSession,
  event: StructuredEvent,
  url: string,
): Json {
  const zone = event.circuitTimezone;
  const value: Json = {
    "@type": "SportsEvent",
    name: `${event.eventName} - ${session.categoryShortName} ${session.displayName}`,
    startDate: toLocalIso(session.startsAtUtc, zone),
    eventStatus: eventStatusUrl(session.status),
    eventAttendanceMode: "https://schema.org/OfflineEventAttendanceMode",
    location: place(event),
    url,
  };
  if (session.endsAtUtc) value.endDate = toLocalIso(session.endsAtUtc, zone);
  return value;
}

/**
 * The weekend itself.
 *
 * Start and end come from the sessions rather than from the event's own stored
 * bounds, so the markup can never disagree with the times printed on the page.
 */
export function sportsEventJsonLd(
  event: StructuredEvent,
  sessions: StructuredSession[],
  description: string,
): Json {
  const path = weekendPath(event);
  const url = `${SITE_URL}${path}`;
  const zone = event.circuitTimezone;

  const ordered = [...sessions].sort(
    (a, b) => toDate(a.startsAtUtc).getTime() - toDate(b.startsAtUtc).getTime(),
  );

  const first = ordered[0];
  const endTimes = ordered
    .map((session) => toDate(session.endsAtUtc ?? session.startsAtUtc).getTime())
    .filter((time) => Number.isFinite(time));

  const value: Json = {
    "@context": "https://schema.org",
    "@type": "SportsEvent",
    "@id": url,
    name: `${event.eventName} ${event.season}`,
    description,
    url,
    sport: "Motorsport",
    eventStatus: eventStatusUrl(event.eventStatus),
    eventAttendanceMode: "https://schema.org/OfflineEventAttendanceMode",
    location: place(event),
    image: `${SITE_URL}/opengraph-image`,
    // The championship this round belongs to, which is how people search for it
    // ("f1 monza") even though the round has its own name.
    superEvent: {
      "@type": "SportsEvent",
      name: `${event.seriesName} ${event.season}`,
      sport: "Motorsport",
    },
  };

  if (event.officialName && event.officialName !== event.eventName) {
    value.alternateName = event.officialName;
  }

  if (first) {
    value.startDate = toLocalIso(first.startsAtUtc, zone);
    if (endTimes.length > 0) {
      value.endDate = toLocalIso(new Date(Math.max(...endTimes)), zone);
    }
    value.subEvent = ordered.map((session) => subEvent(session, event, url));
  }

  return value;
}

export interface Crumb {
  name: string;
  path: string;
}

/** Breadcrumbs, mirroring the trail the page actually renders. */
export function breadcrumbJsonLd(crumbs: Crumb[]): Json {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((crumb, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: crumb.name,
      item: `${SITE_URL}${crumb.path}`,
    })),
  };
}

/**
 * Site-level identity, emitted once from the root layout.
 *
 * No SearchAction: there is no site search to point one at, and describing one
 * that does not exist is the kind of claim this file exists to avoid.
 */
export function websiteJsonLd(description: string): Json {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    "@id": `${SITE_URL}/#website`,
    name: "ON TRACK",
    alternateName: "ON TRACK motorsport schedule",
    url: `${SITE_URL}/`,
    description,
    inLanguage: "en",
    publisher: {
      "@type": "Organization",
      name: "ON TRACK",
      url: `${SITE_URL}/`,
      logo: {
        "@type": "ImageObject",
        url: `${SITE_URL}/icon-512.png`,
        width: 512,
        height: 512,
      },
    },
  };
}

/** The season calendar, as an ordered list of rounds. */
export function seasonListJsonLd(
  season: number,
  rounds: { name: string; seriesCode: string; season: number; slug: string }[],
): Json {
  return {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: `Motorsport calendar ${season}`,
    numberOfItems: rounds.length,
    itemListOrder: "https://schema.org/ItemListOrderAscending",
    itemListElement: rounds.map((round, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: round.name,
      url: `${SITE_URL}${weekendPath({
        seriesCode: round.seriesCode,
        season: round.season,
        eventSlug: round.slug,
      })}`,
    })),
  };
}
