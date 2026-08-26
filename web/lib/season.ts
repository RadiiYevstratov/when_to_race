/**
 * Reading a season out of a URL.
 *
 * A season arrives as untrusted text in a path segment or a query string, and
 * "is it a number" is not enough of a check. `season` is a Postgres `integer`,
 * so anything past 2147483647 is not an empty result - it is a database error
 * and a 500, which /weekend/f1/2147483648/anything and ?season=99999999999
 * both produced. Cheap to fire at, and it lands in the logs as a stack trace
 * every time.
 *
 * A range is the honest guard rather than a numeric-limit one: a season outside
 * living motorsport is not a season, whatever fits in a column. The lower bound
 * is the first Formula 1 world championship; the upper allows for calendars
 * published a few years ahead, which organisers do.
 */

const FIRST_SEASON = 1950;
const YEARS_AHEAD = 5;

export function maxSeason(now: Date = new Date()): number {
  return now.getUTCFullYear() + YEARS_AHEAD;
}

/**
 * The season this text names, or null if it names none.
 *
 * Null rather than a fallback: a caller rendering a page for a specific season
 * should answer "not found", while a caller with a sensible default can choose
 * one. Deciding that here would take the choice away from both.
 */
export function parseSeason(value: string | number | null | undefined, now = new Date()): number | null {
  if (value === null || value === undefined || value === "") return null;

  const text = String(value).trim();
  // Number() accepts "0x7e2", " 12 ", "1e3" and Infinity. A season is digits.
  if (!/^\d{4}$/.test(text)) return null;

  const season = Number(text);
  if (!Number.isSafeInteger(season)) return null;
  if (season < FIRST_SEASON || season > maxSeason(now)) return null;
  return season;
}
