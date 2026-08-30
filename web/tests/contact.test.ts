/**
 * The contact form's gatekeeping.
 *
 * This is the only place on the site where a stranger's input is accepted and
 * stored, so what matters here is what gets refused: a message with no way to
 * reply to it, a subject line carrying a second email header, and a bot that
 * filled in a field no person can see.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  HONEYPOT_FIELD,
  LIMITS,
  assess,
  hasHeaderInjection,
  looksLikeEmail,
  validate,
} from "../lib/contact.ts";
import { buildNotification } from "../lib/contact-notify.ts";

function form(fields: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.append(key, value);
  return data;
}

const GOOD = {
  name: "Radii",
  email: "someone@example.com",
  subject: "Missing championship",
  message: "Any chance of adding the British Touring Car Championship?",
};

describe("contact validation", () => {
  test("a complete message is accepted", () => {
    const result = assess(form(GOOD));
    assert.equal(result.ok, true);
    assert.equal(result.trap, false);
    assert.deepEqual(result.errors, {});
    assert.equal(result.values.body, GOOD.message);
  });

  test("every field is required", () => {
    const errors = validate({ name: "", email: "", subject: "", body: "" });
    assert.deepEqual(Object.keys(errors).sort(), ["body", "email", "name", "subject"]);
  });

  test("whitespace alone is not an answer", () => {
    const result = assess(form({ ...GOOD, name: "   ", message: "  \n  " }));
    assert.equal(result.ok, false);
    assert.ok(result.errors.name);
    assert.ok(result.errors.body);
  });

  test("an address has to be plausible, without being pedantic about it", () => {
    // Real addresses that a strict pattern would wrongly reject.
    for (const address of [
      "someone+ontrack@example.com",
      "a@b.co",
      "first.last@sub.domain.museum",
      "someone@example.travel",
    ]) {
      assert.equal(looksLikeEmail(address), true, address);
    }
    for (const address of ["someone", "@example.com", "a@b", "two@at@example.com", "a b@c.com"]) {
      assert.equal(looksLikeEmail(address), false, address);
    }
  });

  test("a newline in the name or subject is refused, not stripped", () => {
    // These end up in an email header. A newline there lets a sender append
    // their own - a Bcc to a list, a different Reply-To - and turn the form
    // into a relay. Refused rather than cleaned, so the attempt is visible.
    assert.equal(hasHeaderInjection("Bcc: everyone@example.com"), false);
    assert.equal(hasHeaderInjection("Subject\nBcc: everyone@example.com"), true);
    assert.equal(hasHeaderInjection("Name\rBcc: x@y.com"), true);

    const injected = assess(form({ ...GOOD, subject: "Hello\nBcc: everyone@example.com" }));
    assert.equal(injected.ok, false);
    assert.ok(injected.errors.subject);
  });

  test("a message body may contain newlines, because it is a message", () => {
    const result = assess(form({ ...GOOD, message: "One line.\n\nAnd another." }));
    assert.equal(result.ok, true);
  });

  test("over-long fields are refused", () => {
    assert.ok(validate({ ...GOOD, body: GOOD.message, name: "x".repeat(LIMITS.name + 1) }).name);
    assert.ok(validate({ ...GOOD, body: "x".repeat(LIMITS.body + 1) }).body);
    assert.ok(
      validate({ ...GOOD, body: GOOD.message, subject: "x".repeat(LIMITS.subject + 1) }).subject,
    );
  });

  test("a filled honeypot is caught and told nothing", () => {
    // Reported as fine with nothing to store. An error message here would only
    // teach whoever wrote the bot to leave the field alone next time.
    const result = assess(form({ ...GOOD, [HONEYPOT_FIELD]: "http://spam.example" }));
    assert.equal(result.trap, true);
    assert.equal(result.ok, true);
    assert.deepEqual(result.errors, {});
  });

  test("an empty honeypot is what a person sends", () => {
    const result = assess(form({ ...GOOD, [HONEYPOT_FIELD]: "" }));
    assert.equal(result.trap, false);
    assert.equal(result.ok, true);
  });
});

describe("notification email", () => {
  const fields = {
    name: "Radii",
    email: "someone@example.com",
    subject: "Missing championship",
    body: "Any chance of adding the BTCC?",
  };

  test("replying answers the person who wrote in", () => {
    const mail = buildNotification(fields, 42, "owner@example.com");
    assert.equal(mail.reply_to, "someone@example.com");
    assert.deepEqual(mail.to, ["owner@example.com"]);
  });

  test("the subject carries the sender's own words", () => {
    const mail = buildNotification(fields, 42, "owner@example.com");
    assert.equal(mail.subject, "[ON TRACK] Missing championship");
  });

  test("the body carries who wrote it and which message it is", () => {
    const mail = buildNotification(fields, 42, "owner@example.com");
    assert.match(mail.text, /Radii <someone@example\.com>/);
    assert.match(mail.text, /Message #42/);
    assert.match(mail.text, /adding the BTCC/);
  });
});
