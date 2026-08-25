import type { MetadataRoute } from "next";

/**
 * Web app manifest.
 *
 * Worth having for a schedule: the natural way to use this is to keep it on a
 * phone home screen and open it at a race weekend. `theme_color` matches the
 * board so the browser chrome does not frame a near-black page in white.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "ON TRACK - motorsport schedule",
    short_name: "ON TRACK",
    description:
      "Every practice, qualifying and race session from Formula 1, MotoGP, " +
      "WorldSBK and the FIA WEC, in your own timezone.",
    start_url: "/",
    display: "standalone",
    background_color: "#08090a",
    theme_color: "#08090a",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      // Android crops a maskable icon to its own shape and guarantees only a
      // centred circle of 80% diameter. At the normal inset this mark's corners
      // fall outside that circle - the green square among them - so the maskable
      // copy is a separate, smaller drawing rather than the same file relabelled.
      {
        src: "/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
