/**
 * Painting a class's identity mark.
 *
 * The NASCAR Cup Series is the reason this exists: three colours side by side,
 * where every other class here is one. What is worth pinning is that the
 * ordinary case did not become a special case - a single colour still paints as
 * a flat fill, not a one-stop gradient - and that a malformed value shows the
 * colour we do have rather than nothing at all.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { accentBackground, accentBands } from "../lib/accent.ts";

describe("accent marks", () => {
  test("one colour stays a flat fill", () => {
    assert.equal(accentBackground("#0096D6"), "#0096D6");
    assert.equal(accentBackground("#0096D6", null), "#0096D6");
    assert.deepEqual(accentBands("#0096D6", null), ["#0096D6"]);
  });

  test("three colours become three hard-edged bands", () => {
    // Hard stops rather than a blend: at 3px wide, a gradient between three
    // strong colours is mostly the muddy seams between them.
    const cup = accentBackground("#FCD43D", "#FCD43D,#EE293D,#1478C7");
    assert.equal(
      cup,
      "linear-gradient(180deg, #FCD43D 0% 33.33%, #EE293D 33.33% 66.67%, #1478C7 66.67% 100%)",
    );
  });

  test("the bands are read in the order they are stored", () => {
    assert.deepEqual(accentBands("#FCD43D", "#FCD43D,#EE293D,#1478C7"), [
      "#FCD43D",
      "#EE293D",
      "#1478C7",
    ]);
  });

  test("whitespace around a band does not break it", () => {
    assert.deepEqual(accentBands("#A", "#FCD43D, #EE293D"), ["#FCD43D", "#EE293D"]);
  });

  test("a single band is the same thing as none", () => {
    // Otherwise the mark would be a gradient from a colour to itself, and the
    // stored value would be a second place to change one colour.
    assert.equal(accentBackground("#DE1E26", "#DE1E26"), "#DE1E26");
  });

  test("an unusable value falls back to the colour we do have", () => {
    assert.equal(accentBackground("#DE1E26", ""), "#DE1E26");
    assert.equal(accentBackground("#DE1E26", "   "), "#DE1E26");
    assert.equal(accentBackground("#DE1E26", ","), "#DE1E26");
  });
});
