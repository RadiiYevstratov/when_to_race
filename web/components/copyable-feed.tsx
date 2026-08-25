"use client";

/**
 * The feed URL has to be absolute for a calendar client to subscribe, and the
 * origin is only known in the browser unless NEXT_PUBLIC_SITE_URL is set. So
 * this renders the relative path server-side and upgrades to the full webcal://
 * link once mounted.
 */

import { useEffect, useState } from "react";

export function CopyableFeed({ selection }: { selection: string }) {
  const path = `/api/calendar/${selection}.ics`;
  const [origin, setOrigin] = useState(process.env.NEXT_PUBLIC_SITE_URL ?? "");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!origin) setOrigin(window.location.origin);
  }, [origin]);

  const httpUrl = origin ? `${origin}${path}` : path;
  const webcalUrl = origin ? httpUrl.replace(/^https?:/, "webcal:") : path;

  async function copy() {
    try {
      await navigator.clipboard.writeText(webcalUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 truncate border border-rule bg-panel px-2 py-1.5 font-mono text-xs">
          {webcalUrl}
        </code>
        <button
          type="button"
          onClick={copy}
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
