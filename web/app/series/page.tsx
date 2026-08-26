/**
 * Every class, grouped by the championship it runs with.
 *
 * The filter row already names all of these, but a chip is a control rather
 * than a link - it narrows the board, it does not take you anywhere. This is
 * the way in to a class's own page, and the grouping is the point: it shows at
 * a glance that Formula 2 shares a weekend with Formula 1 rather than being a
 * separate thing that happens somewhere else.
 */

import Link from "next/link";

import { JsonLd } from "../../components/json-ld.tsx";
import { getSeriesCatalogue } from "../../lib/queries.ts";
import { breadcrumbJsonLd, seriesPath } from "../../lib/structured-data.ts";

export const dynamic = "force-dynamic";

const TITLE = "Every championship";
const DESCRIPTION =
  "Every championship and class ON TRACK follows, from Formula 1 and its " +
  "support series to MotoGP, WorldSBK and the FIA WEC.";

export const metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/series" },
  openGraph: { title: TITLE, description: DESCRIPTION, url: "/series", siteName: "ON TRACK" },
};

export default async function SeriesIndexPage() {
  const catalogue = await getSeriesCatalogue();
  const live = catalogue.filter((item) => item.lastSuccessfulScrape !== null);
  const coming = catalogue.filter((item) => item.lastSuccessfulScrape === null);

  return (
    <div className="space-y-6">
      <JsonLd
        data={breadcrumbJsonLd([
          { name: "ON TRACK", path: "/" },
          { name: TITLE, path: "/series" },
        ])}
      />

      <header>
        <h1 className="text-2xl">{TITLE}</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">
          Each class has its own schedule. The ones under a single heading share a race weekend.
        </p>
      </header>

      <div className="space-y-6">
        {live.map((item) => {
          // A class seeded but never run has no schedule to show. It is left
          // out rather than linked to a page that would 404.
          const runnable = item.categories.filter((category) => category.sessionCount > 0);
          if (runnable.length === 0) return null;

          return (
            <section key={item.code} aria-labelledby={`series-${item.code}`}>
              <h2
                id={`series-${item.code}`}
                className="flex items-center gap-2 border-b border-rule pb-1.5 font-mono text-xs uppercase tracking-wider text-ink-faint"
              >
                <span
                  aria-hidden="true"
                  className="inline-block h-2 w-2"
                  style={{ backgroundColor: item.accentColor }}
                />
                {item.shortName}
              </h2>

              <ul className="mt-1">
                {runnable.map((category) => (
                  <li key={category.code} className="border-b border-rule">
                    <Link
                      href={seriesPath(category.code)}
                      className="flex items-baseline gap-3 py-3 hover:text-ink-muted"
                    >
                      <span
                        aria-hidden="true"
                        className="h-3.5 w-[3px] shrink-0"
                        style={{ backgroundColor: category.accentColor }}
                      />
                      <span className="flex-1">{category.shortName}</span>
                      <span className="tnum shrink-0 font-mono text-xs text-ink-faint">
                        {category.sessionCount} sessions
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}

        {coming.length > 0 ? (
          <section aria-labelledby="coming-soon">
            <h2
              id="coming-soon"
              className="border-b border-rule pb-1.5 font-mono text-xs uppercase tracking-wider text-ink-faint"
            >
              Coming soon
            </h2>
            <p className="mt-3 text-sm text-ink-muted">
              {coming.map((item) => item.shortName).join(", ")} are being added. Their schedules
              are not published here yet.
            </p>
          </section>
        ) : null}
      </div>
    </div>
  );
}
