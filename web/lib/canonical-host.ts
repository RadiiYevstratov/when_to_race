/**
 * Deciding whether a request's Host is ours, and where it should go.
 *
 * Split out of middleware.ts so the rule can be tested. The Host header is
 * attacker-controlled and this builds a redirect target out of it, which is a
 * combination worth pinning with tests rather than trusting to review: an
 * earlier version answered `Host: www.evil.example` with a 308 to
 * `https://evil.example/`, our own server lending its name to a redirect
 * somewhere else entirely.
 */

/** The host the site is served at, read from the origin it was built with. */
export function canonicalHost(siteUrl: string | undefined | null): string | null {
  if (!siteUrl) return null;
  try {
    return new URL(siteUrl).host.toLowerCase();
  } catch {
    return null;
  }
}

export interface RedirectRequest {
  host: string | null | undefined;
  forwardedProto?: string | null;
  pathname: string;
  search?: string;
}

/**
 * Where a www request should be sent, or null to leave it alone.
 *
 * Null covers every case that is not "our own domain, spelled with www":
 * a host that is not ours, a missing host, and the apex itself. Passing the
 * request through costs nothing, whereas inventing a destination from an
 * untrusted header is the whole problem.
 */
export function apexRedirectTarget(
  request: RedirectRequest,
  expectedHost: string | null,
): string | null {
  const host = request.host?.toLowerCase();
  if (!host?.startsWith("www.")) return null;

  const stripped = host.slice(4);
  if (!expectedHost || stripped !== expectedHost) return null;

  // https unless the proxy explicitly says the hop was plain http; emitting
  // http:// by default would cost every visitor a needless extra redirect.
  const proto = request.forwardedProto === "http" ? "http" : "https";
  return `${proto}://${stripped}${request.pathname}${request.search ?? ""}`;
}
