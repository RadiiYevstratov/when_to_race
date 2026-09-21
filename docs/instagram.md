# The Instagram account

## Status: live — connected to @ontrackapp.me on 21 September 2026

The token was verified against Meta the same day (Business account, 60-day
token, now stored and self-renewing). The job runs every afternoon and posts
when there is something worth posting. `python -m social.run` with no flags is
still a complete dry run, and every mode except `--publish` stops before
Instagram.

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
| publish | `social/instagram.py` | Two calls to `graph.instagram.com`, plus the token's own upkeep |
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
| `INSTAGRAM_TOKEN_ISSUED_AT` | optional | ISO date. Lets a hand-made token override the stored one |
| `INSTAGRAM_ACCOUNT_ID` | optional | Defaults to `me`, the token's own owner. Only needed on the Facebook Login path |
| `INSTAGRAM_API_HOST` | optional | Only for the Facebook Login path: `https://graph.facebook.com/v26.0` |
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

`.github/workflows/instagram.yml` fires at **:23 and :53 past every hour from
10:00 to 15:59 UTC** — twelve times a day. That is deliberate. GitHub's
scheduler delays scheduled jobs under load, the start of every hour is its
busiest time, and when load is high enough it drops queued jobs altogether. On
the first live day, firings set on the hour started hours late or not at all.

Each firing runs `--check-hour`, which acts only between **12:00 and 18:00
Bratislava** and only if the day is not already settled. The first firing
through decides — a post, or a recorded decision not to post — and the rest see
that and stop in seconds. A failure leaves the day open, so the next firing is
the retry. Daylight saving needs no special case: the window is in local time.

One more GitHub rule worth knowing: in a public repository, scheduled workflows
are **disabled after 60 days without repository activity**. Scheduled runs do
not count as activity. A commit every few weeks keeps both this job and the
scrapers alive.

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

**GitHub emails you when it needs a person.** The status step at the end of
every run fails - and a failed scheduled run is something GitHub emails the repo
owner about - when Meta rejects the token, or when the token is within two weeks
of expiry because refreshes have kept failing. Not being configured yet is not a
failure, so nothing goes red before setup.

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

## Which of the two Instagram APIs this uses

Meta has two, they are not interchangeable, and picking the wrong one fails in a
way that reads like a permissions problem.

| | **Instagram API with Instagram Login** ← this project | Instagram API with Facebook Login |
|---|---|---|
| Facebook Page | **not needed** | required, linked to the IG account |
| Host | `graph.instagram.com` | `graph.facebook.com` |
| Token | Instagram User access token | Facebook Page access token |
| Permissions | `instagram_business_basic`, `instagram_business_content_publish` | `instagram_basic`, `instagram_content_publish`, `pages_read_engagement` |
| Self-refreshing | **yes**, `ig_refresh_token` | no equivalent |

We use Instagram Login for two reasons: it needs no Facebook Page, and its token
refreshes itself — which is the only reason a job nobody watches can keep
working past 60 days. `INSTAGRAM_API_HOST` exists for anyone who has to use the
other one, but the token and permissions differ too, so it is not only a host.

## What is left: connecting the account

This needs the Instagram account holder and a browser. It is done once.
Meta's own walkthrough is
[Create a Meta app for the Instagram API](https://developers.facebook.com/docs/instagram-platform/create-an-instagram-app).

1. **Make the Instagram account a Business or Creator account.** Personal
   accounts cannot publish through the API at all. It must also be **public** —
   a private account cannot be added as a tester in step 4.
2. **Create an app** at developers.facebook.com. When it asks for a use case,
   choose **Other**, then app type **Business**. This is counter-intuitive:
   there is a tile called *"Manage messaging & content on Instagram"* whose
   description matches this project exactly, but Meta's documented route to the
   product we need is Other → Business.
3. **Add the *Instagram* product** from the dashboard and click *Set up*. There
   is no longer a product called "Instagram Graph API" — it is just
   **Instagram**, and it covers both APIs above. *API setup with Instagram
   login* is added automatically, which is the one we want.
4. **Make the Instagram account an *Instagram Tester* of the app, and accept.**
   While an app is in development, Meta only lets accounts with a role on it
   connect, and being the app's administrator is not enough — the Instagram
   account needs its own role. Skipping this is what produces
   **"Insufficient Developer Role"** at the Instagram login step.
   - App Dashboard → **App roles → Roles → Add People → Instagram Tester**, and
     enter the Instagram username.
   - Accept it from the Instagram side, logged in as that account:
     **instagram.com/accounts/manage_access → Tester Invites → Accept**.
   - If *App roles* has no *Add People*, the app is attached to a business
     portfolio, and roles are managed in Meta Business Suite instead.

   This role is what grants **Standard Access**, and Standard Access is enough
   to publish to an account you own — so **no App Review is needed**. The
   dashboard does show a "Complete App Review" step; that is for Advanced
   Access, i.e. posting on behalf of accounts you do not own.
5. **Generate a long-lived token** with `instagram_business_basic` and
   `instagram_business_content_publish`. The dashboard can generate one
   directly; the full OAuth flow in
   [Business Login for Instagram](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login)
   is only needed for other people's accounts.
6. **Add the repository secrets**: `INSTAGRAM_ACCESS_TOKEN` and
   `INSTAGRAM_TOKEN_ISSUED_AT` set to today's date. `INSTAGRAM_ACCOUNT_ID` is
   not needed — the job posts as the token's own owner.
7. **Run the workflow by hand** — Actions → *instagram* → *Run workflow*, with
   *dry run* left ticked. Nothing is posted. In the last step, *Token and recent
   decisions*, look for:

   ```
   account:   @your_username (BUSINESS), id 1784...
   ```

   That line comes from Meta itself, so it proves the token is valid, belongs
   to the right account, and that the account can publish. `TOKEN REJECTED`
   there means the token is wrong or expired; the step fails and says why.
8. Nothing else. The next noon run publishes.

After that, nothing further is needed. The token renews itself.

### Limits worth knowing

- 100 published posts per rolling 24 hours. This job uses one.
- JPEG only, sRGB, 320–1440px wide, aspect ratio between 4:5 and 1.91:1, under
  8MB. The card is 1080×1350 and about 80KB; `_check_media()` asserts all of it
  before anything is sent.
- No native scheduling through the API. "Scheduled" means the job runs at noon.
- Captions: 2200 characters, 30 hashtags. Posts here use seven.
- A container must be published within 24 hours or it expires. This job
  publishes within seconds.
- Meta has an `is_ai_generated` flag for self-disclosing AI-generated **media**.
  We do not set it: the card is a deterministic drawing, not generated imagery.
  The caption is model-written, which that flag is not about. If a future post
  ever carries a generated image, it must be set.
