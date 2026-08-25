/**
 * Renders a JSON-LD block.
 *
 * dangerouslySetInnerHTML is the documented way to emit a script body in React,
 * and the payload is built by lib/structured-data.ts from database rows rather
 * than from anything a visitor controls. The `<` escape still matters: a venue
 * or event name containing "</script" would otherwise close the tag early and
 * spill the rest of the payload into the document as markup.
 */
export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(data).replace(/</g, "\u003c"),
      }}
    />
  );
}
