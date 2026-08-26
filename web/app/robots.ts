import type { MetadataRoute } from "next";

import { SITE_URL } from "../lib/site.ts";

/**
 * Cloudflare currently serves a managed robots.txt in front of this one. This
 * exists so the rules travel with the app rather than living only in a
 * dashboard, and so the sitemap is always advertised.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Operational only, behind basic auth, and nothing a search result should
      // ever point at.
      disallow: ["/admin", "/api/"],
    },
    // Advertising the sitemap here is what actually gets it discovered:
    // submitting it in Search Console only makes the status visible.
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
