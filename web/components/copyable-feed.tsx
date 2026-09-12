"use client";

/**
 * The feed for whatever the viewer is following, with its URL on show.
 *
 * The hero version: one feed, so the URL itself is worth the space. The
 * per-championship rows below it use the compact FeedLinks instead.
 */

import { useCopied, useFeedUrls } from "../lib/feed-url.ts";

export function CopyableFeed({ selection }: { selection: string }) {
  const { path, webcalUrl } = useFeedUrls(selection);
  const [copied, copy] = useCopied();

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 truncate border border-rule bg-panel px-2 py-1.5 font-mono text-xs">
          {webcalUrl}
        </code>
        <button
          type="button"
          onClick={() => copy(webcalUrl)}
          className="border border-ink px-3 py-1.5 font-mono text-xs hover:bg-panel"
        >
          {copied ? "Copied" : "Copy link"}
        </button>
      </div>
      <div className="flex gap-4 text-xs">
        <a href={webcalUrl} className="border-b border-ink-muted text-ink-muted hover:text-ink">
          Add to calendar
        </a>
        <a href={path} className="border-b border-ink-muted text-ink-muted hover:text-ink">
          Download once
        </a>
      </div>
    </div>
  );
}
