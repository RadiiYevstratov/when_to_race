/**
 * Season calendar.
 *
 * Past rounds are de-emphasised but never removed, and never show results -
 * results are a spoiler risk on a schedule product, so they are out of scope
 * entirely rather than hidden behind a toggle.
 */

import Link from "next/link";

import { EmptyBoard } from "../../components/board.tsx";
import { readPreferences } from "../../lib/preferences.ts";
import { getSeasonEvents } from "../../lib/queries.ts";
import { dayKey, formatShortDay } from "../../lib/time.ts";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Season calendar",
  description: "Every round of the season, in your timezone.",
};

interface PageProps {
  searchParams: Promise<{ season?: string }>;
}

export default async function CalendarPage({ searchParams }: PageProps) {
  const now = new Date();
  const { season: seasonParam } = await searchParams;
  const season = Number(seasonParam) || now.getUTCFullYear();

  const { timeZone, seriesCodes } = await readPreferences();
  const events = await getSeasonEvents(seriesCodes, season);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl">Season {season}</h1>
        <nav className="flex gap-3 font-mono text-xs text-ink-muted">
          <Link href={`/calendar?season=${season - 1}`} className="hover:text-ink">
            &larr; {season - 1}
          </Link>
          <Link href={`/calendar?season=${season + 1}`} className="hover:text-ink">
            {season + 1} &rarr;
          </Link>
        </nav>
      </header>

      {events.length === 0 ? (
        <EmptyBoard
          message={`No rounds published for ${season} yet.`}
          hint="Calendars usually appear several months ahead."
        />
      ) : (
        <ul className="border-t border-rule">
          {events.map((event) => {
            const past = new Date(event.endsAtUtc).getTime() < now.getTime();
            const startKey = dayKey(event.startsAtUtc, timeZone);
            const endKey = dayKey(event.endsAtUtc, timeZone);
            const span =
              startKey === endKey
                ? formatShortDay(startKey)
                : `${formatShortDay(startKey)} \u2013 ${formatShortDay(endKey)}`;

            return (
              <li
                key={`${event.seriesCode}-${event.id}`}
                className={`flex items-baseline gap-3 border-b border-rule py-3 ${
                  past ? "opacity-50" : ""
                }`}
              >
                <span
                  aria-hidden="true"
                  className="mt-1 h-3.5 w-[3px] shrink-0"
                  style={{ backgroundColor: event.accentColor }}
                />
                <span className="tnum w-10 shrink-0 font-mono text-xs text-ink-faint">
                  {event.roundNumber ? `R${event.roundNumber}` : "\u2014"}
                </span>
                <span className="min-w-0 flex-1">
                  <Link
                    href={`/weekend/${event.seriesCode}/${event.season}/${event.slug}`}
                    className="block truncate hover:text-ink-muted"
                  >
                    {event.name}
                  </Link>
                  <span className="block truncate text-xs text-ink-muted">
                    {event.venueName}
                    {event.detailLevel === "partial" ? " \u00b7 partial schedule" : ""}
                  </span>
                </span>
                <span className="tnum shrink-0 font-mono text-xs text-ink-muted">{span}</span>
                {event.status === "cancelled" ? (
                  <span className="font-mono text-xs text-cancelled">Cancelled</span>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
