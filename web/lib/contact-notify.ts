/**
 * Telling the operator a message arrived.
 *
 * Optional on purpose, and off until configured. The contact form works
 * without this: every message is stored, and /admin/messages lists them. What
 * this adds is not having to remember to look.
 *
 * Set both to turn it on:
 *   RESEND_API_KEY   an API key from resend.com
 *   CONTACT_TO       where to send the notification
 *   CONTACT_FROM     optional; must be an address on a domain verified with
 *                    the provider. Defaults to Resend's shared sending domain,
 *                    which works without verifying anything.
 *
 * This must never be the reason a submission fails, so every path here either
 * returns quietly or logs and returns. The caller has already saved the row.
 */

import type { ContactFields } from "./contact.ts";

const ENDPOINT = "https://api.resend.com/emails";
const DEFAULT_FROM = "ON TRACK <onboarding@resend.dev>";

export interface Notification {
  from: string;
  to: string[];
  subject: string;
  text: string;
  reply_to: string;
}

/**
 * What gets sent. Separated from the sending so it can be tested.
 *
 * `reply_to` is the point of the whole thing: hitting reply in a mail client
 * answers the person who wrote in, without their address having to be copied
 * out of a web page by hand.
 */
export function buildNotification(
  fields: ContactFields,
  id: number,
  to: string,
  from: string = DEFAULT_FROM,
): Notification {
  return {
    from,
    to: [to],
    // The subject is the sender's own words, which is what makes an inbox
    // useful - and it is why the validator refuses a newline in it.
    subject: `[ON TRACK] ${fields.subject}`,
    reply_to: fields.email,
    text: [
      `From: ${fields.name} <${fields.email}>`,
      `Message #${id}`,
      "",
      fields.body,
      "",
      "--",
      "Sent from the contact form at ontrackapp.me",
    ].join("\n"),
  };
}

/**
 * The outcome, so it can be recorded against the message.
 *
 * "skipped" is not a failure - it is the supported state when no provider is
 * configured. Anything else that is not "sent" is the provider's own refusal,
 * kept verbatim because it is usually the entire answer.
 */
export async function notifyOwner(fields: ContactFields, id: number): Promise<string> {
  const key = process.env.RESEND_API_KEY;
  const to = process.env.CONTACT_TO;
  if (!key || !to) return "skipped";

  try {
    const reply = await fetch(ENDPOINT, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(buildNotification(fields, id, to, process.env.CONTACT_FROM)),
      // A message already saved is not worth holding a request open for.
      signal: AbortSignal.timeout(8000),
    });

    if (reply.ok) return "sent";

    // The body is where the useful part is: a shared sending domain that will
    // only deliver to the account owner says exactly that here. Truncated
    // because this is a status column, not a log.
    const detail = await reply.text().catch(() => "");
    const status = `HTTP ${reply.status}: ${detail.slice(0, 400)}`.trim();
    console.error(`contact: notification refused for message ${id} - ${status}`);
    return status;
  } catch (error) {
    const status = `request failed: ${error instanceof Error ? error.message : String(error)}`;
    console.error(`contact: notification failed for message ${id}`, error);
    return status.slice(0, 400);
  }
}
