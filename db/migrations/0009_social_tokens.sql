-- Where the Instagram token lives after the first day.
--
-- Meta's long-lived token lasts 60 days. It can be refreshed indefinitely with
-- no human present, but the refreshed token is a *new string* that has to be
-- kept somewhere the next run will read - and a job cannot rewrite its own
-- deployment secret without being handed credentials to do so.
--
-- So the environment variable is only the seed. The first run copies it here,
-- every run refreshes it once it is past halfway, and from then on the token
-- renews itself forever without anyone touching a settings page. A token that
-- lapses cannot be recovered by retrying - it needs an interactive
-- re-authorisation - which is exactly why this is worth a table.
--
-- The row is as sensitive as the database it sits in. Nothing in the web app
-- reads this table; only the social job does.

CREATE TABLE social_credentials (
    name        text PRIMARY KEY,
    value       text NOT NULL,
    issued_at   timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE social_credentials IS
    'Current Instagram token, refreshed in place by the social job. Seeded from '
    'INSTAGRAM_ACCESS_TOKEN on first use.';

COMMENT ON COLUMN social_credentials.issued_at IS
    'When this exact token was issued. The refresh schedule is measured from here.';
