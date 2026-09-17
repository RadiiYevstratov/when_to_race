# The Instagram account

## Status: built and tested. Not connected to an Instagram account yet

Everything up to publishing runs today against the real calendar: the job picks
the day's subject, draws the card, writes the caption, checks the caption back
against the database and stores it. What it cannot do is post, because posting
needs credentials that only a person with the Instagram account can create. That
is the one remaining step, and it is described at the bottom.

Until then `python -m social.run` is a complete dry run. Nothing about the code
changes when the token arrives; `--publish` starts working.

---

## What it does

Once a day, at 12:00 Europe/Bratislava, the job asks one question: *is there
anything worth saying today?* Most days there is. Some days there is not, and it
says nothing, which is the part that needed the most care - an account that
posts because the cron fired rather than because something is on reads as
automation within a week.

```
decide -> brief -> card -> caption -> validate -> store -> publish -> record
```

| Step | Module | What it is |
|---|---|---|
| decide | `social/selection.py` | Scores every candidate and picks one, or none |
| policy | `social/policy.py` | The numbers that decide. Tuned by season replay |
| brief | `social/brief.py` | The facts the post is allowed to state, and nothing else |
| card | `social/cards.py` | 1080×1350 JPEG, drawn from the circuit outline |
| caption | `social/captions.py` | Written by Claude from the brief, or composed if that fails |
| validate | `social/captions.py` | Rejects any time, weekday, year or result not in the brief |
| publish | `social/instagram.py` | Two Graph API calls, plus the token's own upkeep |
| record | `social/repository.py` | Every outcome, including the quiet days |

### Why the caption is checked rather than trusted

The generator is given the brief and nothing else - never the database, never
the wider calendar - and the finished text is then read back against that same
brief. Every clock time, weekday and year in the caption must appear in the
brief; anything else is a claim that came from somewhere other than the
schedule, and the post is dropped rather than published. Results, winners and
standings are rejected outright: this account publishes schedules, and a spoiler
in the feed of someone avoiding one is the worst thing it could do.

If the model is unavailable, refuses, or writes something that fails the check,
a caption composed by string formatting is used instead. It is plainer. It
cannot be wrong. The account keeps working when Anthropic is down.

### Why the image is drawn rather than photographed

Motorsport photography is owned by Getty and the championships, and cannot be
licensed by an unattended job. Photorealistic generated imagery is detected by
Meta through C2PA and IPTC provenance, labelled "AI info", and subject to
mandatory disclosure. Neither is available here, so the card is drawn from the
circuit outlines the site already traces - free, consistent, and for a schedule
account more useful than a stock photograph of a car.

### Two calendars, never mixed

A NASCAR race at 20:00 on Thursday in Tennessee is 02:00 on Friday in
Bratislava. Everything a reader sees is in *their* frame, because "today" and
"tomorrow" are theirs; the circuit's clock is given alongside and names its own
weekday whenever the two disagree. `SessionLine` deliberately has no plain
`weekday` field, so no future change can pair one frame's day with the other's
time by accident.

---

## Running it

```bash
python -m social.run                       # today, build everything, publish nothing
python -m social.run --publish             # today, for real
python -m social.run --date 2026-10-04     # explain one day's choice, build nothing
python -m social.run --replay 2026-03-01 2026-12-06   # a whole season's cadence
python -m social.run --status              # recent decisions and token health
python -m social.run --prune 60            # drop card images older than 60 days
python -m social.cards --out card.jpg      # draw a sample card and look at it
```

`--replay` is the one to reach for after changing anything in `policy.py`. It
walks the calendar day by day keeping its own history, so the novelty rules
behave exactly as they would in production, and prints how many posts a week the
new numbers produce. The current settings give about 4.5.

Every mode except `--publish` stops before Instagram.

---

## Environment

| Variable | Needed for | Notes |
|---|---|---|
| `DATABASE_URL` | everything | The same database the scrapers write to |
| `INSTAGRAM_ACCESS_TOKEN` | publishing | Seed only; see "The token" below |
| `INSTAGRAM_ACCOUNT_ID` | publishing | The Instagram **Business** account id, not the page id |
| `INSTAGRAM_TOKEN_ISSUED_AT` | optional | ISO date. Lets a hand-made token override the stored one |
| `ANTHROPIC_API_KEY` | optional | Without it, captions are composed rather than written |
| `SITE_URL` | optional | Defaults to `https://ontrackapp.me` |

