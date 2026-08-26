"use client";

/**
 * What a visitor sees when a page fails.
 *
 * Every page on this site reads from a database on every request, so "the
 * database is briefly unreachable" is a normal operating condition rather than
 * an exotic one. Without this, that condition renders Next's own error screen:
 * unstyled, unbranded, and reading "a server-side exception has occurred",
 * which tells a person nothing and offers them nothing to do.
 *
 * The error text itself is deliberately not shown. It is written to the server
 * log, where it belongs; a stack trace or a connection string in front of a
 * visitor is an information leak and means nothing to them anyway. The digest
 * is shown because it is the one thing that ties what they saw to a log line.
 */

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("page failed to render", error);
  }, [error]);

  return (
    <div className="border border-dashed border-rule px-4 py-16 text-center">
      <h1 className="font-mono text-sm text-ink">This page could not be loaded</h1>
      <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-ink-faint">
        The schedule is read fresh on every visit, so this is usually momentary.
        Trying again is worth doing before anything else.
      </p>

      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="border border-rule px-4 py-2 font-mono text-xs hover:border-ink"
        >
          Try again
        </button>
        <a href="/" className="border-b border-ink-muted font-mono text-xs hover:text-ink">
          Back to what&rsquo;s on
        </a>
      </div>

      {error.digest ? (
        <p className="mt-6 font-mono text-[0.625rem] text-ink-faint">
          Reference {error.digest}
        </p>
      ) : null}
    </div>
  );
}
