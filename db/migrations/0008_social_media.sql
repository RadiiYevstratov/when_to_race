-- Where the card lives, and when the post went out.
--
-- Instagram does not accept an upload. It fetches the image from a public URL,
-- which means the card has to be served from somewhere before it can be
-- published. Rather than add an object store and another secret, the bytes are
-- kept here and served by the site that already exists, at
-- /api/social/card/<id>.jpg - one fewer vendor, one fewer credential, and the
-- image is bound to the row that describes it.
--
-- Size is not a concern at one post a day: a card is about 80KB, so a full year
-- is under 30MB. The pruning function below keeps it that way regardless.

ALTER TABLE social_posts
    ADD COLUMN media_bytes bytea,
    ADD COLUMN media_type text NOT NULL DEFAULT 'image/jpeg',
    ADD COLUMN published_at timestamptz;

COMMENT ON COLUMN social_posts.media_bytes IS
    'The rendered card. Served publicly so Instagram can fetch it.';

-- Old cards have no use once the post is live: Instagram keeps its own copy,
-- and nothing on the site links to them. The row stays - it is the publication
-- record - but the bytes go.
CREATE OR REPLACE FUNCTION prune_social_media(older_than interval DEFAULT '60 days')
RETURNS integer LANGUAGE sql AS $$
    WITH pruned AS (
        UPDATE social_posts
           SET media_bytes = NULL
         WHERE media_bytes IS NOT NULL
           AND decided_at < now() - older_than
        RETURNING 1
    )
    SELECT count(*)::integer FROM pruned;
$$;
