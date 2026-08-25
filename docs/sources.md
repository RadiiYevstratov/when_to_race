# Sources

## Status: F1, MotoGP, WorldSBK and WEC live, the rest outstanding

Formula 1, MotoGP, WorldSBK and WEC are `status = "live"` and running against
confirmed sources (see the findings below). MotoGP, WorldSBK and WEC were set
live on 2026-08-23 after the owner accepted the Terms-of-Use risk documented in
the MotoGP findings (all three restrict use to personal purposes; WorldSBK is the
same publisher as MotoGP, WEC is a separate organiser with equivalent terms).
Every other series (WRC, IMSA, IndyCar, NASCAR) is still `status = "unverified"`,
and `python -m scrapers.run` refuses to run an unverified source unless you pass
`--allow-unverified`.

That refusal is deliberate. The worst outcome for this product is showing a
confident wrong time, and a parser pointed at a guessed endpoint is exactly how
that happens.

Do the discovery below, fill in the tables, then flip `status` to `"live"` and
set `source.url`. The F1 parser is written and tested against a committed
fixture, so once a real feed is confirmed the work is a URL and a fixture
refresh, not a rewrite.

---

## How to do discovery for a series

Work in browser devtools, in this order of preference. Stop at the first one
that works.

**1. An ICS / iCal feed.** Structured, timezone-aware, stable, and usually
published precisely so people can subscribe. If it exists it is the right answer
and `scrapers/sources/ics_source.py` already handles it.

Where to look: a "add to calendar" or "subscribe" link on the calendar page;
`/calendar.ics`, `/schedule.ics`, `/feed.ics`; a `webcal://` href anywhere in
the page source; `<link rel="alternate" type="text/calendar">` in the head.

**2. A JSON endpoint behind the site's own calendar page.** Most official sites
are React frontends calling an internal API, and that API is far more stable
than the rendered HTML. Open the Network tab, filter to Fetch/XHR, reload the
calendar page, and look for a response containing session names and times.

Record the exact request, including any headers the site sends that turn out to
be required (API keys in headers are common; if one is required, note it and
flag it to me before using it — see the legal section).

**3. Structured data in the page.** Look for `<script type="application/ld+json">`
with `SportsEvent` objects, or a `__NEXT_DATA__` / `__NUXT__` / hydration payload
containing the schedule as JSON. Search the page source for a session name you
can see on screen ("Free Practice 1") and see what wraps it.

**4. HTML parsing.** Last resort. Brittle by nature, and the first thing to break
on a redesign.

### For each source, record all of this

| Field | Why it matters |
|---|---|
| Endpoint URL (with a working example) | The thing itself |
| Response shape | A trimmed sample, committed as a fixture |
| **Timezone convention** | Circuit-local? UTC? An offset field? A `tz` string? This is the single most important field to get right |
| Whether provisional times are distinguishable | If the source cannot say "TBC", we cannot either, and `time_status` becomes a lie |
| Are support categories in the same feed? | Determines whether one weekend needs one fetch or several |
| Refresh behaviour | How often does it actually change? Any `Last-Modified` / `ETag`? |
| Auth requirements | Any key, cookie or referer header needed |
| robots.txt verdict | Quote the relevant lines |
| Terms of Use verdict | Quote the relevant clause, with a link and the date you read it |
| Confidence | high / medium / low, and why |

### The timezone question, specifically

For every source, answer this before writing a parser: **if I take a session
time from this response and treat it as circuit-local, is that correct?**

Verify it against a known case rather than assuming. Pick a round where you can
check the published local start time independently — a Grand Prix start time is
widely reported — and confirm your conversion produces the right UTC instant.
Do this for a northern-summer round *and* a round outside DST, because a source
that silently publishes fixed offsets will agree with you in one and not the
other.

---

## Per-series prior assessment

Unverified. These are expectations to test, not facts. Confidence refers to my
prior that a good structured source exists, nothing more.

