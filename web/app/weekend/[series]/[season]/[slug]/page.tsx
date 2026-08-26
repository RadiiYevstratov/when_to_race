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
import { JsonLd } from "../../../../../components/json-ld.tsx";
import { readPreferences } from "../../../../../lib/preferences.ts";
import { getAdjacentEvents, getWeekend } from "../../../../../lib/queries.ts";
import {
  breadcrumbJsonLd,
  circuitPath,
  seasonPath,
  seriesPath,
  sportsEventJsonLd,
} from "../../../../../lib/structured-data.ts";
import { formatTime, isStale, offsetLabel } from "../../../../../lib/time.ts";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ series: string; season: string; slug: string }>;
}

/** Shared so the meta description and the JSON-LD description cannot drift. */
function describe(event: {
  seriesShortName: string;
  eventName: string;
  venueName: string;
  venueCity: string | null;
}): string {
  const where = event.venueCity ? `${event.venueName}, ${event.venueCity}` : event.venueName;
  return (
    `Every ${event.seriesShortName} session at the ${event.eventName}: practice, ` +
    `qualifying and race times at ${where}, converted to your own timezone.`
  );
}

export async function generateMetadata({ params }: PageProps) {
  const { series, season, slug } = await params;
  const weekend = await getWeekend(series, Number(season), slug);
  if (!weekend) return { title: "Weekend not found" };

  const event = weekend.event;
  const title = `${event.eventName} ${event.season} - session times`;
  const description = describe(event);
  const path = `/weekend/${series}/${season}/${slug}`;

  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: { type: "article", title, description, url: path, siteName: "ON TRACK" },
    twitter: { card: "summary_large_image", title, description },
  };
}

export default async function WeekendPage({ params }: PageProps) {
  const { series, season, slug } = await params;
  const seasonNumber = Number(season);
  if (!Number.isInteger(seasonNumber)) notFound();

  const weekend = await getWeekend(series, seasonNumber, slug);
  if (!weekend) notFound();

  const now = new Date();
  const [{ timeZone }, adjacent] = await Promise.all([
    readPreferences(),
    getAdjacentEvents(series, seasonNumber, weekend.sessions[0].startsAtUtc),
  ]);
  const event = weekend.event;
  const circuitZone = event.circuitTimezone;
  const stale = isStale(event.lastSuccessfulScrape, now);

  // Listed in championship order rather than the order they first run. F1
  // Academy often opens a Friday, but "F1 Academy - F3 - F2 - F1" reads as an
  // odd way round to anyone who knows the hierarchy.
  const categoryLinks = [
    ...new Map(
      [...weekend.sessions]
        .sort((a, b) => a.categorySortOrder - b.categorySortOrder)
        .map((session) => [
          session.categoryCode,
          { code: session.categoryCode, shortName: session.categoryShortName },
        ]),
    ).values(),
  ];

  const description = describe(event);
  const crumbs = [
    { name: "ON TRACK", path: "/" },
    { name: `Season ${event.season}`, path: seasonPath(event.season, now.getUTCFullYear()) },
    { name: `${event.eventName} ${event.season}`, path: `/weekend/${series}/${season}/${slug}` },
  ];

  return (
    <article className="space-y-8">
      <JsonLd data={sportsEventJsonLd(event, weekend.sessions, description)} />
      <JsonLd data={breadcrumbJsonLd(crumbs)} />

      <nav aria-label="Breadcrumb" className="font-mono text-xs text-ink-faint">
        <ol className="flex flex-wrap items-center gap-1.5">
          {crumbs.map((crumb, index) => (
            <li key={crumb.path} className="flex items-center gap-1.5">
              {index > 0 ? <span aria-hidden="true">/</span> : null}
              {index === crumbs.length - 1 ? (
                <span aria-current="page" className="text-ink-muted">
                  {crumb.name}
                </span>
              ) : (
                <Link href={crumb.path} className="hover:text-ink-muted">
                  {crumb.name}
                </Link>
              )}
            </li>
          ))}
        </ol>
      </nav>

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
          <Link href={circuitPath(event.venueSlug)} className="hover:text-ink">
            {event.venueName}
          </Link>
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
            {/* Each one links to its own schedule: someone here for Formula 2
                arrived at a page named after the Grand Prix. */}
            <dd className="mt-0.5 flex flex-wrap items-center gap-x-1.5">
              {categoryLinks.map((category, index) => (
                <span key={category.code} className="flex items-center gap-x-1.5">
                  {index > 0 ? <span aria-hidden="true">&middot;</span> : null}
                  <Link href={seriesPath(category.code)} className="hover:text-ink">
                    {category.shortName}
                  </Link>
                </span>
              ))}
            </dd>
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
        {adjacent.previous || adjacent.next ? (
          <nav
            aria-label={`Other ${event.seriesShortName} rounds`}
            className="flex flex-wrap justify-between gap-4 border-y border-rule py-3"
          >
            {adjacent.previous ? (
              <Link
                href={`/weekend/${adjacent.previous.seriesCode}/${adjacent.previous.season}/${adjacent.previous.slug}`}
                className="hover:text-ink"
              >
                &larr; {adjacent.previous.name}
              </Link>
            ) : (
              <span />
            )}
            {adjacent.next ? (
              <Link
                href={`/weekend/${adjacent.next.seriesCode}/${adjacent.next.season}/${adjacent.next.slug}`}
                className="text-right hover:text-ink"
              >
                {adjacent.next.name} &rarr;
              </Link>
            ) : (
              <span />
            )}
          </nav>
        ) : null}

        <div className="flex flex-wrap gap-4">
          <Link
            href={`/api/calendar/${event.seriesCode}.ics`}
            className="border-b border-ink-muted hover:text-ink"
          >
            Download {event.seriesShortName} calendar
          </Link>
          <Link
            href={seasonPath(event.season, now.getUTCFullYear())}
            className="border-b border-ink-muted hover:text-ink"
          >
            Full {event.season} calendar
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
