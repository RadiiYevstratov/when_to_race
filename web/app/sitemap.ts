import type { MetadataRoute } from "next";

import { getPublishedSeasons, getSeasonEvents } from "../lib/queries.ts";
import { SITE_URL } from "../lib/site.ts";
import { seasonPath } from "../lib/structured-data.ts";

/**
 * Generated per request rather than at build time.
 *
 * The event list comes from the database, and the build deliberately does not
 * require database credentials (see lib/queries.ts). Requesting it live also
 * means a newly scraped round appears in the sitemap without a redeploy.
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

    const perSeason = await Promise.all(
      seasons.map((season) => getSeasonEvents([], season)),
    );

    const weekends: MetadataRoute.Sitemap = perSeason.flat().map((event) => ({
      url: `${SITE_URL}/weekend/${event.seriesCode}/${event.season}/${event.slug}`,
      // A past round is settled history; the current season is still moving.
      changeFrequency: event.season < thisYear ? ("yearly" as const) : ("daily" as const),
      priority: event.season === thisYear ? 0.7 : 0.3,
    }));

    return [...staticPages, ...weekends];
  } catch {
    // A sitemap missing its event pages is far better than a 500 that tells
    // search engines the whole site is broken.
    return staticPages;
  }
}
