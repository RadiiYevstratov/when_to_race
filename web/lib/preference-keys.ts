/**
 * Cookie names and lifetime, shared by the server reader and the client
 * writers. Kept in their own module with no server imports: lib/preferences.ts
 * imports next/headers, and a client component importing constants from there
 * would drag next/headers into the browser bundle.
 */

export const TIMEZONE_COOKIE = "ms_tz";
export const SERIES_COOKIE = "ms_series";
export const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;