/**
 * Reading what came in through the contact form.
 *
 * Behind the same basic auth as the health dashboard - middleware guards the
 * whole of /admin, so there is no separate check here and no separate password
 * to lose.
 *
 * Deliberately plain. This is an operational page for one person: no paging, no
 * search, no reply box. It shows the message and the address it came from, and
 * replying happens in a mail client where replying belongs.
 */

import type { Metadata } from "next";

import { recentMessages } from "../../../lib/contact-store.ts";

export const dynamic = "force-dynamic";

// An operational page, and one nobody but the operator should be looking at.
export const metadata: Metadata = {
  title: "Messages",
  robots: { index: false, follow: false },
};

function stamp(value: Date): string {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(value);
}

export default async function MessagesPage() {
  const messages = await recentMessages();
  const unread = messages.filter((message) => message.handledAt === null).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl">Messages</h1>
        <p className="mt-1 text-sm text-ink-muted">
          {messages.length === 0
            ? "Nothing yet."
            : `${messages.length} message${messages.length === 1 ? "" : "s"}, ${unread} unread. Times in UTC.`}
        </p>
      </div>

      {messages.map((message) => (
        <article
          key={message.id}
          className="border border-rule bg-panel p-4"
        >
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="text-sm font-semibold">{message.subject}</h2>
            {message.handledAt === null ? (
              <span className="font-mono text-xs uppercase tracking-wide text-live">New</span>
            ) : null}
            <span className="ml-auto font-mono text-xs text-ink-faint">
              #{message.id} &middot; {stamp(message.submittedAt)}
            </span>
          </div>

          {/* Why no email arrived, next to the message it is about. "skipped"
              means no provider is configured, which is a supported state
              rather than a fault; anything else is what the provider said. */}
          {message.notifyStatus && message.notifyStatus !== "sent" ? (
            <p className="mt-2 border-l-2 border-provisional pl-3 font-mono text-xs text-provisional">
              {message.notifyStatus === "skipped"
                ? "No email sent: notifications are not configured."
                : `No email sent — ${message.notifyStatus}`}
            </p>
          ) : null}

          <p className="mt-1 text-xs text-ink-muted">
            {message.name} &middot;{" "}
            <a
              href={`mailto:${message.email}?subject=${encodeURIComponent(`Re: ${message.subject}`)}`}
              className="border-b border-ink-faint hover:text-ink"
            >
              {message.email}
            </a>
          </p>

          {/* Whitespace preserved and never rendered as markup: this is text a
              stranger typed, and the only safe thing to do with it is show it
              as text. React escapes it; `whitespace-pre-wrap` keeps the line
              breaks the writer put in. */}
          <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{message.body}</p>
        </article>
      ))}
    </div>
  );
}
