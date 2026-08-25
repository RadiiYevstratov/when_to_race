/**
 * Following a class rather than a whole championship.
 *
 * The rules that matter here are the ones a user would notice going wrong: a
 * saved filter that empties the board with no chip left to undo it, and a
 * selection that silently stops meaning what it meant when it was saved.
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  collapse,
  formatSelection,
  isCategorySelected,
  isEverything,
  parseSelection,
  prune,
  selectedCount,
  toggleCategory,
  toggleSeries,
  type Selection,
  type SeriesGroup,
} from "../lib/selection.ts";

const F1: SeriesGroup = { code: "f1", categoryCodes: ["f1", "f2", "f3", "f1a"] };
const MOTOGP: SeriesGroup = { code: "motogp", categoryCodes: ["motogp", "moto2", "moto3"] };
const WEC: SeriesGroup = { code: "wec", categoryCodes: ["wec"] };
const GROUPS = [F1, MOTOGP, WEC];

const NOTHING: Selection = { seriesCodes: [], categoryCodes: [] };

describe("reading a selection", () => {
  test("empty and \"all\" both mean everything", () => {
    assert.ok(isEverything(parseSelection("")));
    assert.ok(isEverything(parseSelection("all")));
    assert.ok(isEverything(parseSelection("all.ics")));
  });

  test("a bare token is a series, a dotted one is a category", () => {
    assert.deepEqual(parseSelection("f1.f2+motogp"), {
      seriesCodes: ["motogp"],
      categoryCodes: ["f2"],
    });
  });

  test("commas work as well as plus, because the cookie uses them", () => {
    assert.deepEqual(parseSelection("f1.f2,f1.f3"), {
      seriesCodes: [],
      categoryCodes: ["f2", "f3"],
    });
  });

  test("a cookie written before categories existed still reads correctly", () => {
    assert.deepEqual(parseSelection("motogp,wsbk"), {
      seriesCodes: ["motogp", "wsbk"],
      categoryCodes: [],
    });
  });

  test("malformed tokens are dropped", () => {
    assert.deepEqual(parseSelection("f1';--+motogp+a.b.c"), {
      seriesCodes: ["motogp"],
      categoryCodes: [],
    });
  });

  test("a well-formed but unknown code parses, and prune is what removes it", () => {
    // Parsing only checks shape. Nothing here reaches SQL unparameterised, so
    // an unknown code is a filter that matches nothing rather than a risk - and
    // prune drops it against the real catalogue before it can empty the board.
    const parsed = parseSelection("nosuchseries+motogp");
    assert.deepEqual(parsed.seriesCodes, ["nosuchseries", "motogp"]);
    assert.deepEqual(prune(parsed, GROUPS), { seriesCodes: ["motogp"], categoryCodes: [] });
  });
});

describe("writing a selection back", () => {
  test("categories are written with the series that owns them", () => {
    const value = formatSelection({ seriesCodes: ["motogp"], categoryCodes: ["f2"] }, GROUPS);
    assert.equal(value, "motogp+f1.f2");
  });

  test("survives a round trip", () => {
    const original = { seriesCodes: ["wec"], categoryCodes: ["f2", "moto3"] };
    assert.deepEqual(parseSelection(formatSelection(original, GROUPS)), original);
  });

  test("an unknown category is dropped, never written bare", () => {
    // Written without its prefix it would be read back as a *series* next time.
    const value = formatSelection({ seriesCodes: [], categoryCodes: ["gone"] }, GROUPS);
    assert.equal(value, "all");
  });
});

describe("clicking a series", () => {
  test("takes the whole championship", () => {
    assert.deepEqual(toggleSeries(NOTHING, F1), { seriesCodes: ["f1"], categoryCodes: [] });
  });

  test("clicking it again clears it", () => {
    const on = toggleSeries(NOTHING, F1);
    assert.deepEqual(toggleSeries(on, F1), NOTHING);
  });

  test("clears the group even when only one class of it is on", () => {
    const justF2 = toggleCategory(NOTHING, F1, "f2");
    assert.deepEqual(toggleSeries(justF2, F1), NOTHING);
  });

  test("leaves other series alone", () => {
    const both = toggleSeries(toggleSeries(NOTHING, F1), MOTOGP);
    assert.deepEqual(toggleSeries(both, F1), { seriesCodes: ["motogp"], categoryCodes: [] });
  });
});

describe("clicking a class", () => {
  test("takes just that class", () => {
    assert.deepEqual(toggleCategory(NOTHING, F1, "f2"), {
      seriesCodes: [],
      categoryCodes: ["f2"],
    });
  });

  test("removing one class from a whole series keeps the rest", () => {
    const whole = toggleSeries(NOTHING, F1);
    const withoutAcademy = toggleCategory(whole, F1, "f1a");
    assert.deepEqual(withoutAcademy.seriesCodes, []);
    assert.deepEqual(withoutAcademy.categoryCodes.sort(), ["f1", "f2", "f3"]);
  });

  test("selecting every class collapses back to the series", () => {
    let selection = NOTHING;
    for (const code of F1.categoryCodes) {
      selection = toggleCategory(selection, F1, code);
    }
    // Not tidiness: "f1" keeps meaning "all of Formula 1" when a class is added
    // to the championship, where a list of today's four would exclude it.
    assert.deepEqual(selection, { seriesCodes: ["f1"], categoryCodes: [] });
  });
});

describe("what shows as selected", () => {
  test("nothing is highlighted when everything is shown", () => {
    assert.equal(isCategorySelected(NOTHING, F1, "f2"), false);
  });

  test("a whole series lights up all of its classes", () => {
    const whole = toggleSeries(NOTHING, F1);
    for (const code of F1.categoryCodes) {
      assert.ok(isCategorySelected(whole, F1, code), code);
    }
    assert.equal(selectedCount(whole, F1), 4);
  });

  test("one class lights up only itself", () => {
    const justF2 = toggleCategory(NOTHING, F1, "f2");
    assert.ok(isCategorySelected(justF2, F1, "f2"));
    assert.equal(isCategorySelected(justF2, F1, "f1"), false);
    assert.equal(selectedCount(justF2, F1), 1);
    assert.equal(selectedCount(justF2, MOTOGP), 0);
  });
});

describe("healing a stale selection", () => {
  test("a class that no longer exists is dropped", () => {
    // WorldSSP300 was seeded and then discontinued. A filter naming it would
    // empty the board, and its chip is gone, so nothing could undo it.
    const stale = { seriesCodes: ["f1"], categoryCodes: ["wssp300"] };
    assert.deepEqual(prune(stale, GROUPS), { seriesCodes: ["f1"], categoryCodes: [] });
  });

  test("a series that is still coming soon is dropped", () => {
    const stale = { seriesCodes: ["f1", "indycar"], categoryCodes: [] };
    assert.deepEqual(prune(stale, GROUPS), { seriesCodes: ["f1"], categoryCodes: [] });
  });

  test("a single-class series collapses like any other", () => {
    assert.deepEqual(collapse({ seriesCodes: [], categoryCodes: ["wec"] }, GROUPS), {
      seriesCodes: ["wec"],
      categoryCodes: [],
    });
  });
});
