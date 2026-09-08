/**
 * Season calendar.
 *
 * Ordered by distance from now, in both directions: what is still to come
 * lists soonest first, what has already run lists most recent first, and the
 * two meet at today. One rule, applied twice.
 *
 * It used to be a single run in season order, which meant opening this in
 * August and scrolling past every round since February to find the next one. A
 * season is written forwards; nobody arrives wanting to start at round one.
 *
 * Past rounds are de-emphasised but never removed, and never show results -
 * results are a spoiler risk on a schedule product, so they are out of scope
 * entirely rather than hidden behind a toggle.
 */

import Link from "next/link";

import { EmptyBoard } from "../../components/board.tsx";
import { JsonLd } from "../../components/json-ld.tsx";
import { readPreferences } from "../../lib/preferences.ts";
import { parseSeason } from "../../lib/season.ts";
import { getSeasonEvents } from "../../lib/queries.ts";
import {
  breadcrumbJsonLd,
  circuitPath,
  seasonListJsonLd,
  seasonPath,
} from "../../lib/structured-data.ts";
import { dayKey, formatShortDay } from "../../lib/time.ts";

export const dynamic = "force-dynamic";

interface PageProps {
  searchParams: Promise<{ season?: string }>;
}

type SeasonEvent = Awaited<ReturnType<typeof getSeasonEvents>>[number];

export async function generateMetadata({ searchParams }: PageProps) {
  const { season: seasonParam } = await searchParams;
  const thisYear = new Date().getUTCFullYear();
  // A nonsense season shows this year rather than erroring: someone editing a
  // URL by hand should land somewhere useful, not on a stack trace.
  const season = parseSeason(seasonParam) ?? thisYear;
  const path = seasonPath(season, thisYear);

  const title = `${season} season calendar`;
  const description =
    `Every round of the ${season} Formula 1, MotoGP, WorldSBK and FIA WEC seasons, ` +
    `with dates and circuits, in your own timezone.`;

  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: { title, description, url: path, siteName: "ON TRACK" },
  };
}

function RoundRow({ event, timeZone }: { event: SeasonEvent; timeZone: string }) {
  const startKey = dayKey(event.startsAtUtc, timeZone);
  const endKey = dayKey(event.endsAtUtc, timeZone);
  const span =
    startKey === endKey
      ? formatShortDay(startKey)
      : `${formatShortDay(startKey)} – ${formatShortDay(endKey)}`;

  return (
    <li className="flex items-baseline gap-3 border-b border-rule py-3">
      <span
        aria-hidden="true"
        className="mt-1 h-3.5 w-[3px] shrink-0"
        style={{ backgroundColor: event.accentColor }}
      />
      <span className="tnum w-10 shrink-0 font-mono text-xs text-ink-faint">
        {event.roundNumber ? `R${event.roundNumber}` : "—"}
      </span>
      <span className="min-w-0 flex-1">
        <Link
          href={`/weekend/${event.seriesCode}/${event.season}/${event.slug}`}
          className="block truncate hover:text-ink-muted"
        >
          {event.name}
        </Link>
        <span className="block truncate text-xs text-ink-muted">
          <Link href={circuitPath(event.venueSlug)} className="hover:text-ink">
            {event.venueName}
          </Link>
          {event.detailLevel === "partial" ? " · partial schedule" : ""}
        </span>
      </span>
      <span className="tnum shrink-0 font-mono text-xs text-ink-muted">{span}</span>
      {event.status === "cancelled" ? (
        <span className="font-mono text-xs text-cancelled">Cancelled</span>
      ) : null}
    </li>
  );
}

export default async function CalendarPage({ searchParams }: PageProps) {
  const now = new Date();
  const { season: seasonParam } = await searchParams;
  const thisYear = now.getUTCFullYear();
  const season = parseSeason(seasonParam, now) ?? thisYear;

  const { timeZone, selection } = await readPreferences();
  const events = await getSeasonEvents(selection, season);

  // Done means finished, not started: a weekend running right now belongs with
  // what is coming, because it is on.
  const hasRun = (event: SeasonEvent) =>
    new Date(event.endsAtUtc).getTime() < now.getTime();

  const upcoming = events.filter((event) => !hasRun(event));
  // Reversed so this list also reads outwards from today, rather than starting
  // at the far end of the season.
  const past = events.filter(hasRun).reverse();

  return (
    <div className="space-y-6">
      {events.length > 0 ? <JsonLd data={seasonListJsonLd(season, events)} /> : null}
      <JsonLd
        data={breadcrumbJsonLd([
          { name: "ON TRACK", path: "/" },
          { name: `Season ${season}`, path: seasonPath(season, thisYear) },
        ])}
      />
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
        <>
          {upcoming.length > 0 ? (
            <section aria-labelledby="coming-heading">
              <h2 id="coming-heading" className="eyebrow">
                Still to come
              </h2>
              <ul className="mt-3 border-t border-rule">
                {upcoming.map((event) => (
                  <RoundRow
                    key={`${event.seriesCode}-${event.id}`}
                    event={event}
                    timeZone={timeZone}
                  />
                ))}
              </ul>
            </section>
          ) : null}

          {past.length > 0 ? (
            <section aria-labelledby="run-heading">
              <h2 id="run-heading" className="eyebrow">
                Already run
              </h2>
              {/* Dimmed as a group rather than row by row. The heading has
                  said these are done; repeating it on every line is noise. */}
              <ul className="mt-3 border-t border-rule opacity-60">
                {past.map((event) => (
                  <RoundRow
                    key={`${event.seriesCode}-${event.id}`}
                    event={event}
                    timeZone={timeZone}
                  />
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
