/**
 * Reading and checking what someone typed into the contact form.
 *
 * Pure functions, deliberately: this is the part that decides whether a
 * stranger's message is accepted, and it should be testable without a database
 * or a request. The action does the storing; this does the deciding.
 *
 * Every limit here is also a CHECK constraint in the database. That is not
 * redundancy for its own sake - the form is one client of this table and the
 * database is the last place that can still say no.
 */

export const LIMITS = {
  name: 100,
  email: 254, // the maximum length of an address, per RFC 5321
  subject: 150,
  body: 5000,
} as const;

export interface ContactFields {
  name: string;
  email: string;
  subject: string;
  body: string;
}

export interface ContactErrors {
  name?: string;
  email?: string;
  subject?: string;
  body?: string;
  form?: string;
}

export interface ContactResult {
  ok: boolean;
  errors: ContactErrors;
  /** What the person typed, so a rejected form can be sent back filled in. */
  values: ContactFields;
}

/** The field a person never sees and a crude bot fills in anyway. */
export const HONEYPOT_FIELD = "website";

function text(value: FormDataEntryValue | null): string {
  // A File here means someone posted something other than this form.
  return typeof value === "string" ? value.trim() : "";
}

export function readFields(form: FormData): ContactFields {
  return {
    name: text(form.get("name")),
    email: text(form.get("email")),
    subject: text(form.get("subject")),
    body: text(form.get("message")),
  };
}

/**
 * Is this address plausible?
 *
 * Deliberately loose. The only way to know an address works is to send to it,
 * and a strict pattern rejects valid addresses that people really have - plus
 * signs, new top-level domains, unicode. This catches a typo and a bot posting
 * junk, and lets everything else through rather than telling someone their own
 * address is wrong.
 */
export function looksLikeEmail(value: string): boolean {
  if (value.length > LIMITS.email) return false;
  if (/\s/.test(value)) return false;
  const at = value.indexOf("@");
  if (at < 1 || at !== value.lastIndexOf("@")) return false;
  const domain = value.slice(at + 1);
  return domain.includes(".") && !domain.startsWith(".") && !domain.endsWith(".");
}

/**
 * Header injection, which is the one thing a contact form must not pass on.
 *
 * The name and subject end up in an email notification. A newline in either
 * lets someone append their own headers - a Bcc to a mailing list, a different
 * Reply-To - and turn this form into a relay for sending mail to strangers.
 * There is no legitimate newline in a name or a subject line, so this is a
 * refusal rather than a strip: silently removing it would hide the attempt.
 */
export function hasHeaderInjection(value: string): boolean {
  return /[\r\n]/.test(value);
}

export function validate(fields: ContactFields): ContactErrors {
  const errors: ContactErrors = {};

  if (!fields.name) errors.name = "Please tell us your name.";
  else if (fields.name.length > LIMITS.name) errors.name = `Please keep this under ${LIMITS.name} characters.`;
  else if (hasHeaderInjection(fields.name)) errors.name = "Please use a single line.";

  if (!fields.email) errors.email = "Please give us an address to reply to.";
  else if (!looksLikeEmail(fields.email)) errors.email = "That does not look like an email address.";

  if (!fields.subject) errors.subject = "Please give the message a subject.";
  else if (fields.subject.length > LIMITS.subject)
    errors.subject = `Please keep this under ${LIMITS.subject} characters.`;
  else if (hasHeaderInjection(fields.subject)) errors.subject = "Please use a single line.";

  if (!fields.body) errors.body = "Please write a message.";
  else if (fields.body.length > LIMITS.body)
    errors.body = `Please keep this under ${LIMITS.body} characters.`;

  return errors;
}

/**
 * Everything the action needs to decide, in one place.
 *
 * A filled honeypot is reported as `ok` with nothing to store. Telling a bot it
 * was caught only teaches whoever wrote it to stop filling the field in, and
 * the person who does not exist is not owed an error message.
 */
export function assess(form: FormData): ContactResult & { trap: boolean } {
  const values = readFields(form);
  const trap = text(form.get(HONEYPOT_FIELD)) !== "";
  if (trap) return { ok: true, trap: true, errors: {}, values };

  const errors = validate(values);
  return { ok: Object.keys(errors).length === 0, trap: false, errors, values };
}

/**
 * What the form shows after a submission.
 *
 * Lives here rather than beside the action because a "use server" module may
 * only export async functions - exporting this constant from there gave the
 * form `undefined` on its first render, which is a blank page rather than a
 * form. Types are erased and would have been fine; the value was not.
 */
export interface ContactState {
  status: "idle" | "sent" | "error";
  errors: ContactErrors;
  /** Sent back so a rejected form comes back filled in rather than blank. */
  values?: ContactFields;
}

export const EMPTY_STATE: ContactState = { status: "idle", errors: {} };