No secret belongs in the repository. These are GitHub Actions secrets in
production and, locally, environment variables in the shell.

### The token, and why there is a table for it

Meta's long-lived token lasts 60 days. It can be refreshed indefinitely with no
human present - but the refresh returns a **different string**, and a job cannot
rewrite its own deployment secret. So `INSTAGRAM_ACCESS_TOKEN` is a seed, not the
source of truth: the first run copies it into `social_credentials`, and every run
afterwards reads, refreshes at the halfway mark, and writes back there. From that
point the integration renews itself forever with nobody present.

A token that lapses cannot be recovered by retrying - it needs a person and a
browser - which is why the refresh happens at 30 days rather than 55, why a
failed refresh is a warning rather than an error, and why the age is printed on
every run.

To replace the token by hand, set both `INSTAGRAM_ACCESS_TOKEN` and
`INSTAGRAM_TOKEN_ISSUED_AT`. The environment wins only when it holds a different
token with a newer issue date, so a stale seed cannot undo a refresh.

---

## The schedule

`.github/workflows/instagram.yml` fires at **10:00 and 11:00 UTC** every day.
GitHub's cron is UTC only and knows nothing about daylight saving, so the job
runs `--check-hour` and acts only on the firing that is actually noon in
Bratislava: the first in summer, the second in winter. The test is the hour
itself, not a window around noon, because GitHub routinely starts a scheduled
job a quarter of an hour late and a window wide enough to absorb that would also
admit the other firing.

A post can be made by hand from the Actions tab at any time. The dispatch form
defaults to a dry run.

### It cannot post twice

Three layers, in order of how much you would have to break to get past them:

1. `already_published()` is checked before anything is generated, so a re-run
   costs nothing.
2. A unique partial index, `social_posts_one_per_day`, makes a second published
   row for a day impossible at the database.
3. The workflow's `concurrency` group stops two runs overlapping.

`--force` exists for the case where a post failed halfway and was fixed by hand.

---

## Where to look when something is wrong

`python -m social.run --status`, or `/admin/social` on the site. Every run writes
a row whatever happened - published, dry run, quiet day or failure - so the log
answers "what did it do on the 4th?" rather than only "what did it post?".

| Outcome | Means |
|---|---|
| `published` | It went out. `instagram_post_id` is the post |
| `dry_run` | Everything was built and nothing was sent. Also what a missing token produces |
| `skipped` | Nothing was worth posting, or the day was already covered. `error_message` says which |
| `failed` | Something broke. `error_message` says what, and the card is kept so it can be retried |

The most likely production failure is Instagram being unable to fetch the card.
It does not accept an upload - it fetches the image from a public URL - so the
card is served from `/api/social/card/<id>.jpg` by the site itself. If that route
is down or the site is mid-deploy, the container ends in `ERROR` and the job says
so in those words.

---

## What is left: connecting the account

This needs the Instagram account holder and a browser. It is done once.

1. **Make the Instagram account a Business or Creator account** and link it to a
   Facebook Page. Personal accounts cannot publish through the API at all.
2. **Create an app** at developers.facebook.com - type *Business* - and add the
   **Instagram Graph API** product.
3. **Generate a long-lived access token** for the account with the
   `instagram_basic`, `instagram_content_publish` and `pages_show_list`
   permissions. Standard Access is enough for posting to your own account, so
   **no App Review is required**.
4. **Find the Instagram Business account id** - `GET /me/accounts` then
   `GET /<page-id>?fields=instagram_business_account`. It is a 17-digit number
   and is *not* the page id.
5. **Add the repository secrets**: `INSTAGRAM_ACCESS_TOKEN`,
   `INSTAGRAM_ACCOUNT_ID`, and `INSTAGRAM_TOKEN_ISSUED_AT` set to today's date.
6. **Run the workflow by hand** with *dry run* left ticked, and read the log.
   Then run it again with dry run unticked.

After that, nothing further is needed. The token renews itself.

### Limits worth knowing

- 100 published posts per rolling 24 hours. This job uses one.
- JPEG only, sRGB, 320–1440px wide, aspect ratio between 4:5 and 1.91:1, under
  8MB. The card is 1080×1350 and about 80KB; `_check_media()` asserts all of it
  before anything is sent.
- No native scheduling through the API. "Scheduled" means the job runs at noon.
- Captions: 2200 characters, 30 hashtags. Posts here use seven.