| Series | Expected best source | Prior confidence | Notes to check |
|---|---|---|---|
| Formula 1 | ICS or internal JSON | Medium-high | Support series (F2/F3/F1 Academy) may be published separately from F1; if so, three fetches, one event. Sprint weekends reorder sessions — never assume Friday is practice |
| MotoGP | Internal JSON | Medium | Four classes share a weekend. Check whether MotoE appears only at selected rounds |
| WorldSBK | Internal JSON | Medium | Same publisher family as MotoGP; check whether the shape is shared. "Superpole" is qualifying, "Superpole Race" is a race — already handled in `normalize.py`, but confirm the source's exact strings |
| WEC | ICS plausible | Medium | Le Mans is 24 hours: `ends_at_utc` is mandatory, and the frontend must render a session spanning three viewer-days |
| IndyCar | JSON | Medium | Practice/qualifying naming varies by oval vs road course. Indy 500 has a qualifying weekend a week before the race — two events or one? Decide and document |
| IMSA | JSON | Medium | Daytona 24 and Sebring 12 have the same multi-day span problem as Le Mans |
| NASCAR | JSON | Medium | Some rounds have no practice or qualifying at all. The session floor for NASCAR is set to 1 for this reason |
| WRC | Hardest | Low | 15–20 timed stages across four days. Stage-level data may not be reliably available ahead of time. Degrade to shakedown + day start/end + Power Stage and set `detail_level = 'partial'` rather than showing nothing — the schema and validation already support this |

---

## Legal and operational

Read §10 of the brief alongside this. Three rules, in order of how much trouble
ignoring them causes:

**1. If a site's Terms of Use prohibit automated access, stop and flag it.** Do
not proceed on the theory that the data is public. For some series an official
ICS feed, a partner arrangement, or a licensed data provider may be the only
defensible route, and that is a decision to make deliberately rather than
discover later.

Record the verdict here per series, with the clause quoted and the date read.
Terms change; a verdict from a year ago is not a verdict.

**2. Take only what the product needs.** Times, session names, venues, round
numbers. The EU sui generis database right can attach to a substantial
extraction from an organiser's database even where the individual facts are not
copyrightable. Never republish descriptive editorial text, images, or logos
scraped from a source.

**3. Be a good citizen, visibly.** `scrapers/http.py` already enforces:
robots.txt respected, one request per host per two seconds, a descriptive
User-Agent with a contact URL, three retries maximum with exponential backoff.
Set `CONTACT_URL` in that file to a real page before running against any live
site — an operator who wants to complain should be able to reach you rather than
just block you.

Polling: every 6 hours for full calendars, hourly within 72 hours of a session
start. Full calendars change slowly; there is no case for hitting them harder.

**Attribution.** Every event detail view links back to the official page via
`events.source_url`, and the footer carries the provisional-times disclaimer.
Both are already implemented.

---

## Findings

*(Fill in as discovery is completed. One section per series, using the field
list above. Commit a trimmed sample response as a fixture in
`scrapers/fixtures/` at the same time — the parser tests run against those
fixtures, and they are what catches a site redesign before users see a wrong
time.)*

### Formula 1

**Status: live.** Verified 21 August 2026.

| Field | Finding |
|---|---|
| Endpoint | `https://f1.vidmar.net/calendar.ics` |
| Type | ICS feed, published for public subscription |
| Official? | **No.** Community project by @F1_Calendar. Formula 1 publishes no public developer API, and no official ICS feed was found |
| Response shape | RFC 5545, one VEVENT per session. Captured in `scrapers/fixtures/f1_ical_feed.ics` |
| **Timezone convention** | **All times UTC-stamped** (`DTSTART:20260906T130000Z`). No TZID, no floating times, no local-time conversion needed |
| Provisional times distinguishable? | **No.** No STATUS:TENTATIVE, no TBC marker. Everything arrives as if confirmed, so `time_status` is always `confirmed` for this source. See "Known limitations" |
| Support categories included? | **No.** F1 only. No F2, F3 or F1 Academy |
| Coverage | 22 rounds, 110 sessions for 2026. Sprint weekends correctly distinguish Sprint Qualifying from Sprint |
| Refresh behaviour | Feed carries `DTSTAMP` for the whole file, not per event. Current build stamped 20 May 2026 |
| Auth | None |
| robots.txt | Fetched 200 and permits the calendar path. Verified 21 August 2026 |
| Terms of Use | No terms page found on the site. Not the same as permission granted - revisit if usage grows |
| Confidence | Medium. The data is good; the dependency is one person's side project |

**Format quirks this feed has, all handled in `scrapers/sources/f1.py`:**

- Every SUMMARY is decorated with emoji: `🇮🇹 Italian GP: 🏁 Race`. Stripped by
  `strip_decoration()` - left alone they end up in the slug and the calendar UID.
- Sessions split on `": "`, giving event and session parts.
- Practice sessions are named "First / Second / Third Free Practice" rather than
  FP1/FP2/FP3, so sequence falls back to chronological position. This works, but
  it means a source that renamed them would renumber silently.
- Each session carries a nested `VALARM` reminder. The ICS reader skips nested
  components; before it did, the alarm's DESCRIPTION overwrote the event's.
