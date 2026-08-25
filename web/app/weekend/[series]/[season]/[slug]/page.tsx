/**
 * Weekend view.
 *
 * One event, every category on it, in chronological order. This is the view
 * that does not exist anywhere else: F2 and F3 interleaved with F1 rather than
 * on a separate page, because that is how the weekend actually runs.
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import { DayBoard } from "../../../../../components/board.tsx";
import { CircuitArt } from "../../../../../components/circuit-art.tsx";
import { readPreferences } from "../../../../../lib/preferences.ts";
import { getWeekend } from "../../../../../lib/queries.ts";
import { formatTime, isStale, offsetLabel } from "../../../../../lib/time.ts";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ series: string; season: string; slug: string }>;
}

export async function generateMetadata({ params }: PageProps) {
  const { series, season, slug } = await params;
  const weekend = await getWeekend(series, Number(season), slug);
  if (!weekend) return { title: "Weekend not found" };
  return {
    title: `${weekend.event.eventName} - session times`,
    description: `Every session at the ${weekend.event.eventName}, in your timezone.`,
  };
}

export default async function WeekendPage({ params }: PageProps) {
  const { series, season, slug } = await params;
  const seasonNumber = Number(season);
  if (!Number.isInteger(seasonNumber)) notFound();

  const weekend = await getWeekend(series, seasonNumber, slug);
  if (!weekend) notFound();

  const now = new Date();
  const { timeZone } = await readPreferences();
  const event = weekend.event;
  const circuitZone = event.circuitTimezone;
  const stale = isStale(event.lastSuccessfulScrape, now);

  const categories = [...new Set(weekend.sessions.map((session) => session.categoryShortName))];

  return (
    <article className="space-y-8">
      <header className="has-circuit-art relative overflow-hidden">
        <CircuitArt venueSlug={event.venueSlug} />
        <div className="flex items-baseline gap-3">
          <span
            aria-hidden="true"
            className="h-4 w-[3px]"
            style={{ backgroundColor: event.accentColor }}
          />
          <span className="eyebrow">{event.seriesShortName}</span>
          <span className="font-mono text-xs text-ink-faint">{event.season}</span>
        </div>

        <h1 className="mt-2 text-3xl leading-tight">{event.eventName}</h1>
        <p className="mt-1 text-sm text-ink-muted">
          {event.venueName}
          {event.venueCity ? `, ${event.venueCity}` : ""} &middot; {event.venueCountry}
        </p>

        <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2 border-y border-rule py-3 font-mono text-xs">
          <div>
            <dt className="eyebrow">Your time</dt>
            <dd className="mt-0.5">
              {timeZone.replace(/_/g, " ")} {offsetLabel(now, timeZone)}
            </dd>
          </div>
          <div>
            <dt className="eyebrow">Circuit time</dt>
            <dd className="mt-0.5">
              {circuitZone.replace(/_/g, " ")} {offsetLabel(now, circuitZone)}
            </dd>
          </div>
          <div>
            <dt className="eyebrow">Categories</dt>
            <dd className="mt-0.5">{categories.join(" \u00b7 ")}</dd>
          </div>
        </dl>

        {stale ? (
          <p className="mt-3 border-l-2 border-provisional bg-panel px-3 py-2 text-xs text-provisional">
            These times have not been refreshed from the official source in over 48 hours. Confirm
            before relying on them.
          </p>
        ) : null}
      </header>

      <DayBoard sessions={weekend.sessions} timeZone={timeZone} now={now} />

      <footer className="space-y-3 border-t border-rule pt-4 text-xs text-ink-muted">
        <p>
          All times shown in {timeZone.replace(/_/g, " ")}. The first session starts at{" "}
          {formatTime(weekend.sessions[0].startsAtUtc, circuitZone)} local time at the circuit.
        </p>
        <div className="flex flex-wrap gap-4">
          <Link
            href={`/api/calendar/${event.seriesCode}.ics`}
            className="border-b border-ink-muted hover:text-ink"
          >
            Download {event.seriesShortName} calendar
          </Link>
          {event.sourceUrl ? (
            <a
              href={event.sourceUrl}
              rel="noopener noreferrer nofollow"
              target="_blank"
              className="border-b border-ink-muted hover:text-ink"
            >
              Official schedule
            </a>
          ) : null}
        </div>
      </footer>
    </article>
  );
}
