/**
 * Where to send a reader who wants to check a time against the organiser.
 *
 * The site's own disclaimer tells people to confirm a time with the official
 * source before setting an alarm, and until the footer carried these links it
 * gave them no way to do that from here.
 *
 * Derived from what is in the database rather than written out, so a
 * championship that goes live is linked the same day and one that is configured
 * but has no sessions yet is not. WRC and IMSA both have their URLs recorded and
 * neither is listed, which is that rule working rather than an oversight.
 */

import type { SeriesCatalogue } from "./queries.ts";

export const CONTACT_EMAIL = "ontrackappme@gmail.com";

export interface OfficialSite {
  key: string;
  label: string;
  url: string;
}

/**
 * One link per championship that has something on the board.
 *
 * A class gets its own entry only where it is its own championship with its own
 * site: Formula 2, Formula 3 and F1 Academy each have one, while Moto2 and
 * WorldSSP live on their series' site and would only be the same link twice.
 */
export function officialSites(allSeries: SeriesCatalogue): OfficialSite[] {
  const sites: OfficialSite[] = [];

  for (const item of allSeries) {
    const live = item.categories.filter((category) => category.sessionCount > 0);
    if (live.length === 0) continue;

    if (item.officialUrl) {
      sites.push({ key: item.code, label: item.shortName, url: item.officialUrl });
    }
    for (const category of live) {
      if (category.officialUrl && category.officialUrl !== item.officialUrl) {
        sites.push({ key: category.code, label: category.shortName, url: category.officialUrl });
      }
    }
  }

  return sites;
}
