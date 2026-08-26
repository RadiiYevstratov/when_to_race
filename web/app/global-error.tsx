"use client";

/**
 * The last resort: an error in the root layout itself.
 *
 * error.tsx renders *inside* the layout, so it cannot catch a layout that
 * throws - and this layout reads the series catalogue from the database, which
 * is exactly the kind of call that fails when a database is unreachable. The
 * layout now degrades rather than throwing, so reaching this file should mean
 * something genuinely unexpected.
 *
 * It replaces the whole document, which is why it carries its own html and body
 * and its own colours: none of the app's stylesheet is guaranteed to be here.
 */

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("root layout failed", error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#08090a",
          color: "#eef0f1",
          fontFamily: "ui-monospace, Consolas, monospace",
          padding: "2rem",
        }}
      >
        <main style={{ maxWidth: "32rem", textAlign: "center" }}>
          <p style={{ fontSize: "0.75rem", letterSpacing: "0.16em", color: "#565d62" }}>
            ON TRACK
          </p>
          <h1 style={{ marginTop: "1rem", fontSize: "1rem", fontWeight: 600 }}>
            The site is temporarily unavailable
          </h1>
          <p style={{ marginTop: "0.75rem", fontSize: "0.8rem", lineHeight: 1.7, color: "#8a9298" }}>
            Something failed before the page could be built. This is being logged.
            Reloading in a moment is usually enough.
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: "1.5rem",
              padding: "0.6rem 1.2rem",
              fontFamily: "inherit",
              fontSize: "0.75rem",
              color: "#eef0f1",
              background: "transparent",
              border: "1px solid #24272d",
              cursor: "pointer",
            }}
          >
            Reload
          </button>
          {error.digest ? (
            <p style={{ marginTop: "1.5rem", fontSize: "0.625rem", color: "#565d62" }}>
              Reference {error.digest}
            </p>
          ) : null}
        </main>
      </body>
    </html>
  );
}
