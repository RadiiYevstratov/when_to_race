"""Publishing to Instagram, and keeping the token alive.

Publishing is two calls, not one: create a media container pointing at a public
image URL, then publish that container. Instagram fetches the image itself -
there is no byte upload - which is why the pipeline has to put the card
somewhere reachable before it gets here.

The token is the fragile part of the whole system. A long-lived token lasts 60
days and can be refreshed indefinitely without a human present, but one that
lapses cannot be recovered by retrying: it needs an interactive re-authorisation.
So `current()` keeps the token in the database rather than in the environment -
the variable is a seed, the table is the truth - refreshes it at halfway, and
reports its age on every run. The failure worth engineering against is the
silent one, and a token quietly aging out over a holiday is that failure exactly.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

API_VERSION = "v26.0"

# There are two Instagram publishing APIs and they are not interchangeable.
#
#   Instagram API with Instagram Login   graph.instagram.com, an Instagram User
#                                        token, no Facebook Page needed
#   Instagram API with Facebook Login    graph.facebook.com, a Facebook Page
#                                        token, an IG account linked to a Page
#
# This project uses the first, because it needs no Facebook Page and because its
# token refreshes itself - which is the only reason an unattended daily job is
# possible at all. The host is overridable for anyone who has to use the other
# one; the permission names and the token differ too, so it is not only a host.
GRAPH = os.environ.get(
    "INSTAGRAM_API_HOST", f"https://graph.instagram.com/{API_VERSION}"
).rstrip("/")

# Refreshing is Instagram-Login-only and always on graph.instagram.com, whatever
# the host above says: there is no equivalent for a Page token, which is
# long-lived by other means.
REFRESH_HOST = "https://graph.instagram.com"

# Meta's documented lifetime. Refresh well inside it: a token is refreshable
# from 24 hours old, and leaving it to the last week means one failed run turns
# into a dead integration.
TOKEN_LIFETIME = timedelta(days=60)
REFRESH_AFTER = timedelta(days=30)
WARN_AFTER = timedelta(days=45)

# Instagram fetches and processes the image asynchronously, and publishing an
# unfinished container fails. Meta's guidance is to poll "once per minute, for
# no more than 5 minutes", so the first checks are quick - an 80KB JPEG is
# usually ready immediately - and the interval then backs off to a minute for
# the long tail rather than making 100 requests.
CONTAINER_FIRST_DELAY = 3
CONTAINER_MAX_DELAY = 60
CONTAINER_DEADLINE = 300

REQUEST_TIMEOUT = 30


class InstagramError(RuntimeError):
    """Anything that stopped a post going out."""


class NotConfigured(InstagramError):
    """No credentials. Expected until the account is connected."""


@dataclass(frozen=True)
class Credentials:
    access_token: str
    account_id: str
    issued_at: Optional[datetime] = None

    @property
    def age(self) -> Optional[timedelta]:
        if self.issued_at is None:
            return None
        return datetime.now(timezone.utc) - self.issued_at

    @property
    def should_refresh(self) -> bool:
        age = self.age
        return age is None or age >= REFRESH_AFTER

    @property
    def is_stale(self) -> bool:
        age = self.age
        return age is not None and age >= WARN_AFTER


def credentials_from_env() -> Credentials:
    """Read the credentials, or say precisely which one is missing."""
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()

    # The account is the token's own owner unless told otherwise. On the
    # Instagram Login path "me" resolves to exactly that, so there is nothing to
    # look up; the explicit id is there for the Facebook Login path, where the
    # token belongs to a Page and the target has to be named.
    account = os.environ.get("INSTAGRAM_ACCOUNT_ID", "").strip() or "me"

    if not token:
        raise NotConfigured(
            "INSTAGRAM_ACCESS_TOKEN not set. Everything up to publishing still "
            "runs; see docs/instagram.md for the one-time Meta setup "
            "(permissions: instagram_business_basic, "
            "instagram_business_content_publish)."
        )

    issued_raw = os.environ.get("INSTAGRAM_TOKEN_ISSUED_AT", "").strip()
    issued: Optional[datetime] = None
    if issued_raw:
        try:
            issued = datetime.fromisoformat(issued_raw)
            if issued.tzinfo is None:
                issued = issued.replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning("INSTAGRAM_TOKEN_ISSUED_AT is not a date: %r", issued_raw)

    return Credentials(token, account, issued)


def is_configured() -> bool:
    try:
        credentials_from_env()
        return True
    except NotConfigured:
        return False


# --------------------------------------------------------------------------
# the API
# --------------------------------------------------------------------------


def _redact(text: str, token: str) -> str:
    """Never let a token reach a log, an error, or a CI transcript."""
    return text.replace(token, "<token>") if token else text


def _request(method: str, url: str, token: str, **kwargs):
    """One Graph API call, with the token in the header.

    Meta accepts the token as a query parameter and every example uses it that
    way, which is how access tokens end up in error strings, proxy logs and
    pasted CI output. A bearer header costs nothing and keeps it out of all of
    them; whatever does escape is redacted on the way out.
    """
    import httpx

    headers = {"Authorization": f"Bearer {token}"}

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            response = client.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as error:
        raise InstagramError(f"could not reach Instagram: {_redact(str(error), token)}") from None

    if response.status_code >= 400:
        # Meta puts the useful part in a JSON envelope; the status alone rarely
        # says what was actually wrong.
        detail = response.text[:400]
        try:
            payload = response.json().get("error", {})
            detail = f"{payload.get('type')}: {payload.get('message')} (code {payload.get('code')})"
        except Exception:  # noqa: BLE001 - keep the raw body if it is not JSON
            pass
        raise InstagramError(
            f"Instagram returned {response.status_code} - {_redact(detail, token)}"
        )

    return response.json()


def publish(image_url: str, caption: str, credentials: Optional[Credentials] = None) -> str:
    """Put one image on the account. Returns the Instagram post id."""
    creds = credentials or credentials_from_env()

    container = _request(
        "POST",
        f"{GRAPH}/{creds.account_id}/media",
        creds.access_token,
        data={"image_url": image_url, "caption": caption},
    )
    container_id = container.get("id")
    if not container_id:
        raise InstagramError(f"no container id in the response: {container}")

    _await_container(container_id, creds)

    published = _request(
        "POST",
        f"{GRAPH}/{creds.account_id}/media_publish",
        creds.access_token,
        data={"creation_id": container_id},
    )
    post_id = published.get("id")
    if not post_id:
        raise InstagramError(f"no post id in the response: {published}")

    logger.info("published %s", post_id)
    return post_id


def _await_container(container_id: str, creds: Credentials) -> None:
    """Wait for Instagram to finish fetching and checking the image.

    Publishing an unfinished container fails, and the error does not say why.
    ERROR almost always means Instagram could not fetch the image URL, which is
    worth saying in those words because it is the most likely thing to break in
    production - a mid-deploy site, or a route that stopped being public.
    """
    deadline = time.monotonic() + CONTAINER_DEADLINE
    delay = CONTAINER_FIRST_DELAY
    last = "unknown"

    while True:
        status = _request(
            "GET",
            f"{GRAPH}/{container_id}",
            creds.access_token,
            params={"fields": "status_code,status"},
        )
        code = status.get("status_code")
        last = code or last

        # PUBLISHED means something already published this container. Treating
        # it as success rather than an error is deliberate: the post exists, and
        # failing here would invite a retry that made a second one.
        if code in ("FINISHED", "PUBLISHED"):
            return
        if code == "ERROR":
            raise InstagramError(
                f"Instagram could not process the media: {status.get('status')}. "
                "The usual cause is an image URL it could not fetch."
            )
        if code == "EXPIRED":
            raise InstagramError(
                f"media container {container_id} expired before it was published"
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise InstagramError(
                f"media container {container_id} was still {last} after "
                f"{CONTAINER_DEADLINE}s"
            )
        time.sleep(min(delay, remaining))
        delay = min(delay * 2, CONTAINER_MAX_DELAY)


TOKEN_NAME = "instagram_access_token"


def current(connection, refresh: bool = True) -> Credentials:
    """The token to use now, refreshed if it is past halfway through its life.

    The environment variable is a seed, not the source of truth. Meta's refresh
    returns a *new* token string, and a deployment secret is not something a job
    can rewrite by itself - so the first run copies the seed into the database
    and every run afterwards reads, refreshes and writes back there. The
    integration then renews itself indefinitely with nobody present, which is
    the only version of this that survives a holiday.

    A refresh that fails is not fatal: the existing token is still valid for
    weeks, and the run continues with it. It becomes fatal only if nothing ever
    succeeds before the sixty days run out, which is why the age is reported on
    every run and again on the status command.

    `refresh=False` reads without renewing, for the status command: asking what
    the token looks like should not be the thing that changes it.
    """
    creds = _resolve(connection, credentials_from_env())

    if not refresh or not creds.should_refresh:
        logger.info("%s", token_health(creds))
        return creds

    try:
        fresh, expires_in = refresh_token(creds)
    except InstagramError as error:
        logger.warning("token refresh failed (%s); continuing with the current token", error)
        if creds.is_stale:
            logger.error("THE INSTAGRAM TOKEN IS CLOSE TO EXPIRY AND WILL NOT REFRESH")
        return creds

    creds = Credentials(fresh, creds.account_id, _now())
    _save(connection, creds)
    logger.info("token refreshed; good for another %d days", expires_in // 86400)
    return creds


def _resolve(connection, seed: Credentials) -> Credentials:
    """Which token is the live one: the stored one, or the environment's.

    The stored one, normally. The environment wins only when it holds a
    different token that is demonstrably newer - which happens exactly once, when
    somebody has re-authorised in a browser after letting the old one lapse.
    Without the date comparison the seed would win every day and undo every
    refresh, so a seed with no INSTAGRAM_TOKEN_ISSUED_AT never overrides.
    """
    from .repository import load_credential

    try:
        stored = load_credential(connection, TOKEN_NAME)
    except Exception as error:  # noqa: BLE001 - an unmigrated database is not a crash
        logger.warning("could not read the stored token (%s); using the environment", error)
        return seed

    if stored is None:
        logger.info("no stored token; seeding from INSTAGRAM_ACCESS_TOKEN")
        creds = Credentials(seed.access_token, seed.account_id, seed.issued_at or _now())
        _save(connection, creds)
        return creds

    token, issued = stored
    if (
        seed.access_token
        and seed.access_token != token
        and seed.issued_at is not None
        and seed.issued_at > issued
    ):
        logger.info("INSTAGRAM_ACCESS_TOKEN is newer than the stored token; taking it")
        creds = Credentials(seed.access_token, seed.account_id, seed.issued_at)
        _save(connection, creds)
        return creds

    return Credentials(token, seed.account_id, issued)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _save(connection, creds: Credentials) -> None:
    from .repository import store_credential

    try:
        store_credential(connection, TOKEN_NAME, creds.access_token, creds.issued_at)
    except Exception:  # noqa: BLE001 - a post is worth more than a bookkeeping row
        logger.exception("could not store the refreshed token; it will refresh again tomorrow")


def refresh_token(credentials: Optional[Credentials] = None) -> tuple[str, int]:
    """Extend the long-lived token. Returns the new token and its lifetime.

    Refreshing needs no human, which is what makes the automation possible at
    all - but the new token has to be written back to wherever the secret lives,
    and this function cannot do that. The caller reports it.
    """
    creds = credentials or credentials_from_env()
    # Two things here are not like the other calls. The host is always
    # graph.instagram.com, because refreshing exists only for the Instagram
    # Login token. And the token stays in the query string, because this
    # endpoint identifies the token being renewed by that parameter - a bearer
    # header does not stand in for it.
    payload = _request(
        "GET",
        f"{REFRESH_HOST}/refresh_access_token",
        creds.access_token,
        params={"grant_type": "ig_refresh_token", "access_token": creds.access_token},
    )
    token = payload.get("access_token")
    if not token:
        raise InstagramError(f"no token in the refresh response: {payload}")
    return token, int(payload.get("expires_in", 0))


def whoami(credentials: Optional[Credentials] = None) -> dict:
    """Which account the token belongs to - the one Meta call that cannot post.

    Without it, the only way to learn whether a token works is to publish with
    it. This is the check the status command runs, so a manual dry run from the
    Actions tab proves the whole setup - token valid, right account, professional
    type - before anything goes out.

    Meta documents the response wrapped in `data` and returns it flat in
    practice; both are accepted.
    """
    creds = credentials or credentials_from_env()
    payload = _request(
        "GET",
        f"{GRAPH}/me",
        creds.access_token,
        params={"fields": "user_id,username,account_type"},
    )
    if isinstance(payload.get("data"), list) and payload["data"]:
        payload = payload["data"][0]
    return {
        "user_id": payload.get("user_id") or payload.get("id"),
        "username": payload.get("username"),
        "account_type": payload.get("account_type"),
    }


def publishing_limit(credentials: Optional[Credentials] = None) -> Optional[int]:
    """How many posts have gone out in the last 24 hours.

    The ceiling is 100 and this job uses at most one, so this exists to catch
    something else publishing on the same account rather than to ration.
    """
    creds = credentials or credentials_from_env()
    try:
        payload = _request(
            "GET",
            f"{GRAPH}/{creds.account_id}/content_publishing_limit",
            creds.access_token,
            params={"fields": "quota_usage"},
        )
        data = payload.get("data") or []
        return int(data[0].get("quota_usage", 0)) if data else None
    except InstagramError as error:
        logger.warning("could not read the publishing limit: %s", error)
        return None


def token_health(credentials: Optional[Credentials] = None) -> str:
    """A line for the log, so a dying token is visible before it dies."""
    try:
        creds = credentials or credentials_from_env()
    except NotConfigured as error:
        return f"not configured - {error}"

    age = creds.age
    if age is None:
        return "configured; token age unknown (set INSTAGRAM_TOKEN_ISSUED_AT)"

    days = age.days
    remaining = (TOKEN_LIFETIME - age).days
    if creds.is_stale:
        return f"TOKEN EXPIRES IN {remaining} DAYS - refresh or re-authorise now"
    if creds.should_refresh:
        return f"token is {days} days old; due for refresh ({remaining} days left)"
    return f"token is {days} days old, {remaining} days left"
