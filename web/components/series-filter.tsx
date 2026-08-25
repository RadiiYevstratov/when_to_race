"use client";

/**
 * What to follow, persisted without an account.
 *
 * Selection works at two levels because a race weekend does. Someone who
 * follows Formula 1 wants the whole weekend; someone who follows Formula 2
 * wants four sessions out of seventeen. Clicking a series name takes or clears
 * the lot; clicking a category takes just that one.
 *
 * Written to localStorage and mirrored into a cookie so the server can apply
 * the filter during render rather than shipping everything and hiding most of
 * it on the client.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { COOKIE_MAX_AGE, SERIES_COOKIE } from "../lib/preference-keys.ts";
import {
  formatSelection,
  isCategorySelected,
  isEverything,
  prune,
  selectedCount,
  toggleCategory,
  toggleSeries,
  type Selection,
  type SeriesGroup,
} from "../lib/selection.ts";

const STORAGE_KEY = "ms_series";

export interface CategoryOption {
  code: string;
  shortName: string;
  /** The class's own colour, already resolved against its series. */
  accentColor: string;
  /** Zero means seeded but never run - a discontinued class, or one not yet started. */
  sessionCount: number;
}

export interface SeriesOption {
  code: string;
  shortName: string;
  accentColor: string;
  /** Null until the series has been scraped at least once - i.e. not launched. */
  lastSuccessfulScrape: Date | string | null;
  categories: CategoryOption[];
}

function writeCookie(value: string) {
  document.cookie = `${SERIES_COOKIE}=${encodeURIComponent(value)}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`;
}

export function SeriesFilter({
  allSeries,
  selected,
}: {
  allSeries: SeriesOption[];
  selected: Selection;
}) {
  const router = useRouter();
  const showingAll = isEverything(selected);

  // A category with no sessions would be a chip that always empties the board.
  // A series that has never scraped is shown, but as a label rather than a
  // control - see below.
  const live = allSeries.filter((item) => item.lastSuccessfulScrape !== null);
  const coming = allSeries.filter((item) => item.lastSuccessfulScrape === null);
  const groups: SeriesGroup[] = live.map((item) => ({
    code: item.code,
    categoryCodes: item.categories.filter((c) => c.sessionCount > 0).map((c) => c.code),
  }));
  const fingerprint = groups.map((g) => `${g.code}:${g.categoryCodes.join(".")}`).join("|");

  useEffect(() => {
    // A selection saved before a series went live - or naming one that has
    // since gone - would render an empty board with no way to clear it,
    // because those chips are not buttons. Drop them and heal the preference.
    const usable = prune(selected, groups);
    if (
      usable.seriesCodes.length !== selected.seriesCodes.length ||
      usable.categoryCodes.length !== selected.categoryCodes.length
    ) {
      commit(usable);
      return;
    }

    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === null) return;
    if (saved !== formatSelection(selected, groups, ",")) {
      writeCookie(saved);
      router.refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, router, fingerprint]);

  function commit(next: Selection) {
    // Commas in the cookie, but the same token format the feed URLs use.
    const value = isEverything(next) ? "" : formatSelection(next, groups, ",");
    window.localStorage.setItem(STORAGE_KEY, value);
    writeCookie(value);
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-2" role="group" aria-label="Filter by series and class">
      <button
        type="button"
        onClick={() => commit({ seriesCodes: [], categoryCodes: [] })}
        aria-pressed={showingAll}
        className={`self-start border px-2 py-1 font-mono text-xs ${
          showingAll ? "border-ink text-ink" : "border-rule text-ink-faint hover:text-ink"
        }`}
      >
        All
      </button>

      {live.map((item, index) => {
        const group = groups[index];
        const runnable = item.categories.filter((category) => category.sessionCount > 0);
        if (runnable.length === 0) return null;

        const active = selectedCount(selected, group) > 0;

        return (
          <div key={item.code} className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
            <button
              type="button"
              onClick={() => commit(toggleSeries(selected, group))}
              aria-pressed={active}
              title={`Follow all of ${item.shortName}`}
              className={`flex w-[5.5rem] shrink-0 items-center gap-1.5 text-left font-mono text-xs ${
                active ? "text-ink" : "text-ink-faint hover:text-ink"
              }`}
            >
              <span
                aria-hidden="true"
                className="inline-block h-2 w-2 shrink-0"
                style={{ backgroundColor: item.accentColor }}
              />
              <span className="truncate">{item.shortName}</span>
            </button>

            {/* A series with one class needs no second chip repeating its name. */}
            {runnable.length > 1
              ? runnable.map((category) => {
                  const on = isCategorySelected(selected, group, category.code);
                  return (
                    <button
                      key={category.code}
                      type="button"
                      onClick={() => commit(toggleCategory(selected, group, category.code))}
                      aria-pressed={on}
                      className={`flex items-center gap-1.5 border px-2 py-1 font-mono text-xs ${
                        on ? "border-ink text-ink" : "border-rule text-ink-faint hover:text-ink"
                      }`}
                    >
                      {/* The same colour this class's rows carry on the board,
                          so the chip and the schedule read as one thing. */}
                      <span
                        aria-hidden="true"
                        className={`inline-block h-2 w-2 shrink-0 ${on ? "" : "opacity-60"}`}
                        style={{ backgroundColor: category.accentColor }}
                      />
                      {category.shortName}
                    </button>
                  );
                })
              : null}
          </div>
        );
      })}

      {coming.length > 0 ? (
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
          <span className="w-[5.5rem] shrink-0 font-mono text-xs text-ink-faint">soon</span>
          {coming.map((item) => (
            // Nothing scraped yet, so selecting it would produce an empty board -
            // which reads as a broken site rather than one still being built. Shown
            // as a label until its first scrape lands, then it becomes a control.
            <span
              key={item.code}
              title={`${item.shortName} is being added - schedules are not available yet.`}
              className="cursor-default border border-dashed border-rule px-2 py-1 font-mono text-xs text-ink-faint"
            >
              {item.shortName}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
