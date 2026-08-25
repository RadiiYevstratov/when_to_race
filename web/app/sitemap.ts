import type { MetadataRoute } from "next";

import { getSeasonEvents } from "../lib/queries.ts";
import { SITE_URL } from "../lib/site.ts";

/**
 * Generated per request rather than at build time.
 *
 * The event list comes from the database, and the build deliberately does not
 * require database credentials (see lib/queries.ts). Requesting it live also
 * means a newly scraped round appears in the sitemap without a redeploy.
 */
export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const season = new Date().getUTCFullYear();

  const staticPages: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, changeFrequency: "hourly", priority: 1 },
    { url: `${SITE_URL}/calendar`, changeFrequency: "daily", priority: 0.8 },
    { url: `${SITE_URL}/subscribe`, changeFrequency: "monthly", priority: 0.5 },
  ];

  let weekends: MetadataRoute.Sitemap = [];
  try {
    const events = await getSeasonEvents([], season);
    weekends = events.map((event) => ({
      url: `${SITE_URL}/weekend/${event.seriesCode}/${event.season}/${event.slug}`,
      lastModified: event.endsAtUtc ?? undefined,
      changeFrequency: "daily" as const,
      priority: 0.7,
    }));
  } catch {
    // A sitemap missing its event pages is far better than a 500 that tells
    // search engines the whole site is broken.
  }

  return [...staticPages, ...weekends];
}
