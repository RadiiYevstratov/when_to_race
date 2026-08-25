/**
 * What the viewer follows.
 *
 * A selection is a set of tokens. A bare token is a whole series - `motogp`
 * means every category in it, including any added later. A dotted token is one
 * category - `f1.f2` is Formula 2 and nothing else. An empty selection means
 * everything, which is the default and the thing most people want.
 *
 * The prefix is not decoration: without it there is no way to tell the series
 * `f1` from the category `f1`, which are different filters that happen to share
 * a name.
 *
 * This format already existed for calendar feed URLs (`f1.f2+motogp`). The
 * board now uses the same one, so a feed URL and a board filter are the same
 * thing written down, and the subscribe page needs no translation layer.
 */

export interface Selection {
  /** Whole series. Empty *and* no categories means "everything". */
  seriesCodes: string[];
  /** Individual categories, stored bare - category codes are globally unique. */
  categoryCodes: string[];
}

/** A series and the categories under it, as the UI knows them. */
export interface SeriesGroup {
  code: string;
  categoryCodes: string[];
}

export const EMPTY_SELECTION: Selection = { seriesCodes: [], categoryCodes: [] };

export function isEverything(selection: Selection): boolean {
  return selection.seriesCodes.length === 0 && selection.categoryCodes.length === 0;
}

/** Tokens may be separated by `+` (URLs), commas (the cookie) or spaces. */
export function parseSelection(raw: string): Selection {
  const cleaned = decodeURIComponent(raw).replace(/\.ics$/i, "").trim().toLowerCase();
  if (!cleaned || cleaned === "all") return { seriesCodes: [], categoryCodes: [] };

  const seriesCodes: string[] = [];
  const categoryCodes: string[] = [];
  for (const token of cleaned.split(/[+,\s]+/).filter(Boolean)) {
    if (!/^[a-z0-9_]+(\.[a-z0-9_]+)?$/.test(token)) continue;
    if (token.includes(".")) {
      const [, category] = token.split(".");
      if (category) categoryCodes.push(category);
    } else {
      seriesCodes.push(token);
    }
  }
  return { seriesCodes: unique(seriesCodes), categoryCodes: unique(categoryCodes) };
}

/**
 * Back to tokens, with each category prefixed by the series it belongs to.
 *
 * A category the catalogue does not know is dropped rather than written back
 * without a prefix, where it would be read as a series next time.
 */
export function formatSelection(
  selection: Selection,
  groups: SeriesGroup[],
  separator = "+",
): string {
  const owner = new Map<string, string>();
  for (const group of groups) {
    for (const code of group.categoryCodes) owner.set(code, group.code);
  }

  const tokens = [
    ...selection.seriesCodes,
    ...selection.categoryCodes
      .filter((code) => owner.has(code))
      .map((code) => `${owner.get(code)}.${code}`),
  ];
  return tokens.length > 0 ? tokens.join(separator) : "all";
}

export function isSeriesSelected(selection: Selection, group: SeriesGroup): boolean {
  return selection.seriesCodes.includes(group.code);
}

export function isCategorySelected(
  selection: Selection,
  group: SeriesGroup,
  categoryCode: string,
): boolean {
  if (isEverything(selection)) return false;
  return isSeriesSelected(selection, group) || selection.categoryCodes.includes(categoryCode);
}

/** How many of a group's categories are on, for the header's summary. */
export function selectedCount(selection: Selection, group: SeriesGroup): number {
  if (isSeriesSelected(selection, group)) return group.categoryCodes.length;
  return group.categoryCodes.filter((code) => selection.categoryCodes.includes(code)).length;
}

export function toggleSeries(selection: Selection, group: SeriesGroup): Selection {
  const anyOn = selectedCount(selection, group) > 0;
  const withoutGroup: Selection = {
    seriesCodes: selection.seriesCodes.filter((code) => code !== group.code),
    categoryCodes: selection.categoryCodes.filter(
      (code) => !group.categoryCodes.includes(code),
    ),
  };
  // Clicking the name clears the group when any of it is on, so one click
  // always undoes whatever state the group is in.
  return anyOn ? withoutGroup : collapse({
    ...withoutGroup,
    seriesCodes: [...withoutGroup.seriesCodes, group.code],
  }, [group]);
}

export function toggleCategory(
  selection: Selection,
  group: SeriesGroup,
  categoryCode: string,
): Selection {
  // A whole-series token has to be expanded before one category can be removed
  // from underneath it.
  const expanded: Selection = isSeriesSelected(selection, group)
    ? {
        seriesCodes: selection.seriesCodes.filter((code) => code !== group.code),
        categoryCodes: unique([...selection.categoryCodes, ...group.categoryCodes]),
      }
    : selection;

  const on = expanded.categoryCodes.includes(categoryCode);
  const next: Selection = {
    seriesCodes: expanded.seriesCodes,
    categoryCodes: on
      ? expanded.categoryCodes.filter((code) => code !== categoryCode)
      : [...expanded.categoryCodes, categoryCode],
  };
  return collapse(next, [group]);
}

/**
 * Rewrite a fully-selected group back to its series token.
 *
 * Not only for tidiness: `motogp` keeps meaning "all of MotoGP" when a class is
 * added to the championship, where a list of today's three categories would
 * quietly exclude the new one.
 */
export function collapse(selection: Selection, groups: SeriesGroup[]): Selection {
  let seriesCodes = [...selection.seriesCodes];
  let categoryCodes = [...selection.categoryCodes];

  for (const group of groups) {
    if (group.categoryCodes.length === 0) continue;
    const all = group.categoryCodes.every((code) => categoryCodes.includes(code));
    if (!all) continue;
    categoryCodes = categoryCodes.filter((code) => !group.categoryCodes.includes(code));
    if (!seriesCodes.includes(group.code)) seriesCodes.push(group.code);
  }

  return { seriesCodes: unique(seriesCodes), categoryCodes: unique(categoryCodes) };
}

/**
 * Drop anything the catalogue no longer offers.
 *
 * A selection saved before a category existed - or naming one that has gone
 * away - would filter the board down to nothing, with no chip left to click to
 * undo it.
 */
export function prune(selection: Selection, groups: SeriesGroup[]): Selection {
  const seriesKnown = new Set(groups.map((group) => group.code));
  const categoryKnown = new Set(groups.flatMap((group) => group.categoryCodes));
  return {
    seriesCodes: selection.seriesCodes.filter((code) => seriesKnown.has(code)),
    categoryCodes: selection.categoryCodes.filter((code) => categoryKnown.has(code)),
  };
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}
