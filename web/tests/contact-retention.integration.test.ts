/**
 * The seven-day keep-by date, against a real database.
 *
 * This one has to be an integration test. The promise is that a message is
 * *deleted*, and whether a DELETE with a timestamp comparison removes the right
 * rows and leaves the others alone is not something the type system can answer.
 *
 * Every row it creates is written with an unmistakable marker in the email
 * address and removed again afterwards, so a failed run cannot leave test data
 * sitting in the operator's inbox page.
 *
 * Skipped when DATABASE_URL is unset, like the other integration tests.
 */

import { test, describe, before, after, afterEach } from "node:test";
import assert from "node:assert/strict";

const HAS_DB = Boolean(process.env.DATABASE_URL);
const skip = HAS_DB ? false : "DATABASE_URL is not set";

const MARKER = "retention-test@example.invalid";

type Store = typeof import("../lib/contact-store.ts");
type Queries = typeof import("../lib/queries.ts");

describe("contact message retention", { skip }, () => {
  let store: Store;
  let q: Queries;
  let schema: typeof import("../lib/schema.ts");
  let drizzle: typeof import("drizzle-orm");

  before(async () => {
    store = await import("../lib/contact-store.ts");
    q = await import("../lib/queries.ts");
    schema = await import("../lib/schema.ts");
    drizzle = await import("drizzle-orm");
  });

  afterEach(async () => {
    await q.db.delete(schema.contactMessages).where(drizzle.eq(schema.contactMessages.email, MARKER));
  });

  after(async () => {
    await q.closeDb();
  });

  /** A message stored with a chosen arrival time. */
  async function seed(daysAgo: number, subject: string): Promise<number> {
    const [row] = await q.db
      .insert(schema.contactMessages)
      .values({
        name: "Retention test",
        email: MARKER,
        subject,
        body: "Created by the retention test.",
        submittedAt: new Date(Date.now() - daysAgo * 86_400_000),
      })
      .returning({ id: schema.contactMessages.id });
    return row.id;
  }

  async function exists(id: number): Promise<boolean> {
    const rows = await q.db
      .select({ id: schema.contactMessages.id })
      .from(schema.contactMessages)
      .where(drizzle.eq(schema.contactMessages.id, id));
    return rows.length === 1;
  }

  test("a message past the keep-by date is deleted", async () => {
    const old = await seed(store.RETENTION_DAYS + 1, "too old");
    await store.purgeExpired();
    assert.equal(await exists(old), false);
  });

  test("a message inside the window is kept", async () => {
    // The boundary is the one worth pinning: a message from six days ago is
    // still someone waiting for an answer.
    const fresh = await seed(store.RETENTION_DAYS - 1, "still fresh");
    await store.purgeExpired();
    assert.equal(await exists(fresh), true);
  });

  test("purging twice removes nothing extra", async () => {
    const fresh = await seed(1, "recent");
    const old = await seed(30, "ancient");
    await store.purgeExpired();
    await store.purgeExpired();
    assert.equal(await exists(fresh), true);
    assert.equal(await exists(old), false);
  });

  test("the list never shows a message past the date, even before a purge", async () => {
    // Belt and braces: the delete is the promise, and the filter keeps the page
    // honest in the moment between a row expiring and being removed.
    const old = await seed(store.RETENTION_DAYS + 2, "expired but present");
    const listed = await store.recentMessages(500);
    assert.equal(
      listed.some((message) => message.id === old),
      false,
    );
  });

  test("an expired message is not counted as unread", async () => {
    await seed(store.RETENTION_DAYS + 2, "expired and unread");
    const before = await store.unhandledCount();
    await store.purgeExpired();
    assert.equal(await store.unhandledCount(), before);
  });
});
