/**
 * Two unrelated jobs, in one file because Next.js allows exactly one middleware.
 *
 *   1. Redirect www to the bare domain. Serving a site at both spellings splits
 *      it into two copies as far as a search engine is concerned. Doing it here
 *      rather than only in DNS means it holds however the host is configured.
 *   2. Basic auth for /admin. Deliberately minimal - the health dashboard is an
 *      operational tool, not a product surface, and a full auth system for one
 *      page would be more attack surface than it removes.
 */

import { NextResponse, type NextRequest } from "next/server";

export const config = {
  // Everything a person can navigate to. Next's own build output and the icon
  // files are excluded: they are never reached by the wrong hostname in a way
  // that matters, and matching them would run this on every asset request.
  matcher: ["/((?!_next/static|_next/image).*)"],
};

function unauthorized() {
  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="admin", charset="UTF-8"' },
  });
}

/** Comparison in constant time, so a wrong password cannot be found by timing. */
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) {
    difference |= a.charCodeAt(index) ^ b.charCodeAt(index);
  }
  return difference === 0;
}

/**
 * Send www to the bare domain, once and permanently.
 *
 * Only ever strips a leading "www.", so the target can never itself start with
 * one and the redirect cannot loop. The scheme comes from the forwarded header
 * because the app sits behind a proxy that terminates TLS.
 */
function apexRedirect(request: NextRequest): NextResponse | null {
  const host = request.headers.get("host");
  if (!host?.toLowerCase().startsWith("www.")) return null;

  // Built as a string rather than by mutating nextUrl: assigning `protocol` on
  // a cloned URL does not reliably stick, and silently emitting http:// would
  // cost every visitor an extra hop through the TLS redirect.
  const proto = request.headers.get("x-forwarded-proto") ?? "https";
  const { pathname, search } = request.nextUrl;
  return NextResponse.redirect(`${proto}://${host.slice(4)}${pathname}${search}`, 308);
}

export function middleware(request: NextRequest) {
  const redirect = apexRedirect(request);
  if (redirect) return redirect;

  if (!request.nextUrl.pathname.startsWith("/admin")) return NextResponse.next();

  const expectedUser = process.env.ADMIN_USER;
  const expectedPassword = process.env.ADMIN_PASSWORD;

  if (!expectedUser || !expectedPassword) {
    return new NextResponse("Admin access is not configured", { status: 503 });
  }

  const header = request.headers.get("authorization");
  if (!header?.startsWith("Basic ")) return unauthorized();

  let decoded: string;
  try {
    decoded = atob(header.slice(6));
  } catch {
    return unauthorized();
  }

  const separator = decoded.indexOf(":");
  if (separator === -1) return unauthorized();

  const user = decoded.slice(0, separator);
  const password = decoded.slice(separator + 1);

  if (safeEqual(user, expectedUser) && safeEqual(password, expectedPassword)) {
    return NextResponse.next();
  }
  return unauthorized();
}
