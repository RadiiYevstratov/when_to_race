/**
 * Weekend view.
 *
 * One event, every category on it, interleaved. This is the view that does not
 * exist anywhere else: F2 and F3 between F1's sessions rather than on a
 * separate page, because that is how the weekend actually runs.
 *
 * Once the weekend is under way, what is still to come is listed first and what
 * has already run follows it - the same rule as every other list on the site.
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import { DayBoard } from "../../../../../components/board.tsx";
import { CircuitArt } from "../../../../../components/circuit-art.tsx";
import { JsonLd } from "../../../../../components/json-ld.tsx";
import { readPreferences } from "../../../../../lib/preferences.ts";
import { parseSeason } from "../../../../../lib/season.ts";
import { getAdjacentEvents, getWeekend } from "../../../../../lib/queries.ts";
import {
  breadcrumbJsonLd,
  circuitPath,
  seasonPath,
  seriesPath,
  sportsEventJsonLd,
} from "../../../../../lib/structured-data.ts";
import {
  formatTime,
  formatZoneName,
  isStale,
  offsetLabel,
  splitByFinished,
} from "../../../../../lib/time.ts";

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
  const seasonNumber = parseSeason(season);
  if (seasonNumber === null) return { title: "Not found", robots: { index: false } };

  const weekend = await getWeekend(series, seasonNumber, slug);
  if (!weekend) return { title: "Not found", robots: { index: false } };

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
  // Range-checked, not just "is it a number": `season` is a Postgres integer,
  // so an absurd one is a database error rather than an empty result.
  const seasonNumber = parseSeason(season);
  if (seasonNumber === null) notFound();

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

  // During a race weekend what is still to come goes first and the finished
  // sessions follow, most recent first. Before the weekend only the first list
  // exists, after it only the second - and neither then needs a label.
  const { ahead, done } = splitByFinished(weekend.sessions, now);
  const split = ahead.length > 0 && done.length > 0;

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

      {/* Two zones in one card. The drawing lives only in the upper one, which
          clips it, so the rule between the zones can never run through the
          track - however tall the title wraps or however wide the screen. */}
      <header className="page-card border border-rule">
        <div className="has-circuit-art relative overflow-hidden p-5">
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
        </div>

        <dl className="flex flex-wrap gap-x-8 gap-y-3 border-t border-rule px-5 py-4 font-mono text-xs">
          <div>
            <dt className="eyebrow">Your time</dt>
            <dd className="mt-0.5">
              {formatZoneName(timeZone)} {offsetLabel(now, timeZone)}
            </dd>
          </div>
          <div>
            <dt className="eyebrow">Circuit time</dt>
            <dd className="mt-0.5">
              {formatZoneName(circuitZone)} {offsetLabel(now, circuitZone)}
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
          <p className="border-t border-rule px-5 py-3 text-xs text-provisional">
            These times have not been refreshed from the official source in over 48 hours. Confirm
            before relying on them.
          </p>
        ) : null}
      </header>

      {ahead.length > 0 ? (
        <section aria-labelledby={split ? "ahead-heading" : undefined}>
          {split ? (
            <h2 id="ahead-heading" className="eyebrow mb-3">
              Still to come
            </h2>
          ) : null}
          <DayBoard sessions={ahead} timeZone={timeZone} now={now} headingLevel={split ? 3 : 2} />
        </section>
      ) : null}

      {done.length > 0 ? (
        <section aria-labelledby={split ? "done-heading" : undefined}>
          {split ? (
            <h2 id="done-heading" className="eyebrow mb-3">
              Already run
            </h2>
          ) : null}
          <DayBoard
            sessions={done}
            timeZone={timeZone}
            now={now}
            headingLevel={split ? 3 : 2}
            order="desc"
          />
        </section>
      ) : null}

      <footer className="space-y-3 border-t border-rule pt-4 text-xs text-ink-muted">
        <p>
          All times shown in {formatZoneName(timeZone)}. The first session starts at{" "}
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
