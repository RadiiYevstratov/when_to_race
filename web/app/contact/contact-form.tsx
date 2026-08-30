"use client";

/**
 * The form itself.
 *
 * A client component only because it needs `useActionState` to show what went
 * wrong beside the field that went wrong. Everything it does works without
 * JavaScript too: it is a plain form posting to a server action, so a browser
 * with scripting off still submits and still gets an answer.
 *
 * Errors are announced rather than only coloured. Someone using a screen
 * reader finds out the form was rejected at the moment it happens, and each
 * message is tied to its input with aria-describedby rather than sitting near
 * it visually.
 */

import { useActionState } from "react";

import {
  EMPTY_STATE,
  HONEYPOT_FIELD,
  LIMITS,
  type ContactState,
} from "../../lib/contact.ts";
import { submitContact } from "./actions.ts";

const field = "w-full border border-rule bg-panel px-3 py-2 text-sm text-ink " +
  "placeholder:text-ink-faint focus:border-ink focus:outline-none";
const label = "block font-mono text-xs uppercase tracking-wide text-ink-muted";

function Error({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="mt-1 text-xs text-cancelled">
      {message}
    </p>
  );
}

export function ContactForm() {
  const [state, action, pending] = useActionState<ContactState, FormData>(
    submitContact,
    EMPTY_STATE,
  );

  if (state.status === "sent") {
    return (
      <div
        role="status"
        className="border border-live/40 bg-panel px-4 py-6 text-sm"
      >
        <p className="text-live">Thank you — your message has been sent.</p>
        <p className="mt-2 text-ink-muted">
          We read everything that comes in. If your message needs an answer, we will reply
          to the address you gave.
        </p>
      </div>
    );
  }

  const values = state.values;

  return (
    <form action={action} className="space-y-5" noValidate>
      {state.errors.form ? (
        <p role="alert" className="border border-cancelled/40 px-3 py-2 text-sm text-cancelled">
          {state.errors.form}
        </p>
      ) : null}

      <div>
        <label htmlFor="contact-name" className={label}>
          Name <span aria-hidden="true">*</span>
        </label>
        <input
          id="contact-name"
          name="name"
          required
          maxLength={LIMITS.name}
          autoComplete="name"
          defaultValue={values?.name}
          aria-invalid={state.errors.name ? true : undefined}
          aria-describedby={state.errors.name ? "contact-name-error" : undefined}
          className={`mt-1 ${field}`}
        />
        <Error id="contact-name-error" message={state.errors.name} />
      </div>

      <div>
        <label htmlFor="contact-email" className={label}>
          Email <span aria-hidden="true">*</span>
        </label>
        <input
          id="contact-email"
          name="email"
          type="email"
          required
          maxLength={LIMITS.email}
          autoComplete="email"
          defaultValue={values?.email}
          aria-invalid={state.errors.email ? true : undefined}
          aria-describedby={state.errors.email ? "contact-email-error" : undefined}
          className={`mt-1 ${field}`}
        />
        <Error id="contact-email-error" message={state.errors.email} />
      </div>

      <div>
        <label htmlFor="contact-subject" className={label}>
          Subject <span aria-hidden="true">*</span>
        </label>
        <input
          id="contact-subject"
          name="subject"
          required
          maxLength={LIMITS.subject}
          defaultValue={values?.subject}
          aria-invalid={state.errors.subject ? true : undefined}
          aria-describedby={state.errors.subject ? "contact-subject-error" : undefined}
          className={`mt-1 ${field}`}
        />
        <Error id="contact-subject-error" message={state.errors.subject} />
      </div>

      <div>
        <label htmlFor="contact-message" className={label}>
          Message <span aria-hidden="true">*</span>
        </label>
        <textarea
          id="contact-message"
          name="message"
          required
          rows={8}
          maxLength={LIMITS.body}
          defaultValue={values?.body}
          aria-invalid={state.errors.body ? true : undefined}
          aria-describedby={state.errors.body ? "contact-message-error" : undefined}
          className={`mt-1 ${field}`}
        />
        <Error id="contact-message-error" message={state.errors.body} />
      </div>

      {/* Not a captcha. A field no person can see and a crude bot fills in
          anyway - it costs nothing, needs no third-party script, and does not
          make a human prove anything. aria-hidden and tabIndex keep it away
          from screen readers and the keyboard, so it is invisible to everyone
          it should be invisible to. */}
      <div className="hidden" aria-hidden="true">
        <label htmlFor="contact-website">Leave this field empty</label>
        <input id="contact-website" name={HONEYPOT_FIELD} tabIndex={-1} autoComplete="off" />
      </div>

      <div className="flex items-center gap-4">
        <button
          type="submit"
          disabled={pending}
          className="border border-ink px-5 py-2 font-mono text-xs uppercase tracking-wide hover:bg-panel disabled:opacity-50"
        >
          {pending ? "Sending…" : "Send message"}
        </button>
        <span className="text-xs text-ink-faint">
          <span aria-hidden="true">*</span> Required
        </span>
      </div>
    </form>
  );
}
