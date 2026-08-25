"use client";

/**
 * The timezone in use is always visible. Ambiguity here would undo the whole
 * point of the site, so it sits in the header on every page rather than in a
 * settings screen.
 *
 * On first visit the server has no cookie and renders in UTC. This component
 * detects the real zone, stores it, and refreshes - so the correction happens
 * once, on the first load, rather than on every render.
 */


import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { COOKIE_MAX_AGE, TIMEZONE_COOKIE } from "../lib/preference-keys.ts";
import { offsetLabel } from "../lib/time.ts";

const STORAGE_KEY = "ms_timezone";

function writeCookie(name: string, value: string) {
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`;
}

function supportedZones(): string[] {
  const withValues = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  try {
    return withValues.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    return [];
  }
}

export function TimezoneBar({ timeZone, isAssumed }: { timeZone: string; isAssumed: boolean }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const zones = useMemo(supportedZones, []);

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const preferred = saved || detected;
    if (!preferred) return;

    if (isAssumed || preferred !== timeZone) {
      writeCookie(TIMEZONE_COOKIE, preferred);
      router.refresh();
    }
  }, [isAssumed, timeZone, router]);

  function choose(zone: string) {
    window.localStorage.setItem(STORAGE_KEY, zone);
    writeCookie(TIMEZONE_COOKIE, zone);
    setOpen(false);
    router.refresh();
  }

  function useDeviceZone() {
    window.localStorage.removeItem(STORAGE_KEY);
    choose(Intl.DateTimeFormat().resolvedOptions().timeZone);
  }

  const offset = offsetLabel(new Date(), timeZone);

  return (
    <div className="relative text-right">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="font-mono text-xs text-ink-muted hover:text-ink"
      >
        <span className="eyebrow mr-2">Times in</span>
        <span className="text-ink">{timeZone.replace(/_/g, " ")}</span>
        <span className="ml-1 text-ink-faint">{offset}</span>
      </button>

      {open ? (
        <div className="absolute right-0 z-20 mt-2 w-72 border border-rule bg-panel p-3 text-left shadow-lg">
          <label htmlFor="tz" className="eyebrow block">
            Show times in
          </label>
          <select
            id="tz"
            value={timeZone}
            onChange={(event) => choose(event.target.value)}
            className="mt-2 w-full border border-rule bg-board px-2 py-1.5 font-mono text-sm"
          >
            {zones.length === 0 ? <option value={timeZone}>{timeZone}</option> : null}
            {zones.map((zone) => (
              <option key={zone} value={zone}>
                {zone.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={useDeviceZone}
            className="mt-3 text-xs text-ink-muted underline hover:text-ink"
          >
            Use this device&rsquo;s timezone
          </button>
        </div>
      ) : null}
    </div>
  );
}
