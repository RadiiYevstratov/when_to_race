"""Loads config/series.toml and config/venues.toml.

Validation happens at load time, not at first use: a bad IANA zone or a missing
headline category should fail the process immediately, not halfway through a
scrape run.
"""

from __future__ import annotations

import tomllib
import zoneinfo
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class CategoryConfig:
    code: str
    name: str
    short_name: str
    is_headline: bool = False
    sort_order: int = 100
    # None inherits the parent series colour, which is what a headline class
    # wants: Formula 1 within Formula 1 has no separate identity to state.
    accent_color: Optional[str] = None
    # Where a class's identity is more than one colour - the NASCAR Cup Series
    # is yellow, red and blue together, and any one of them is a third of a
    # logo. Empty is the usual case and means the mark is `accent_color`.
    # When set, the first band is `accent_color`, so nothing that wants a
    # single colour has to know this exists.
    accent_colors: tuple[str, ...] = ()
    # The championship's own site, for sending a reader to the source. Only
    # for a class that is its own championship with its own site: Formula 2 has
    # one, Moto2 does not - it lives on motogp.com with the series.
    official_url: Optional[str] = None


@dataclass(frozen=True)
class SourceConfig:
    adapter: str
    status: str = "unverified"  # unverified | live
    url: Optional[str] = None
    # Further feeds fetched alongside `url`, for a series whose categories are
    # published separately - Formula 1, whose support championships come from a
    # different publisher than the Grand Prix itself.
    extra_urls: tuple[str, ...] = ()
    discovery_notes: Optional[str] = None

    @property
    def is_verified(self) -> bool:
        return self.status == "live"


@dataclass(frozen=True)
class SeriesConfig:
    code: str
    name: str
    short_name: str
    accent_color: str
    sort_order: int
    source: SourceConfig
    # The championship's own site. Where a reader is sent to check a time
    # against the organiser, and what the footer links out to.
    official_url: Optional[str] = None
    categories: tuple[CategoryConfig, ...] = field(default_factory=tuple)

    def category(self, code: str) -> CategoryConfig:
        for cat in self.categories:
            if cat.code == code:
                return cat
        raise ConfigError(f"series {self.code!r} has no category {code!r}")

    @property
    def headline_category(self) -> CategoryConfig:
        for cat in self.categories:
            if cat.is_headline:
                return cat
        return self.categories[0]


@dataclass(frozen=True)
class VenueConfig:
    slug: str
    name: str
    country_code: str
    iana_timezone: str
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


HEX_COLOR_LENGTH = 7


def _load_toml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _check_hex(series_code: str, cat: dict, field: str, color) -> str:
    if not (isinstance(color, str) and color.startswith("#") and len(color) == HEX_COLOR_LENGTH):
        raise ConfigError(
            f"series {series_code!r} category {cat['code']!r}: "
            f"{field} must be #rrggbb, got {color!r}"
        )
    return color


def _official_url(where: str, raw: dict) -> Optional[str]:
    """The championship's public site, if it has one here.

    https only, and rejected loudly rather than skipped: this is rendered as a
    link on every page of the site, so a typo is a dead end in the footer
    rather than something that shows up in a log.
    """
    url = raw.get("official_url")
    if url is None:
        return None
    if not (isinstance(url, str) and url.startswith("https://")):
        raise ConfigError(f"{where}: official_url must be an https:// URL, got {url!r}")
    return url


def _category_color(series_code: str, cat: dict) -> Optional[str]:
    color = cat.get("accent_color")
    if color is None:
        return None
    return _check_hex(series_code, cat, "accent_color", color)


def _category_colors(series_code: str, cat: dict) -> tuple[str, ...]:
    """The bands of a multi-colour identity mark, or nothing.

    One band is rejected rather than accepted quietly: it would duplicate
    `accent_color` and leave two places to change the same colour.
    """
    colors = cat.get("accent_colors")
    if colors is None:
        return ()
    if not isinstance(colors, list) or len(colors) < 2:
        raise ConfigError(
            f"series {series_code!r} category {cat['code']!r}: "
            f"accent_colors must be a list of two or more #rrggbb, got {colors!r}"
        )
    bands = tuple(_check_hex(series_code, cat, "accent_colors", c) for c in colors)

    # The first band is the single colour, so a caller that wants one is never
    # choosing between them.
    single = cat.get("accent_color")
    if single is not None and single.lower() != bands[0].lower():
        raise ConfigError(
            f"series {series_code!r} category {cat['code']!r}: "
            f"accent_color {single!r} must be the first of accent_colors {bands[0]!r}"
        )
    return bands


