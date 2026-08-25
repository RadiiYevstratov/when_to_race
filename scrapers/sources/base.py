"""Source interface.

A source knows two things and nothing else: which URLs to fetch, and how to turn
the bodies into ParsedSession records. It must not touch the database, convert
timezones, or use the controlled vocabulary - those belong to later stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Protocol

from ..config import SeriesConfig, VenueConfig
from ..records import ParsedSession


@dataclass
class FetchedDocument:
    url: str
    body: bytes
    content_type: Optional[str] = None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class Source(Protocol):
    series_code: str
    detail_level: str

    def urls(self, season: int) -> list[str]:
        """Every URL this source needs for a season, in fetch order.

        A source whose URL list can only be known after a first request (an
        index of rounds, say) may instead implement
        ``resolve_urls(season, client)``; the pipeline passes it the polite HTTP
        client to do that discovery and uses the URLs it returns. Implement one
        or the other, not both.
        """

    def parse(
        self,
        documents: Iterable[FetchedDocument],
        series: SeriesConfig,
        venues: dict[str, VenueConfig],
        season: int,
    ) -> list[ParsedSession]:
        """Loosely-typed extraction. The only layer that knows a site's quirks."""


_REGISTRY: dict[str, Callable[..., Source]] = {}


def register(adapter_name: str) -> Callable[[Callable[..., Source]], Callable[..., Source]]:
    def decorator(factory: Callable[..., Source]) -> Callable[..., Source]:
        if adapter_name in _REGISTRY:
            raise ValueError(f"source adapter {adapter_name!r} is already registered")
        _REGISTRY[adapter_name] = factory
        return factory

    return decorator


def get_source(adapter_name: str, **kwargs) -> Source:
    if adapter_name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise KeyError(f"no source adapter named {adapter_name!r}; registered: {known}")
    return _REGISTRY[adapter_name](**kwargs)


def registered_adapters() -> list[str]:
    return sorted(_REGISTRY)


def resolve_venue(location_text: str, venues: dict[str, VenueConfig], aliases: dict[str, str]) -> Optional[str]:
    """Best-effort map from a source's free-text location to a venue slug.

    Tried in order: explicit alias, exact slug, venue name, city, then a
    containment check. Returns None rather than guessing wildly - an unmapped
    venue should surface as a validation error, not as a session at the wrong
    circuit in the wrong timezone.
    """
    if not location_text:
        return None
    needle = location_text.strip().lower()

    if needle in aliases:
        return aliases[needle]
    if needle in venues:
        return needle

    for slug, venue in venues.items():
        if venue.name.lower() == needle:
            return slug
    for slug, venue in venues.items():
        if venue.city and venue.city.lower() == needle:
            return slug
    for alias, slug in aliases.items():
        if alias in needle:
            return slug
    for slug, venue in venues.items():
        if venue.name.lower() in needle or needle in venue.name.lower():
            return slug
    return None
