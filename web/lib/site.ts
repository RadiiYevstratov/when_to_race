/**
 * The public origin, used for canonical URLs, Open Graph and the sitemap.
 *
 * NEXT_PUBLIC_SITE_URL is baked in at build time. The fallback keeps local
 * development and any preview deploy working rather than emitting links to a
 * domain that is not the one being viewed.
 */
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"
).replace(/\/$/, "");
