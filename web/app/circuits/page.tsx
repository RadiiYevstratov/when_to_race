/**
 * Every circuit, as a wall of outlines.
 *
 * The index exists because a circuit page was otherwise unreachable: you could
 * only arrive at one if a round there happened to be on screen. Scanning for a
 * place you know is a different act from reading a schedule, so this is ordered
 * by name and shows no times at all.
 *
 * It is also the only place the traced outlines are shown at a size worth
 * looking at. Everywhere else they sit at nine percent opacity behind text.
 */

import Link from "next/link";

import { JsonLd } from "../../components/json-ld.tsx";
import { circuitOutline } from "../../lib/circuits.ts";
import { getCircuitIndex } from "../../lib/queries.ts";
import { breadcrumbJsonLd, circuitPath } from "../../lib/structured-data.ts";

export const dynamic = "force-dynamic";

const TITLE = "Every circuit";
const DESCRIPTION =
  "Every circuit on the Formula 1, MotoGP, WorldSBK and FIA WEC calendars, " +
  "with the championships that race at each.";

export const metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/circuits" },
  openGraph: { title: TITLE, description: DESCRIPTION, url: "/circuits", siteName: "ON TRACK" },
};

export default async function CircuitsPage() {
  const circuits = await getCircuitIndex();

  return (
    <div className="space-y-6">
      <JsonLd
        data={breadcrumbJsonLd([
          { name: "ON TRACK", path: "/" },
          { name: TITLE, path: "/circuits" },
        ])}
      />

      <header>
        <h1 className="text-2xl">{TITLE}</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">
          {circuits.length} circuits with a round this season. Each outline is traced from the
          real layout.
        </p>
      </header>

      {/* auto-rows-fr so every row is the same height: a name that wraps to two
          lines, or a circuit with three championships, must not make its row
          taller than the others and leave the wall looking ragged. */}
      <ul className="grid auto-rows-fr grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {circuits.map((circuit) => {
          const outline = circuitOutline(circuit.slug);
          return (
            <li key={circuit.slug}>
              <Link
                href={circuitPath(circuit.slug)}
                className="flex h-full flex-col border border-rule bg-panel p-3 transition-colors hover:border-ink"
              >
                {/* A fixed box whether or not there is an outline, so a venue
                    without one does not shorten its card and ripple the grid. */}
                <span className="flex h-16 items-center justify-center">
                  {outline ? (
                    <svg
                      viewBox="0 0 480 260"
                      aria-hidden="true"
                      className="h-full w-full text-ink-muted"
                      preserveAspectRatio="xMidYMid meet"
                    >
                      <path d={outline} fill="currentColor" fillRule="evenodd" />
                    </svg>
                  ) : null}
                </span>

                <span className="mt-2 line-clamp-2 text-sm leading-snug">{circuit.name}</span>
                <span className="mt-0.5 grow font-mono text-xs text-ink-faint">
                  {circuit.city ? `${circuit.city} · ` : ""}
                  {circuit.countryCode}
                </span>

                {/* Classes rather than championships: "Formula 1" at Albert
                    Park hides that Formula 2 and Formula 3 are there too, and
                    what races here is the whole question this page answers.
                    Pushed to the bottom of the card so the rows stay aligned
                    however many there are - Assen and Barcelona have seven. */}
                <span className="mt-2 flex flex-wrap gap-x-1.5 gap-y-1 pt-1">
                  {circuit.classes.map((item) => (
                    <span
                      key={item.code}
                      className="flex items-center gap-1 font-mono text-[0.625rem] leading-tight text-ink-faint"
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
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
