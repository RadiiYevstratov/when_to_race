"""The day's run, including every way it can go wrong.

Selection has its own tests. This file is about the rest of the job: that a
chosen candidate becomes a card and a caption that agree with the database, that
nothing is ever published twice, and that each failure - no schedule, no image,
no Instagram - ends as a recorded outcome rather than an exception on a runner
nobody is watching.

The database is not involved. Every function the pipeline imports from the
repository is replaced, which keeps these tests fast, deterministic, and honest
about what they cover: this is the pipeline's logic, not Postgres.
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from social import brief as brief_module
from social import captions, policy
from social.selection import EventFact, PostRecord, SessionFact

try:
    from social import pipeline
    HAS_PILLOW = True
except ImportError:  # pragma: no cover - the card needs Pillow
    HAS_PILLOW = False

BRATISLAVA = ZoneInfo("Europe/Bratislava")


def setUpModule():
    """Quiet the job's own logging.

    Half these tests provoke an exception on purpose, and the pipeline logs each
    one with a traceback. That is right in production and unreadable here: a
    passing run should not print five stack traces.
    """
    import logging

    logging.disable(logging.CRITICAL)


def tearDownModule():
    import logging

    logging.disable(logging.NOTSET)


def utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def noon(year, month, day):
    """Decisions are taken at noon where the audience is, never on server time."""
    return datetime(year, month, day, policy.POSTING_HOUR, tzinfo=BRATISLAVA)


def session(sid, kind, name, when, category="f1", short="F1", headline=True):
    return SessionFact(
        session_id=sid,
        session_type=kind,
        display_name=name,
        starts_at_utc=when,
        category_code=category,
        category_short_name=short,
        is_headline_class=headline,
    )


def event(
    eid=1,
    series="f1",
    short="Formula 1",
    name="Italian Grand Prix",
    sessions=(),
    venue="Autodromo Nazionale Monza",
    city="Monza",
    country="IT",
    zone="Europe/Rome",
):
    return EventFact(
        event_id=eid,
        series_code=series,
        series_short_name=short,
        season=2026,
        slug="italian-grand-prix",
        name=name,
        venue_name=venue,
        venue_city=city,
        venue_country=country,
        venue_timezone=zone,
        starts_at_utc=min((s.starts_at_utc for s in sessions), default=utc(2026, 9, 25, 10)),
        ends_at_utc=max((s.starts_at_utc for s in sessions), default=utc(2026, 9, 27, 15)),
        sessions=tuple(sessions),
    )


def f1_weekend():
    """A conventional Friday-to-Sunday Grand Prix at Monza."""
    return event(sessions=[
        session(1, "practice", "Free Practice 1", utc(2026, 9, 25, 11)),
        session(2, "practice", "Free Practice 2", utc(2026, 9, 25, 15)),
        session(3, "qualifying", "Qualifying", utc(2026, 9, 26, 14)),
        session(4, "race", "Race", utc(2026, 9, 27, 13)),
    ])


def motogp_weekend(eid=2):
    return event(
        eid=eid,
        series="motogp",
        short="MotoGP",
        name="Gran Premio de Aragón",
        venue="MotorLand Aragón",
        city="Alcañiz",
        country="ES",
        zone="Europe/Madrid",
        sessions=[
            session(10, "practice", "Free Practice", utc(2026, 9, 25, 8),
                    category="motogp", short="MotoGP"),
            session(11, "qualifying", "Qualifying 2", utc(2026, 9, 26, 8, 50),
                    category="motogp", short="MotoGP"),
            session(12, "race", "Race", utc(2026, 9, 27, 12),
                    category="motogp", short="MotoGP"),
            session(13, "race", "Race", utc(2026, 9, 27, 10, 15),
                    category="moto3", short="Moto3", headline=False),
        ],
    )


class FakeRepository:
    """Stands in for every repository call the pipeline makes.

    A counter rather than a mock per function: the assertions that matter are
    about how many times something happened - one insert, one publish - and a
    small object states that more plainly than six patch decorators.
    """

    def __init__(self, events=(), history=(), published_days=()):
        self.events = list(events)
        self.history = list(history)
        self.published_days = set(published_days)
        self.rows = []
        self.media = {}
        self.updates = []

    # --- reads ---------------------------------------------------------
    def load_events(self, connection, window_from, window_to):
        return self.events

    def load_history(self, connection, since):
        return self.history

    def venue_slugs(self, connection, event_ids):
        return {eid: "monza" for eid in event_ids}

    def already_published(self, connection, day):
        return day in self.published_days

    def accent_colour(self, connection, series_code, category_code=None):
        return (232, 17, 45)

    # --- writes --------------------------------------------------------
    def record(self, connection, **fields):
        self.rows.append(fields)
        return len(self.rows)

    def store_media(self, connection, record_id, data, media_type="image/jpeg",
                    media_url=None):
        self.media[record_id] = data
        self.rows[record_id - 1]["media_url"] = media_url

    def update(self, connection, record_id, published=False, **fields):
        self.updates.append((record_id, dict(fields, published=published)))
        for key, value in fields.items():
            self.rows[record_id - 1][{"error": "error_message"}.get(key, key)] = value

    def install(self, stack):
        for name in ("load_events", "load_history", "venue_slugs", "accent_colour",
                     "already_published", "record", "store_media"):
            stack.enter_context(
                mock.patch.object(pipeline, name, getattr(self, name))
            )
        stack.enter_context(mock.patch.object(pipeline, "_update", self.update))

    @property
    def outcomes(self):
        return [row["outcome"] for row in self.rows]


@unittest.skipUnless(HAS_PILLOW, "the card needs Pillow (pip install -r social/requirements.txt)")
class PipelineTests(unittest.TestCase):
    """The happy paths, one per kind of weekend the calendar actually has."""

    def run_day(self, repo, when, publish=False, post_id="17841_1", publish_error=None,
                **kwargs):
        """One run, with Instagram replaced by something that cannot post."""
        from contextlib import ExitStack

        with ExitStack() as stack:
            repo.install(stack)
            if publish_error is not None:
                publisher = mock.Mock(side_effect=publish_error)
            else:
                publisher = mock.Mock(return_value=post_id)
            stack.enter_context(mock.patch.object(pipeline.instagram, "publish", publisher))
            # Credentials are resolved by the pipeline so that a token refresh
            # happens once per run; with none in the environment every publish
            # would otherwise degrade to a dry run.
            stack.enter_context(
                mock.patch.object(
                    pipeline.instagram,
                    "current",
                    return_value=pipeline.instagram.Credentials("token", "17841", None),
                )
            )
            result = pipeline.run(
                object(), when, dry_run=not publish, site_url="https://example.test", **kwargs
            )
        self.published = publisher
        return result

    # ---- 1. a Formula 1 weekend ---------------------------------------
    def test_f1_race_day(self):
        repo = FakeRepository(events=[f1_weekend()])
        result = self.run_day(repo, noon(2026, 9, 27))

        self.assertEqual(result.outcome, "dry_run")
        self.assertEqual(result.brief.series, "Formula 1")
        self.assertEqual(result.brief.event_name, "Italian Grand Prix")
        self.assertEqual(result.brief.headline.session_type, "race")
        self.assertIn("Italian Grand Prix", result.caption)
        self.assertIn("#F1", result.caption)
        # The card is a real JPEG of the size Instagram takes.
        self.assertTrue(result.media_bytes.startswith(b"\xff\xd8"))
        pipeline._check_media(result.media_bytes)
        self.assertEqual(repo.outcomes, ["dry_run"])

    # ---- 2. a MotoGP weekend ------------------------------------------
    def test_motogp_race_day(self):
        repo = FakeRepository(events=[motogp_weekend()])
        result = self.run_day(repo, noon(2026, 9, 27))

        self.assertEqual(result.outcome, "dry_run")
        self.assertEqual(result.brief.series_code, "motogp")
        # The premier class leads, not the Moto3 race that runs earlier.
        self.assertEqual(result.brief.headline.category, "MotoGP")
        self.assertIn("MotoGP", result.caption)

    # ---- 3. two majors on the same weekend ----------------------------
    def test_one_post_when_two_championships_race(self):
        repo = FakeRepository(events=[f1_weekend(), motogp_weekend()])
        result = self.run_day(repo, noon(2026, 9, 27))

        self.assertEqual(result.outcome, "dry_run")
        self.assertEqual(len(repo.rows), 1, "one decision, one row")
        # Whichever wins, exactly one event is the subject and the other is not
        # silently merged into it.
        self.assertIn(result.brief.series_code, {"f1", "motogp"})
        self.assertEqual(result.decision.chosen.events[0].name, result.brief.event_name)

    # ---- 4. nothing worth saying --------------------------------------
    def test_quiet_day_is_recorded_not_forced(self):
        """A week with one practice session in it should produce silence.

        The failure this guards is an account that posts something every day
        because the job ran, rather than because there was anything on.
        """
        thin = event(sessions=[session(1, "practice", "Free Practice 1", utc(2026, 10, 9, 11))])
        repo = FakeRepository(events=[thin])
        result = self.run_day(repo, noon(2026, 10, 2))

        self.assertEqual(result.outcome, "skipped")
        self.assertIsNone(result.media_bytes)
        self.assertEqual(repo.outcomes, ["skipped"])
        self.assertTrue(repo.rows[0]["error_message"], "the reason is written down")

    # ---- 5. today has already gone out --------------------------------
    def test_a_published_day_is_left_alone(self):
        repo = FakeRepository(events=[f1_weekend()], published_days={noon(2026, 9, 27).date()})
        result = self.run_day(repo, noon(2026, 9, 27), publish=True)

        self.assertEqual(result.outcome, "skipped")
        self.published.assert_not_called()
        self.assertEqual(repo.rows, [], "no second row for a day already covered")

    # ---- 6. the schedule is unreadable --------------------------------
    def test_a_database_failure_is_recorded(self):
        repo = FakeRepository(events=[f1_weekend()])
        repo.load_events = mock.Mock(side_effect=RuntimeError("connection reset"))
        result = self.run_day(repo, noon(2026, 9, 27))

        self.assertEqual(result.outcome, "failed")
        self.assertIn("connection reset", result.error)
        self.assertEqual(repo.outcomes, ["failed"])

    # ---- 7. the card cannot be drawn ----------------------------------
    def test_a_media_failure_stops_before_publishing(self):
        repo = FakeRepository(events=[f1_weekend()])
        from contextlib import ExitStack

        with ExitStack() as stack:
            repo.install(stack)
            stack.enter_context(
                mock.patch.object(pipeline, "render", side_effect=OSError("no font"))
            )
            publisher = mock.Mock()
            stack.enter_context(mock.patch.object(pipeline.instagram, "publish", publisher))
            result = pipeline.run(object(), noon(2026, 9, 27), dry_run=False)
            # Publishing is never reached, so the token is never even resolved.

        self.assertEqual(result.outcome, "failed")
        self.assertIn("media failed", result.error)
        publisher.assert_not_called()
        self.assertEqual(repo.outcomes, ["failed"])

    # ---- 8. Instagram refuses -----------------------------------------
    def test_an_api_failure_keeps_the_row_and_the_card(self):
        """A failed publish must leave enough behind to see what was attempted."""
        repo = FakeRepository(events=[f1_weekend()])
        result = self.run_day(
            repo,
            noon(2026, 9, 27),
            publish=True,
            publish_error=pipeline.instagram.InstagramError("OAuthException: token expired"),
        )

        self.assertEqual(result.outcome, "failed")
        self.assertIn("token expired", result.error)
        self.assertEqual(repo.outcomes, ["failed"])
        self.assertTrue(repo.media, "the card is kept, so the post can be retried by hand")
        self.assertIsNotNone(repo.rows[0]["caption"])

    def test_missing_credentials_degrade_to_a_dry_run(self):
        """No token is not a failure. It is the state the project ships in."""
        repo = FakeRepository(events=[f1_weekend()])
        result = self.run_day(
            repo,
            noon(2026, 9, 27),
            publish=True,
            publish_error=pipeline.instagram.NotConfigured("INSTAGRAM_ACCESS_TOKEN not set"),
        )

        self.assertEqual(result.outcome, "dry_run")
        self.assertEqual(repo.outcomes, ["dry_run"])

    # ---- 9. the job runs twice ----------------------------------------
    def test_running_twice_publishes_once(self):
        repo = FakeRepository(events=[f1_weekend()])
        first = self.run_day(repo, noon(2026, 9, 27), publish=True)
        self.assertEqual(first.outcome, "published")
        self.assertEqual(self.published.call_count, 1)

        # What the first run wrote is what the second run sees.
        repo.published_days.add(noon(2026, 9, 27).date())
        second = self.run_day(repo, noon(2026, 9, 27), publish=True)

        self.assertEqual(second.outcome, "skipped")
        self.assertEqual(self.published.call_count, 0, "the second run never reaches the API")
        self.assertEqual(len(repo.rows), 1)

    def test_force_overrides_the_guard(self):
        """The manual escape hatch, for a post that failed halfway and was fixed."""
        repo = FakeRepository(events=[f1_weekend()], published_days={noon(2026, 9, 27).date()})
        result = self.run_day(repo, noon(2026, 9, 27), publish=True, force=True)
        self.assertEqual(result.outcome, "published")

    # ---- 10. the date boundary ----------------------------------------
    def test_a_late_american_race_keeps_its_two_calendars_apart(self):
        """20:00 Thursday at Bristol is 02:00 Friday in Bratislava.

        The first version of the brief carried one weekday and one clock per
        frame and paired them freely, so a card read "Friday, 20:00 at the
        circuit" for a session that ran on Thursday evening there. Everything a
        reader sees is now in their frame, and the circuit's clock names its own
        day whenever the two disagree.
        """
        bristol = event(
            eid=3,
            series="nascar",
            short="NASCAR",
            name="Bass Pro Shops Night Race",
            venue="Bristol Motor Speedway",
            city="Bristol",
            country="US",
            zone="America/New_York",
            sessions=[session(20, "race", "Race", utc(2026, 9, 18, 0),
                              category="cup", short="Cup")],
        )
        repo = FakeRepository(events=[bristol])
        result = self.run_day(repo, noon(2026, 9, 17))

        head = result.brief.headline
        self.assertEqual(head.circuit_time, "20:00")
        self.assertEqual(head.circuit_weekday, "Thursday")
        self.assertEqual(head.viewer_time, "02:00")
        self.assertEqual(head.viewer_weekday, "Friday")
        self.assertTrue(head.crosses_midnight)
        # The circuit's clock carries its own day, so nothing can pair 20:00
        # with Friday.
        self.assertEqual(head.circuit_stamp, "20:00 Thursday")

        card = pipeline._card_for(result.brief)
        rows = dict(card.fields)
        self.assertEqual(card.kicker, "Tomorrow")
        self.assertEqual(rows["date"], "Friday 18 September")
        self.assertEqual(rows["start"], "02:00 CEST")
        # The circuit's clock gets its own labelled row, carrying its own day.
        self.assertEqual(rows["at Bristol"], "20:00 Thursday")

    def test_a_european_race_says_the_time_once(self):
        """The common case must not be cluttered by the fix for the rare one."""
        repo = FakeRepository(events=[f1_weekend()])
        result = self.run_day(repo, noon(2026, 9, 27))
        head = result.brief.headline
        self.assertFalse(head.crosses_midnight)
        self.assertEqual(head.circuit_stamp, head.circuit_time)

        labels = [label for label, _ in pipeline._card_for(result.brief).fields]
        self.assertEqual(labels, ["date", "start", "where"])
        self.assertNotIn("at Monza", labels, "Monza time and reader time are the same time")

    # ---- what ends up in the row --------------------------------------
    def test_the_row_describes_the_post(self):
        repo = FakeRepository(events=[f1_weekend()])
        self.run_day(repo, noon(2026, 9, 27), publish=True)
        row = repo.rows[0]

        self.assertEqual(row["outcome"], "published")
        self.assertEqual(row["series_code"], "f1")
        self.assertEqual(row["event_name"], "Italian Grand Prix")
        self.assertEqual(row["session_type"], "race")
        self.assertEqual(row["instagram_post_id"], "17841_1")
        self.assertTrue(row["reasons"], "the scoring is kept, so a bad choice can be read back")

    def test_only_a_real_publish_is_stamped_as_published(self):
        """`published_at` on a row that never went out is a lie in the log."""
        repo = FakeRepository(events=[f1_weekend()])
        self.run_day(
            repo,
            noon(2026, 9, 27),
            publish=True,
            publish_error=pipeline.instagram.InstagramError("nope"),
        )
        self.assertFalse(repo.updates[-1][1]["published"])

        clean = FakeRepository(events=[f1_weekend()])
        self.run_day(clean, noon(2026, 9, 27), publish=True)
        self.assertTrue(clean.updates[-1][1]["published"])

    def test_the_class_colour_is_the_one_the_site_uses(self):
        """An F2 session is blue on the board; the card must not paint it red."""
        repo = FakeRepository(events=[f1_weekend()])
        repo.accent_colour = mock.Mock(return_value=(0, 150, 214))
        result = self.run_day(repo, noon(2026, 9, 27))

        self.assertEqual(result.brief.accent, (0, 150, 214))
        # Resolved for the chosen session's class, not for the championship.
        self.assertEqual(repo.accent_colour.call_args.args[1:], ("f1", "f1"))

    def test_the_card_is_published_from_its_own_row(self):
        """The image URL has to point at the record that holds the bytes."""
        repo = FakeRepository(events=[f1_weekend()])
        result = self.run_day(repo, noon(2026, 9, 27), publish=True)
        self.assertEqual(result.media_url, "https://example.test/api/social/card/1.jpg")
        self.assertEqual(self.published.call_args.args[0], result.media_url)
        self.assertIn(1, repo.media)


@unittest.skipUnless(HAS_PILLOW, "the CLI imports the renderer")
class PostingWindowTests(unittest.TestCase):
    """When a scheduled firing is allowed to act, and how often.

    The first version let through only the noon hour, on the assumption that
    GitHub runs cron on time. This repository's scheduled jobs start one to
    three hours late, so that gate would have turned away every firing and the
    account would never have posted. Found by the setup check on the first day.
    """

    def check(self, utc_hour, month, day, minute=0):
        from social.run import within_posting_window

        when = datetime(2026, month, day, utc_hour, minute, tzinfo=timezone.utc)
        return within_posting_window(when, "Europe/Bratislava")

    def test_a_firing_two_hours_late_still_posts(self):
        """The case that actually happens: 10:00 UTC scheduled, 11:58 started."""
        self.assertTrue(self.check(11, 9, 21, minute=58))   # 13:58 CEST

    def test_nothing_goes_out_before_noon(self):
        self.assertFalse(self.check(9, 7, 1, minute=59))    # 11:59 CEST
        self.assertFalse(self.check(10, 1, 15))             # 11:00 CET

    def test_nor_too_late_in_the_day(self):
        """A "today" post at eight in the evening is not worth making."""
        self.assertTrue(self.check(15, 7, 1, minute=59))    # 17:59 CEST
        self.assertFalse(self.check(16, 7, 1))              # 18:00 CEST

    def test_both_seasons_get_a_firing_inside_the_window(self):
        """Daylight saving needs no special case, only enough firings."""
        for month, day in ((7, 1), (1, 15), (10, 25)):
            allowed = [h for h in (10, 11, 12, 13) if self.check(h, month, day)]
            self.assertGreaterEqual(len(allowed), 3, (month, day))


@unittest.skipUnless(HAS_PILLOW, "the CLI imports the renderer")
class OncePerDayTests(unittest.TestCase):
    """Four firings a day must still mean one decision a day."""

    def run_cli(self, settled=None, now="2026-09-21T13:58:00+02:00", force=False):
        import io
        from contextlib import ExitStack, redirect_stdout

        from social import run

        pipeline_run = mock.Mock()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(run, "connect", mock.MagicMock()))
            stack.enter_context(mock.patch.object(run, "decided_today", return_value=settled))
            stack.enter_context(mock.patch.object(run, "run_pipeline", pipeline_run))
            stack.enter_context(mock.patch.object(run, "show_run"))
            stack.enter_context(mock.patch("logging.basicConfig"))
            argv = ["--check-hour", "--publish", "--now", now] + (["--force"] if force else [])
            with redirect_stdout(io.StringIO()) as out:
                code = run.main(argv)
        return code, pipeline_run, out.getvalue()

    def test_the_first_firing_in_the_window_decides(self):
        _, pipeline_run, _ = self.run_cli(settled=None)
        pipeline_run.assert_called_once()

    def test_a_later_firing_leaves_a_published_day_alone(self):
        code, pipeline_run, out = self.run_cli(settled="published")
        self.assertEqual(code, 0)
        pipeline_run.assert_not_called()
        self.assertIn("already settled", out)

    def test_a_decision_to_stay_quiet_is_respected_too(self):
        """Otherwise every later firing would re-ask and might change its mind."""
        _, pipeline_run, _ = self.run_cli(settled="skipped")
        pipeline_run.assert_not_called()

    def test_a_firing_outside_the_window_does_nothing(self):
        _, pipeline_run, out = self.run_cli(now="2026-09-21T11:30:00+02:00")
        pipeline_run.assert_not_called()
        self.assertIn("outside the posting window", out)


@unittest.skipUnless(HAS_PILLOW, "the CLI imports the renderer")
class StatusTests(unittest.TestCase):
    """--status is the alert: its exit code is what makes GitHub send an email."""

    def status(self, creds=None, not_configured=False, whoami=None, whoami_error=None):
        import io
        from contextlib import ExitStack, redirect_stdout

        from social import run

        with ExitStack() as stack:
            if not_configured:
                current = mock.Mock(side_effect=pipeline.instagram.NotConfigured("no token"))
            else:
                current = mock.Mock(return_value=creds)
            stack.enter_context(mock.patch.object(run.instagram, "current", current))
            stack.enter_context(mock.patch.object(
                run.instagram, "whoami",
                mock.Mock(side_effect=whoami_error, return_value=whoami),
            ))
            stack.enter_context(mock.patch.object(run, "recent", return_value=[]))
            out = io.StringIO()
            with redirect_stdout(out):
                healthy = run.show_status(object())
        return healthy, out.getvalue()

    def fresh(self):
        return pipeline.instagram.Credentials(
            "t", "me", datetime.now(timezone.utc) - timedelta(days=2)
        )

    def test_not_yet_configured_is_not_an_alert(self):
        """Before setup, a red run every day would teach everyone to ignore it."""
        healthy, out = self.status(not_configured=True)
        self.assertTrue(healthy)
        self.assertIn("not configured", out)

    def test_a_working_token_names_the_account(self):
        healthy, out = self.status(
            creds=self.fresh(),
            whoami={"user_id": "178", "username": "ontrackapp", "account_type": "BUSINESS"},
        )
        self.assertTrue(healthy)
        self.assertIn("@ontrackapp", out)

    def test_a_rejected_token_fails_the_run(self):
        healthy, out = self.status(
            creds=self.fresh(),
            whoami_error=pipeline.instagram.InstagramError("OAuthException: expired"),
        )
        self.assertFalse(healthy)
        self.assertIn("TOKEN REJECTED", out)

    def test_a_token_near_expiry_fails_the_run(self):
        """At 45 days, refreshes have been failing for two weeks. Someone must know."""
        old = pipeline.instagram.Credentials(
            "t", "me", datetime.now(timezone.utc) - timedelta(days=50)
        )
        healthy, _ = self.status(
            creds=old,
            whoami={"user_id": "178", "username": "ontrackapp", "account_type": "BUSINESS"},
        )
        self.assertFalse(healthy)

    def test_a_personal_account_is_called_out(self):
        _, out = self.status(
            creds=self.fresh(),
            whoami={"user_id": "178", "username": "someone", "account_type": "PERSONAL"},
        )
        self.assertIn("only Business and Creator accounts can publish", out)


class CaptionValidationTests(unittest.TestCase):
    """The check that makes a language model safe to have in this loop."""

    def brief_for(self, **overrides):
        line = brief_module.SessionLine(
            category="F1",
            name="Race",
            session_type="race",
            circuit_time="15:00",
            circuit_weekday="Sunday",
            circuit_date_label="27 September",
            viewer_time="15:00",
            viewer_weekday="Sunday",
            viewer_date_label="27 September",
            viewer_zone_label="CEST",
            is_headline=True,
        )
        fields = dict(
            kind="today",
            series="Formula 1",
            series_code="f1",
            event_name="Italian Grand Prix",
            season=2026,
            circuit="Autodromo Nazionale Monza",
            city="Monza",
            country="IT",
            circuit_timezone="Europe/Rome",
            viewer_timezone="Europe/Bratislava",
            headline=line,
        )
        fields.update(overrides)
        return brief_module.Brief(**fields)

    def test_a_time_nobody_gave_is_rejected(self):
        with self.assertRaises(captions.ValidationError):
            captions.validate("Italian Grand Prix. Lights out at 14:00.", self.brief_for())

    def test_a_weekday_nobody_gave_is_rejected(self):
        with self.assertRaises(captions.ValidationError):
            captions.validate("Italian Grand Prix, racing on Saturday.", self.brief_for())

    def test_the_circuits_own_weekday_is_allowed(self):
        """Both frames are legitimate; only a third invented one is not."""
        brief = self.brief_for(
            headline=brief_module.SessionLine(
                category="Cup", name="Race", session_type="race",
                circuit_time="20:00", circuit_weekday="Thursday",
                circuit_date_label="17 September",
                viewer_time="02:00", viewer_weekday="Friday",
                viewer_date_label="18 September", viewer_zone_label="CEST",
                is_headline=True,
            ),
            event_name="Bass Pro Shops Night Race",
            series="NASCAR",
            series_code="nascar",
        )
        captions.validate(
            "Bass Pro Shops Night Race. Green flag 20:00 Thursday at the circuit, "
            "02:00 Friday in central Europe.",
            brief,
        )

    def test_a_result_is_rejected(self):
        with self.assertRaises(captions.ValidationError):
            captions.validate(
                "Italian Grand Prix today. Verstappen won here last time.", self.brief_for()
            )

    def test_the_wrong_season_is_rejected(self):
        with self.assertRaises(captions.ValidationError):
            captions.validate("Italian Grand Prix, the 2025 running.", self.brief_for())

    def test_a_caption_about_nothing_is_rejected(self):
        with self.assertRaises(captions.ValidationError):
            captions.validate("Big weekend ahead. Tune in.", self.brief_for())

    def test_the_composed_caption_passes_its_own_check(self):
        """The fallback is validated too, so a template bug cannot slip through."""
        for kind in ("today", "tomorrow", "weekend_preview"):
            brief = self.brief_for(kind=kind)
            body = captions.compose(brief)
            captions.validate(f"{body}\n\n{captions.CALL_TO_ACTION}", brief)

    def test_an_over_long_caption_is_rejected(self):
        with self.assertRaises(captions.ValidationError):
            captions.validate("Italian Grand Prix. " + "x" * 2300, self.brief_for())


if __name__ == "__main__":
    unittest.main()


class WeekAheadValidationTests(unittest.TestCase):
    """The week-ahead post names days, and the validator has to know them.

    Found on the first real run: the model expanded "Thu" in the fact sheet to
    "Thursday" - true - and the validator, which only knew the weekdays of
    session lines, rejected the caption. A correct caption was thrown away for
    a plainer one.
    """

    def week_ahead(self):
        from social.selection import Candidate

        events = [
            event(eid=1, name="Azerbaijan Grand Prix",
                  sessions=[session(1, "race", "Race", utc(2026, 9, 24, 11))]),
            event(eid=2, series="wec", short="WEC", name="6 Hours of Fuji",
                  zone="Asia/Tokyo",
                  sessions=[session(2, "race", "Race", utc(2026, 9, 25, 2),
                                    category="wec", short="WEC")]),
        ]
        candidate = Candidate("week_ahead", tuple(events), None, 0)
        return brief_module.build(candidate, noon(2026, 9, 21))

    def test_the_days_in_the_list_are_allowed(self):
        brief = self.week_ahead()
        self.assertIn("Thursday", brief.allowed_weekdays)
        self.assertIn("Friday", brief.allowed_weekdays)
        captions.validate(
            "A busy week: Formula 1 is in Baku on Thursday, and the WEC runs "
            "the 6 Hours of Fuji on Friday.",
            brief,
        )

    def test_a_day_not_in_the_list_is_still_refused(self):
        with self.assertRaises(captions.ValidationError):
            captions.validate("Formula 1 races on Sunday in Baku.", self.week_ahead())


@unittest.skipUnless(HAS_PILLOW, "the card needs Pillow")
class WeekAheadCardTests(unittest.TestCase):
    """A post about four championships is not a post about the first of them.

    The first real week-ahead card was headed "FORMULA 1" in F1 red and tagged
    #F1 #Formula1, because the brief names a leading series for scoring and the
    card and hashtags borrowed it.
    """

    def brief(self):
        from social.selection import Candidate

        events = [
            event(eid=1, name="Azerbaijan Grand Prix",
                  sessions=[session(1, "race", "Race", utc(2026, 9, 24, 11))]),
            event(eid=2, series="wec", short="WEC", name="6 Hours of Fuji",
                  sessions=[session(2, "race", "Race", utc(2026, 9, 25, 2),
                                    category="wec", short="WEC")]),
            event(eid=3, series="nascar", short="NASCAR", name="Hollywood Casino 400",
                  sessions=[session(3, "race", "Race", utc(2026, 9, 25, 19),
                                    category="cup", short="Cup")]),
        ]
        return brief_module.build(Candidate("week_ahead", tuple(events), None, 0),
                                  noon(2026, 9, 21))

    def test_the_card_belongs_to_no_single_championship(self):
        card = pipeline._card_for(self.brief())
        self.assertEqual(card.series, "Motorsport")
        self.assertEqual(card.accent, pipeline.WEEK_AHEAD_ACCENT)
        self.assertIsNone(card.lines_label)

    def test_every_championship_gets_one_tag(self):
        tags = brief_module.hashtags(self.brief())
        self.assertEqual(tags[:3], ["#F1", "#WEC", "#NASCAR"])
        self.assertNotIn("#Formula1", tags)


class HashtagSpellingTests(unittest.TestCase):
    """Championships spell their own names; the tags must not respell them."""

    def test_the_official_spellings_survive(self):
        for code, expected in (("nascar", "#NASCAR"), ("wec", "#WEC"),
                               ("motogp", "#MotoGP"), ("wsbk", "#WorldSBK")):
            brief = brief_module.Brief(
                kind="today", series="x", series_code=code, event_name="Round",
                season=2026, circuit=None, city=None, country=None,
                circuit_timezone=None, viewer_timezone="Europe/Bratislava",
                headline=None,
            )
            self.assertIn(expected, brief_module.hashtags(brief))

    def test_multi_word_names_are_joined_without_losing_capitals(self):
        brief = brief_module.Brief(
            kind="today", series="Formula 1", series_code="f1",
            event_name="Azerbaijan Grand Prix", season=2026,
            circuit="Baku City Circuit", city="Bristol, TN", country="AZ",
            circuit_timezone=None, viewer_timezone="Europe/Bratislava", headline=None,
        )
        tags = brief_module.hashtags(brief)
        self.assertIn("#AzerbaijanGP", tags)
        self.assertIn("#BristolTN", tags)
        self.assertIn("#BakuCityCircuit", tags)
