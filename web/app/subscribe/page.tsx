/**
 * Subscribe.
 *
 * Two ways to take the schedule with you: a one-off download, or a webcal
 * subscription that keeps updating. The subscription is the one worth having,
 * so it leads.
 */

import { accentBackground } from "../../lib/accent.ts";
import { readPreferences } from "../../lib/preferences.ts";
import { getSeriesCatalogue } from "../../lib/queries.ts";
import { categoryToken, formatSelection, isEverything } from "../../lib/selection.ts";
import { CopyableFeed } from "../../components/copyable-feed.tsx";
import { FeedLinks } from "../../components/feed-links.tsx";

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
        <h2 className="eyebrow">One championship at a time</h2>
        <p className="text-sm text-ink-muted">
          A Formula 1 weekend also runs F2, F3 and F1 Academy, and a MotoGP weekend runs Moto2 and
          Moto3. Each championship has its own feed, so you can take only the ones you watch - or
          the whole weekend from the row above them.
        </p>
        <ul className="border-t border-rule">
          {allSeries.map((item) => {
            // A class with no sessions would hand someone an empty calendar
            // they then have to notice and remove.
            const classes = item.categories.filter((category) => category.sessionCount > 0);
            const ready = item.lastSuccessfulScrape !== null && classes.length > 0;

            return (
              <li key={item.code} className="border-b border-rule py-2.5">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span
                    aria-hidden="true"
                    className="h-3.5 w-[3px] shrink-0"
                    style={{ backgroundColor: item.accentColor }}
                  />
                  <span className="min-w-0 flex-1 truncate text-sm">{item.shortName}</span>
                  {!ready ? (
                    // Nothing scraped yet, so this feed would be an empty calendar.
                    <span className="font-mono text-xs text-ink-faint">Coming soon</span>
                  ) : (
                    <FeedLinks
                      // The series token, not a list of today's classes: it
                      // keeps meaning "everything here" when one is added.
                      selection={item.code}
                      label={
                        classes.length > 1
                          ? `every ${item.shortName} championship`
                          : item.shortName
                      }
                    />
                  )}
                </div>

                {ready && classes.length > 1 ? (
                  <ul className="mt-2 space-y-2 pl-6">
                    {classes.map((category) => (
                      <li
                        key={category.code}
                        className="flex flex-wrap items-center gap-x-3 gap-y-1"
                      >
                        <span
                          aria-hidden="true"
                          className="h-3 w-[3px] shrink-0"
                          style={{
                            background: accentBackground(
                              category.accentColor,
                              category.accentColors,
                            ),
                          }}
                        />
                        <span className="min-w-0 flex-1 truncate text-sm text-ink-muted">
                          {category.shortName}
                        </span>
                        <FeedLinks
                          selection={categoryToken(item.code, category.code)}
                          label={category.shortName}
                        />
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            );
          })}
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
