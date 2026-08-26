/**
 * One circuit, and everything that races there.
 *
 * A weekend page belongs to a championship; this belongs to a place. Someone
 * who follows a circuit rather than a series - or who is going to it - wants
 * every round held there, whichever championship owns each one, and that view
 * exists nowhere else on the site.
 *
 * It is also the only page where the traced outline is the subject rather than
 * a watermark behind text.
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import { CircuitArt } from "../../../components/circuit-art.tsx";
import { JsonLd } from "../../../components/json-ld.tsx";
import { readPreferences } from "../../../lib/preferences.ts";
import { getEventsAtVenue, getVenueBySlug } from "../../../lib/queries.ts";
import {
  breadcrumbJsonLd,
  circuitJsonLd,
  circuitPath,
  weekendPath,
} from "../../../lib/structured-data.ts";
import { dayKey, formatShortDay, formatTime, offsetLabel } from "../../../lib/time.ts";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ slug: string }>;
}

function where(venue: { name: string; city: string | null; countryCode: string }) {
  return venue.city ? `${venue.city}, ${venue.countryCode}` : venue.countryCode;
}

export async function generateMetadata({ params }: PageProps) {
  const { slug } = await params;
  const venue = await getVenueBySlug(slug.toLowerCase());
  if (!venue) return { title: "Not found", robots: { index: false } };

  const title = `${venue.name} - session times`;
  const description =
    `Every race weekend at ${venue.name} in ${where(venue)}: practice, ` +
    `qualifying and race times, converted to your own timezone.`;
  const path = circuitPath(venue.slug);

  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: { title, description, url: path, siteName: "ON TRACK" },
    twitter: { card: "summary_large_image", title, description },
  };
}

export default async function CircuitPage({ params }: PageProps) {
  const { slug } = await params;
  const venue = await getVenueBySlug(slug.toLowerCase());
  if (!venue) notFound();

  const now = new Date();
  const [{ timeZone }, events] = await Promise.all([readPreferences(), getEventsAtVenue(venue.slug)]);

  const upcoming = events.filter((event) => new Date(event.endsAtUtc) >= now);
  const past = events.filter((event) => new Date(event.endsAtUtc) < now);

  const crumbs = [
    { name: "ON TRACK", path: "/" },
    { name: venue.name, path: circuitPath(venue.slug) },
  ];

  return (
    <div className="space-y-8">
      <JsonLd data={circuitJsonLd(venue)} />
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
        <CircuitArt venueSlug={venue.slug} />
        <span className="eyebrow">Circuit</span>
        <h1 className="mt-2 text-3xl leading-tight">{venue.name}</h1>
        <p className="mt-1 text-sm text-ink-muted">{where(venue)}</p>

        <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2 border-y border-rule py-3 font-mono text-xs">
          <div>
            <dt className="eyebrow">Local time now</dt>
            <dd className="tnum mt-0.5">
              {formatTime(now, venue.ianaTimezone)} {offsetLabel(now, venue.ianaTimezone)}
            </dd>
          </div>
          <div>
            <dt className="eyebrow">Your time now</dt>
            <dd className="tnum mt-0.5">
              {formatTime(now, timeZone)} {offsetLabel(now, timeZone)}
            </dd>
          </div>
          <div>
            <dt className="eyebrow">Rounds here</dt>
            <dd className="mt-0.5">{events.length}</dd>
          </div>
        </dl>
      </header>

      {upcoming.length > 0 ? (
        <section aria-labelledby="coming-heading">
          <h2 id="coming-heading" className="eyebrow">
            Coming up
          </h2>
          <ul className="mt-3 border-t border-rule">
            {upcoming.map((event) => (
              <RoundRow key={`${event.seriesCode}-${event.slug}`} event={event} timeZone={timeZone} />
            ))}
          </ul>
        </section>
      ) : null}

      {past.length > 0 ? (
        <section aria-labelledby="past-heading">
          <h2 id="past-heading" className="eyebrow">
            Earlier this season
          </h2>
          {/* Past rounds stay listed but never show results - a schedule that
              spoils a race someone has recorded is worse than no schedule. */}
          <ul className="mt-3 border-t border-rule opacity-60">
            {past.map((event) => (
              <RoundRow key={`${event.seriesCode}-${event.slug}`} event={event} timeZone={timeZone} />
            ))}
          </ul>
        </section>
      ) : null}

      <footer className="border-t border-rule pt-4 text-xs text-ink-muted">
        <Link href="/" className="border-b border-ink-muted hover:text-ink">
          Everything on this week
        </Link>
      </footer>
    </div>
  );
}

function RoundRow({
  event,
  timeZone,
}: {
  event: Awaited<ReturnType<typeof getEventsAtVenue>>[number];
  timeZone: string;
}) {
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
      <span className="w-20 shrink-0 font-mono text-xs text-ink-faint">
        {event.seriesShortName}
      </span>
      <span className="min-w-0 flex-1">
        <Link
          href={weekendPath({
            seriesCode: event.seriesCode,
            season: event.season,
            eventSlug: event.slug,
          })}
          className="block truncate hover:text-ink-muted"
        >
          {event.name}
        </Link>
        {/* The classes actually running that weekend. A round listed only as
            "Formula 1" says nothing about the two championships sharing it. */}
        <span className="mt-1 flex flex-wrap gap-x-2 gap-y-1">
          {event.classes.map((item) => (
            <span
              key={item.code}
              className="flex items-center gap-1 font-mono text-[0.625rem] text-ink-faint"
            >
              <span
                aria-hidden="true"
                className="inline-block h-1.5 w-1.5 shrink-0"
                style={{ backgroundColor: item.accentColor }}
              />
              {item.shortName}
            </span>
          ))}
        </span>
      </span>
      <span className="tnum shrink-0 font-mono text-xs text-ink-muted">{span}</span>
      {event.status === "cancelled" ? (
        <span className="font-mono text-xs text-cancelled">Cancelled</span>
      ) : null}
    </li>
  );
}
