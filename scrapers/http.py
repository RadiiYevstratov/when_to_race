"""Fetch stage.

Reliability rules 4 and 5 live here: retry with backoff capped at 3 attempts,
at most one request every 2 seconds per host, robots.txt respected, and a
User-Agent that says who we are and how to reach us.

httpx is imported lazily so that parsing, normalizing and validating stay
testable in an environment with nothing installed. The rate limiter and the
retry policy are plain objects for the same reason - they are the parts with
logic worth testing, and tests inject a fake transport.
"""

from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

# A page a site owner can actually open if they want to know who this is.
# The clone URL is not that page.
CONTACT_URL = "https://github.com/RadiiYevstratov/when_to_race"
USER_AGENT = f"MotorsportScheduleBot/0.1 (+{CONTACT_URL})"

MIN_INTERVAL_SECONDS = 2.0
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 30.0

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class FetchError(Exception):
    def __init__(self, message: str, *, status: Optional[int] = None, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url


class RobotsDisallowed(FetchError):
    pass


@dataclass
class Response:
    url: str
    status: int
    body: bytes
    content_type: Optional[str] = None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class RateLimiter:
    """One request per host per `min_interval` seconds."""

    def __init__(self, min_interval: float = MIN_INTERVAL_SECONDS, clock: Callable[[], float] = time.monotonic):
        self.min_interval = min_interval
        self._clock = clock
        self._last_seen: dict[str, float] = {}

    def delay_for(self, host: str) -> float:
        last = self._last_seen.get(host)
        if last is None:
            return 0.0
        elapsed = self._clock() - last
        return max(0.0, self.min_interval - elapsed)

    def record(self, host: str) -> None:
        self._last_seen[host] = self._clock()


def backoff_delay(attempt: int, base: float = BACKOFF_BASE_SECONDS) -> float:
    """Exponential: 2s, 4s, 8s. Attempt is 1-indexed."""
    if attempt < 1:
        raise ValueError("attempt is 1-indexed")
    return base * (2 ** (attempt - 1))


def should_retry(status: Optional[int], attempt: int, max_attempts: int = MAX_ATTEMPTS) -> bool:
    if attempt >= max_attempts:
        return False
    if status is None:  # network-level failure
        return True
    return status in RETRYABLE_STATUS


class RobotsCache:
    def __init__(self, fetch: Callable[[str], Response]):
        self._fetch = fetch
        self._parsers: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}

    def allowed(self, url: str, user_agent: str = USER_AGENT) -> bool:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            parser: Optional[urllib.robotparser.RobotFileParser]
            try:
                response = self._fetch(f"{origin}/robots.txt")
                if response.status >= 400:
                    parser = None  # no robots.txt means no restriction
                else:
                    parser = urllib.robotparser.RobotFileParser()
                    parser.parse(response.text.splitlines())
            except FetchError:
                parser = None
            self._parsers[origin] = parser

        parser = self._parsers[origin]
        return True if parser is None else parser.can_fetch(user_agent, url)


class HttpClient:
    """Thin httpx wrapper. Pass `transport` in tests to avoid the network."""

    def __init__(
        self,
        transport: Optional[Callable[[str], Response]] = None,
        rate_limiter: Optional[RateLimiter] = None,
        sleep: Callable[[float], None] = time.sleep,
        respect_robots: bool = True,
        max_attempts: int = MAX_ATTEMPTS,
    ):
        self._transport = transport or self._httpx_transport
        self._rate_limiter = rate_limiter or RateLimiter()
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._robots = RobotsCache(self._raw_get) if respect_robots else None

    @staticmethod
    def _httpx_transport(url: str) -> Response:
        import httpx  # imported here so the module loads without it installed

        try:
            reply = httpx.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
                timeout=REQUEST_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        except Exception as exc:  # noqa: BLE001 - httpx raises a family of errors
            raise FetchError(str(exc), url=url) from exc
        return Response(
            url=str(reply.url),
            status=reply.status_code,
            body=reply.content,
            content_type=reply.headers.get("content-type"),
        )

    def _raw_get(self, url: str) -> Response:
        host = urlparse(url).netloc
        delay = self._rate_limiter.delay_for(host)
        if delay > 0:
            self._sleep(delay)
        try:
            response = self._transport(url)
        finally:
            self._rate_limiter.record(host)
        return response

    def get(self, url: str) -> Response:
        if self._robots is not None and not self._robots.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}", url=url)

        last_error: Optional[FetchError] = None
        for attempt in range(1, self._max_attempts + 1):
            status: Optional[int] = None
            try:
                response = self._raw_get(url)
                status = response.status
                if status < 400:
                    return response
                last_error = FetchError(f"HTTP {status} for {url}", status=status, url=url)
            except FetchError as exc:
                last_error = exc
                status = exc.status

            if not should_retry(status, attempt, self._max_attempts):
                break
            self._sleep(backoff_delay(attempt))

        # Rule 4: record the failure and move on. One dead source must not block
        # the other nine, so this raises rather than exiting.
        raise last_error or FetchError(f"failed to fetch {url}", url=url)
