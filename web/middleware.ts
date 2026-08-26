/**
 * Two unrelated jobs, in one file because Next.js allows exactly one middleware.
 *
 *   1. Redirect www to the bare domain. Serving a site at both spellings splits
 *      it into two copies as far as a search engine is concerned. Doing it here
 *      rather than only in DNS means it holds however the host is configured.
 *   2. Guard /admin. The health dashboard is an operational tool, not a product
 *      surface, and a full auth system for one page would be more attack
 *      surface than it removes - but basic auth on its own is a password
 *      oracle, so it is rate limited and it refuses a dangerous configuration.
 */

import { NextResponse, type NextRequest } from "next/server";

import { apexRedirectTarget, canonicalHost } from "./lib/canonical-host.ts";

export const config = {
  // Everything a person can navigate to. Next's own build output and the icon
  // files are excluded: they are never reached by the wrong hostname in a way
  // that matters, and matching them would run this on every asset request.
  matcher: ["/((?!_next/static|_next/image).*)"],
};

/** Failed attempts per client, for the brute-force guard. */
const attempts = new Map<string, { count: number; first: number }>();

const WINDOW_MS = 15 * 60 * 1000;
const MAX_ATTEMPTS = 10;

/**
 * In-memory, and that is a deliberate limit rather than an oversight.
 *
 * One process holds one map, so this slows an attacker per instance rather
 * than globally. For a single-container deployment guarding one operational
 * page that is the right amount of machinery; a shared store would mean adding
 * Redis to the stack to protect a page nobody but the operator visits. If this
 * ever runs multi-instance, that trade needs revisiting.
 */
function tooManyAttempts(key: string): boolean {
  const now = Date.now();
  const record = attempts.get(key);
  if (!record) return false;
  if (now - record.first > WINDOW_MS) {
    attempts.delete(key);
    return false;
  }
  return record.count >= MAX_ATTEMPTS;
}

function recordFailure(key: string): void {
  const now = Date.now();
  const record = attempts.get(key);
  if (!record || now - record.first > WINDOW_MS) {
    attempts.set(key, { count: 1, first: now });
    return;
  }
  record.count += 1;

  // Unbounded growth is its own denial of service. The cap is far above any
  // real number of clients hitting an admin page.
  if (attempts.size > 1000) {
    for (const [existing, value] of attempts) {
      if (now - value.first > WINDOW_MS) attempts.delete(existing);
    }
  }
}

function clientKey(request: NextRequest): string {
  // Behind Cloudflare and Railway, the socket address is a proxy. The left-most
  // forwarded address is the closest thing to the real client available here.
  const forwarded = request.headers.get("x-forwarded-for");
  return forwarded?.split(",")[0]?.trim() || "unknown";
}

function unauthorized() {
  return new NextResponse("Authentication required", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="admin", charset="UTF-8"',
      "Cache-Control": "no-store",
    },
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
 * Refuse a password that is also the database password.
 *
 * Sharing one secret between basic auth and Postgres means the weaker surface
 * hands over the stronger one: guess the admin page and you have the database.
 * Failing closed costs an operational page until one environment variable is
 * changed, which is a far smaller price than the alternative.
 */
function misconfigured(password: string): string | null {
  if (password.length < 12) {
    return "ADMIN_PASSWORD is shorter than 12 characters";
  }
  const databaseUrl = process.env.DATABASE_URL;
  if (databaseUrl && databaseUrl.includes(encodeURIComponent(password))) {
    return "ADMIN_PASSWORD is also the database password";
  }
  if (databaseUrl && databaseUrl.includes(password)) {
    return "ADMIN_PASSWORD is also the database password";
  }
  return null;
}

/** Resolved once: the origin is fixed at build time. */
const CANONICAL_HOST = canonicalHost(process.env.NEXT_PUBLIC_SITE_URL);

/**
 * Send www to the bare domain, once and permanently.
 *
 * The rule itself lives in lib/canonical-host.ts, where it is tested. It has to
 * be a rule rather than a string operation because the Host header is
 * attacker-controlled: stripping "www." from whatever arrives and redirecting
 * there had this server answering `Host: www.evil.example` with a 308 to
 * `https://evil.example/`.
 */
function apexRedirect(request: NextRequest): NextResponse | null {
  const target = apexRedirectTarget(
    {
      host: request.headers.get("host"),
      forwardedProto: request.headers.get("x-forwarded-proto"),
      pathname: request.nextUrl.pathname,
      search: request.nextUrl.search,
    },
    CANONICAL_HOST,
  );
  return target ? NextResponse.redirect(target, 308) : null;
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

  const problem = misconfigured(expectedPassword);
  if (problem) {
    console.error(`admin access refused: ${problem}`);
    return new NextResponse(
      `Admin access is disabled: ${problem}. Set a different ADMIN_PASSWORD.`,
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  const key = clientKey(request);
  if (tooManyAttempts(key)) {
    return new NextResponse("Too many attempts. Try again later.", {
      status: 429,
      headers: { "Retry-After": String(WINDOW_MS / 1000), "Cache-Control": "no-store" },
    });
  }

  const header = request.headers.get("authorization");
  if (!header?.startsWith("Basic ")) return unauthorized();

  let decoded: string;
  try {
    decoded = atob(header.slice(6));
  } catch {
    recordFailure(key);
    return unauthorized();
  }

  const separator = decoded.indexOf(":");
  if (separator === -1) {
    recordFailure(key);
    return unauthorized();
  }

  const user = decoded.slice(0, separator);
  const password = decoded.slice(separator + 1);

  // Both compared every time: short-circuiting on the username would leak
  // whether a username exists.
  const userOk = safeEqual(user, expectedUser);
  const passwordOk = safeEqual(password, expectedPassword);
  if (userOk && passwordOk) {
    attempts.delete(key);
    return NextResponse.next();
  }

  recordFailure(key);
  return unauthorized();
}
