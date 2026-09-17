/**
 * The card for one social post.
 *
 * This route exists because Instagram will not accept an upload: it fetches the
 * image from a public URL. Rather than add an object store and another
 * credential, the job writes the rendered JPEG into the row and this serves it
 * from there - the site is already public, so the image is too.
 *
 * Instagram fetches once, shortly after the row is written, and never again.
 * The long cache header is for everything else that might follow the link
 * later; the bytes for a given id never change, because a new post is a new row.
 */

import { NextResponse } from "next/server";

import { getSocialCard } from "../../../../../lib/queries.ts";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  // "12.jpg" and "12" both work: the extension is there so the URL ends in
  // something Instagram's fetcher recognises as an image.
  const numeric = Number.parseInt(id.replace(/\.jpe?g$/i, ""), 10);
  if (!Number.isInteger(numeric) || numeric <= 0 || numeric > 2_147_483_647) {
    return new NextResponse("Not found", { status: 404 });
  }

  const card = await getSocialCard(numeric);
  if (!card) {
    return new NextResponse("Not found", { status: 404 });
  }

  return new NextResponse(new Uint8Array(card.bytes), {
    headers: {
      "Content-Type": card.mediaType,
      "Content-Length": String(card.bytes.length),
      "Cache-Control": "public, max-age=31536000, immutable",
      // Nothing here is private, but it is also not a page: keep it out of
      // search results rather than have a bare image indexed under the domain.
      "X-Robots-Tag": "noindex",
    },
  });
}