@lru_cache(maxsize=1)
def load_series(config_dir: Optional[str] = None) -> dict[str, SeriesConfig]:
    directory = Path(config_dir) if config_dir else CONFIG_DIR
    raw = _load_toml(directory / "series.toml")

    result: dict[str, SeriesConfig] = {}
    for entry in raw.get("series", []):
        code = entry["code"]
        if code in result:
            raise ConfigError(f"duplicate series code {code!r}")

        color = entry["accent_color"]
        if not (color.startswith("#") and len(color) == HEX_COLOR_LENGTH):
            raise ConfigError(f"series {code!r}: accent_color must be #rrggbb, got {color!r}")

        categories = tuple(
            CategoryConfig(
                code=cat["code"],
                name=cat["name"],
                short_name=cat["short_name"],
                is_headline=cat.get("is_headline", False),
                sort_order=cat.get("sort_order", 100),
                accent_color=_category_color(code, cat),
                accent_colors=_category_colors(code, cat),
                official_url=_official_url(f"series {code!r} category {cat['code']!r}", cat),
            )
            for cat in entry.get("categories", [])
        )
        if not categories:
            raise ConfigError(f"series {code!r} has no categories")

        codes = [cat.code for cat in categories]
        if len(codes) != len(set(codes)):
            raise ConfigError(f"series {code!r} has duplicate category codes")
        if sum(1 for cat in categories if cat.is_headline) > 1:
            raise ConfigError(f"series {code!r} has more than one headline category")

        source_raw = entry.get("source", {})
        source = SourceConfig(
            adapter=source_raw.get("adapter", code),
            status=source_raw.get("status", "unverified"),
            url=source_raw.get("url"),
            extra_urls=tuple(source_raw.get("extra_urls", ())),
            discovery_notes=source_raw.get("discovery_notes"),
        )
        if source.status not in ("unverified", "live"):
            raise ConfigError(f"series {code!r}: unknown source status {source.status!r}")

        result[code] = SeriesConfig(
            code=code,
            name=entry["name"],
            short_name=entry["short_name"],
            accent_color=color,
            sort_order=entry.get("sort_order", 100),
            source=source,
            categories=categories,
            official_url=_official_url(f"series {code!r}", entry),
        )

    if not result:
        raise ConfigError("series.toml defined no series")
    return result


@lru_cache(maxsize=1)
def load_session_floors(config_dir: Optional[str] = None) -> dict[str, int]:
    """Minimum plausible session count per event, per series."""
    directory = Path(config_dir) if config_dir else CONFIG_DIR
    raw = _load_toml(directory / "series.toml")
    floors = raw.get("validation", {}).get("min_sessions_per_event", {})
    known = {entry["code"] for entry in raw.get("series", [])}
    for code in floors:
        if code not in known:
            raise ConfigError(f"validation floor set for unknown series {code!r}")
    return {code: int(value) for code, value in floors.items()}


@lru_cache(maxsize=1)
def load_venues(config_dir: Optional[str] = None) -> dict[str, VenueConfig]:
    directory = Path(config_dir) if config_dir else CONFIG_DIR
    raw = _load_toml(directory / "venues.toml")

    result: dict[str, VenueConfig] = {}
    for entry in raw.get("venue", []):
        slug = entry["slug"]
        if slug in result:
            raise ConfigError(f"duplicate venue slug {slug!r}")

        tz_name = entry["iana_timezone"]
        try:
            zoneinfo.ZoneInfo(tz_name)
        except Exception as exc:  # noqa: BLE001 - surface the zone name in the message
            raise ConfigError(
                f"venue {slug!r}: unknown IANA timezone {tz_name!r}. "
                "On Windows this usually means the tzdata package is missing: pip install tzdata"
            ) from exc
        if tz_name.upper() in ("UTC", "GMT") and slug != "utc":
            raise ConfigError(f"venue {slug!r}: UTC is not a circuit-local timezone")

        country = entry["country_code"]
        if len(country) != 2 or not country.isalpha():
            raise ConfigError(f"venue {slug!r}: country_code must be ISO 3166-1 alpha-2")

        result[slug] = VenueConfig(
            slug=slug,
            name=entry["name"],
            country_code=country.upper(),
            iana_timezone=tz_name,
            city=entry.get("city"),
            latitude=entry.get("latitude"),
            longitude=entry.get("longitude"),
        )

    if not result:
        raise ConfigError("venues.toml defined no venues")
    return result
