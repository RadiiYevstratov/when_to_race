/**
 * Contact.
 *
 * The footer already carries an address, and that is a different thing: it
 * asks someone to leave the site, open a mail client and start from a blank
 * page. Most people do not. A form asks for four fields and takes the message
 * where it is.
 *
 * The circuits note is here rather than in the footer because this is where it
 * gets read. The site lists forty-odd venues with their own pages, and a
 * reader who has just been looking at one is exactly the person about to ask
 * us about tickets for it.
 */

import type { Metadata } from "next";

import { RETENTION_DAYS } from "../../lib/contact-store.ts";
import { CONTACT_EMAIL } from "../../lib/official-sites.ts";
import { ContactForm } from "./contact-form.tsx";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Contact us",
  description:
    "Get in touch with ON TRACK. Tell us about a missing championship, a session time " +
    "that looks wrong, or anything that would make the schedule more useful.",
  alternates: { canonical: "/contact" },
};

export default function ContactPage() {
  return (
    <div className="max-w-2xl">
      <h1 className="text-3xl leading-tight">Contact us</h1>

      <p className="mt-4 text-sm text-ink-muted">
        If you want to get in touch with ontrackapp.me, please use the form below. We welcome
        your feedback, so please do get in touch — a championship that is missing, a feature
        that would make the board more useful, or a session time that looks wrong.
      </p>

      <p className="mt-4 border-l-2 border-rule pl-4 text-sm text-ink-faint">
        <strong className="text-ink-muted">Please note:</strong> we do not own, operate or
        have any affiliation with the circuits listed on this website. Any enquiry about
        track availability, bookings or tickets for an event should be made directly with
        the relevant circuit or promoter.
      </p>

      <div className="mt-8">
        <ContactForm />
      </div>

      <p className="mt-8 border-t border-rule pt-5 text-xs text-ink-faint">
        We keep what you send for {RETENTION_DAYS} days and then delete it. Your address is
        used to reply to you and for nothing else.
      </p>

      <p className="mt-2 text-xs text-ink-faint">
        If you would rather write to us directly, the address is{" "}
        <a
          href={`mailto:${CONTACT_EMAIL}`}
          className="border-b border-ink-faint hover:text-ink"
        >
          {CONTACT_EMAIL}
        </a>
        {"."}
      </p>
    </div>
  );
}
