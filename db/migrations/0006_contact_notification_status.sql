-- Whether the notification for a message actually went out.
--
-- Without this a failed notification is a line in a log, and a log is exactly
-- what nobody has when they are asking "why did I not get an email?". The
-- answer belongs next to the message it is about, where the person asking is
-- already looking.
--
-- Three states worth telling apart, and the column holds the reason rather
-- than a flag so the third one is useful:
--
--   'skipped'   no provider configured. Not a failure - the supported default.
--   'sent'      the provider accepted it.
--   anything    what the provider said when it refused, verbatim.
--
-- The provider's own words are kept because they are usually the whole answer:
-- a shared sending domain that will only deliver to the account owner says so
-- in the response body, and no amount of guessing from this end would find it.
--
-- No API key or credential is ever written here - only the response.

ALTER TABLE contact_messages
    ADD COLUMN notified_at timestamptz,
    ADD COLUMN notify_status text;

COMMENT ON COLUMN contact_messages.notified_at IS
    'When the notification attempt finished, successful or not. NULL if never attempted.';
COMMENT ON COLUMN contact_messages.notify_status IS
    '''skipped'', ''sent'', or the provider''s refusal in its own words.';
