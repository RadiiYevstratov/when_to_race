# Data model review

This answers §11.1 of the brief: what I think is wrong or missing in the data
model as specified.

The model is sound. Everything below is either a gap that would have surfaced
during implementation, or a place where following the brief literally would have
caused a specific failure. Nothing was removed or renamed — every addition is
marked `[ADDED]` in `db/migrations/0001_init.sql`, and every one is reversible.

Three of these are deviations from what the brief says rather than additions to
it. They are flagged as **Deviation** and are the ones worth your explicit
agreement or veto.

---

## Gaps

### 1. `categories` is referenced but never defined

`sessions.category_id` is in the spec; the table it points at is not. The scope
table lists the categories per championship, so the shape is implied, but it
needs to exist as a table with a `series_id` parent, a code, a display name, a
sort order, and an `is_headline` flag.

`is_headline` earns its place: the weekend view needs to know which category the
event is named for, and "the one with the lowest sort order" is a convention
waiting to be broken.

### 2. Nothing to make the calendar subscription work

§6 requires stable `UID`s per session and an incrementing `SEQUENCE` on change.
Neither has a column. Without both stored, a rescheduled session appears twice
in a subscriber's calendar instead of moving — which is the entire failure mode
that feature exists to prevent.

Added `sessions.ics_uid` (unique) and `sessions.ics_sequence`, incremented on
update by the upsert layer.

The UID is deliberately keyed on `display_name`, **not** on `sequence`. If a
source renumbers its sessions, a sequence-based UID changes and every subscriber
gets a duplicate. Display names survive renumbering. See `build_ics_uid()` in
`scrapers/records.py`.

Only meaningful changes bump the sequence — start time, end time, status, time
status, display name. A corrected source URL should not push a notification to
everyone's phone. See `NOTIFIABLE_FIELDS` in `scrapers/sync.py`.

### 3. No way to say "we know the day, not the time"

`time_status` distinguishes confirmed from provisional from TBC, which is the
right axis but not the only one. Organisers routinely publish a round as "Sunday
in October" months ahead, with no time at all.

With only `time_status`, that becomes `00:00` flagged provisional — and `00:00`
is a real time that a lot of people will read as midnight. The brief names
showing a provisional time as confirmed the single worst failure mode; this is
the same failure wearing a different hat.

Added `sessions.starts_at_precision` (`exact` / `hour` / `day`). The UI renders
`--:--` rather than a fabricated midnight when precision is `day`.

### 4. One snapshot hash per run cannot represent a run

`scrape_runs.raw_snapshot_hash` is singular, but a run fetches a calendar index
plus, for most series, a page or endpoint per event. One hash cannot identify
several artefacts.

Added a `scrape_snapshots` table, one row per fetched body, linked to the run.
Kept `raw_snapshot_hash` on `scrape_runs` so nothing in the brief breaks.

### 5. Soft delete is required by the reliability rules but has no column

Rule 1 says never destructively sync. But if a session disappears from a feed,
something has to happen to the row, and the options are "delete it" (forbidden)
or "leave it displayed forever" (wrong).

Added `retired_at` to `events` and `sessions`. A session that vanishes is
retired, not deleted; if it comes back, it is revived. The audit trail survives
either way, and a parser that starts dropping sessions leaves evidence.

### 6. The audit trail does not survive the thing it audits

`schedule_changes.session_id` is the only link back. If a session row is ever
removed, the history becomes unreadable, and "what was rescheduled in F1 this
week" needs a three-table join to answer.

Added denormalised `series_id` and `event_id`, plus `scrape_run_id` so a change
can be traced to the run that detected it, plus an index on `detected_at`.

### 7. Smaller things

- **`events.slug`** — the natural key is `(series, season, round_number)`, but
  `round_number` is legitimately null for tests and non-championship rounds, and
  a null in a unique key does not behave the way you want. Added a slug, unique
  per series and season, and used it in the key and in URLs.
- **`events.detail_level`** (`full` / `partial`) — the brief describes graceful
  WRC degradation but gives it nowhere to live. Validation downgrades the
  session-floor error to a warning when an event is `partial`.
- **`sessions.iana_timezone`**, nullable — venue-level timezone is right almost
  always, but a rally can cross a border. Null means inherit from the venue.
- **`venues.slug`** — so config seeding is idempotent and does not match on name.
- **`updated_at`** everywhere, and a check constraint that end is not before
  start on both events and sessions.

---

## Deviations

### Deviation 1: `sequence` is the ordinal within (category, session type), not within the weekend

The brief describes `sequence` as ordering within the weekend and puts it in the
upsert natural key. Those two things fight each other.

If `sequence` is a weekend-wide index, inserting one session renumbers every
later one. On the next run the natural key of the race changes from 12 to 13,
the upsert finds no match, and it creates a duplicate while the original is
retired — plus a `schedule_changes` row for every session in the weekend. A
support-series session appearing late in the week would do this.

So: FP1 → 1, FP2 → 2, FP3 → 3, Qualifying → 1, Race → 1. Stable under insertion.
Where a name carries a number ("Free Practice 2", "SS4"), that number is used;
otherwise sessions are numbered positionally in chronological order.

Nothing is lost, because display order comes from `starts_at_utc`, which is what
the brief also says to sort by. There is a regression test for exactly this
(`test_sequence_is_stable_when_an_earlier_session_is_added`).

Number extraction is deliberately narrow — only known shapes like `FP2`, `Q1`,
`SS4`, `Practice 2`. A loose "first integer in the string" rule reads *24 Hours
of Le Mans* as session 24.

### Deviation 2: `status` should be derived, not stored

`sessions.status` includes `live` and `finished`, and `events.status` includes
`in_progress` and `completed`. Those are functions of the current time and the
session's start and end. Storing them means a cron job has to keep them accurate,
and the moment it fails the site shows "LIVE" on a race that finished yesterday —
a visible, embarrassing, entirely avoidable failure.

I kept the columns exactly as specified, but the scrapers only ever write states
a source actually reports (`scheduled`, `cancelled`, `delayed`, `postponed`), and
the frontend derives live/finished from timestamps at render time (`isLive()` in
`web/lib/time.ts`).

If you would rather store them, the change is a scheduled job and one query; I
would still not recommend it.

### Deviation 3: plain dataclasses instead of Pydantic

The brief specifies Pydantic for parsed-record validation. I used stdlib
dataclasses plus an explicit validation module.

Two reasons. The practical one: I could not install Pydantic in the environment
I built this in, so Pydantic code would have shipped to you unrun. The better
one: the constraints that actually matter here are cross-record, not per-field —
"no duplicate `(event, category, type, sequence)` in this batch", "session count
per event above the series floor", "every session inside its event's span". Those
do not fit field validators, so they need a validation pass regardless, and
having two validation layers is worse than having one good one.

The cost is losing Pydantic's coercion and error messages. If you want it back,
it is one module: `scrapers/records.py` becomes `BaseModel`s and
`scrapers/validate.py` stays exactly as it is. Say the word and I will do it.

---

## One thing I would raise but not change

`venues` assumes an event happens at a place. For circuit racing that is true.
For a rally it is a convenient fiction — Rally Finland is a service park in
Jyväskylä and twenty stages spread across a hundred kilometres of Central
Finland.

Modelling that properly means stage-level locations, which is a real schema
change and a lot of scraping for information most people do not want. The
current compromise — venue is the rally HQ, stages carry their own names, and
`sessions.iana_timezone` can override when a stage crosses a border — is the
right call for v1. It is worth knowing it is a compromise before someone files
a bug about it.
