/**
 * What the Instagram account has been saying.
 *
 * The job runs on a GitHub Actions cron that nobody watches, so the question
 * this page answers is the same one the scraper health page does: is it quietly
 * broken? A run that fails and a week with no motorsport in it produce the same
 * silence on Instagram, and only the log tells them apart.
 *
 * Every run writes a row - published, dry run, quiet day or failure - so this is
 * a complete record of the decisions, not just of the posts.
 *
 * Behind basic auth via middleware.ts.
 */

import { getSocialPosts, type SocialPostRow } from "../../../lib/queries.ts";

export const dynamic = "force-dynamic";

export const metadata = { title: "Instagram", robots: { index: false, follow: false } };

const TONE: Record<string, string> = {
  published: "text-live",
  dry_run: "text-provisional",
  skipped: "text-ink-muted",
  failed: "text-cancelled",
};

function stamp(value: string) {
  return new Date(value).toISOString().replace("T", " ").slice(0, 16);
}

function Summary({ rows }: { rows: SocialPostRow[] }) {
  const published = rows.filter((row) => row.outcome === "published");
  const failed = rows.filter((row) => row.outcome === "failed");
  const last = published[0];

  // Counted over the rows on screen rather than the whole table: the useful
  // question is what it has been doing lately, and the cadence the policy aims
  // for is about four and a half posts a week.
  const span = rows.length
    ? Math.max(
        1,
        Math.round(
          (Date.parse(rows[0].decidedAt) - Date.parse(rows[rows.length - 1].decidedAt)) /
            (7 * 24 * 3600 * 1000),
        ),
      )
    : 1;

  return (
    <dl className="grid grid-cols-2 gap-4 font-mono text-xs sm:grid-cols-4">
      <div>
        <dt className="eyebrow">Last published</dt>
        <dd className={last ? "text-live" : "text-ink-muted"}>
          {last ? stamp(last.decidedAt) : "never"}
        </dd>
      </div>
      <div>
        <dt className="eyebrow">Published</dt>
        <dd>{published.length} in these {rows.length} runs</dd>
      </div>
      <div>
        <dt className="eyebrow">Rate</dt>
        <dd>{(published.length / span).toFixed(1)} per week</dd>
      </div>
      <div>
        <dt className="eyebrow">Failures</dt>
        <dd className={failed.length ? "text-cancelled" : "text-ink-muted"}>{failed.length}</dd>
      </div>
    </dl>
  );
}

export default async function SocialPage() {
  const rows = await getSocialPosts(40);

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl">Instagram</h1>
        <p className="mt-1 text-sm text-ink-muted">
          One decision a day at noon, whether or not it becomes a post. A quiet day is a
          decision too.
        </p>
      </header>

      {rows.length === 0 ? (
        <p className="font-mono text-xs text-ink-muted">
          Nothing recorded yet. Run <code>python -m social.run</code> to see what it would
          say today.
        </p>
      ) : (
        <>
          <Summary rows={rows} />

          <section>
            <h2 className="eyebrow border-b border-ink pb-1.5">Last {rows.length} decisions</h2>
            <ul className="font-mono text-xs">
              {rows.map((row) => (
                <li key={row.id} className="border-b border-rule py-3">
                  <div className="flex flex-wrap items-baseline gap-3">
                    <span className="w-24 text-ink-muted">{row.decidedFor}</span>
                    <span className={`w-20 ${TONE[row.outcome] ?? ""}`}>{row.outcome}</span>
                    <span className="w-32 text-ink-muted">{row.postKind ?? "—"}</span>
                    <span>
                      {row.seriesCode ? `${row.seriesCode.toUpperCase()} · ` : ""}
                      {row.eventName ?? ""}
                      {row.sessionType ? ` · ${row.sessionType}` : ""}
                    </span>
                    {row.score !== null ? (
                      <span className="text-ink-faint">score {row.score}</span>
                    ) : null}
                    {row.hasMedia ? (
                      <a className="underline" href={`/api/social/card/${row.id}.jpg`}>
                        card
                      </a>
                    ) : null}
                    {row.instagramPostId ? (
                      <span className="text-ink-faint">{row.instagramPostId}</span>
                    ) : null}
                  </div>

                  {row.errorMessage ? (
                    <p
                      className={`mt-1 ${
                        row.outcome === "failed" ? "text-cancelled" : "text-ink-muted"
                      }`}
                    >
                      {row.errorMessage}
                    </p>
                  ) : null}

                  {row.caption ? (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-ink-faint">caption</summary>
                      <p className="mt-1 whitespace-pre-wrap text-ink-muted">{row.caption}</p>
                    </details>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
