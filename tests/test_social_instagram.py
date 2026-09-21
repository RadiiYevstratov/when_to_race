"""The Instagram edge: publishing, and the token that has to outlive everyone.

The publishing call is two requests and a poll, and each of the three has a way
of failing that says nothing useful unless it is translated. The token is worse:
it expires after sixty days, refreshing it produces a *different* string, and a
token allowed to lapse cannot be recovered by any amount of retrying - it needs
a person and a browser. So the refresh path is tested more carefully than the
publishing one, because the publishing one fails loudly and this one does not.
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from social import instagram

try:
    import httpx  # noqa: F401 - only probed
    HAS_HTTPX = True
except ImportError:  # the stdlib-only CI job installs nothing
    HAS_HTTPX = False


def setUpModule():
    import logging

    logging.disable(logging.CRITICAL)


def tearDownModule():
    import logging

    logging.disable(logging.NOTSET)


def ago(days):
    return datetime.now(timezone.utc) - timedelta(days=days)


# What the environment holds: the bootstrap token, with no issue date, which is
# how it looks unless someone has deliberately set INSTAGRAM_TOKEN_ISSUED_AT.
CREDS = instagram.Credentials("seed-token", "17841400000000000")


class FakeStore:
    """The two repository functions the token path uses."""

    def __init__(self, stored=None, readable=True):
        self.stored = stored
        self.readable = readable
        self.writes = []

    def load_credential(self, connection, name):
        if not self.readable:
            raise RuntimeError("relation social_credentials does not exist")
        return self.stored

    def store_credential(self, connection, name, value, issued_at=None):
        self.writes.append((value, issued_at))
        self.stored = (value, issued_at or datetime.now(timezone.utc))

    def install(self, stack):
        # Patched on the repository module itself, not swapped into sys.modules:
        # `from .repository import ...` resolves through the package attribute,
        # so a replacement module in sys.modules is quietly ignored.
        from social import repository

        stack.enter_context(
            mock.patch.object(repository, "load_credential", self.load_credential)
        )
        stack.enter_context(
            mock.patch.object(repository, "store_credential", self.store_credential)
        )


class EnvironmentTests(unittest.TestCase):
    def test_a_missing_token_is_named(self):
        with mock.patch.dict("os.environ", {"INSTAGRAM_ACCESS_TOKEN": "",
                                            "INSTAGRAM_ACCOUNT_ID": ""}, clear=False):
            with self.assertRaises(instagram.NotConfigured) as caught:
                instagram.credentials_from_env()
        message = str(caught.exception)
        self.assertIn("INSTAGRAM_ACCESS_TOKEN", message)
        # The permission names are in the message because they are the thing
        # people get wrong: Meta renamed them for the Instagram Login API.
        self.assertIn("instagram_business_content_publish", message)

    def test_the_account_defaults_to_the_tokens_own_owner(self):
        """On the Instagram Login path there is no id to look up: "me" is it."""
        with mock.patch.dict("os.environ", {"INSTAGRAM_ACCESS_TOKEN": "t",
                                            "INSTAGRAM_ACCOUNT_ID": ""}, clear=False):
            self.assertEqual(instagram.credentials_from_env().account_id, "me")

        with mock.patch.dict("os.environ", {"INSTAGRAM_ACCESS_TOKEN": "t",
                                            "INSTAGRAM_ACCOUNT_ID": "17841400000000000"}):
            self.assertEqual(
                instagram.credentials_from_env().account_id, "17841400000000000"
            )

    def test_an_unparseable_issue_date_does_not_stop_the_post(self):
        """A malformed date makes the age unknown, not the credentials invalid."""
        with mock.patch.dict("os.environ", {
            "INSTAGRAM_ACCESS_TOKEN": "t",
            "INSTAGRAM_ACCOUNT_ID": "a",
            "INSTAGRAM_TOKEN_ISSUED_AT": "last Tuesday",
        }):
            creds = instagram.credentials_from_env()
        self.assertEqual(creds.access_token, "t")
        self.assertIsNone(creds.issued_at)


def _refuses(message):
    def refuse(*_args, **_kwargs):
        raise instagram.InstagramError(message)
    return refuse


class TokenLifecycleTests(unittest.TestCase):
    """Sixty days is long enough that nobody will remember. It has to be automatic."""

    def resolve(self, store, env_creds=CREDS, refresh=None):
        """One call to current(), with the environment and Meta both replaced.

        refresh_token is always patched, never left live: a test that reached the
        real one would make a network call to Meta with a fake token.
        """
        from contextlib import ExitStack

        if refresh is None:
            refresh = _refuses("nothing here should be refreshing")

        with ExitStack() as stack:
            store.install(stack)
            stack.enter_context(
                mock.patch.object(instagram, "credentials_from_env", return_value=env_creds)
            )
            self.refresh = mock.Mock(
                side_effect=refresh if callable(refresh) else None,
                return_value=None if callable(refresh) else refresh,
            )
            stack.enter_context(mock.patch.object(instagram, "refresh_token", self.refresh))
            return instagram.current(object())

    def test_the_first_run_seeds_the_store(self):
        store = FakeStore(stored=None)
        creds = self.resolve(store)

        self.assertEqual(creds.access_token, "seed-token")
        self.assertEqual(len(store.writes), 1, "the seed is copied in, once")

    def test_a_fresh_stored_token_is_used_as_is(self):
        store = FakeStore(stored=("stored-token", ago(3)))
        creds = self.resolve(store)

        self.assertEqual(creds.access_token, "stored-token")
        self.assertEqual(store.writes, [], "nothing to do")

    def test_a_token_past_halfway_is_refreshed_and_saved(self):
        store = FakeStore(stored=("old-token", ago(31)))
        creds = self.resolve(store, refresh=("new-token", 60 * 86400))

        self.assertEqual(creds.access_token, "new-token")
        self.assertEqual(store.writes[-1][0], "new-token")
        # The clock restarts from the refresh, not from the original issue.
        self.assertLess(datetime.now(timezone.utc) - creds.issued_at, timedelta(minutes=1))

    def test_a_failed_refresh_still_returns_a_working_token(self):
        """Thirty days of headroom is the entire point of refreshing at halfway."""
        store = FakeStore(stored=("old-token", ago(31)))
        creds = self.resolve(store, refresh=_refuses("rate limit"))

        self.assertEqual(creds.access_token, "old-token")
        self.assertEqual(store.writes, [])

    def test_a_hand_rotated_secret_wins(self):
        """If someone re-authorises in a browser, their token is the newer one."""
        store = FakeStore(stored=("stored-token", ago(40)))
        seeded = instagram.Credentials("hand-made", "17841400000000000", ago(1))
        creds = self.resolve(store, env_creds=seeded)

        self.assertEqual(creds.access_token, "hand-made")
        self.assertEqual(store.writes[-1][0], "hand-made")

    def test_an_unmigrated_database_falls_back_to_the_environment(self):
        """The table may not exist yet. That must not stop the first post.

        An unknown age means the refresh is attempted, which is the safe way
        round: a wasted call costs nothing and a skipped one costs the account.
        """
        store = FakeStore(readable=False)
        creds = self.resolve(store, refresh=_refuses("no network"))
        self.assertEqual(creds.access_token, "seed-token")
        self.assertEqual(store.writes, [], "nothing can be written to a missing table")

    def test_health_says_how_long_is_left(self):
        self.assertIn("days left", instagram.token_health(
            instagram.Credentials("t", "a", ago(2))
        ))
        self.assertIn("due for refresh", instagram.token_health(
            instagram.Credentials("t", "a", ago(35))
        ))
        self.assertIn("EXPIRES", instagram.token_health(
            instagram.Credentials("t", "a", ago(50))
        ))


class PublishingTests(unittest.TestCase):
    def responses(self, *payloads):
        return mock.Mock(side_effect=list(payloads))

    def test_the_happy_path_is_container_then_publish(self):
        request = self.responses(
            {"id": "container-1"},
            {"status_code": "FINISHED"},
            {"id": "17900000000000000"},
        )
        with mock.patch.object(instagram, "_request", request):
            post_id = instagram.publish("https://example.test/c.jpg", "hello", CREDS)

        self.assertEqual(post_id, "17900000000000000")
        self.assertEqual(request.call_count, 3)
        # The image is never uploaded; Instagram is told where to fetch it.
        self.assertEqual(
            request.call_args_list[0].kwargs["data"]["image_url"],
            "https://example.test/c.jpg",
        )

    def test_an_unfetchable_image_is_reported_as_such(self):
        """The most likely failure in production, and the least self-explanatory."""
        request = self.responses(
            {"id": "container-1"},
            {"status_code": "ERROR", "status": "Media could not be fetched"},
        )
        with mock.patch.object(instagram, "_request", request):
            with self.assertRaises(instagram.InstagramError) as caught:
                instagram.publish("https://example.test/missing.jpg", "hello", CREDS)

        self.assertIn("could not fetch", str(caught.exception))

    def test_a_container_that_never_finishes_gives_up(self):
        """Polling stops at Meta's five-minute ceiling rather than forever."""
        def never_ready(*_args, **kwargs):
            return {"id": "c"} if kwargs.get("data") else {"status_code": "IN_PROGRESS"}

        # The clock is driven by the sleeps rather than left real: otherwise the
        # deadline is honoured by spinning for five actual minutes.
        slept: list[float] = []
        clock = [0.0]

        def sleep(seconds):
            slept.append(seconds)
            clock[0] += seconds

        with mock.patch.object(instagram, "_request", side_effect=never_ready), \
             mock.patch.object(instagram.time, "monotonic", lambda: clock[0]), \
             mock.patch.object(instagram.time, "sleep", sleep):
            with self.assertRaises(instagram.InstagramError) as caught:
                instagram.publish("https://example.test/c.jpg", "hello", CREDS)

        self.assertIn("IN_PROGRESS", str(caught.exception))
        self.assertLessEqual(sum(slept), instagram.CONTAINER_DEADLINE)
        # Quick at first, because a small JPEG is usually ready immediately,
        # then backing off rather than making a hundred requests.
        self.assertEqual(slept[0], instagram.CONTAINER_FIRST_DELAY)
        self.assertEqual(max(slept), instagram.CONTAINER_MAX_DELAY)

    def test_an_expired_container_says_so(self):
        request = self.responses({"id": "c"}, {"status_code": "EXPIRED"})
        with mock.patch.object(instagram, "_request", request):
            with self.assertRaises(instagram.InstagramError) as caught:
                instagram.publish("https://example.test/c.jpg", "hello", CREDS)
        self.assertIn("expired", str(caught.exception))

    def test_an_already_published_container_is_not_retried(self):
        """PUBLISHED means the post exists. Failing here would invite a second."""
        request = self.responses(
            {"id": "c"}, {"status_code": "PUBLISHED"}, {"id": "17900000000000000"}
        )
        with mock.patch.object(instagram, "_request", request):
            self.assertEqual(
                instagram.publish("https://example.test/c.jpg", "hello", CREDS),
                "17900000000000000",
            )

    def test_whoami_reads_the_account_without_posting(self):
        """The setup check: one GET to /me, and nothing that could publish."""
        request = self.responses(
            {"user_id": "17841400000000000", "username": "ontrackapp",
             "account_type": "BUSINESS"}
        )
        with mock.patch.object(instagram, "_request", request):
            me = instagram.whoami(CREDS)

        self.assertEqual(me["username"], "ontrackapp")
        self.assertEqual(me["account_type"], "BUSINESS")
        self.assertEqual(request.call_count, 1)
        method, url = request.call_args.args[:2]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://graph.instagram.com/v26.0/me")

    def test_whoami_accepts_the_documented_envelope(self):
        """Meta's docs show /me wrapped in `data`; the API returns it flat."""
        request = self.responses(
            {"data": [{"user_id": "178", "username": "ontrackapp",
                       "account_type": "MEDIA_CREATOR"}]}
        )
        with mock.patch.object(instagram, "_request", request):
            me = instagram.whoami(CREDS)
        self.assertEqual(me["user_id"], "178")
        self.assertEqual(me["account_type"], "MEDIA_CREATOR")

    def test_publishing_goes_to_the_instagram_login_host(self):
        """graph.instagram.com, not graph.facebook.com.

        The two Instagram publishing APIs take different tokens and different
        permissions, and pointing an Instagram User token at the Facebook host
        fails in a way that reads like a permissions problem.
        """
        request = self.responses(
            {"id": "container-1"},
            {"status_code": "FINISHED"},
            {"id": "17900000000000000"},
        )
        with mock.patch.object(instagram, "_request", request):
            instagram.publish("https://example.test/c.jpg", "hello", CREDS)

        for call in request.call_args_list:
            self.assertTrue(
                call.args[1].startswith("https://graph.instagram.com/"), call.args[1]
            )

    def test_refreshing_always_uses_the_instagram_host(self):
        """Refreshing exists only for the Instagram Login token."""
        request = self.responses({"access_token": "new", "expires_in": 5183944})
        with mock.patch.object(instagram, "_request", request):
            token, expires = instagram.refresh_token(CREDS)

        self.assertEqual(token, "new")
        self.assertEqual(expires, 5183944)
        self.assertEqual(
            request.call_args.args[1], "https://graph.instagram.com/refresh_access_token"
        )
        # This one call keeps the token as a parameter: the endpoint identifies
        # the token being renewed by it, and a bearer header does not.
        self.assertEqual(
            request.call_args.kwargs["params"]["grant_type"], "ig_refresh_token"
        )

    def test_the_token_is_never_put_in_a_url(self):
        """Access tokens in query strings end up in logs, proxies and CI output.

        Meta's own examples pass the token as a parameter. Every call here sends
        it as a bearer header instead - except the refresh endpoint, which
        identifies the token being renewed by that parameter and has no
        alternative.
        """
        request = self.responses(
            {"id": "container-1"},
            {"status_code": "FINISHED"},
            {"id": "17900000000000000"},
        )
        with mock.patch.object(instagram, "_request", request):
            instagram.publish("https://example.test/c.jpg", "hello", CREDS)

        for call in request.call_args_list:
            url = call.args[1]
            self.assertNotIn(CREDS.access_token, url)
            self.assertEqual(call.args[2], CREDS.access_token, "passed as the token argument")
            params = call.kwargs.get("params") or {}
            data = call.kwargs.get("data") or {}
            self.assertNotIn("access_token", params)
            self.assertNotIn("access_token", data)

    @unittest.skipUnless(HAS_HTTPX, "exercises the real client (pip install -r social/requirements.txt)")
    def test_an_error_carrying_the_token_is_redacted(self):
        """Meta occasionally echoes the request back inside the error message."""
        import httpx

        def boom(*_args, **_kwargs):
            raise httpx.ConnectError(
                "failed connecting to graph.facebook.com/?access_token=seed-token"
            )

        with mock.patch("httpx.Client") as client:
            client.return_value.__enter__.return_value.request.side_effect = boom
            with self.assertRaises(instagram.InstagramError) as caught:
                instagram._request("GET", "https://graph.facebook.com/me", "seed-token")

        message = str(caught.exception)
        self.assertNotIn("seed-token", message)
        self.assertIn("<token>", message)

    def test_a_response_without_an_id_is_an_error_not_a_none(self):
        request = self.responses({"error": {"message": "Invalid parameter"}})
        with mock.patch.object(instagram, "_request", request):
            with self.assertRaises(instagram.InstagramError):
                instagram.publish("https://example.test/c.jpg", "hello", CREDS)


if __name__ == "__main__":
    unittest.main()
