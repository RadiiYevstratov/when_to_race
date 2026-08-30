"use server";

/**
 * Receiving a message from a stranger.
 *
 * The order matters and is the whole design: check the honeypot, rate limit,
 * validate, store, and only then try to notify. Storing before notifying means
 * a mail provider having a bad afternoon costs a notification rather than
 * somebody's message.
 */

import { headers } from "next/headers";

import { assess, type ContactState } from "../../lib/contact.ts";
import { storeMessage } from "../../lib/contact-store.ts";
import { notifyOwner } from "../../lib/contact-notify.ts";

/**
 * Three messages per address per quarter hour.
 *
 * In memory, with the same limitation as the admin guard in middleware.ts: one
 * process holds one map, so this slows a flood per instance rather than
 * globally. For a contact form on a schedule site that is the right amount of
 * machinery - the alternative is adding Redis to stop someone sending a fourth
 * email.
 *
 * Keyed on the forwarded address and never stored anywhere. The database keeps
 * no IP at all, which is why this map forgets by itself.
 */
const RECENT = new Map<string, number[]>();
const WINDOW_MS = 15 * 60 * 1000;
const MAX_PER_WINDOW = 3;

function tooMany(key: string): boolean {
  const now = Date.now();
  const times = (RECENT.get(key) ?? []).filter((at) => now - at < WINDOW_MS);
  if (times.length >= MAX_PER_WINDOW) {
    RECENT.set(key, times);
    return true;
  }
  times.push(now);
  RECENT.set(key, times);

  // Bounded so a stream of distinct addresses cannot grow this without limit.
  if (RECENT.size > 1000) {
    for (const [existing, stamps] of RECENT) {
      if (stamps.every((at) => now - at >= WINDOW_MS)) RECENT.delete(existing);
    }
  }
  return false;
}

async function clientKey(): Promise<string> {
  const list = await headers();
  const forwarded = list.get("x-forwarded-for") ?? "";
  return forwarded.split(",")[0]?.trim() || "unknown";
}

export async function submitContact(
  _previous: ContactState,
  form: FormData,
): Promise<ContactState> {
  const { ok, trap, errors, values } = assess(form);

  // A bot that filled the hidden field is told the same thing as a person who
  // succeeded. Saying "caught you" only teaches the next version not to.
  if (trap) return { status: "sent", errors: {} };

  if (!ok) return { status: "error", errors, values };

  if (await clientKey().then(tooMany)) {
    return {
      status: "error",
      values,
      errors: {
        form: "That is a few messages in a short time. Please try again in a little while.",
      },
    };
  }

  try {
    const id = await storeMessage(values);
    // Never allowed to fail the submission: the message is already saved, and
    // the person who wrote it should not see an error because an email did not
    // go out.
    await notifyOwner(values, id);
  } catch (error) {
    console.error("contact: could not store message", error);
    return {
      status: "error",
      values,
      errors: {
        form:
          "Something went wrong at our end and the message was not saved. " +
          "Please try again, or email us directly.",
      },
    };
  }

  return { status: "sent", errors: {} };
}
