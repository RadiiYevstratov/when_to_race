/**
 * Scraper health.
 *
 * The question this page answers is "is anything quietly broken?" - a scraper
 * that has been failing for two days looks identical to a quiet calendar
 * unless someone is shown the difference.
 *
 * Behind basic auth via middleware.ts.
 */

import { desc, eq, sql } from "drizzle-orm";

import { db } from "../../../lib/queries.ts";
import { scrapeRuns, series } from "../../../lib/schema.ts";
import { isStale } from "../../../lib/time.ts";

export const dynamic = "force-dynamic";

export const metadata = { title: "Scraper health", robots: { index: false, follow: false } };

async function loadHealth() {
  const rows = await db
    .select({
      code: series.code,
      shortName: series.shortName,
      lastSuccessfulScrape: series.lastSuccessfulScrape,
      // Written as literal SQL rather than interpolated columns: inside a
      // sql`` fragment Drizzle renders a column as a bare "id", which is
      // ambiguous once the subquery joins two tables that both have one.
      // Fully qualified names keep these correlated subqueries unambiguous.
      sessionCount: sql<number>`(
        SELECT count(*) FROM sessions
        JOIN events ON events.id = sessions.event_id
        WHERE events.series_id = series.id AND sessions.retired_at IS NULL
      )`,
      upcomingCount: sql<number>`(
        SELECT count(*) FROM sessions
        JOIN events ON events.id = sessions.event_id
        WHERE events.series_id = series.id
          AND sessions.retired_at IS NULL
          AND sessions.starts_at_utc >= now()
      )`,
    })
    .from(series)
    .orderBy(series.sortOrder);

  const recentRuns = await db
    .select({
      id: scrapeRuns.id,
      seriesCode: series.code,
      startedAt: scrapeRuns.startedAt,
      finishedAt: scrapeRuns.finishedAt,
      status: scrapeRuns.status,
      recordsFound: scrapeRuns.recordsFound,
      recordsChanged: scrapeRuns.recordsChanged,
      errorMessage: scrapeRuns.errorMessage,
    })
    .from(scrapeRuns)
    .innerJoin(series, eq(series.id, scrapeRuns.seriesId))
    .orderBy(desc(scrapeRuns.startedAt))
    .limit(25);

  return { rows, recentRuns };
}

export default async function HealthPage() {
  const now = new Date();
  const { rows, recentRuns } = await loadHealth();

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl">Scraper health</h1>
        <p className="mt-1 text-sm text-ink-muted">
          A series is flagged stale after 48 hours without a successful run.
        </p>
      </header>

      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ink text-left">
            <th className="eyebrow py-2">Series</th>
            <th className="eyebrow py-2">Last success</th>
            <th className="eyebrow py-2 text-right">Sessions</th>
            <th className="eyebrow py-2 text-right">Upcoming</th>
          </tr>
        </thead>
        <tbody className="font-mono text-xs">
          {rows.map((row) => {
            const stale = isStale(row.lastSuccessfulScrape, now);
            return (
              <tr key={row.code} className="border-b border-rule">
                <td className="py-2">{row.shortName}</td>
                <td className={`py-2 ${stale ? "text-cancelled" : "text-live"}`}>
                  {row.lastSuccessfulScrape
                    ? new Date(row.lastSuccessfulScrape).toISOString().replace("T", " ").slice(0, 16)
                    : "never"}
                </td>
                <td className="py-2 text-right">{row.sessionCount}</td>
                <td className="py-2 text-right">{row.upcomingCount}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <section>
        <h2 className="eyebrow border-b border-ink pb-1.5">Last 25 runs</h2>
        <ul className="font-mono text-xs">
          {recentRuns.map((run) => (
            <li key={run.id} className="flex flex-wrap gap-3 border-b border-rule py-2">
              <span className="w-16">{run.seriesCode}</span>
              <span
                className={
                  run.status === "success"
                    ? "text-live"
                    : run.status === "aborted_guard"
                      ? "text-provisional"
                      : "text-cancelled"
                }
              >
                {run.status}
              </span>
              <span className="text-ink-muted">
                {new Date(run.startedAt).toISOString().replace("T", " ").slice(0, 16)}
              </span>
              <span className="text-ink-muted">
                {run.recordsFound} found / {run.recordsChanged} changed
              </span>
              {run.errorMessage ? (
                <span className="w-full text-cancelled">{run.errorMessage}</span>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
