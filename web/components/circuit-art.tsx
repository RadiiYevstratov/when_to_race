/**
 * The traced outline of a circuit, drawn faintly behind a card's text.
 *
 * Renders nothing when the venue has no traced map, so a venue never gets an
 * approximated stand-in - see lib/circuits.ts for why that matters.
 */

import { circuitPath } from "../lib/circuits.ts";

export function CircuitArt({ venueSlug }: { venueSlug: string | null | undefined }) {
  const path = circuitPath(venueSlug);
  if (!path) return null;

  return (
    // Filled rather than stroked: the traced paths are the ribbon's own outline
    // plus a subpath per enclosed area, so even-odd fill reproduces the source
    // silhouette exactly instead of approximating it with a stroke width.
    <svg className="circuit-art" viewBox="0 0 480 260" aria-hidden="true">
      <path d={path} fill="currentColor" fillRule="evenodd" />
    </svg>
  );
}
