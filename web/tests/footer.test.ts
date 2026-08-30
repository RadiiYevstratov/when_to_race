/**
 * Which championships the footer links out to.
 *
 * The list is derived rather than written out, so what is worth pinning is the
 * derivation: a championship with nothing on the board must not be advertised,
 * and a class that shares its series' site must not appear as a second link to
 * the same place.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { officialSites } from "../lib/official-sites.ts";

type Catalogue = Parameters<typeof officialSites>[0];

function series(
  code: string,
  shortName: string,
  officialUrl: string | null,
  categories: {
    code: string;
    shortName: string;
    officialUrl?: string | null;
    sessionCount?: number;
  }[],
) {
  return {
    code,
    shortName,
    accentColor: "#FFFFFF",
    officialUrl,
    lastSuccessfulScrape: new Date(),
    categories: categories.map((category) => ({
      code: category.code,
      shortName: category.shortName,
      accentColor: "#FFFFFF",
      accentColors: null,
      officialUrl: category.officialUrl ?? null,
      sessionCount: category.sessionCount ?? 10,
    })),
  };
}

const F1 = series("f1", "Formula 1", "https://www.formula1.com/", [
  { code: "f1", shortName: "F1" },
  { code: "f2", shortName: "F2", officialUrl: "https://www.fiaformula2.com/" },
  { code: "f3", shortName: "F3", officialUrl: "https://www.fiaformula3.com/" },
]);

const MOTOGP = series("motogp", "MotoGP", "https://www.motogp.com/", [
  { code: "motogp", shortName: "MotoGP" },
  // Lives on the series' site; no link of its own.
  { code: "moto2", shortName: "Moto2" },
]);

describe("official championship links", () => {
  test("a class with its own championship site gets its own link", () => {
    const sites = officialSites([F1] as unknown as Catalogue);
    assert.deepEqual(
      sites.map((site) => site.label),
      ["Formula 1", "F2", "F3"],
    );
    assert.equal(sites[1].url, "https://www.fiaformula2.com/");
  });

  test("a class that shares its series' site is not listed twice", () => {
    const sites = officialSites([MOTOGP] as unknown as Catalogue);
    assert.deepEqual(
      sites.map((site) => site.label),
      ["MotoGP"],
    );
  });

  test("a championship with nothing on the board is not advertised", () => {
    // WRC and IMSA both have a URL recorded and no sessions. Linking them would
    // send someone to a championship this site shows nothing for.
    const wrc = series("wrc", "WRC", "https://www.wrc.com/", [
      { code: "wrc", shortName: "WRC", sessionCount: 0 },
    ]);
    assert.deepEqual(officialSites([wrc] as unknown as Catalogue), []);
  });

  test("a class with no sessions drops out while its series stays", () => {
    const indycar = series("indycar", "IndyCar", "https://www.indycar.com/", [
      { code: "indycar", shortName: "IndyCar" },
      // Configured, never published - see indycar.py.
      {
        code: "indynxt",
        shortName: "Indy NXT",
        officialUrl: "https://www.indynxt.com/",
        sessionCount: 0,
      },
    ]);
    assert.deepEqual(
      officialSites([indycar] as unknown as Catalogue).map((site) => site.label),
      ["IndyCar"],
    );
  });

  test("a series with no URL recorded is skipped rather than linked to nowhere", () => {
    const nameless = series("x", "Nameless", null, [{ code: "x", shortName: "X" }]);
    assert.deepEqual(officialSites([nameless] as unknown as Catalogue), []);
  });

  test("every link is unique and https", () => {
    const sites = officialSites([F1, MOTOGP] as unknown as Catalogue);
    const urls = sites.map((site) => site.url);
    assert.equal(new Set(urls).size, urls.length);
    assert.ok(urls.every((url) => url.startsWith("https://")));
  });
});
