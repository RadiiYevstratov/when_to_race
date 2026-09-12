/**
 * The URLs for one calendar feed.
 *
 * A calendar client subscribes to an absolute webcal:// link, and the origin is
 * only known in the browser unless NEXT_PUBLIC_SITE_URL is set. So a feed
 * renders as a relative path on the server and upgrades once mounted.
 *
 * Hooks, so only client components may call it - which is every caller, since
 * there is nothing to upgrade to on the server.
 */

import { useEffect, useState } from "react";

export interface FeedUrls {
  /** Relative, and therefore safe to render before mount. */
  path: string;
  httpUrl: string;
  /** What a calendar app subscribes to. Falls back to the path until mounted. */
  webcalUrl: string;
}

export function useFeedUrls(selection: string): FeedUrls {
  const path = `/api/calendar/${selection}.ics`;
  const [origin, setOrigin] = useState(process.env.NEXT_PUBLIC_SITE_URL ?? "");

  useEffect(() => {
    if (!origin) setOrigin(window.location.origin);
  }, [origin]);

  const httpUrl = origin ? `${origin}${path}` : path;
  return { path, httpUrl, webcalUrl: origin ? httpUrl.replace(/^https?:/, "webcal:") : path };
}

/**
 * A "Copied" flag that clears itself.
 *
 * Returns null while the clipboard is unavailable - over plain http, or where
 * the browser refuses - so a button can stay honest instead of claiming a copy
 * that never happened.
 */
export function useCopied(): [boolean, (value: string) => Promise<void>] {
  const [copied, setCopied] = useState(false);

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return [copied, copy];
}
