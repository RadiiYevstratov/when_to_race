/**
 * Home - "what's on".
 *
 * Three zones in priority order: anything running now, the next session with a
 * countdown, and the days ahead grouped in the viewer's timezone. When nothing
 * is running the countdown becomes the hero, because that is the question
 * people actually arrive with.
 */

import Link from "next/link";

import { BoardRow, DayBoard, EmptyBoard, sessionTypeLabel } from "../components/board.tsx";
import { Countdown } from "../components/countdown.tsx";
import { CircuitArt } from "../components/circuit-art.tsx";
import { readPreferences } from "../lib/preferences.ts";
import {
  getLiveSessions,
  getSessionsInWindow,
  getUpcomingSessions,
  hasSessionsAfter,
} from "../lib/queries.ts";
import { countdown, formatCountdown, formatTime } from "../lib/time.ts";

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

  return (
    <div className="space-y-10">
      {live.length > 0 ? (
        <section aria-labelledby="live-heading">
          <h2 id="live-heading" className="eyebrow border-b border-ink pb-1.5 text-live">
            Running now
          </h2>
          <ul className="mt-1">
            {live.map((session) => (
              <BoardRow key={session.id} session={session} timeZone={timeZone} now={now} showEvent />
            ))}
          </ul>
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
                style={{ backgroundColor: next.categoryAccentColor }}
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
              {next.venueName}
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

      <section aria-labelledby="soon-heading">
        <h2 id="soon-heading" className="eyebrow">
          The next {days} days
        </h2>
        <div className="mt-3">
          {windowWithoutLive.length > 0 ? (
            <DayBoard sessions={windowWithoutLive} timeZone={timeZone} now={now} showEvent />
          ) : (
            <EmptyBoard
              message={`Nothing scheduled in the next ${days} days.`}
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
