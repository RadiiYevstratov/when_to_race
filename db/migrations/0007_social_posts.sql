-- What the Instagram account has already said.
--
-- The selection algorithm is only as good as its memory: without this table it
-- would choose the same race weekend every day for a week, because that weekend
-- stays the most newsworthy thing on the calendar the whole time. Every rule
-- that stops the account repeating itself reads from here.
--
-- A row is written for every decision, including the decision not to post. A
-- quiet day is a fact about the calendar, not a failure, and the log is far
-- easier to read when the silences are in it.

CREATE TYPE social_outcome AS ENUM (
    'published',     -- live on Instagram, with a post id
    'dry_run',       -- everything built, publishing deliberately skipped
    'skipped',       -- nothing cleared the floor; a normal quiet day
    'failed'         -- something broke; error_message says what
);

CREATE TABLE social_posts (
    id              bigserial PRIMARY KEY,

    -- When the decision was taken, and for which local day. decided_for is the
    -- date in the posting timezone, so "one post per day" is a question this
    -- table can answer without re-deriving anybody's midnight.
    decided_at      timestamptz NOT NULL DEFAULT now(),
    decided_for     date NOT NULL,

    outcome         social_outcome NOT NULL,
    post_kind       text,            -- weekend_preview | tomorrow | today | week_ahead

    -- What it was about. Nullable because a skipped day is about nothing.
    -- ON DELETE SET NULL rather than CASCADE: if a source retires an event we
    -- still want the record that we posted about it.
    event_id        integer REFERENCES events(id) ON DELETE SET NULL,
    session_id      integer REFERENCES sessions(id) ON DELETE SET NULL,
    series_code     text,
    category_code   text,
    event_name      text,
    session_type    text,
    session_starts_at_utc timestamptz,

    -- Why it won. Kept because a selection that looks wrong six weeks from now
    -- is unanswerable without the score it beat the others with.
    score           integer,
    reasons         jsonb,

    caption         text,
    hashtags        text[],
    media_path      text,
    media_url       text,

    instagram_post_id text,
    error_message   text,

    created_at      timestamptz NOT NULL DEFAULT now()
);

-- The novelty rules ask two questions constantly: what have we posted about
-- this event, and what did we post recently.
CREATE INDEX social_posts_event ON social_posts (event_id, decided_at DESC);
CREATE INDEX social_posts_recent ON social_posts (decided_at DESC);

-- One published post per day. A dry run or a skip may be repeated while
-- testing, but a second live post on a day already published is always a bug -
-- a retry after a partial failure is the way it would happen.
CREATE UNIQUE INDEX social_posts_one_per_day
    ON social_posts (decided_for)
    WHERE outcome = 'published';

COMMENT ON TABLE social_posts IS
    'Every daily Instagram decision, including the decision to stay quiet.';