- The feed also contains car launches and pre-season testing as `VALUE=DATE`
  entries. Dropped, because no category pattern matches them.
- LOCATION is a bare circuit or city name ("Monza", "Melbourne", "Madrid"),
  mapped through `venue_aliases`.

**Known limitations, in order of how much they matter:**

1. **No provisional-time signal.** The product's stated worst failure mode is
   showing a provisional time as confirmed, and this source makes that
   impossible to avoid - it does not distinguish them. Anything better here
   would need a second source.
2. **F1 only.** The unified weekend view, which is the reason this project
   exists, is not exercised by this source at all.
3. **Single point of failure.** One unofficial feed, no fallback. If it goes
   stale the 48-hour staleness marker will show it, but the site has nothing
   else to fall back to.
4. **Two Spanish rounds from 2026** - Barcelona and Madrid. A `"spain"` venue
   alias was deliberately removed: it would have silently sent Madrid sessions
   to the wrong circuit. Watch for this pattern in every other series.

### WEC

**Status: live (set 2026-08-23).** Investigated 23 August 2026. A different
organiser (ACO / Le Mans Endurance Management), a different platform, and the
most careful timezone handling of any source so far.

| Field | Finding |
|---|---|
| Endpoint | Base `https://www.fiawec.com`. Two stages: `/en/season/{year}` lists the race slugs; each `/en/race/{slug}` page carries that weekend's schedule |
| Type | **schema.org JSON-LD** embedded in each server-rendered race page (a `SportsEvent` whose `subEvent`s are the sessions). No session-level JSON API exists - the pages are SSR and `api.fia.com` is just an HTML site. This is discovery option 3 (structured data in the page) |
| One fetch or many? | Many: 1 season-index call + 1 per round (8 rounds). Implemented via `resolve_urls` (see scrapers/sources/base.py). The pre-season Prologue is filtered out |
| Response shape | `SportsEvent` `{name, location:{name}, subEvent:[{name, startDate}]}`. Captured (minimal pages, JSON-LD only) in `scrapers/fixtures/wec_*.html` |
| **Timezone convention** | **The dangerous one.** Every `startDate` is stamped with the CMS server's offset (CEST/CET), *not* the circuit's - Fuji reads `10:15:00+02:00` for a 10:15 **JST** session. The wall-clock is circuit-local and the offset is noise. The adapter drops the offset and hands normalize a naive local time for the venue's IANA zone to resolve. Verified: Fuji race -> 02:00 UTC (11:00 JST), Sao Paulo and Austin likewise corrected; European rounds unaffected (their offset happened to be right) |
| End times | **`endDate` is always null.** Practice/qualifying can live without one; a race cannot (a 6h/24h race as a point in time is the failure end_utc exists to prevent), so the race duration is read from the event name: "24 Hours" -> 1440, "N Hours" -> N*60, else 360 (the standard WEC round, e.g. Lone Star Le Mans). Le Mans then correctly spans two days |
| Classes | One `wec` category by design - Hypercar, LMP2 and LMGT3 share the timetable. Class-specific qualifying/hyperpole sessions (e.g. "Qualifying - HYPERCAR") remain distinct sessions within it |
| Provisional times distinguishable? | No; treated as confirmed |
| Auth | None |
| robots.txt | `www.fiawec.com/robots.txt` is `Allow: /`. Verified 23 August 2026 |
| Terms of Use | Personal-and-private-use only, excluding public display/distribution, with database copyright asserted (read 23 August 2026). Same class of restriction as the Dorna sources; risk accepted on the same basis, same revert path |
| Confidence | High on the data once the offset trap is handled; JSON-LD is stable structured data. The offset behaviour is the thing to watch - if the site ever starts stamping real circuit offsets, revisit `_naive_local` |

**Quirks handled in `scrapers/sources/wec.py`:**

