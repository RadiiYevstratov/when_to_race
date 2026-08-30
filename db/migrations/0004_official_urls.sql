-- Where to send someone who wants to check a time against the organiser.
--
-- Not the same thing as `source.url` in config, which is the machine endpoint
-- this project scrapes: a JSON cacher, an ICS file, an API base. That is the
-- back door. This is the front one - the championship's public site, the thing
-- a reader recognises and would have searched for.
--
-- On both tables because a class can be its own championship with its own site.
-- Formula 2 has fiaformula2.com; Moto2 has nothing of its own, because it lives
-- on motogp.com with the series. NULL on a class therefore means "no site of
-- its own", not "unknown", and is the ordinary case.

ALTER TABLE series
    ADD COLUMN official_url text;

ALTER TABLE categories
    ADD COLUMN official_url text;

COMMENT ON COLUMN series.official_url IS
    'The championship''s own public site. NULL if none is recorded.';
COMMENT ON COLUMN categories.official_url IS
    'Set only where the class is its own championship with its own site. '
    'NULL means it shares the series'' site.';

-- https only. These are rendered as links on every page, so a bad scheme is a
-- broken footer rather than a line in a log - and http:// on an outbound link
-- from a site that sets HSTS is its own small embarrassment.
ALTER TABLE series
    ADD CONSTRAINT series_official_url_https
    CHECK (official_url IS NULL OR official_url LIKE 'https://%');

ALTER TABLE categories
    ADD CONSTRAINT categories_official_url_https
    CHECK (official_url IS NULL OR official_url LIKE 'https://%');
