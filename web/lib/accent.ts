/**
 * Painting a class's identity mark.
 *
 * Almost every class is one colour and this is a one-line answer. The NASCAR
 * Cup Series is three - yellow, red and blue side by side - and choosing one of
 * them would be showing a third of a logo, so its mark is banded instead.
 *
 * The bands are hard stops rather than a gradient. A gradient would blend three
 * strong colours into two muddy seams, and at the size this is drawn - a 3px
 * rule beside a row, a 6px dot in the filter - the blend is most of the mark.
 */

/** The bands of a mark, or a single colour as a one-element list. */
export function accentBands(accentColor: string, accentColors?: string | null): string[] {
  if (!accentColors) return [accentColor];
  const bands = accentColors
    .split(",")
    .map((band) => band.trim())
    .filter(Boolean);
  // One band is the same thing as no bands, and an unparseable value should
  // show the colour we do have rather than nothing at all.
  return bands.length > 1 ? bands : [accentColor];
}

/**
 * A CSS `background` for the mark.
 *
 * Returns a plain colour for the ordinary case, so the common path stays a flat
 * fill rather than a one-stop gradient.
 */
export function accentBackground(accentColor: string, accentColors?: string | null): string {
  const bands = accentBands(accentColor, accentColors);
  if (bands.length === 1) return bands[0];

  // Rounded, because thirds are not exact and 33.333333333333336% in a style
  // attribute is noise. Two decimals is finer than the mark is wide.
  const at = (index: number) => Number(((index * 100) / bands.length).toFixed(2));
  const stops = bands
    .map((band, index) => `${band} ${at(index)}% ${at(index + 1)}%`)
    .join(", ");
  return `linear-gradient(180deg, ${stops})`;
}
