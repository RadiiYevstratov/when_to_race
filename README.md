# ON TRACK — unified motorsport schedule

One question, answered better than anywhere else: **what motorsport is on right
now, and what is on next** — across several international championships, in your
own timezone, including practice and qualifying rather than just the race.

Live at **[ontrackapp.me](https://ontrackapp.me)**.

---

## What is covered

Four championships are scraped and served. The rest appear in the interface as
greyed-out chips, so the site is honest about what it does not yet cover rather
than pretending the list is complete. A series goes live the moment it records a
successful scrape — nothing is switched on by hand.

| Championship | Classes | Source |
|---|---|---|
| Formula 1 | F1, F2, F3 | Community ICS for the Grand Prix; the F2 and F3 championships' own race pages |
| MotoGP | MotoGP, Moto2, Moto3 | motogp.com, embedded JSON |
| WorldSBK | WorldSBK, WorldSSP, WorldSPB, WorldWCR | worldsbk.com, JSON:API, two-stage |
| FIA WEC | WEC | fiawec.com, schema.org JSON-LD |

Not yet covered: WRC, IMSA, IndyCar, NASCAR, and F1 Academy. Each needs its own
source discovery — see `docs/sources.md` for the procedure and the legal checks.

---

## Layout

```
config/          series and venue registries — adding a championship starts here
db/              migrations (source of truth for the schema) and the seed script
scrapers/        the Python pipeline
  sources/       one module per series; the only layer that knows a site's quirks
  fixtures/      committed sample responses; the parser tests run against these
web/             Next.js app (App Router, server components)
tools/           one-off generators kept so their output can be rebuilt
docs/            discovery record and data model review
deploy/          systemd unit and timer, as an alternative to GitHub Actions
```

Python for the scrapers, TypeScript for the web app. The two halves never share
a process — they communicate only through the database.

---

## Running it

### Scrapers

The core — parse, normalize, validate, diff — is stdlib-only, so the test suite
needs no install step:

```bash
python -m unittest discover -s tests -t .
```

Exercise the whole pipeline against the committed fixtures, writing nothing:

```bash
python -m scrapers.run --series f1 --source fixture --season 2026 --dry-run
```

Against a real database:

```bash
pip install -r requirements.txt
for f in db/migrations/*.sql; do psql "$DATABASE_URL" -f "$f"; done
python -m db.seed
python -m scrapers.run --series all
```

Exit codes: `0` all requested series succeeded, `1` at least one failed, `2` bad
invocation. `--series all` runs only the sources that have been verified, so a
championship still awaiting discovery never fails the scheduled job.

### Web app

```bash
cd web
npm install
cp .env.example .env.local   # then fill it in — every value but the last is required
npm run dev
```

```bash
npm test          # logic, plus integration tests when DATABASE_URL is set
npm run typecheck
npm run build     # must succeed with no DATABASE_URL — see below
```

---

## The parts that matter

**Timezones.** Every time is stored and transmitted as UTC and converted at
render. Circuit-local times go through the venue's IANA zone, never a fixed
offset — a hardcoded offset is wrong on every DST boundary. Sessions are grouped
under the day they fall on *in the viewer's* timezone; a 15:00 race in Melbourne
is the previous evening in Los Angeles, and the board marks the difference with
`+1` / `-1` rather than filing it under a day that will not match what the
broadcaster says.

**A missing end time is never invented.** Some organisers publish no end at all,
and MotoGP publishes one identical to the start for every race — which is an
absent end wearing the costume of one. Both are stored as absent. The display
layer applies a stated assumption, per session type and per championship, from
the medians of the sessions where an end *is* published. `web/lib/time.ts` is the
only place that decides this, because the board, the live query and the calendar
export must not each carry their own guess.

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

**Circuit outlines are traced, never drawn.** A venue with no traced map renders
no art at all rather than an approximation — a fan recognises Monza instantly,
and a nearly-right shape reads as broken. `tools/make_icons.py` and
`web/lib/circuits.ts` carry the same rule.

**No results, ever.** Not in scope, and a spoiler risk on a schedule product.

---

## Operational rules

**The build must never need a secret.** `next build` runs where runtime
environment variables are not available, so the database connects on first query
rather than on import. CI builds with `DATABASE_URL` empty to keep it that way.

**`/admin` fails closed.** Basic auth guards the health dashboard, rate limited
to ten attempts per quarter hour. It refuses to serve at all if `ADMIN_PASSWORD`
is under twelve characters or appears anywhere in `DATABASE_URL` — sharing one
secret between the weaker surface and the stronger one means guessing the first
hands over the second.

**The web app reads the schedule and never writes it.** Only the scrapers write
that, and the rule exists so a bug in a page can never put a time on the board
that no source published.

There is exactly one exception, and it is not the schedule: the contact form
inserts into `contact_messages`. Nothing reads that table into the board and no
scraper touches it. **A strictly read-only database role will therefore break
the contact form** - it needs INSERT on that one table, and UPDATE on it if the
"mark as handled" control is ever added. Everything else can stay read-only.

---

## Adding a championship

1. Add an entry to `config/series.toml` with its categories.
2. Do discovery and record it in `docs/sources.md`.
3. Add a module in `scrapers/sources/` and decorate it with `@register("code")`.
4. Commit a trimmed sample response as a fixture and write a parser test.
5. Set `source.url` and flip `status` to `"live"`.

No schema change, no frontend change. Classes, colours and pages are all derived
from what has actually run: a class with no sessions gets no chip, no page and no
sitemap entry, and appears on its own the moment it does.

If a series publishes an ICS feed, step 3 is usually a subclass of `IcsSource`
with two or three overrides — see `scrapers/sources/f1.py`.

---

## Testing

- **Parser tests run against committed fixtures**, with the source's own
  escaping preserved. These are what catch a site redesign before users do.
- **Integration tests execute every read query against a real database.** A type
  checker cannot tell you an ORM changed the SQL it generates. They skip
  themselves when `DATABASE_URL` is unset, so CI without a database still runs.
- **Timezone tests** cover DST boundaries in both hemispheres, zones that never
  observe DST (`America/Phoenix`), non-hour offsets (`Asia/Kolkata`), and
  sessions crossing midnight for viewers in several zones.
- **Idempotency:** running the same scrape twice produces zero changes and zero
  `schedule_changes` rows.
- **Guard rails:** an empty response and a wholesale-different response both
  abort without mutating data.

CI runs the Python suite, the web suite, a type check, a credential-free build,
and `npm audit` at high severity.

---

## Deployment

Web app on **Railway**, with the root directory set to `web` — the repository
root carries `requirements.txt` and `pyproject.toml`, and a builder sniffing
those will otherwise decide this is a Python project. DNS and TLS through
Cloudflare, flattened at the apex.

Scrapers run every six hours on GitHub Actions (`.github/workflows/scrape.yml`),
or on a VPS via the systemd timer in `deploy/`. The runner is a plain CLI with no
platform coupling, so both invoke it identically, with a randomised delay so ten
sites are not hit at exactly the same second.

---

## Legal

Schedule facts are not themselves copyrightable, but the EU sui generis database
right can attach to substantial extraction from an organiser's database. Take
only times, names, venues and round numbers. Never republish scraped editorial
text, images or logos. Where a site's terms prohibit automated access, stop and
raise it rather than proceeding — see `docs/sources.md`.

Requests identify themselves with a User-Agent naming the project and linking to
this repository, respect `robots.txt`, and are rate limited to one request every
two seconds per host.

The site states plainly that it is independent and unaffiliated, and names every
source it draws from.
