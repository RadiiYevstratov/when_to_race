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
      // The card images the Instagram job publishes have to stay fetchable.
      // Instagram does not accept an upload - it fetches the image from this
      // URL - and a blanket Disallow on /api/ is exactly the kind of rule that
      // would break posting months later with no obvious cause. They are kept
      // out of search by an X-Robots-Tag: noindex on the response instead,
      // which only works if crawling is permitted in the first place.
      allow: ["/", "/api/social/card/"],
      // Operational only, behind basic auth, and nothing a search result should
      // ever point at.
      disallow: ["/admin", "/api/"],
    },
    // Advertising the sitemap here is what actually gets it discovered:
    // submitting it in Search Console only makes the status visible.
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
