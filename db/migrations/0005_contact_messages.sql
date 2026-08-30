-- Messages sent from the contact form.
--
-- This is the first table the web app writes to, and that is worth stating
-- plainly rather than letting someone discover it. The rule has been that the
-- scrapers write and the web app only reads, and the reason for it is that the
-- schedule is owned by the pipeline: a web write there could put a time on the
-- board that no source ever published.
--
-- Nothing about that reason applies here. This table is not schedule data, no
-- scraper touches it, and no page reads it into the board. The rule keeps its
-- meaning; this sits outside it.
--
-- Stored rather than only emailed, deliberately. A form that just hands a
-- message to a mail provider loses it whenever that provider is down, and the
-- person who wrote it has no way of knowing. The row is the record; the email
-- is a notification about the row.
--
-- No IP address is kept. It would be the obvious thing to store for abuse
-- handling, and it is personal data under GDPR that would need a retention
-- policy and a lawful basis to hold - for a contact form on a hobby schedule
-- site that is a poor trade. Rate limiting happens in memory, in the process,
-- and forgets by itself.

CREATE TABLE contact_messages (
    id            serial PRIMARY KEY,
    name          text NOT NULL,
    email         text NOT NULL,
    subject       text NOT NULL,
    body          text NOT NULL,
    submitted_at  timestamptz NOT NULL DEFAULT now(),
    -- Set when the operator has dealt with it, so the admin list can separate
    -- what is new from what has been read.
    handled_at    timestamptz,

    -- The same limits the form enforces, repeated here because the database is
    -- the last place that can still say no.
    CONSTRAINT contact_messages_name_length    CHECK (length(name) BETWEEN 1 AND 100),
    CONSTRAINT contact_messages_email_length   CHECK (length(email) BETWEEN 3 AND 254),
    CONSTRAINT contact_messages_subject_length CHECK (length(subject) BETWEEN 1 AND 150),
    CONSTRAINT contact_messages_body_length    CHECK (length(body) BETWEEN 1 AND 5000)
);

-- The admin list reads newest first, and only ever this way.
CREATE INDEX contact_messages_recent ON contact_messages (submitted_at DESC);
