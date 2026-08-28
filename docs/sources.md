# Sources

## Status: F1, MotoGP, WorldSBK, WEC, IndyCar and NASCAR live. IMSA is built and blocked

IndyCar and NASCAR run under a **recorded decision by the site owner**, not
under permission from the organisers: their Terms of Use prohibit automated
collection without written consent, and the site owner chose on 28 August 2026
to proceed anyway, taking session times, session names and venues only. The
clauses are quoted in `config/series.toml` beside each entry and in "The
American series and their terms" below, so the position is stated rather than
assumed by whoever reads this next.

IMSA has a finished adapter that has never run: imsa.com refuses this project's
HTTP client outright, and the only way past that is to change which client
appears to be asking.

Formula 1, MotoGP, WorldSBK and WEC are `status = "live"` and running against
confirmed sources (see the findings below). MotoGP, WorldSBK and WEC were set
live on 2026-08-23 after the owner accepted the Terms-of-Use risk documented in
the MotoGP findings (all three restrict use to personal purposes; WorldSBK is the
same publisher as MotoGP, WEC is a separate organiser with equivalent terms).
WRC and IMSA are still `status = "unverified"`, and `python -m scrapers.run`
refuses to run an unverified source unless you pass `--allow-unverified`. WRC
has no adapter yet; IMSA has one that cannot fetch.

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
| IndyCar | JSON | Medium | ~~Practice/qualifying naming varies by oval vs road course. Indy 500 has a qualifying weekend a week before the race — two events or one? Decide and document~~ **Wrong on the format: there is no JSON, it is server-rendered HTML.** Right about the naming. The Indy 500 is one event of thirteen days, as the source publishes it |
| IMSA | JSON | Medium | Daytona 24 and Sebring 12 have the same multi-day span problem as Le Mans |
| NASCAR | JSON | Medium | **Right on the format.** And right about the thin rounds: a Cup race can be the only session of its weekend, and the six playoff weekends have no timetable published at all |
| WRC | Hardest | Low | 15–20 timed stages across four days. Stage-level data may not be reliably available ahead of time. Degrade to shakedown + day start/end + Power Stage and set `detail_level = 'partial'` rather than showing nothing — the schema and validation already support this |

---

## The American series and their terms

IndyCar, NASCAR and IMSA were discovered, written, tested and - for the first
two - run against the live database before their Terms of Use were read. Rule 1
below says to read them first and stop if they prohibit automated access. All
three do prohibit it.

