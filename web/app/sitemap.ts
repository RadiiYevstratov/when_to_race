import type { MetadataRoute } from "next";

import {
  getPublishedSeasons,
  getRunnableCategoryCodes,
  getSeasonEvents,
  getVisitedVenueSlugs,
} from "../lib/queries.ts";
import { SITE_URL } from "../lib/site.ts";
import { EMPTY_SELECTION } from "../lib/selection.ts";
import { circuitPath, seasonPath, seriesPath } from "../lib/structured-data.ts";

/**
 * Generated per request rather than at build time.
 *
 * The event list comes from the database, and the build deliberately does not
 * require database credentials (see lib/queries.ts). Requesting it live also
 * means a newly scraped round appears in the sitemap without a redeploy.
 *
 * On a database failure this fails rather than shrinking - see the catch at the
 * end for why a truncated sitemap is worse than none.
 *
 * No lastModified anywhere. The obvious candidate, events.updated_at, is
 * touched by every scrape whether or not anything changed, so it would claim
 * the whole site changes four times a day; the previous version used the
 * event's own end date, which is a future timestamp for any upcoming round and
 * not a modification date at all. An absent lastmod is read as "unknown",
 * which is true. A wrong one teaches a crawler to ignore the file.
 */
export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const thisYear = new Date().getUTCFullYear();

  const staticPages: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, changeFrequency: "hourly", priority: 1 },
    { url: `${SITE_URL}/calendar`, changeFrequency: "daily", priority: 0.8 },
    { url: `${SITE_URL}/series`, changeFrequency: "weekly", priority: 0.7 },
    { url: `${SITE_URL}/circuits`, changeFrequency: "weekly", priority: 0.7 },
    { url: `${SITE_URL}/subscribe`, changeFrequency: "monthly", priority: 0.5 },
  ];

  try {
    const seasons = await getPublishedSeasons();

    // Season index pages, so a crawler can reach an archived year at all.
    for (const season of seasons) {
      if (season === thisYear) continue;
      staticPages.push({
        url: `${SITE_URL}${seasonPath(season, thisYear)}`,
        changeFrequency: "yearly",
        priority: 0.4,
      });
    }

    // One page per class and per circuit. Both lists are derived from what
    // has actually run, so a discontinued class or a circuit nothing visits
    // never reaches the sitemap as a page that would render empty.
    const [categoryCodes, venueSlugs] = await Promise.all([
      getRunnableCategoryCodes(),
      getVisitedVenueSlugs(),
    ]);

    for (const code of categoryCodes) {
      staticPages.push({
        url: `${SITE_URL}${seriesPath(code)}`,
        changeFrequency: "daily",
        priority: 0.8,
      });
    }
    for (const slug of venueSlugs) {
      staticPages.push({
        url: `${SITE_URL}${circuitPath(slug)}`,
        changeFrequency: "weekly",
        priority: 0.6,
      });
    }

    const perSeason = await Promise.all(
      // No filter: the sitemap lists every page, whatever a visitor follows.
      seasons.map((season) => getSeasonEvents(EMPTY_SELECTION, season)),
    );

    const weekends: MetadataRoute.Sitemap = perSeason.flat().map((event) => ({
      url: `${SITE_URL}/weekend/${event.seriesCode}/${event.season}/${event.slug}`,
      // A past round is settled history; the current season is still moving.
      changeFrequency: event.season < thisYear ? ("yearly" as const) : ("daily" as const),
      priority: event.season === thisYear ? 0.7 : 0.3,
    }));

    return [...staticPages, ...weekends];
  } catch (error) {
    // Deliberately not degrading to the five static pages here, which is what
    // this used to do. A sitemap that lists five URLs when the site has 126 is
    // not a smaller truth, it is a wrong one: it tells a crawler those are the
    // pages, and the 121 it listed yesterday are withdrawn.
    //
    // Failing is the honest answer. A crawler treats a 5xx on a sitemap as
    // "come back later" and keeps the copy it already has, which is exactly
    // what should happen while a database is briefly unreachable.
    console.error("sitemap unavailable; the database could not be reached", error);
    throw error;
  }
}
