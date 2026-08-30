import type { Metadata, Viewport } from "next";
import { Archivo, IBM_Plex_Mono } from "next/font/google";
import Link from "next/link";

import { Footer } from "../components/footer.tsx";
import { JsonLd } from "../components/json-ld.tsx";
import { TimezoneBar } from "../components/timezone-bar.tsx";
import { readPreferences } from "../lib/preferences.ts";
import { getSeriesCatalogue } from "../lib/queries.ts";
import { SeriesFilter } from "../components/series-filter.tsx";
import { SITE_URL } from "../lib/site.ts";
import { websiteJsonLd } from "../lib/structured-data.ts";

import "./globals.css";

const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-archivo",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

const DESCRIPTION =
  "Every practice, qualifying and race session from Formula 1, MotoGP, WorldSBK " +
  "and the FIA WEC, converted to your own timezone. One board for the whole weekend.";

export const metadata: Metadata = {
  // metadataBase lets every other route give a relative canonical and still
  // emit absolute URLs, which Open Graph requires.
  metadataBase: new URL(SITE_URL),
  title: {
    default: "ON TRACK - what motorsport is on, and when",
    // Page titles read "Italian GP - session times | ON TRACK".
    template: "%s | ON TRACK",
  },
  description: DESCRIPTION,
  applicationName: "ON TRACK",
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: "ON TRACK",
    title: "ON TRACK - what motorsport is on, and when",
    description: DESCRIPTION,
    url: "/",
    locale: "en",
  },
  twitter: {
    card: "summary_large_image",
    title: "ON TRACK - what motorsport is on, and when",
    description: DESCRIPTION,
  },
  // Search Console's meta-tag verification. Read from the environment so the
  // token is configured on the host rather than committed, and so the tag is
  // simply absent when it is not set.
  verification: process.env.GOOGLE_SITE_VERIFICATION
    ? { google: process.env.GOOGLE_SITE_VERIFICATION }
    : undefined,
};

// Icons are picked up from the files in this directory - favicon.ico, icon.svg
// and apple-icon.png - so they are not declared here.
export const viewport: Viewport = {
  // Match the board, so a phone does not frame a near-black page in white
  // chrome.
  themeColor: "#08090a",
};

/**
 * The filter needs the database; the rest of the page does not.
 *
 * This runs on every request on every route, so a failure here takes the whole
 * site down rather than one page - and error.tsx cannot catch it, because
 * error.tsx renders inside this layout. Degrading to an empty catalogue costs
 * the filter row and keeps everything else: the nav, the content, and any page
 * that does not happen to need the database.
 */
async function loadCatalogue() {
  try {
    return await getSeriesCatalogue();
  } catch (error) {
    console.error("series catalogue unavailable; rendering without the filter", error);
    return [];
  }
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const [preferences, allSeries] = await Promise.all([readPreferences(), loadCatalogue()]);

  return (
    <html lang="en" className={`${archivo.variable} ${plexMono.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        <JsonLd data={websiteJsonLd(DESCRIPTION)} />
        <a
          href="#board"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:bg-panel focus:px-3 focus:py-2"
        >
          Skip to the schedule
        </a>

        <header className="border-b border-rule bg-panel">
          <div className="mx-auto flex max-w-4xl flex-wrap items-baseline gap-x-6 gap-y-3 px-4 py-6">
            <Link href="/" className="font-mono text-base font-semibold tracking-tight">
              ON TRACK
            </Link>
            <nav className="flex gap-4 text-sm text-ink-muted" aria-label="Main">
              <Link href="/" className="hover:text-ink">
                Now
              </Link>
              <Link href="/calendar" className="hover:text-ink">
                Season
              </Link>
              <Link href="/series" className="hover:text-ink">
                Series
              </Link>
              <Link href="/circuits" className="hover:text-ink">
                Circuits
              </Link>
              <Link href="/subscribe" className="hover:text-ink">
                Subscribe
              </Link>
            </nav>
            <div className="ml-auto">
              <TimezoneBar
                timeZone={preferences.timeZone}
                isAssumed={preferences.timeZoneIsAssumed}
              />
            </div>
          </div>

          {allSeries.length > 0 ? (
            <div className="mx-auto max-w-4xl px-4 pb-6 pt-1">
              <SeriesFilter allSeries={allSeries} selected={preferences.selection} />
            </div>
          ) : null}
        </header>

        <main id="board" className="mx-auto max-w-4xl px-4 py-6">
          {children}
        </main>

        <Footer allSeries={allSeries} />
      </body>
    </html>
  );
}