/**
 * Viewer preferences: timezone and series selection.
 *
 * Both are mirrored into cookies as well as localStorage. localStorage alone
 * would mean the server renders in the wrong zone and the client corrects it
 * after hydration - a visible flash of wrong times, and wrong for anyone
 * reading with JS disabled. The cookie lets the server render it right the
 * first time; localStorage remains the source of truth the client writes from.
 *
 * The cookie names live in preference-keys.ts because client components need
 * them too, and importing them from here would pull next/headers into the
 * browser bundle.
 */

import { cookies } from "next/headers";

import { COOKIE_MAX_AGE, SERIES_COOKIE, TIMEZONE_COOKIE } from "./preference-keys.ts";
import { parseSelection, type Selection } from "./selection.ts";
import { isValidTimeZone } from "./time.ts";

export { COOKIE_MAX_AGE, SERIES_COOKIE, TIMEZONE_COOKIE };

export interface ViewerPreferences {
  timeZone: string;
  /**
   * What the viewer follows: whole series, individual categories, or - when
   * both lists are empty, which is the default - everything.
   */
  selection: Selection;
  /** True when we are falling back rather than honouring a real preference. */
  timeZoneIsAssumed: boolean;
}

export async function readPreferences(): Promise<ViewerPreferences> {
  const store = await cookies();

  const rawZone = store.get(TIMEZONE_COOKIE)?.value;
  const timeZoneIsAssumed = !rawZone || !isValidTimeZone(rawZone);
  const timeZone = timeZoneIsAssumed ? "UTC" : rawZone!;

  // Cookies written before categories were selectable hold bare series codes,
  // which this format still reads as whole-series tokens.
  const selection = parseSelection(store.get(SERIES_COOKIE)?.value ?? "");

  return { timeZone, selection, timeZoneIsAssumed };
}
