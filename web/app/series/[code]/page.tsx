/**
 * One class, on its own page.
 *
 * The board answers "what is on"; this answers "when does Formula 2 run", which
 * is a different question and the one people type into a search box. It exists
 * because a class that shares a weekend with a bigger one has nowhere else to
 * be found on its own - the weekend page is named for the Grand Prix, and the
 * board mixes every championship together by design.
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import { DayBoard, EmptyBoard } from "../../../components/board.tsx";
import { JsonLd } from "../../../components/json-ld.tsx";
import { readPreferences } from "../../../lib/preferences.ts";
import {
  getCategoryByCode,
  getUpcomingSessions,
  getVenuesForCategory,
} from "../../../lib/queries.ts";
import {
  breadcrumbJsonLd,
  seasonPath,
  seriesPath,
  weekendPath,
} from "../../../lib/structured-data.ts";
import { formatShortDay, dayKey, isStale } from "../../../lib/time.ts";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ code: string }>;
}

function describe(name: string, seriesShortName: string, season: number, isHeadline: boolean) {
  const within = isHeadline ? "" : ` It runs alongside ${seriesShortName}.`;
  return (
    `Every ${name} session of the ${season} season - practice, qualifying and ` +
    `race times, converted to your own timezone.${within}`
  );
}

export async function generateMetadata({ params }: PageProps) {
  const { code } = await params;
  const category = await getCategoryByCode(code.toLowerCase());
  if (!category) return { title: "Not found", robots: { index: false } };

  const season = new Date().getUTCFullYear();
  const title = `${category.name} ${season} schedule`;
  const description = describe(
    category.shortName,
    category.seriesShortName,
    season,
    category.isHeadline,
  );
  const path = seriesPath(category.code);

  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: { title, description, url: path, siteName: "ON TRACK" },
    twitter: { card: "summary_large_image", title, description },
  };
}

export default async function SeriesPage({ params }: PageProps) {
  const { code } = await params;
  const category = await getCategoryByCode(code.toLowerCase());
  if (!category) notFound();

  const now = new Date();
  const season = now.getUTCFullYear();
  const selection = { seriesCodes: [], categoryCodes: [category.code] };

  const [{ timeZone }, upcoming, rounds] = await Promise.all([
    readPreferences(),
    getUpcomingSessions(selection, 30, now),
    getVenuesForCategory(category.code, season),
  ]);

  const stale = isStale(category.lastSuccessfulScrape, now);
  const remaining = rounds.filter((round) => new Date(round.startsAtUtc) >= now);
  const crumbs = [
    { name: "ON TRACK", path: "/" },
    { name: `${category.shortName} ${season}`, path: seriesPath(category.code) },
  ];

  return (
    <div className="space-y-8">
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

      <header>
        <div className="flex items-baseline gap-3">
          <span
            aria-hidden="true"
            className="h-4 w-[3px]"
            style={{ backgroundColor: category.accentColor }}
          />
          <span className="eyebrow">{category.shortName}</span>
          <span className="font-mono text-xs text-ink-faint">{season}</span>
        </div>
        <h1 className="mt-2 text-3xl leading-tight">{category.name}</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">
          {describe(category.shortName, category.seriesShortName, season, category.isHeadline)}
        </p>

        {stale ? (
          <p className="mt-3 border-l-2 border-provisional bg-panel px-3 py-2 text-xs text-provisional">
            These times have not been refreshed from the official source in over 48 hours.
            Confirm before relying on them.
          </p>
        ) : null}
      </header>

      <section aria-labelledby="next-heading">
        <h2 id="next-heading" className="eyebrow">
          Next sessions
        </h2>
        <div className="mt-3">
          {upcoming.length > 0 ? (
            <DayBoard sessions={upcoming} timeZone={timeZone} now={now} showEvent />
          ) : (
            <EmptyBoard
              message={`Nothing left on the ${season} ${category.shortName} calendar.`}
              hint="Next season's dates usually appear several months ahead."
            />
          )}
        </div>
      </section>

      {remaining.length > 0 ? (
        <section aria-labelledby="rounds-heading">
          <h2 id="rounds-heading" className="eyebrow">
            Remaining {season} rounds
          </h2>
          <ul className="mt-3 border-t border-rule">
            {remaining.map((round) => (
              <li
                key={`${round.seriesCode}-${round.eventSlug}`}
                className="flex items-baseline gap-3 border-b border-rule py-3"
              >
                <span className="tnum w-24 shrink-0 font-mono text-xs text-ink-faint">
                  {formatShortDay(dayKey(round.startsAtUtc, timeZone))}
                </span>
                <span className="min-w-0 flex-1">
                  <Link
                    href={weekendPath({
                      seriesCode: round.seriesCode,
                      season: round.season,
                      eventSlug: round.eventSlug,
                    })}
                    className="block truncate hover:text-ink-muted"
                  >
                    {round.eventName}
                  </Link>
                  <Link
                    href={`/circuit/${round.venueSlug}`}
                    className="block truncate text-xs text-ink-muted hover:text-ink"
                  >
                    {round.venueName}
                  </Link>
                </span>
                <span className="shrink-0 font-mono text-xs text-ink-faint">
                  {round.venueCountry}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <footer className="flex flex-wrap gap-4 border-t border-rule pt-4 text-xs text-ink-muted">
        <Link
          href={`/api/calendar/${category.seriesCode}.${category.code}.ics`}
          className="border-b border-ink-muted hover:text-ink"
        >
          Subscribe to {category.shortName}
        </Link>
        <Link href={seasonPath(season, season)} className="border-b border-ink-muted hover:text-ink">
          Full {season} calendar
        </Link>
        <Link href="/" className="border-b border-ink-muted hover:text-ink">
          Everything on this week
        </Link>
      </footer>
    </div>
  );
}