- Session names carry a " - {event}" suffix ("Free Practice 1 - 6 Hours of
  Fuji"); stripped. Sponsor prefixes (TotalEnergies/Rolex) are dropped from the
  event name but kept in `official_name`.
- Le Mans has 12 sessions incl. night runs and split Hyperpole; the sequence
  falls back to positional so the several qualifying/hyperpole sessions never
  collide on the natural key.
- One new venue: Fuji Speedway.
- **Limitation:** a distance race with no hours in its name (e.g. the 2027
  "Qatar 1812km") would default to a 6-hour end. Revisit when such a round is in
  scope.

### WRC

Status: not investigated.

### MotoGP

**Status: live (set 2026-08-23).** Investigated 23 August 2026. The endpoint is
clean and the parser passes against a committed fixture and a live dry-run (440
sessions, 22 rounds). Set live after the owner accepted the Terms-of-Use risk
described under "Terms of Use" below.

| Field | Finding |
|---|---|
| Endpoint | `https://api.motogp.pulselive.com/motogp/v1/events?seasonYear={season}` |
| Type | Internal JSON API (Pulselive), the site's own calendar backend. Unauthenticated |
| Official? | Yes - it is motogp.com's own API, not a third party |
| One fetch or many? | **One.** The season-list response embeds a fully populated `broadcasts` array per event, so every session for every class arrives in a single request. No per-event fetch needed |
| Response shape | JSON array of events. Filter `kind == "GP"` (drops tests, launches, presentations). Each event carries `broadcasts[]`; each broadcast is one session. Captured trimmed in `scrapers/fixtures/motogp_events.json` |
| **Timezone convention** | **Offset-stamped local times** (`"2026-02-27T15:00:00+0700"`). The offset makes the instant unambiguous, so no IANA conversion is needed - the parser emits `start_utc` directly. Verified: Thailand race 15:00+07:00 = 08:00 UTC (Thailand has no DST); Qatar night race 20:00+03:00 = 17:00 UTC; Valencia 14:00+01:00 = CET in November. All internally consistent |
| Classes in one feed? | **Yes** - MotoGP, Moto2, Moto3 all in the same event's `broadcasts`, keyed by `category.name`. This is the source that finally exercises the unified weekend view. MotoE is mapped but absent from the 2026 calendar |
| Provisional times distinguishable? | **No.** `status` is `FINISHED`/`NOT-STARTED` (temporal, not confidence). Future rounds carry full realistic timetables (the whole season is pre-published) with no "provisional" marker, so `time_status` is always `confirmed` for this source. Same limitation as the F1 feed |
| Refresh behaviour | `Cache-Control: max-age=30, stale-while-revalidate=600`. No per-event `ETag`/`Last-Modified` |
| Auth | None |
| robots.txt | `www.motogp.com/robots.txt` fetched 200; disallows only tracking params and old news archives, nothing under the calendar. `api.motogp.pulselive.com/robots.txt` is 404 (no restriction). Verified 23 August 2026 |
| Terms of Use | **See below - this is the open decision.** |
| Confidence | High on the data and its stability; the endpoint is the site's own backend. The only open question is legal, not technical |

**Format quirks, all handled in `scrapers/sources/motogp.py`:**

- A **"Baggers"** invitational class appears at six 2026 rounds (USA, Italy,
  Netherlands, Great Britain, Aragon, Austria). It is dropped - `_CATEGORY_MAP`
  only maps MotoGP/Moto2/Moto3/MotoE, and an unmapped class is skipped rather
  than forced into a category.
- `broadcasts` includes non-track `type == "MEDIA"` entries (press conferences,
  group photos, TV shows). Only `type == "SESSION"` is kept.
- **"Tissot Sprint"** arrives with `kind == "RACE"` but is a sprint. Classified
  by name in `normalize.py`, not by `kind`, so it lands as `sprint`. The MotoGP
  race itself is named "Grand Prix"; Moto2/Moto3 races are "Race".
- Session labels use an "Nr." infix ("Free Practice Nr. 1", "Qualifying Nr.2").
  Stripped to "Free Practice 1" / "Qualifying 2" so the sequence patterns can
  read the ordinal.
- Three new venues the F1 registry did not have: **Sachsenring** (Germany),
  **Balaton Park** (new Hungarian circuit), **Circuit Ricardo Tormo / Valencia**,
  plus **Goiânia** (Brazil's MotoGP round is here, *not* Interlagos - the same
  "one country, two circuits" trap as Spain in F1). Added to `config/venues.toml`.

**Terms of Use - the decision that gates going live.** motogp.com's terms
(read 23 August 2026, no effective date shown on the page) contain no explicit
anti-scraping or robots clause, but Clause 3 restricts use: *"You are only
authorised to use Our Channels for personal purposes"* and *"You are not
permitted to provide, copy... or transmit any Content that you access through
Our Channels for any purpose, whether for profit or free of charge."* Clause 1
asserts intellectual-property protection over site Content.

A public site that redistributes these session times is not obviously "personal
purposes", and the EU sui generis database right can attach to a substantial
extraction from an organiser's database even where individual facts (a time, a
session name) are not themselves copyrightable. This is a deliberate call to
make, not to discover later. Options, roughly in order of safety:

1. Seek permission or a data-licence arrangement with Dorna (the rights holder).
2. Use an unofficial community ICS feed instead, as was done for F1 - though that
   only moves the redistribution question one hop and adds a single-person
   dependency.
