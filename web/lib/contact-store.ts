/**
 * The one place the web app writes.
 *
 * Kept out of queries.ts on purpose. That module is the read side and says so
 * in its first line; putting an INSERT in it would quietly retire a rule the
 * whole project is built on. A separate file makes the exception visible to
 * anyone looking for it, and keeps "does the web app write to the schedule?"
 * answerable with a straight no.
 */

import { desc, eq, sql } from "drizzle-orm";

import { db } from "./queries.ts";
import { contactMessages } from "./schema.ts";
import type { ContactFields } from "./contact.ts";

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

export async function recentMessages(limit = 100): Promise<StoredMessage[]> {
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
    .orderBy(desc(contactMessages.submittedAt))
    .limit(limit);
}

export async function unhandledCount(): Promise<number> {
  const [row] = await db
    .select({ count: sql<number>`count(*)`.mapWith(Number) })
    .from(contactMessages)
    .where(sql`${contactMessages.handledAt} is null`);
  return row?.count ?? 0;
}

export async function markHandled(id: number): Promise<void> {
  await db
    .update(contactMessages)
    .set({ handledAt: new Date() })
    .where(eq(contactMessages.id, id));
}
