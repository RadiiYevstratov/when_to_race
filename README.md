# On Track — unified motorsport schedule

One question, answered better than anywhere else: **what motorsport is on right
now, and what's on next** — across every major international series, in your own
timezone, including practice and qualifying rather than just the race.

---

## Status

Milestones 1, 2 and 4 are built and tested. Milestone 3 is blocked on discovery.

| # | Milestone | State |
|---|---|---|
| 1 | Schema + migrations + config seed | Done |
| 2 | Scraper framework | Done, 112 tests |
| 3 | F1 scraper (incl. F2/F3/F1 Academy) | Parser written and tested against a fixture; **no verified endpoint yet** |
| 4 | Frontend core | Home, weekend and season views, timezone handling, 28 tests |
| 5–8 | MotoGP, WSBK, NASCAR, IndyCar, IMSA, WEC, WRC | Not started — blocked on the same discovery step |
| 9 | Calendar export, filters | Done |
| 10 | Health dashboard | Done, at `/admin/health` |

**The blocking step is discovery.** No official endpoint has been confirmed for
any series. Every source is marked `status = "unverified"` in
`config/series.toml`, and the runner refuses to scrape an unverified source
without `--allow-unverified`. Read `docs/sources.md` — it contains the procedure,
what to record, and the legal checks to do first.

`docs/data-model-review.md` answers §11.1 of the brief: what I changed in the
data model and why, including three deviations worth your explicit sign-off.

---

## Layout

```
config/          series and venue registries — adding a championship starts here
db/              migrations (source of truth for the schema) and the seed script
scrapers/        the Python pipeline
  sources/       one module per series; the only layer that knows a site's quirks
  fixtures/      committed sample responses; the parser tests run against these
web/             Next.js app (App Router, server components)
docs/            discovery record and data model review
deploy/          systemd unit and timer
```

Python for scrapers, TypeScript for the web app. The two halves never share a
process — they communicate only through the database.

---

## Running it

### Scrapers

The core (parse, normalize, validate, diff) is stdlib-only, so the test suite
needs no install:

```bash
python -m unittest discover -s tests -t .
```

Exercise the whole pipeline against the committed fixture, writing nothing:

```bash
python -m scrapers.run --series f1 --source fixture --season 2026 --dry-run
```

Against a real database:

```bash
pip install -r requirements.txt
psql "$DATABASE_URL" -f db/migrations/0001_init.sql
python -m db.seed
python -m scrapers.run --series f1
```

Exit codes: `0` all requested series succeeded, `1` at least one failed, `2` bad
invocation.

### Web app

```bash
cd web
npm install
cp .env.example .env.local   # set DATABASE_URL
npm run dev
npm test                     # timezone and calendar-export tests
npm run typecheck
```

---

## The parts that matter

**Timezones.** Every time is stored and transmitted as UTC and converted at
render. Circuit-local times are converted through the venue's IANA zone, never a
fixed offset — a hardcoded offset is wrong on every DST boundary. Sessions are
grouped under the day they fall on *in the viewer's* timezone; a 15:00 race in
Melbourne is the previous evening in Los Angeles, and the board marks the
difference with a `+1` / `-1` on the time rather than filing it under a day that
will not match what the broadcaster says.

**Never destructively sync.** A run returning zero records is a failed run, not
an empty calendar. A run that would change more than 30% of a series' upcoming
sessions aborts for manual review. A session that disappears from a feed is
retired, not deleted. All three have tests; if any goes red, the scraper is
capable of destroying a working calendar.

**Staleness is visible.** Every series tracks its last successful scrape. Past 48
hours, affected rows carry a quiet marker. Users are never silently shown stale
times.

**Provisional times are marked as provisional**, and a session whose day is known
but whose time is not renders as `--:--` rather than a fabricated `00:00`.

**Calendar subscriptions update in place.** Stable per-session `UID`s and a
`SEQUENCE` that increments only on meaningful change, so a rescheduled session
moves in someone's phone calendar instead of appearing twice.

**No results, ever.** Not in scope, and a spoiler risk on a schedule product.

---

## Adding a championship

1. Add an entry to `config/series.toml` with its categories.
2. Do discovery and record it in `docs/sources.md`.
3. Add a module in `scrapers/sources/` and decorate it with `@register("code")`.
4. Commit a trimmed sample response as a fixture and write a parser test.
5. Set `source.url` and flip `status` to `"live"`.

No schema change, no frontend change. If a series publishes an ICS feed, step 3
is usually a subclass of `IcsSource` with two or three overrides — see
`scrapers/sources/f1.py`.

---

## Testing

- **Parser tests run against committed fixtures.** These are what catch a site
  redesign before users do.
- **Timezone tests** cover DST boundaries in both hemispheres, zones that never
  observe DST (`America/Phoenix`), non-hour offsets (`Asia/Kolkata`), and
  sessions crossing midnight for viewers in several zones.
- **Idempotency:** running the same scrape twice produces zero changes and zero
  `schedule_changes` rows.
- **Guard rails:** an empty response and a wholesale-different response both
  abort without mutating data.

---

## Deployment

Web app on Vercel. Scrapers on a VPS via the systemd timer in `deploy/`, or on
GitHub Actions via `.github/workflows/scrape.yml` — the runner is a plain CLI
with no platform coupling, so both invoke it identically. Every six hours, with
a randomised delay so ten sites are not hit at exactly the same second.

Set `CONTACT_URL` in `scrapers/http.py` to a real page before running against any
live site.

---

## Legal

Schedule facts are not themselves copyrightable, but the EU sui generis database
right can attach to substantial extraction from an organiser's database. Take
only times, names, venues and round numbers. Never republish scraped editorial
text, images or logos. Where a site's terms prohibit automated access, stop and
raise it rather than proceeding — see `docs/sources.md`.