3. Proceed on the public-facts theory - weakest, and squarely the thing Clause 3
   speaks to.

**Decision (2026-08-23):** the owner chose to proceed and set `status = "live"`,
accepting the risk above. If usage grows or Dorna objects, revisit - option 1
(a licence) or option 2 (a community feed) remain the safer footings, and
reverting is a one-line flag flip back to `"unverified"`.

### WorldSBK

**Status: live (set 2026-08-23).** Investigated 23 August 2026. Same publisher
(Dorna) as MotoGP, but a different, older platform - a JSON:API rather than
MotoGP's single embedded-broadcasts call.

| Field | Finding |
|---|---|
| Endpoint | Base `https://api.wsbk.pulselive.com/wsbk-events/v1`. Two stages: `/seasons/{year}/rounds` lists the rounds; `/seasons/{year}/rounds/{code}/sessions` serves the timetable for one round |
| Type | Internal JSON:API (Pulselive gplat). Unauthenticated. Found via `window.SD_DOMAIN` / the site's own resource requests, *not* by guessing paths - the resource prefix is `wsbk-events/v1`, and `wsbk/v1` 404s |
| One fetch or many? | **Many.** No season-wide sessions endpoint (`/seasons/{y}/sessions` is 404) and `?include=sessions` is 403, so it is 1 rounds call + 1 per round (~13 requests). The source implements `resolve_urls` (see scrapers/sources/base.py) to fetch the rounds index and expand it into per-round session URLs |
| Response shape | JSON:API. Round: `{id, attributes:{name, brief_description, source_id, sequence_order, status}, relationships:{circuit}}`. Session: `{id, attributes:{brief_description, start_date_utc, end_date_utc, status}, relationships:{round, category}}`. Trimmed captures in `scrapers/fixtures/wsbk_rounds.json` and `wsbk_sessions_*.json` |
| **Timezone convention** | Sessions carry an explicit `start_date_utc` / `end_date_utc` (real UTC, `+00:00`). Used directly. (There is also a `start_date_circuit` stamped `+00:00` - a wall-clock local time with a misleading UTC marker; ignored.) Verified: Aragon SBK Race 1 `start_date_utc` 12:00 UTC = 14:00 circuit-local, correct for CEST |
| Classes in one feed? | **Yes**, via the per-round sessions call: WorldSBK, WorldSSP, WorldSPB and the Women's WorldWCR (at selected rounds) |
| Provisional times distinguishable? | **No** (`status` is FINISHED/NOT-STARTED, temporal). Treated as confirmed, as for F1 and MotoGP |
| Refresh behaviour | Standard CDN caching; no per-resource ETag relied on |
| Auth | None |
| robots.txt | `www.worldsbk.com/robots.txt` permits the calendar; `api.wsbk.pulselive.com/robots.txt` is 404 (no restriction). Verified 23 August 2026 |
| Terms of Use | Same Dorna terms as MotoGP (personal-use-only). Risk accepted 2026-08-23 - see the MotoGP "Terms of Use" note; the same caveats and revert path apply |
| Confidence | High on the data; the two-stage shape is more moving parts than MotoGP but each part is simple and snapshotted |

**Format quirks, handled in `scrapers/sources/wsbk.py`:**

- Session labels are Superpole-vocabulary: "Superpole" is qualifying and
  "Superpole Race" is a race, both already distinguished in `normalize.py`.
- "Superpole" arrives padded with trailing spaces; collapsed.
- The **YR3EC** class (a Yamaha R3 one-make cup) is dropped - `_CATEGORY_MAP`
  covers only SBK/SSP/SPB/WCR. **WorldSSP300 ended after 2024**; the config
  categories were updated from `wssp300` to `wspb` + `wcr` to match 2026.
- Finished rounds can carry a red-flag artifact (e.g. "Race 1 - Red Flag" then
  "Race 1"); both classify as races and the sequence falls back to positional so
  they never collide on the natural key. Upcoming rounds do not have these.
- Five new venues added to `config/venues.toml`: Most, Cremona, Estoril,
  Magny-Cours, Donington (Balaton was already added for MotoGP).

**Architecture note:** WorldSBK is the first two-stage source. The generic hook
it uses - `resolve_urls(season, client)` - lives in the pipeline and is available
to any future series whose URLs are only knowable after an index fetch (WEC,
IMSA, IndyCar and NASCAR are all likely candidates).

### IMSA

Status: not investigated.

### IndyCar

Status: not investigated.

### NASCAR

Status: not investigated.