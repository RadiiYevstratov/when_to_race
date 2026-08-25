"use client";

/**
 * The countdown ticks, so it has to be a client component. It renders the
 * server-computed string first and only starts updating after hydration, which
 * keeps the first paint correct and identical on both sides.
 */

import { useEffect, useState } from "react";

import { countdown, formatCountdown } from "../lib/time.ts";

export function Countdown({
  target,
  initialLabel,
  className = "",
}: {
  target: string;
  initialLabel: string;
  className?: string;
}) {
  const [label, setLabel] = useState(initialLabel);

  useEffect(() => {
    function tick() {
      setLabel(formatCountdown(countdown(target)));
    }
    tick();
    const value = countdown(target);
    // Tick every second inside the final hour, every 30 seconds before that.
    const interval = window.setInterval(tick, value.totalMs > 3_600_000 ? 30_000 : 1000);
    return () => window.clearInterval(interval);
  }, [target]);

  return (
    <span className={`tnum font-mono ${className}`} aria-live="polite">
      {label}
    </span>
  );
}
