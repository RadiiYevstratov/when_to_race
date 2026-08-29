/**
 * Home - "what's on".
 *
 * Three zones in priority order: anything running now, the next session with a
 * countdown, and the days ahead grouped in the viewer's timezone. When nothing
 * is running the countdown becomes the hero, because that is the question
 * people actually arrive with.
 */

import Link from "next/link";

import { accentBackground } from "../lib/accent.ts";

import {
  DayBoard,
  EmptyBoard,
  QuietEmpty,
  SessionList,
  sessionTypeLabel,
} from "../components/board.tsx";
import { Countdown } from "../components/countdown.tsx";
import { CircuitArt } from "../components/circuit-art.tsx";
import { readPreferences } from "../lib/preferences.ts";
import {
  getLiveSessions,
  getSessionsInWindow,
  getUpcomingSessions,
  hasSessionsAfter,
} from "../lib/queries.ts";
import { circuitPath } from "../lib/structured-data.ts";
import {
  countdown,
  dayKey,
  formatCountdown,
  formatDayHeading,
  formatTime,
  shiftDayKey,
} from "../lib/time.ts";

export const dynamic = "force-dynamic";

// The board starts at one week and grows a week at a time via "Load more".
const WINDOW_STEP_DAYS = 7;
const MAX_WINDOW_DAYS = 120; // a season's worth; the guard against a silly ?days=

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const now = new Date();
  const { timeZone, selection } = await readPreferences();

  const requested = Number.parseInt((await searchParams).days ?? "", 10);
  const days = Math.min(
    Math.max(Number.isFinite(requested) ? requested : WINDOW_STEP_DAYS, WINDOW_STEP_DAYS),
    MAX_WINDOW_DAYS,
  );
  const windowEnd = new Date(now.getTime() + days * 86_400_000);

  const [live, upcoming, window, moreAhead] = await Promise.all([
    getLiveSessions(selection, now),
    getUpcomingSessions(selection, 1, now),
    getSessionsInWindow(selection, days, now),
    hasSessionsAfter(selection, windowEnd),
  ]);

  const next = upcoming[0];
  const windowWithoutLive = window.filter(
    (session) => !live.some((running) => running.id === session.id),
  );

  // Today and tomorrow are the two questions people actually arrive with, so
  // they get their own headings rather than being the first two day groups of
  // a seven-day list. Both are the viewer's days, not the circuit's: a race at
  // 01:30 Sunday in Bratislava is Saturday night in Daytona, and the person
  // reading is in Bratislava.
  const todayKey = dayKey(now, timeZone);
  const tomorrowKey = shiftDayKey(todayKey, 1);
  const dayOf = (session: (typeof windowWithoutLive)[number]) =>
    dayKey(session.startsAtUtc, timeZone);

  const today = windowWithoutLive.filter((session) => dayOf(session) === todayKey);
  const tomorrow = windowWithoutLive.filter((session) => dayOf(session) === tomorrowKey);
  const later = windowWithoutLive.filter(
    (session) => dayOf(session) !== todayKey && dayOf(session) !== tomorrowKey,
  );

  return (
    <div className="space-y-10">
      {/* The page's visible identity is the wordmark in the header, and a
          second title under it would be noise on a board whose entire job is
          to be read at a glance. It still needs a heading: without one a
          screen reader has no name for the page, and this was the only page on
          the site with no h1 at all. */}
      <h1 className="sr-only">
        Motorsport schedule &mdash; what is on now and what is coming up
      </h1>
      {live.length > 0 ? (
        <section aria-labelledby="live-heading">
          <h2 id="live-heading" className="eyebrow border-b border-ink pb-1.5 text-live">
            Running now
          </h2>
          <SessionList sessions={live} timeZone={timeZone} now={now} showEvent />
        </section>
      ) : null}

      {next ? (
        <section aria-labelledby="next-heading">
          <h2 id="next-heading" className="eyebrow">
            Next up
          </h2>
          <div className="nextup-card has-circuit-art mt-2 border border-rule bg-panel p-5">
            <CircuitArt venueSlug={next.venueSlug} />
            <div className="flex items-baseline gap-3">
              <span
                aria-hidden="true"
                className="h-5 w-[3px]"
                style={{
                  background: accentBackground(
                    next.categoryAccentColor,
                    next.categoryAccentColors,
                  ),
                }}
              />
              <span className="font-mono text-xs text-ink-muted">{next.categoryShortName}</span>
              <span className="font-mono text-xs text-ink-faint">
                {sessionTypeLabel(next.sessionType)}
              </span>
            </div>

            <p className="mt-3 text-2xl leading-tight">
              {next.displayName}
              <span className="text-ink-muted"> &middot; {next.eventName}</span>
            </p>

            <p className="mt-1 text-sm text-ink-muted">
              <Link href={circuitPath(next.venueSlug)} className="hover:text-ink">
                {next.venueName}
              </Link>
              {next.venueCity ? `, ${next.venueCity}` : ""}
            </p>

            <div className="mt-4 flex flex-wrap items-baseline gap-x-6 gap-y-2">
              <Countdown
                target={new Date(next.startsAtUtc).toISOString()}
                initialLabel={formatCountdown(countdown(next.startsAtUtc, now))}
                className="text-3xl"
              />
              <time
                dateTime={new Date(next.startsAtUtc).toISOString()}
                className="tnum font-mono text-sm text-ink-muted"
              >
                {next.startsAtPrecision === "day"
                  ? "Time not yet published"
                  : formatTime(next.startsAtUtc, timeZone)}
              </time>
              {next.timeStatus !== "confirmed" ? (
                <span className="font-mono text-xs text-provisional">
                  Provisional &mdash; confirm before setting an alarm
                </span>
              ) : null}
            </div>

            <Link
              href={`/weekend/${next.seriesCode}/${next.season}/${next.eventSlug}`}
              className="mt-4 inline-block border-b border-ink text-sm hover:text-ink-muted"
            >
              See the whole weekend
            </Link>
          </div>
        </section>
      ) : null}

      <section aria-labelledby="today-heading">
        <h2 id="today-heading" className="eyebrow border-b border-ink pb-1.5">
          Today
          <span className="ml-2 text-ink-faint">{formatDayHeading(todayKey, timeZone)}</span>
        </h2>
        {today.length > 0 ? (
          <SessionList sessions={today} timeZone={timeZone} now={now} showEvent />
        ) : (
          // "More" because anything running right now is above, and because a
          // session that finished an hour ago has already dropped off this list.
          <QuietEmpty message="Nothing more today." />
        )}
      </section>

      <section aria-labelledby="tomorrow-heading">
        <h2 id="tomorrow-heading" className="eyebrow border-b border-ink pb-1.5">
          Tomorrow
          <span className="ml-2 text-ink-faint">{formatDayHeading(tomorrowKey, timeZone)}</span>
        </h2>
        {tomorrow.length > 0 ? (
          <SessionList sessions={tomorrow} timeZone={timeZone} now={now} showEvent />
        ) : (
          <QuietEmpty message="Nothing tomorrow." />
        )}
      </section>

      <section aria-labelledby="soon-heading">
        <h2 id="soon-heading" className="eyebrow">
          The next {days} days
        </h2>
        <div className="mt-3">
          {later.length > 0 ? (
            <DayBoard sessions={later} timeZone={timeZone} now={now} showEvent />
          ) : (
            <EmptyBoard
              message={
                windowWithoutLive.length > 0
                  ? `Nothing further in the next ${days} days.`
                  : `Nothing scheduled in the next ${days} days.`
              }
              hint="Check the season calendar for the next round."
            />
          )}

          {moreAhead ? (
            <div className="mt-6 flex justify-center">
              <Link
                href={`/?days=${days + WINDOW_STEP_DAYS}`}
                scroll={false}
                replace
                className="inline-block border border-rule px-5 py-2 font-mono text-xs tracking-wide hover:border-ink"
              >
                Load 7 more days
              </Link>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
