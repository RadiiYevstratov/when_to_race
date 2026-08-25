-- 0001_init.sql
-- Single source of truth for the schema. Drizzle and the scraper both follow this file.
--
-- Columns marked [ADDED] are not in the original brief. Each one is justified in
-- docs/data-model-review.md. Nothing from the brief was removed or renamed.

BEGIN;

-- ---------------------------------------------------------------------------
-- Reference data
-- ---------------------------------------------------------------------------

CREATE TABLE series (
    id              serial PRIMARY KEY,
    code            text NOT NULL UNIQUE,          -- 'f1', 'wec', 'wrc', ...
    name            text NOT NULL,                 -- 'FIA Formula One World Championship'
    short_name      text NOT NULL,                 -- 'Formula 1'
    accent_color    text NOT NULL,                 -- hex, drives series identity in the UI
    sort_order      integer NOT NULL DEFAULT 100,
    is_active       boolean NOT NULL DEFAULT true,
    -- Staleness tracking (frontend requirement 5.3)
    last_successful_scrape timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- [ADDED] The brief references sessions.category_id but never defines this table.
CREATE TABLE categories (
    id              serial PRIMARY KEY,
    series_id       integer NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    code            text NOT NULL,                 -- 'f2', 'moto3', 'wrc2'
    name            text NOT NULL,                 -- 'FIA Formula 2 Championship'
    short_name      text NOT NULL,                 -- 'F2'
    is_headline     boolean NOT NULL DEFAULT false,-- the category the weekend is named for
    sort_order      integer NOT NULL DEFAULT 100,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (series_id, code)
);

CREATE TABLE venues (
    id              serial PRIMARY KEY,
    slug            text NOT NULL UNIQUE,          -- [ADDED] stable key for config seeding
    name            text NOT NULL,
    country_code    char(2) NOT NULL,              -- ISO 3166-1 alpha-2
    city            text,
    -- Load-bearing. Never store a UTC offset here.
    iana_timezone   text NOT NULL,
    latitude        double precision,
    longitude       double precision,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Events and sessions
-- ---------------------------------------------------------------------------

CREATE TYPE event_status AS ENUM (
    'scheduled', 'in_progress', 'completed', 'cancelled', 'postponed'
);

CREATE TYPE session_status AS ENUM (
    'scheduled', 'live', 'finished', 'cancelled', 'delayed'
);

CREATE TYPE session_type AS ENUM (
    'practice', 'qualifying', 'sprint_qualifying', 'sprint', 'race',
    'warmup', 'shakedown', 'stage', 'test', 'other'
);

CREATE TYPE time_status AS ENUM ('confirmed', 'provisional', 'tbc');

-- [ADDED] How precisely the start time is actually known. Organisers publish
-- day-only slots months ahead; without this the UI renders 00:00 as a real time.
CREATE TYPE time_precision AS ENUM ('exact', 'hour', 'day');

CREATE TABLE events (
    id              serial PRIMARY KEY,
    series_id       integer NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    season          integer NOT NULL,
    round_number    integer,                       -- nullable: tests / non-championship rounds
    slug            text NOT NULL,                 -- [ADDED] URL key, unique per series+season
    name            text NOT NULL,                 -- 'Italian Grand Prix'
    official_name   text,                          -- sponsor-laden title
    venue_id        integer NOT NULL REFERENCES venues(id),
    starts_at_utc   timestamptz NOT NULL,
    ends_at_utc     timestamptz NOT NULL,
    status          event_status NOT NULL DEFAULT 'scheduled',
    -- [ADDED] WRC fallback: we have the weekend but not every stage (brief §4, rally note)
    detail_level    text NOT NULL DEFAULT 'full'
                    CHECK (detail_level IN ('full', 'partial')),
    source_url      text,
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    -- [ADDED] Soft delete. Reliability rule 1 forbids destructive sync, so a
    -- disappeared record is retired, never DELETEd.
    retired_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT events_span_ordered CHECK (ends_at_utc >= starts_at_utc)
);

-- Natural key. round_number is nullable, so COALESCE into a sentinel: two tests
-- in one season are disambiguated by slug.
CREATE UNIQUE INDEX events_natural_key
    ON events (series_id, season, slug);
CREATE INDEX events_upcoming ON events (starts_at_utc)
    WHERE retired_at IS NULL;

CREATE TABLE sessions (
    id              serial PRIMARY KEY,
    event_id        integer NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    category_id     integer NOT NULL REFERENCES categories(id),
    session_type    session_type NOT NULL,
    display_name    text NOT NULL,                 -- 'Free Practice 1', 'SS4 Ouninpohja'
    sequence        integer NOT NULL,              -- ordering within the weekend
    starts_at_utc   timestamptz NOT NULL,
    ends_at_utc     timestamptz,                   -- required for endurance
    scheduled_duration_minutes integer,
    time_status     time_status NOT NULL DEFAULT 'confirmed',
    -- [ADDED] see time_precision comment above
    starts_at_precision time_precision NOT NULL DEFAULT 'exact',
    status          session_status NOT NULL DEFAULT 'scheduled',
    -- [ADDED] Rallies can cross a timezone border; overrides venue.iana_timezone
    -- for display of "local time" only. NULL means inherit from the venue.
    iana_timezone   text,
    -- [ADDED] Calendar export needs a UID that survives renumbering, and a
    -- counter that increments on every change so subscribed calendars update
    -- in place instead of duplicating (brief §6, calendar export).
    ics_uid         text NOT NULL,
    ics_sequence    integer NOT NULL DEFAULT 0,
    source_url      text,
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    retired_at      timestamptz,                   -- [ADDED] soft delete
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT sessions_span_ordered
        CHECK (ends_at_utc IS NULL OR ends_at_utc >= starts_at_utc)
);

-- Upsert natural key, per brief §5. category+type+sequence is unique within an event.
CREATE UNIQUE INDEX sessions_natural_key
    ON sessions (event_id, category_id, session_type, sequence);
CREATE UNIQUE INDEX sessions_ics_uid ON sessions (ics_uid);
CREATE INDEX sessions_starts_at ON sessions (starts_at_utc)
    WHERE retired_at IS NULL;
CREATE INDEX sessions_event ON sessions (event_id, starts_at_utc, sequence);

-- ---------------------------------------------------------------------------
-- Audit
-- ---------------------------------------------------------------------------

CREATE TABLE schedule_changes (
    id              bigserial PRIMARY KEY,
    session_id      integer REFERENCES sessions(id) ON DELETE SET NULL,
    -- [ADDED] denormalised so the audit trail survives the session row and so
    -- "recently rescheduled in series X" is a single-table query
    series_id       integer REFERENCES series(id) ON DELETE SET NULL,
    event_id        integer REFERENCES events(id) ON DELETE SET NULL,
    scrape_run_id   bigint,                        -- [ADDED] which run detected it
    field_changed   text NOT NULL,
    old_value       text,
    new_value       text,
    detected_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX schedule_changes_recent ON schedule_changes (detected_at DESC);
CREATE INDEX schedule_changes_session ON schedule_changes (session_id, detected_at DESC);

CREATE TABLE scrape_runs (
    id              bigserial PRIMARY KEY,
    series_id       integer NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    status          text NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'success', 'failed', 'aborted_guard')),
    records_found   integer NOT NULL DEFAULT 0,
    records_changed integer NOT NULL DEFAULT 0,
    error_message   text,
    raw_snapshot_hash text                         -- kept for compatibility with the brief
);

CREATE INDEX scrape_runs_series_recent ON scrape_runs (series_id, started_at DESC);

-- [ADDED] A run fetches several URLs (calendar index + per-event pages), so one
-- hash per run cannot represent it. One row per fetched artefact.
CREATE TABLE scrape_snapshots (
    id              bigserial PRIMARY KEY,
    scrape_run_id   bigint NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
    url             text NOT NULL,
    content_hash    text NOT NULL,
    content_type    text,
    byte_size       integer,
    storage_path    text NOT NULL,                 -- where the raw body was written
    fetched_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX scrape_snapshots_run ON scrape_snapshots (scrape_run_id);

ALTER TABLE schedule_changes
    ADD CONSTRAINT schedule_changes_run_fk
    FOREIGN KEY (scrape_run_id) REFERENCES scrape_runs(id) ON DELETE SET NULL;

COMMIT;
