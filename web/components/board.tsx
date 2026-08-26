/**
 * The board.
 *
 * One row per session, read as a column of times down the left edge. The
 * signature element is the day-shift marker: when a session falls on a
 * different calendar day at the circuit than it does for the viewer, the row
 * says so (+1 / -1) instead of quietly filing it under a day that will not
 * match what the broadcaster says.
 *
 * Server-rendered. The only client JavaScript on a schedule page is the
 * countdown.
 */

import Link from "next/link";

import type { SessionRow } from "../lib/queries.ts";
import { dayShift, formatTime, groupByDay, isLive, isStale } from "../lib/time.ts";

const TYPE_LABEL: Record<string, string> = {
  practice: "Practice",
  qualifying: "Qualifying",
  sprint_qualifying: "Sprint qualifying",
  sprint: "Sprint",
  race: "Race",
  warmup: "Warm-up",
  shakedown: "Shakedown",
  stage: "Stage",
  test: "Test",
  other: "Session",
};

export function sessionTypeLabel(type: string): string {
  return TYPE_LABEL[type] ?? "Session";
}

function StatusTag({ session, now }: { session: SessionRow; now: Date }) {
  if (session.status === "cancelled") {
    return <span className="font-mono text-xs text-cancelled">Cancelled</span>;
  }
  if (isLive(session, now)) {
    return (
      <span className="flex items-center gap-1.5 font-mono text-xs text-live">
        <span aria-hidden="true" className="live-dot inline-block h-1.5 w-1.5 rounded-sm bg-live" />
        Live
      </span>
    );
  }
  if (session.status === "delayed") {
    return <span className="font-mono text-xs text-provisional">Delayed</span>;
  }
  if (session.timeStatus !== "confirmed") {
    return (
      <span className="font-mono text-xs text-provisional">
        {session.timeStatus === "tbc" ? "Time TBC" : "Provisional"}
      </span>
    );
  }
  return null;
}

export function BoardRow({
  session,
  timeZone,
  now,
  showEvent = false,
}: {
  session: SessionRow;
  timeZone: string;
  now: Date;
  showEvent?: boolean;
}) {
  const circuitZone = session.sessionTimezone ?? session.circuitTimezone;
  const shift = dayShift(session.startsAtUtc, timeZone, circuitZone);
  const dayOnly = session.startsAtPrecision === "day";
  const stale = isStale(session.lastSuccessfulScrape, now);
  const past = new Date(session.startsAtUtc).getTime() < now.getTime() && !isLive(session, now);

  return (
    <li
      className={`board-row flex items-baseline gap-3 border-b border-rule py-2.5 last:border-b-0 ${
        past ? "opacity-55" : ""
      }`}
    >
      <time
        dateTime={new Date(session.startsAtUtc).toISOString()}
        className="board-time tnum w-[4.5rem] shrink-0 font-mono text-time text-ink"
      >
        {dayOnly ? (
          <span className="text-ink-faint">--:--</span>
        ) : (
          formatTime(session.startsAtUtc, timeZone)
        )}
        {shift !== 0 && !dayOnly ? (
          <sup
            className="ml-0.5 text-[0.625rem] text-ink-faint"
            title={`${shift > 0 ? "The day after" : "The day before"} the circuit's local day`}
          >
            {shift > 0 ? `+${shift}` : shift}
          </sup>
        ) : null}
      </time>

      <span
        aria-hidden="true"
        className="mt-1 h-3.5 w-[3px] shrink-0"
        style={{ backgroundColor: session.categoryAccentColor }}
      />

      <span className="w-20 shrink-0 font-mono text-xs text-ink-muted">
        {session.categoryShortName}
      </span>

      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm">{session.displayName}</span>
        {showEvent ? (
          <Link
            href={`/weekend/${session.seriesCode}/${session.season}/${session.eventSlug}`}
            className="block truncate text-xs text-ink-muted hover:text-ink"
          >
            {session.eventName}
          </Link>
        ) : null}
      </span>

      <span className="flex shrink-0 items-center gap-2">
        <StatusTag session={session} now={now} />
        {stale ? (
          <span
            className="font-mono text-[0.625rem] text-ink-faint"
            title="This series has not updated in over 48 hours; times may be out of date."
          >
            stale
          </span>
        ) : null}
      </span>
    </li>
  );
}

export function DayBoard({
  sessions,
  timeZone,
  now,
  showEvent = false,
  headingLevel = 3,
}: {
  sessions: SessionRow[];
  timeZone: string;
  now: Date;
  showEvent?: boolean;
  /**
   * What level the day headings sit at.
   *
   * On the home page the board lives inside an h2 section, so its days are
   * h3s. On a weekend page it is the page's only content and follows the h1
   * directly, and an h1 followed by an h3 is a level a screen reader announces
   * as missing.
   */
  headingLevel?: 2 | 3;
}) {
  const groups = groupByDay(sessions, timeZone);
  const DayHeading = (headingLevel === 2 ? "h2" : "h3") as "h2" | "h3";

  return (
    <div className="space-y-8">
      {groups.map((group) => (
        <section key={group.key}>
          <DayHeading className="eyebrow border-b border-ink pb-1.5">{group.heading}</DayHeading>
          <ul className="mt-1">
            {group.items.map((session) => (
              <BoardRow
                key={session.id}
                session={session}
                timeZone={timeZone}
                now={now}
                showEvent={showEvent}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export function EmptyBoard({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="border border-dashed border-rule px-4 py-10 text-center">
      <p className="text-sm text-ink-muted">{message}</p>
      {hint ? <p className="mt-1 text-xs text-ink-faint">{hint}</p> : null}
    </div>
  );
}
