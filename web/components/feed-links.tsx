"use client";

/**
 * Subscribe or download, for one championship.
 *
 * The compact form of CopyableFeed, for a row in a list rather than the hero
 * at the top of the page: no URL on show, because a dozen of them down a list
 * is a wall of near-identical text nobody reads.
 */

import { useCopied, useFeedUrls } from "../lib/feed-url.ts";

export function FeedLinks({ selection, label }: { selection: string; label: string }) {
  const { path, webcalUrl } = useFeedUrls(selection);
  const [copied, copy] = useCopied();

  return (
    <span className="flex shrink-0 items-center gap-3 font-mono text-xs">
      <button
        type="button"
        onClick={() => copy(webcalUrl)}
        // The visible word is the same on every row, so the accessible name
        // has to carry which championship this one is.
        aria-label={`Copy the ${label} subscription link`}
        className="border-b border-ink-muted text-ink-muted hover:text-ink"
      >
        {copied ? "Copied" : "Copy link"}
      </button>
      <a
        href={path}
        aria-label={`Download the ${label} calendar`}
        className="border-b border-ink-muted text-ink-muted hover:text-ink"
      >
        Download
      </a>
    </span>
  );
}
