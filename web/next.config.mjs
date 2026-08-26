/** @type {import('next').NextConfig} */

const isDev = process.env.NODE_ENV !== "production";

/**
 * Response headers.
 *
 * The site serves public schedule data and takes no input beyond a timezone
 * cookie, so the threat model is narrow: the realistic risks are being framed
 * by someone else's page, having a response sniffed into a different content
 * type, and leaking a visitor's path to sites we link out to.
 *
 * The policy is written for what this app actually loads, which was measured
 * rather than assumed: a loaded page makes zero external requests. next/font
 * self-hosts Archivo and IBM Plex Mono under /_next/static, so there is no font
 * CDN to allow and `default-src 'self'` covers everything real.
 *
 * Two allowances are deliberate:
 *
 *   - 'unsafe-inline' for styles, because the board sets a class's colour with
 *     an inline style attribute. Removing it would mean a nonce on every row.
 *   - 'unsafe-inline' for scripts, which Next's hydration bootstrap requires.
 *
 * Development needs two more, and only in development: React's dev build uses
 * eval() to reconstruct stack traces, and hot reload opens a WebSocket. Both
 * are genuinely absent from a production build, so shipping them would weaken
 * the live policy to buy nothing.
 */
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self' data:",
  "img-src 'self' data: blob:",
  `connect-src 'self'${isDev ? " ws: wss:" : ""}`,
  "form-action 'self'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  // Only meaningful over TLS, and it would break a plain-http dev server.
  ...(isDev ? [] : ["upgrade-insecure-requests"]),
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  // Belt and braces with frame-ancestors, for anything that predates CSP.
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Send the origin to other sites, the full path to our own: enough for a
  // referrer report, not enough to hand a circuit page URL to a third party.
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // Nothing here uses any of these, and saying so is cheaper than being asked.
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
  },
];

// Two years, preloadable. Announcing that on a plain-http dev server would be
// a good way to lock a developer out of localhost for two years.
if (!isDev) {
  securityHeaders.push({
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  });
}

const nextConfig = {
  // The framework version is not a secret worth keeping, but it is a free hint
  // to anyone scanning for a known CVE.
  poweredByHeader: false,

  experimental: {
    // Schedule pages are server-rendered per request so the viewer's timezone
    // cookie is honoured on first paint.
    staleTimes: { dynamic: 0 },
  },

  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      {
        // The calendar feed is subscribed to by calendar clients from any
        // origin, and is public read-only data.
        source: "/api/calendar/:selection",
        headers: [{ key: "Access-Control-Allow-Origin", value: "*" }],
      },
    ];
  },
};

export default nextConfig;
