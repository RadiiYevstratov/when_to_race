import { ImageResponse } from "next/og";

/**
 * The card shown when a link is shared.
 *
 * Generated rather than shipped as a file so it stays in step with the design
 * tokens, and drawn with the Carbon palette so a shared link looks like the
 * site it opens. No external fonts or images: ImageResponse would have to fetch
 * them at request time, and a share preview must not depend on a third party.
 */
export const alt = "ON TRACK - what motorsport is on, and when";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "linear-gradient(160deg, #15171c 0%, #08090a 60%)",
          padding: "72px 80px",
          fontFamily: "monospace",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div style={{ width: 10, height: 44, background: "#E8112D" }} />
          <div style={{ fontSize: 40, color: "#eef0f1", letterSpacing: 6 }}>ON TRACK</div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ fontSize: 68, color: "#eef0f1", lineHeight: 1.1 }}>
            What motorsport is on,
          </div>
          <div style={{ fontSize: 68, color: "#8a9298", lineHeight: 1.1 }}>
            and when.
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 28, fontSize: 26 }}>
          {["FORMULA 1", "MOTOGP", "WORLDSBK", "WEC"].map((series) => (
            <div key={series} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 8, height: 8, background: "#35d183" }} />
              <div style={{ color: "#8a9298" }}>{series}</div>
            </div>
          ))}
          <div style={{ marginLeft: "auto", color: "#565d62" }}>ontrackapp.me</div>
        </div>
      </div>
    ),
    size,
  );
}
