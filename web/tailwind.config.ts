import type { Config } from "tailwindcss";

/**
 * Colours are declared as CSS variables in globals.css and referenced here, so
 * light and dark are one token set with two values rather than two themes to
 * keep in sync.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        board: "var(--board)",
        panel: "var(--panel)",
        rule: "var(--rule)",
        ink: "var(--ink)",
        "ink-muted": "var(--ink-muted)",
        "ink-faint": "var(--ink-faint)",
        live: "var(--live)",
        provisional: "var(--provisional)",
        cancelled: "var(--cancelled)",
      },
      fontFamily: {
        sans: ["var(--font-archivo)", "system-ui", "sans-serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "monospace"],
      },
      fontSize: {
        // The whole type scale is bumped +2px from the Tailwind defaults per
        // design direction. Spacing is left alone (it lives in separate padding
        // utilities), so only text grows, not the layout.
        xs: ["0.875rem", { lineHeight: "1.125rem" }], // 14px (was 12)
        sm: ["1rem", { lineHeight: "1.375rem" }], // 16px (was 14)
        base: ["1.125rem", { lineHeight: "1.625rem" }], // 18px (was 16)
        lg: ["1.25rem", { lineHeight: "1.875rem" }], // 20px (was 18)
        xl: ["1.375rem", { lineHeight: "1.875rem" }], // 22px (was 20)
        "2xl": ["1.625rem", { lineHeight: "2.125rem" }], // 26px (was 24)
        "3xl": ["2rem", { lineHeight: "2.375rem" }], // 32px (was 30)
        eyebrow: ["0.8125rem", { lineHeight: "1", letterSpacing: "0.12em" }], // 13px (was 11)
        // The departure-board time size. Named "time" rather than "board": a
        // "board" text token collides with the "board" colour (the surface),
        // and text-board then paints the time in the background colour.
        time: ["1.1875rem", { lineHeight: "1.2" }], // 19px (was 17)
      },
      borderRadius: {
        // A departure board has no soft corners. One small radius, used sparingly.
        none: "0",
        sm: "2px",
      },
    },
  },
  plugins: [],
};

export default config;
