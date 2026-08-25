/**
 * Subscribe.
 *
 * Two ways to take the schedule with you: a one-off download, or a webcal
 * subscription that keeps updating. The subscription is the one worth having,
 * so it leads.
 */

import { readPreferences } from "../../lib/preferences.ts";
import { getAllSeries } from "../../lib/queries.ts";
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
  const [{ seriesCodes }, allSeries] = await Promise.all([readPreferences(), getAllSeries()]);
  const selection = seriesCodes.length > 0 ? seriesCodes.join("+") : "all";

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
          {seriesCodes.length > 0
            ? `Following ${seriesCodes.length} series. Change the selection in the header and this feed changes with it.`
            : "Following every series. Narrow it in the header if you want a smaller feed."}
        </p>
        <CopyableFeed selection={selection} />
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