| Series | Clause | Read |
|---|---|---|
| IndyCar | "use an automatic device (such as a robot or spider) or manual process to copy or 'scrape' the Services (or any portion thereof) or Service Content for any purpose **without our express written permission**" — [indycar.com/terms-of-use](https://www.indycar.com/terms-of-use) | 27 Aug 2026 |
| NASCAR | "Without the NASCAR Parties' **prior written consent**, you shall not: … B. Use robots, spiders, scripts, service, software or any manual or automatic device, tool, or process designed to data mine or scrape the NDM Network Services, including all images, video, data and other information contained on the NDM Network Services ("NASCAR Content"), or collect such information from the NDM Network Services using automated means" — NASCAR Digital Media Terms of Use, served at [imsa.com/terms](https://www.imsa.com/terms/) | 27 Aug 2026 |
| IMSA | The same NDM Network document above. imsa.com is where it is served from | 27 Aug 2026 |

**The decision, recorded.** On 28 August 2026 the site owner read the above and
chose to run IndyCar and NASCAR anyway, on the basis that what this product
takes is **session times, session names and venues** - no drivers, no teams, no
results, no images, no editorial text. Both are `status = "live"` with the
clause quoted beside them in config.

That reasoning is worth stating precisely, because the scope limit is a real
mitigation but it is **not an exemption from these particular clauses**:

- IndyCar's covers the Services "**or any portion thereof**" and "**for any
  purpose**", so a narrow extraction is inside it by construction.
- NASCAR's covers "**data and other information**", which is what a session
  time is.

What the narrow scope does buy is everything the clauses are actually there to
protect: no copyrightable expression is copied, nothing competes with their
media products, and rule 2 below - take only what the product needs - is
honoured rather than merely claimed. Schedule facts are not copyrightable in
the US, so what remains is a contract term rather than a property right, and
the realistic consequence of getting it wrong is a takedown request or an IP
block rather than a court.

**If either organiser objects**, the sequence is: set `status = "unverified"`
in `config/series.toml`, then

```
python -m tools.retire_series --series indycar,nascar --season 2026
```

which is a soft delete - every web query filters on `retired_at IS NULL`, so
the series leaves the board, the calendar feed and the sitemap while staying in
the database with its history. Both were already retired and restored once by
this route on 27-28 August, so it is a tested path rather than a plan. Asking
for written permission remains worth doing; these are ordinary aggregation
requests and organisers do grant them.

**IMSA is a different question and is still off.** imsa.com's front door
answers 403 to this project's HTTP client while serving the identical request
from Python's standard library. It is not about identity - the block does not
depend on the User-Agent, and this bot's own is served fine by the other
client - but the only way past it is to change which client appears to be
asking, and that is disguising who is knocking rather than disagreeing with a
contract term. Rule 3 is to be a good citizen visibly, so this one waits.

**One process note, which is the reason this section exists at all.** Reading
the Terms is the cheapest step in discovery and it was done last, after three
championships were built and two were live. It belongs before the first
request. Doing it in that order is what turns this into a decision someone can
make deliberately, rather than one they find out about later.

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
| Support categories included? | **No.** F1 only. F2, F3 and F1 Academy each come from their own championship's site - see below |
| Coverage | 22 rounds, 110 Formula 1 sessions for 2026, plus 117 support sessions from the feeds below. Sprint weekends correctly distinguish Sprint Qualifying from Sprint |
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

#### F2 and F3

**Status: live.** Verified 26 August 2026. Replaced a community ICS feed that
was serving wrong times - see "The feed that had to be replaced" below.

| Field | Finding |
|---|---|
| Endpoints | `https://www.fiaformula2.com/en/racing/{season}` and the same path on `fiaformula3.com`. These are season **indexes**: the adapter reads the round links out of each and fetches one page per round |
| Type | Server-rendered HTML carrying the timetable as escaped JSON, under `race.meetingSessions` |
| Official? | **Yes.** The championships' own sites, operated by Formula Motorsport Limited |
| **Timezone convention** | Naive local time plus **both** an IANA zone (`Europe/Rome`) and an explicit offset (`+02:00`) per session. Nothing to infer, and the two agree |
| End times | Present on every session |
| Sequence | `sessionNumber` is carried through as `sequence_hint`. This matters: F3 runs **two** qualifying sessions, A and B, which share a category and a session type, so sequence is the only thing separating them in the upsert key |
| Coverage 2026 | F2 at 14 rounds, F3 at 9. Which rounds they attend is read from the calendar each run rather than written down here |
| robots.txt | Neither site serves one - `/robots.txt` returns their 404 page. There is no directive to honour or to breach |
| Auth | None. There *is* an `api.formula1.com` endpoint behind a client-side key, and it returns the same data, but the public page already carries it - reading the page needs no key that was not issued to us |
| Confidence | High. Official, structured, and the timetable is the same object their own page renders from |

**Format quirks, all handled in `scrapers/sources/f1.py`:**

- The payload is escaped into the HTML, so quotes arrive as `\"`. The fixtures
  keep that escaping, because unescaping them first would stop testing the part
  that actually breaks.
- The timetable array is bracket-matched rather than regexed - it contains
  nested objects, and a lazy match stops at the first inner bracket.
- **A published end time is occasionally earlier than its start.** F3 at the Red
  Bull Ring has a sprint race ending the day before it begins. The start is
  still credible, so only the end is discarded; a session without an end is
  already handled everywhere, and correcting the date would be inventing one.
- **An unscheduled round is published as midnight rather than as nothing.**
  Baku, Qatar and Abu Dhabi arrive with every session at 00:00 to 01:00 local -
  practice, qualifying and both races. No race weekend runs four sessions at
  midnight, so this is the site's filler showing through, and passing it on
  would put a wrong time on the board. The round keeps its dates at
  `start_precision = "day"` and the board renders `--:--`.

  The test is the **whole round**, never a single session: one midnight start
  could be genuine at a night race, four cannot. This was found by the
  same-instant rule below rather than by looking - two of the four collided,
  which is the only reason anyone noticed.

**Support sessions are attached to a Grand Prix by time, not by name.** This is
the load-bearing decision in the adapter, and it predates this source. Round
names cannot be matched to Grand Prix names: 2026 has two Spanish rounds, and
these sites call them `barcelona` and `madrid` while the Grand Prix feed calls
them "Spanish GP" and "Madrid GP". A session that runs inside a Grand Prix
weekend belongs to it, and unlike a name that is checkable. The window is three
days rather than one because **Monaco runs Formula 3 on the Thursday**: at one
day that practice missed its weekend by five minutes. Anything with no Grand
Prix inside the window is dropped and logged, never guessed onto the nearest.

#### F1 Academy

**Status: live.** Verified 26 August 2026. Restored from its own site after the
feed it originally came from was removed for serving wrong times.

| Field | Finding |
|---|---|
| Endpoint | `https://www.f1academy.com/Racing-Series/Calendar`. One page for the **whole season**, sessions included - so unlike F2 and F3 there are no round pages to fetch, and a season costs one request |
| Type | Next.js `__NEXT_DATA__`, a JSON payload embedded in the server-rendered page |
| Official? | **Yes.** The championship's own site |
| **Timezone convention** | Full ISO timestamps carrying the circuit's own offset (`2026-03-13T09:10:00+08:00`). The only source here that needs no inference at all - and unlike WEC, the offset is the circuit's rather than a content system's |
| End times | Usually present; absent on rounds that have no confirmed times yet |
| Provisional flag | **Yes**, per session (`Unconfirmed`) and per round (`Provisional`). No other F1-family source distinguishes this |
| Coverage 2026 | 6 rounds |
| robots.txt | Served, and allows this path |
| Confidence | High. Official, structured, explicitly offset, and it says which of its own times it does not stand behind |

**Format quirks, all handled in `scrapers/sources/f1.py`:**

- **The round list is found by shape, not by path.** It is located as "a list
  whose entries have `Sessions`" rather than by walking a fixed key sequence.
  The path is the site's private business and moves with any redesign; what we
  want is the list, and describing it by content survives the redesign.
- **Unconfirmed rounds carry placeholder times.** Austin and Las Vegas are
  published at 01:00 and 02:00 with no end. The site says outright that these
  are unconfirmed, which is more than F2 does for the same defect, so the round
  keeps its dates at `start_precision = "day"` and drops the clock.
- **The page shows whichever season it is currently on**, which is not always
  the one being scraped. Sessions from another year are dropped and counted,
  never quietly filed under the requested season.
- **Every session names its winner.** None of it is read. Results are out of
  scope and a spoiler risk, and the cheapest place to honour that is the point
  the data enters rather than the point it would be displayed - a pinned test
  asserts no winner reaches a stored session.

#### A class cannot be in two places at once

Two sessions of the **same category** at the **same instant** are not a
schedule; they are a schedule with a mistake in it. F1 Academy publishes
Montreal's two qualifying sessions at an identical minute, and Formula 2 does
the same at three rounds.

Which of the two times is wrong is not knowable from here, and guessing a
correction would be worse than saying nothing. What *is* knowable is that the
times are not final, so both sessions are marked provisional and both are kept
- they are real sessions, and dropping one would hide a race.

This lives in `normalize.py` rather than in any one adapter, because it is a
statement about physics rather than about a website. Written for F1 Academy, it
found the Formula 2 faults on its first run - including the midnight rounds
above, which nothing else had caught.

#### The feed that had to be replaced

F2, F3 and F1 Academy were first taken from motorsportcalendars.com, the
publisher behind f1calendar.com. It was convenient - one ICS per championship,
the same shape as the Grand Prix feed - and it was **wrong**.

At Monza its F2 practice was 1h55m late, its F2 sprint 3h40m early, and its F3
sprint **7h15m** out. Not a timezone offset, which would at least be uniform and
correctable; the errors ran in both directions and differed per session. It also
collapsed F3's two qualifying sessions into one, losing a session outright.

Two lessons worth keeping:

1. **A plausible schedule is the hardest kind of wrong to notice.** Every time
   it published was a real time of day on the right date at the right circuit.
   Nothing in the pipeline could have caught it - the validators check internal
   consistency, and it was internally consistent. It took a person comparing it
   against the official page.
2. **Convenience of format is not evidence of quality.** The ICS was easier to
   consume than the official pages and that is the only thing it was better at.

**F1 Academy's 25 sessions went with it**, rather than being left in on the
assumption that they were the accurate part of a source that was wrong
everywhere else. It is now read from its own site, which needed separate
discovery: it does not use the `/en/racing/{season}` layout F2 and F3 share.

**Known limitations, in order of how much they matter:**

1. **F2 and F3 give no provisional-time signal.** The product's stated worst
   failure mode is showing a provisional time as confirmed, and neither site
   distinguishes them - the midnight rounds are the shape that defect takes
   when it is visible, and there is no guarantee it is always visible. F1
   Academy does flag it, per session and per round. Anything better for the
   other two would need a different source.
2. **Four publishers, and the Grand Prix one is still unofficial.** F2, F3
   and F1 Academy each come from their own championship; Formula 1 itself does
   not. Any of them can go stale independently, and the 48-hour marker is per
   series, not per source - so a dead support source shows as a quietly
   F1-only season rather than as an error. Worth a per-category staleness
   check.
3. **Support rounds depend on the Grand Prix feed.** Attachment needs Grand
   Prix weekends to attach to. If the main feed fails, support sessions are
   dropped rather than allowed to invent half-empty events of their own.
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

**Status: built and blocked**, and never run against the live database.
Investigated 27 August 2026.

The Terms are the same NASCAR Digital Media document quoted above, and the site
owner's decision of 28 August 2026 covers this series too - but IMSA is off for
a second reason that the decision does not reach:

**The site refuses this project's client.** `imsa.com` answers 403 to every
   request from httpx, which is what `scrapers/http.py` uses, while serving the
   identical URL to Python's standard-library client. Tested one variable at a
   time: it is not the User-Agent (this bot's own is served fine by the other
   client), not the Accept header, not Connection, and not the TLS context.
   Whatever the filter keys on, getting past it would mean disguising which
   client is asking, and rule 3 is to be a good citizen visibly.

The adapter is written and tested and the findings below are real, so this is
ready the day there is written permission.

| Field | Finding |
|---|---|
| Endpoint | `https://www.imsa.com/wp-json/wp/v2/schedule` lists every event as a WordPress post with a link; each event page carries its weekend timetable. Two stages, so the adapter implements `resolve_urls` |
| Type | The API lists events but not their sessions - `content` comes back empty - so the timetable is read from page markup. The only other namespace the site exposes is `rapi/v1/allresults`, which is results and out of scope |
| Official? | **Yes.** IMSA's own site |
| **Timezone convention** | US Eastern for every circuit, as at IndyCar. **Verified** - see below |
| End times | **Present on every session**, which puts this with WEC and WorldSBK rather than with the other American sources, and matters most for the endurance rounds a generic duration would badly misjudge |
| Provisional times | Not distinguishable |
| Support categories | WeatherTech and Michelin Pilot Challenge are both configured. Porsche Carrera Cup, Lamborghini Super Trofeo, Mazda MX-5 Cup, Mustang Challenge and VP Racing SportsCar Challenge also share the weekends and are dropped rather than filed under a class they do not belong to |
| Coverage 2026 | 12 WeatherTech events and a Pilot Challenge round at Mid-Ohio |
| robots.txt | Disallows only `/wp-admin/` and `/*/feed/`; neither is this |
| Confidence | High on the data, and it does not matter until the Terms do |

**The timezone was verified without needing a document**, which is the part of
this worth keeping. IMSA and IndyCar share the Long Beach street circuit on one
weekend, and two championships cannot be on one track at the same time.
IndyCar's times there are already known to be Eastern, checked against an
official schedule PDF. Reading IMSA's times as Eastern, its nine Long Beach
sessions interleave with IndyCar's with **no overlap at all**; reading them as
Pacific puts **three** of them on top of IndyCar sessions, including the Grand
Prix of Long Beach running during IndyCar qualifying. One reading is a
timetable and the other is impossible.

**Naming the class needed the page to answer itself.** The schedule says it
three ways: `"Practice 1 - WeatherTech Championship"`, `"WeatherTech
Championship Qualifying"`, and - for a named race - not at all. The third is the
problem, because a weekend has one named race per championship: at Watkins Glen
"Sahlen's Six Hours of The Glen" is the WeatherTech race and the "LP Building
Solutions 120" is the Pilot Challenge's, and the names say nothing. The
broadcast schedule lists the same races beside their championship's logo, so
the class is read from there and matched back by name. Only the class - never
the times, which differ by a few minutes because coverage starts before the
session does.

### IndyCar

**Status: live.** Investigated 26 August 2026. Terms of Use read 27 August 2026
and they prohibit scraping without express written permission; running anyway is
the site owner's recorded decision of 28 August 2026, taking times and venues
only - see "The American series and their terms" above.

The only source here parsed from plain HTML, and the only one that publishes
every session in a timezone that is not the circuit's.

| Field | Finding |
|---|---|
| Endpoint | `https://www.indycar.com/Schedule` lists the season's rounds; each links a page like `/Schedule/2026/Mid-Ohio` carrying that weekend's timetable. Two stages, so the adapter implements `resolve_urls` |
| Type | **Server-rendered HTML.** The fourth and last option in the discovery order, taken because there is nothing above it: no calendar feed, no internal API behind the page, no `__NEXT_DATA__`, no JSON-LD. The only network call a loaded page makes is to a share-button widget |
| Official? | **Yes.** IndyCar's own site |
| **Timezone convention** | **US Eastern, for every round, whatever timezone the circuit is in.** Portland practice reads "5:00PM ET". The label is on every row and is read rather than assumed, so a page that ever says CT is not silently taken as Eastern |
| End times | **None anywhere.** Every row is a start |
| Provisional times | Not distinguishable. No TBC, TBD or equivalent appears anywhere in the season |
| Support categories | **No.** Indy NXT shares the weekend but not the web page - see below |
| Coverage 2026 | 18 round pages, 100 rows, becoming 17 events and 89 sessions |
| robots.txt | Not served - `/robots.txt` returns the site's 404 page. There is no directive to honour or to breach |
| Auth | None |
| Confidence | Medium-high on the data, medium on the format. It is official and internally consistent, but markup is the most fragile thing to depend on |

**The timezone was verified against an independent official document**, which is
what the discovery protocol asks for and the one check worth doing twice. The
site lists Laguna Seca practice at "5:00PM ET". The weekend-schedule PDF linked
from that same page prints **"Schedule subject to change - All times local
(Pacific)"** and lists it at 2:00 PM. The two agree exactly, which settles it:
the site normalises to Eastern, and treating those times as circuit-local would
put every West Coast session three hours wrong - plausibly wrong, on a board
where nothing would look out of place.

The adapter therefore resolves Eastern to an absolute instant itself rather than
handing normalize a naive local time. That is a deliberate exception to sources
leaving timezones alone: reading a stamp the source states outright is parsing,
while deciding what zone a *circuit* sits in stays with normalize and the venue
registry. Passing "ET" through as `local_timezone` would be worse than useless -
normalize reads that as a display override, so every Portland session would be
shown to a viewer in Eastern.

**Three ways the source repeats or omits itself, all handled:**

- **A session is listed once per broadcaster.** Indianapolis 500 practice appears
  at 12:00PM on FS2 and again at 4:00PM on FS1. One session running from noon,
  two television windows - and the second stored as a session is a practice at
  an hour nothing starts. Rows sharing a day, a class and a name collapse to the
  earliest time given.
- **A doubleheader is two rounds on one weekend.** Milwaukee Race 1 and Race 2
  have separate pages listing overlapping sessions; qualifying is on both. They
  fold into one event, which is what a weekend view is for. The same collapse
  handles the overlap, which is why it runs across the season rather than per
  page - a per-page rule passed the validators' `duplicate_uid` check straight
  into a failed run.
- **The day headings carry no year.** "Friday, Aug 28" is all there is, so the
  year comes from the season being scraped - and is then checked against the
  weekday the heading names. A date that does not fall on the day the page says
  it does means the assumption is wrong or the page is stale, and neither is
  publishable.

**Two entries on the schedule are not sessions.** The Indianapolis 500 timetable
includes a "Pre-Race" ninety minutes before the race and the Oscar Mayer Wienie
500, which is a hot dog race. The rule is that a row must either name its
championship or read as a session on its own: that keeps Phoenix's unprefixed
"Practice 1", drops the hot dogs, and keeps the Pit Stop Competition, which is
genuinely IndyCar and genuinely on track.

"Pre-Race" needed a fix in `normalize.py` rather than here, because it was being
typed as a **race** - the word is inside it - which would have put a second
Indianapolis 500 on the board two and a half hours before the real one. The same
pass taught the classifier that IndyCar spells qualifying "Qualifications".

**Indy NXT is configured but not published.** Its sessions do not exist in
machine-readable form anywhere: indynxt.com's schedule page carries event cards
with no session times at all, and on indycar.com its rows appear only inside the
per-round PDFs. A category with no source is left empty rather than filled from
a worse one - the same call made for F1 Academy before its own site was found.

**Known limitations, in order of how much they matter:**

1. **Markup is the whole contract.** A redesign breaks this, and unlike a JSON
   API there is no version of it that is meant to be read by anyone. The
   mitigations are that it fails loudly - an empty round page is logged, and the
   validation floor turns a silent breakage into a failed run - and that the
   fixtures are real excerpts, so a shape change fails a test before it reaches
   anyone's phone.
2. **No end times at all**, so every session's duration is the assumed one from
   `web/lib/time.ts`. For an oval race that is a poor guess, and it decides how
   long the board calls something live.
3. **No provisional signal**, so a time that moves cannot be flagged before it
   does. Same limitation as F2 and F3.
4. **Indy NXT is missing**, as above.
5. **The Indianapolis 500 is one event spanning thirteen days**, May 12 to 24,
   because that is how IndyCar publishes it. It is not a weekend, and a weekend
   view will show it as one long one.

### NASCAR

**Status: live.** Investigated 26 August 2026. Terms of Use read 27 August 2026
and they prohibit scraping without prior written consent; running anyway is the
site owner's recorded decision of 28 August 2026, taking times and venues only -
see "The American series and their terms" above.

It is the best-shaped source of any championship here and the cheapest to run:
one request carries the whole season for all three national series.

| Field | Finding |
|---|---|
| Endpoint | `https://cf.nascar.com/cacher/{season}/race_list_basic.json`. The feed behind nascar.com's own schedule page |
| Type | JSON. `{"series_1": [...], "series_2": [...], "series_3": [...]}` - Cup, Xfinity, Craftsman Truck - each a list of races, each race carrying a `schedule` array of timed entries |
| Official? | **Yes.** NASCAR's own content host |
| **Timezone convention** | `start_time_utc`, and it genuinely is UTC - see below. No offsets, no per-track zones, nothing to infer |
| Session typing | **The feed types its own entries.** `run_type` is 1 practice, 2 qualifying, 3 race, and 0 for paddock logistics. No name-guessing needed |
| End times | None. Every entry is a start |
| Provisional times | Not flagged, but effectively signalled: a race whose timetable is not published yet has an empty `schedule` rather than a made-up one |
| Support categories | **Yes, all three in one payload** - the only source here where a weekend needs exactly one fetch |
| Coverage 2026 | 98 races over 42 weekends, 249 sessions. 17 of those sessions are day-precision playoff races |
| robots.txt | `www.nascar.com` disallows only `/wp-admin/` and `/*/feed/`; neither is this. `cf.nascar.com` serves no robots.txt at all (403), so there is no directive to honour or breach |
| Auth | None |
| Confidence | High. Official, structured, self-typing, and the timezone was confirmed against a second independent publication of the same times |

**`start_time_utc` was verified, not trusted.** The field name is a claim, and
the earlier F1 and IndyCar findings are what a wrong claim costs. nascar.com's
schedule page publishes each race a second time and independently, with an
offset-stamped time *and* a Unix epoch:

```
"Event_Time_Est":"2026-07-05T18:00:00-0400","Event_Time_Unix":"1783288800"
```

An epoch cannot be vague about its timezone. Across the 32 races carried by both
representations the feed's UTC and the site's epoch agree **exactly - every one**,
on both sides of the daylight-saving boundary and at Pacific tracks as well as
Eastern ones.

**`race_date` is not used for times**, deliberately. Its offset from the same
race's UTC start is neither the track's zone nor consistently Eastern - Las Vegas
and Sonoma both come out four hours apart, which is neither - so whatever
convention it follows is not one worth guessing at. Only its date is read, and
only for a race that has no timetable at all.

**Two things needed deciding rather than parsing:**

- **A weekend, not a race.** The three series each run their own race under their
  own sponsored name at one track on one weekend, and this product's unit is the
  weekend. Races group into events by track and ISO week - Friday, Saturday and
  Sunday always share a week, which is why the week is the key - and the weekend
  is then named after its **Cup** race, which is what it is known by and what
  anyone would search for: "Coca-Cola 600", not "Charlotte, week 21". Naming
  happens after grouping and not before, which is what lets the three series
  share an event while each keeps its own race name. The Truck-only rounds at
  Lime Rock and Indianapolis Raceway Park have no Cup race and take the
  circuit's name; the month is added to any two names that would collide, which
  in 2026 is Richmond's two "Cook Out 400"s.
- **The playoffs have no timetable yet.** The last six weekends of 2026 carry an
  empty `schedule`, because NASCAR publishes those closer to the date. The dates
  are known, so the race is kept at day precision and marked provisional - the
  board renders `--:--` - rather than either inventing a time or hiding the
  championship decider from the calendar.

**A race that was rained off is still in the feed at the time it did not run.**
Charlotte's truck race in May appears three times: twice with `notes:
"Postponed"` and once with the lap breakdown of the race that actually ran. All
three stored would be three races on one weekend, and one race in a subscribed
calendar three times - which is exactly what the validators reported, as a
duplicate calendar UID. Worth noting that the feed **says** which is which
rather than leaving it to be inferred from the ordering.

**The feed is also full of results**, and none of them are read:
`winner_driver_id`, `pole_winner_speed`, `average_speed`, `margin_of_victory`,
and a `race_comments` field that is a written race report naming the winner in
its first sentence. A pinned test asserts no winner reaches a stored session.

**Known limitations:**

1. **No end times**, so every duration is the assumed one from
   `web/lib/time.ts`. That decides how long the board calls a race live, and a
   500-mile race is a poor fit for any generic assumption.
2. **Practice and qualifying are sometimes published at the same instant**, at
   Nashville and Chicagoland. One class cannot be in two places at once, so
   both are marked provisional by the general rule in `normalize.py` rather than
   one of them being picked as the right one.
3. **Two tracks needed new slugs rather than existing ones.** `las_vegas` here
   was already the Strip circuit Formula 1 races on, and `miami` the Autodrome
   rather than Homestead. Reusing either would have put a race at the wrong
   circuit - the kind of mistake that reads as perfectly plausible.