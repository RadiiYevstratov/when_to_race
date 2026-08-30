/**
 * The one place the web app writes.
 *
 * Kept out of queries.ts on purpose. That module is the read side and says so
 * in its first line; putting an INSERT in it would quietly retire a rule the
 * whole project is built on. A separate file makes the exception visible to
 * anyone looking for it, and keeps "does the web app write to the schedule?"
 * answerable with a straight no.
 */

import { and, desc, eq, gte, lt, sql } from "drizzle-orm";

import { db } from "./queries.ts";
import { contactMessages } from "./schema.ts";
import type { ContactFields } from "./contact.ts";

/**
 * How long a message is kept.
 *
 * Deleted rather than hidden, and that is the point: a message nobody needs any
 * more is data about a stranger sitting in a database for no reason. Seven days
 * is long enough to read and answer one, and short enough that this never
 * becomes an archive of other people's correspondence.
 *
 * The consequence is worth stating plainly rather than discovering: with no
 * email notification configured, a message that is not read within seven days
 * is gone. That is the trade of keeping them in one place and not keeping them
 * long.
 */
export const RETENTION_DAYS = 7;

function cutoff(now: Date): Date {
  return new Date(now.getTime() - RETENTION_DAYS * 86_400_000);
}

/**
 * Delete everything past its keep-by date.
 *
 * Runs when a message arrives and when the admin page is opened - the two
 * moments this table is touched at all - so it needs no scheduler and cannot
 * drift out of step with what the page shows. Idempotent, so running it twice
 * in a second is not a problem.
 */
export async function purgeExpired(now: Date = new Date()): Promise<number> {
  const removed = await db
    .delete(contactMessages)
    .where(lt(contactMessages.submittedAt, cutoff(now)))
    .returning({ id: contactMessages.id });
  return removed.length;
}

export async function storeMessage(fields: ContactFields): Promise<number> {
  const [row] = await db
    .insert(contactMessages)
    .values({
      name: fields.name,
      email: fields.email,
      subject: fields.subject,
      body: fields.body,
    })
    .returning({ id: contactMessages.id });
  return row.id;
}

/** Whether the notification went out, recorded against the message it is about. */
export async function recordNotification(id: number, status: string): Promise<void> {
  await db
    .update(contactMessages)
    .set({ notifiedAt: new Date(), notifyStatus: status })
    .where(eq(contactMessages.id, id));
}

export interface StoredMessage {
  id: number;
  name: string;
  email: string;
  subject: string;
  body: string;
  submittedAt: Date;
  handledAt: Date | null;
  notifiedAt: Date | null;
  notifyStatus: string | null;
}

export async function recentMessages(
  limit = 100,
  now: Date = new Date(),
): Promise<StoredMessage[]> {
  return db
    .select({
      id: contactMessages.id,
      name: contactMessages.name,
      email: contactMessages.email,
      subject: contactMessages.subject,
      body: contactMessages.body,
      submittedAt: contactMessages.submittedAt,
      handledAt: contactMessages.handledAt,
      notifiedAt: contactMessages.notifiedAt,
      notifyStatus: contactMessages.notifyStatus,
    })
    .from(contactMessages)
    // Filtered as well as purged. The delete is the promise; this makes the
    // page keep it even in the moment between a row expiring and being removed.
    .where(gte(contactMessages.submittedAt, cutoff(now)))
    .orderBy(desc(contactMessages.submittedAt))
    .limit(limit);
}

export async function unhandledCount(now: Date = new Date()): Promise<number> {
  const [row] = await db
    .select({ count: sql<number>`count(*)`.mapWith(Number) })
    .from(contactMessages)
    .where(and(sql`${contactMessages.handledAt} is null`, gte(contactMessages.submittedAt, cutoff(now))));
  return row?.count ?? 0;
}

export async function markHandled(id: number): Promise<void> {
  await db
    .update(contactMessages)
    .set({ handledAt: new Date() })
    .where(eq(contactMessages.id, id));
}
