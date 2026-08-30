/**
 * The footer: where to check a time, and where to send an idea.
 *
 * The official links are not decoration. This site's own disclaimer tells
 * people to confirm a time with the organiser before setting an alarm, and
 * until now it gave them no way to do that from here - so the instruction and
 * the means to follow it now sit together.
 *
 * The list is built from what is in the database rather than written out here,
 * so a championship that goes live appears in the footer the same day, and one
 * that is configured but has no sessions yet stays out of it. WRC and IMSA both
 * have their URLs recorded and neither is listed, which is the rule working.
 */

import Link from "next/link";

import type { SeriesCatalogue } from "../lib/queries.ts";
import { CONTACT_EMAIL, officialSites } from "../lib/official-sites.ts";

export function Footer({ allSeries }: { allSeries: SeriesCatalogue }) {
  const sites = officialSites(allSeries);

  return (
    <footer className="mx-auto max-w-4xl px-4 pb-10 pt-6 text-xs leading-relaxed text-ink-faint">
      {sites.length > 0 ? (
        <section aria-labelledby="official-heading" className="border-t border-rule pt-5">
          <h2 id="official-heading" className="eyebrow">
            Official championship sites
          </h2>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
            {sites.map((site) => (
              <li key={site.key}>
                <a
                  href={site.url}
                  rel="noopener noreferrer external"
                  className="border-b border-ink-faint hover:text-ink"
                >
                  {site.label}
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="contact-heading" className="mt-6 border-t border-rule pt-5">
        <h2 id="contact-heading" className="eyebrow">
          Ideas welcome
        </h2>
        <p className="mt-2">
          If there is something you would like to see here &mdash; a championship that is
          missing, a feature that would make the board more useful, or simply a time that
          looks wrong &mdash; use the{" "}
          <Link href="/contact" className="border-b border-ink-faint hover:text-ink">
            contact form
          </Link>
          , or write to{" "}
          <a href={`mailto:${CONTACT_EMAIL}`} className="border-b border-ink-faint hover:text-ink">
            {CONTACT_EMAIL}
          </a>
          {". This is a small independent project and every message is read."}
        </p>
      </section>

      <div className="mt-6 border-t border-rule pt-5">
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
          Schedules are compiled from each championship&rsquo;s own published calendar, with
          one exception worth stating: Formula 1 Grand Prix times come from the
          community-maintained{" "}
          <a
            href="https://f1.vidmar.net/"
            rel="noopener noreferrer external"
            className="border-b border-ink-faint hover:text-ink"
          >
            F1 Calendar
          </a>{" "}
          feed rather than from Formula 1 itself. Formula 2, Formula 3 and F1 Academy times
          do come from their own championships.
        </p>
      </div>
    </footer>
  );
}
