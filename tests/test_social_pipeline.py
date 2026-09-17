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
    """Which of the two daily cron firings is allowed to act.

    GitHub's cron is UTC and knows nothing about daylight saving, so the
    workflow fires at 10:00 and 11:00 UTC every day and the job decides. Getting
    this wrong is either two posts a day or none, and it only shows up twice a
    year, on the Sunday the clocks change.
    """

    def check(self, utc_hour, month, day):
        from social.run import within_posting_window

        when = datetime(2026, month, day, utc_hour, tzinfo=timezone.utc)
        return within_posting_window(when, "Europe/Bratislava")

    def test_summer_time_lets_the_ten_oclock_firing_through(self):
        self.assertTrue(self.check(10, 7, 1))     # 12:00 CEST
        self.assertFalse(self.check(11, 7, 1))    # 13:00 CEST

    def test_winter_time_lets_the_eleven_oclock_firing_through(self):
        self.assertFalse(self.check(10, 1, 15))   # 11:00 CET
        self.assertTrue(self.check(11, 1, 15))    # 12:00 CET

    def test_the_switchover_weekend_still_posts_exactly_once(self):
        """The last Sunday of October, when the clocks go back at 03:00."""
        allowed = [h for h in (10, 11) if self.check(h, 10, 25)]
        self.assertEqual(len(allowed), 1, "one firing acts, whichever it is")

    def test_a_late_runner_is_still_inside_the_hour(self):
        """GitHub routinely starts a scheduled job a quarter of an hour late."""
        from social.run import within_posting_window

        late = datetime(2026, 7, 1, 10, 47, tzinfo=timezone.utc)   # 12:47 CEST
        self.assertTrue(within_posting_window(late, "Europe/Bratislava"))


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
