import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono } from "next/font/google";
import Link from "next/link";

import { TimezoneBar } from "../components/timezone-bar.tsx";
import { readPreferences } from "../lib/preferences.ts";
import { getAllSeries } from "../lib/queries.ts";
import { SeriesFilter } from "../components/series-filter.tsx";

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

export const metadata: Metadata = {
  title: "On Track - what motorsport is on, and when",
  description:
    "Every practice, qualifying and race session across ten championships, in your own timezone.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const [preferences, allSeries] = await Promise.all([readPreferences(), getAllSeries()]);

  return (
    <html lang="en" className={`${archivo.variable} ${plexMono.variable}`}>
      <body className="min-h-screen font-sans antialiased">
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

          <div className="mx-auto max-w-4xl px-4 pb-6 pt-1">
            <SeriesFilter allSeries={allSeries} selected={preferences.seriesCodes} />
          </div>
        </header>

        <main id="board" className="mx-auto max-w-4xl px-4 py-6">
          {children}
        </main>

        <footer className="mx-auto max-w-4xl px-4 pb-10 pt-6 text-xs leading-relaxed text-ink-faint">
          <p>
            Times are provisional and can change at short notice. Confirm with the official
            source before travelling or setting an alarm.
          </p>
          <p className="mt-2">
            An independent, non-commercial project. Not affiliated with, endorsed by or
            connected to any championship, series organiser or rights holder. All series
            names and trade marks belong to their respective owners.
          </p>
          <p className="mt-2">
            Schedules are compiled from each championship&rsquo;s published calendar:{" "}
            <a
              href="https://www.motogp.com/en/calendar"
              rel="noopener noreferrer"
              className="border-b border-ink-faint hover:text-ink-muted"
            >
              MotoGP
            </a>
            ,{" "}
            <a
              href="https://www.worldsbk.com/en/calendar"
              rel="noopener noreferrer"
              className="border-b border-ink-faint hover:text-ink-muted"
            >
              WorldSBK
            </a>{" "}
            and{" "}
            <a
              href="https://www.fiawec.com/en"
              rel="noopener noreferrer"
              className="border-b border-ink-faint hover:text-ink-muted"
            >
              FIA WEC
            </a>
            . Formula 1 times come from the community-maintained{" "}
            <a
              href="https://f1.vidmar.net/"
              rel="noopener noreferrer"
              className="border-b border-ink-faint hover:text-ink-muted"
            >
              F1 Calendar
            </a>{" "}
            feed, not from an official Formula 1 source.
          </p>
        </footer>
      </body>
    </html>
  );
}