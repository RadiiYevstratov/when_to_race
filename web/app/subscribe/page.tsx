/**
 * Subscribe.
 *
 * Two ways to take the schedule with you: a one-off download, or a webcal
 * subscription that keeps updating. The subscription is the one worth having,
 * so it leads.
 */

import { readPreferences } from "../../lib/preferences.ts";
import { getSeriesCatalogue } from "../../lib/queries.ts";
import { formatSelection, isEverything } from "../../lib/selection.ts";
import { CopyableFeed } from "../../components/copyable-feed.tsx";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Subscribe to the calendar",
  description:
    "Add every Formula 1, MotoGP, WorldSBK and FIA WEC session to your phone " +
    "calendar and keep it in sync automatically.",
  alternates: { canonical: "/subscribe" },
  openGraph: {
    title: "Subscribe to the calendar",
    description: "Add session times to your phone calendar and keep them in sync.",
    url: "/subscribe",
    siteName: "ON TRACK",
  },
};

export default async function SubscribePage() {
  const [{ selection }, allSeries] = await Promise.all([
    readPreferences(),
    getSeriesCatalogue(),
  ]);

  // The board filter and the feed URL are the same token format, so what the
  // viewer picked in the header is literally the feed they get.
  const groups = allSeries.map((item) => ({
    code: item.code,
    categoryCodes: item.categories.filter((c) => c.sessionCount > 0).map((c) => c.code),
  }));
  const feed = formatSelection(selection, groups);
  const following = selection.seriesCodes.length + selection.categoryCodes.length;

  return (
    <div className="max-w-2xl space-y-8">
      <header>
        <h1 className="text-2xl">Subscribe</h1>
        <p className="mt-2 text-sm text-ink-muted">
          A subscribed calendar updates itself. When a session is rescheduled, the entry moves in
          your calendar instead of a second one appearing next to it.
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="eyebrow">Your current selection</h2>
        <p className="text-sm text-ink-muted">
          {isEverything(selection)
            ? "Following everything. Narrow it in the header if you want a smaller feed."
            : `Following ${following} ${following === 1 ? "selection" : "selections"}. Change them in the header and this feed changes with it.`}
        </p>
        <CopyableFeed selection={feed} />
      </section>

      <section className="space-y-3">
        <h2 className="eyebrow">One series at a time</h2>
        <ul className="border-t border-rule">
          {allSeries.map((item) => (
            <li key={item.code} className="flex items-center gap-3 border-b border-rule py-2.5">
              <span
                aria-hidden="true"
                className="h-3.5 w-[3px] shrink-0"
                style={{ backgroundColor: item.accentColor }}
              />
              <span className="flex-1 text-sm">{item.shortName}</span>
              {item.lastSuccessfulScrape === null ? (
                // Nothing scraped yet, so this feed would be an empty calendar.
                <span className="font-mono text-xs text-ink-faint">Coming soon</span>
              ) : (
                <a
                  href={`/api/calendar/${item.code}.ics`}
                  className="font-mono text-xs text-ink-muted underline hover:text-ink"
                >
                  Download
                </a>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-2 border-t border-rule pt-4 text-xs text-ink-muted">
        <h2 className="eyebrow">How to add it</h2>
        <p>
          <strong className="font-medium text-ink">iPhone:</strong> Settings &rsaquo; Apps &rsaquo;
          Calendar &rsaquo; Accounts &rsaquo; Add Account &rsaquo; Other &rsaquo; Add Subscribed
          Calendar, then paste the link.
        </p>
        <p>
          <strong className="font-medium text-ink">Google Calendar:</strong> Other calendars &rsaquo;
          From URL, then paste the link. Google refreshes subscribed calendars on its own schedule,
          which can lag by up to a day.
        </p>
        <p>
          <strong className="font-medium text-ink">Outlook:</strong> Add calendar &rsaquo; Subscribe
          from web.
        </p>
      </section>
    </div>
  );
}
