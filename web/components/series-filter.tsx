"use client";

/**
 * Series selection, persisted without an account. Someone who follows only
 * MotoGP and WorldSBK sets it once and the site stays that way.
 *
 * Written to localStorage and mirrored into a cookie so the server can apply
 * the filter during render rather than shipping everything and hiding most of
 * it on the client.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { COOKIE_MAX_AGE, SERIES_COOKIE } from "../lib/preference-keys.ts";

const STORAGE_KEY = "ms_series";

interface SeriesOption {
  code: string;
  shortName: string;
  accentColor: string;
  /** Null until the series has been scraped at least once - i.e. not launched. */
  lastSuccessfulScrape: Date | string | null;
}

function writeCookie(value: string) {
  document.cookie = `${SERIES_COOKIE}=${encodeURIComponent(value)}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`;
}

export function SeriesFilter({
  allSeries,
  selected,
}: {
  allSeries: SeriesOption[];
  selected: string[];
}) {
  const router = useRouter();
  const showingAll = selected.length === 0;

  const liveCodes = allSeries
    .filter((item) => item.lastSuccessfulScrape !== null)
    .map((item) => item.code);

  useEffect(() => {
    // A selection saved before a series went live - or one naming a series that
    // is still coming - would render an empty board with no way to clear it,
    // because those chips are not buttons. Drop them and heal the preference.
    const usable = selected.filter((code) => liveCodes.includes(code));
    if (usable.length !== selected.length) {
      commit(usable);
      return;
    }

    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === null) return;
    if (saved !== selected.join(",")) {
      writeCookie(saved);
      router.refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, router, liveCodes.join(",")]);

  function commit(codes: string[]) {
    const value = codes.join(",");
    window.localStorage.setItem(STORAGE_KEY, value);
    writeCookie(value);
    router.refresh();
  }

  function toggle(code: string) {
    const next = selected.includes(code)
      ? selected.filter((item) => item !== code)
      : [...selected, code];
    commit(next);
  }

  return (
    <div className="flex flex-wrap items-center gap-2.5" role="group" aria-label="Filter by series">
      <button
        type="button"
        onClick={() => commit([])}
        aria-pressed={showingAll}
        className={`border px-2 py-1 font-mono text-xs ${
          showingAll ? "border-ink text-ink" : "border-rule text-ink-faint hover:text-ink"
        }`}
      >
        All
      </button>

      {allSeries.map((item) => {
        // A series that has never scraped has no sessions to show. Selecting it
        // would produce an empty board, which reads as a broken site rather than
        // one still being built - so it is shown, disabled, and labelled. The
        // moment its first scrape lands the chip becomes selectable on its own.
        const comingSoon = item.lastSuccessfulScrape === null;
        const active = selected.includes(item.code);

        if (comingSoon) {
          return (
            <span
              key={item.code}
              title={`${item.shortName} is being added - schedules are not available yet.`}
              className="flex cursor-default items-center gap-1.5 border border-dashed border-rule px-2 py-1 font-mono text-xs text-ink-faint"
            >
              <span
                aria-hidden="true"
                className="inline-block h-2 w-2 opacity-40"
                style={{ backgroundColor: item.accentColor }}
              />
              {item.shortName}
              <span className="text-[0.625rem] uppercase tracking-wider opacity-70">soon</span>
            </span>
          );
        }

        return (
          <button
            key={item.code}
            type="button"
            onClick={() => toggle(item.code)}
            aria-pressed={active}
            className={`flex items-center gap-1.5 border px-2 py-1 font-mono text-xs ${
              active ? "border-ink text-ink" : "border-rule text-ink-faint hover:text-ink"
            }`}
          >
            <span
              aria-hidden="true"
              className="inline-block h-2 w-2"
              style={{ backgroundColor: item.accentColor }}
            />
            {item.shortName}
          </button>
        );
      })}
    </div>
  );
}
