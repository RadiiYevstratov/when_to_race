"""Fixture source.

Milestone 2 needs the whole pipeline provable before a single real endpoint
exists. This source reads committed files from scrapers/fixtures/ instead of the
network, so `python -m scrapers.run --series f1 --source fixture` exercises
fetch -> snapshot -> parse -> normalize -> validate -> upsert end to end.

It is also what the parser tests run against: a stored snapshot is the only
thing that catches a site redesign before users do.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import register
from .f1 import FormulaOneSource

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"

FIXTURE_SCHEME = "fixture://"


class FixtureF1Source(FormulaOneSource):
    """F1 parsing, fixture input."""

    def __init__(self, fixture_name: str = "f1_sample.ics"):
        super().__init__(feed_url=None)
        self.fixture_name = fixture_name

    def urls(self, season: int) -> list[str]:
        return [f"{FIXTURE_SCHEME}{self.fixture_name}"]


def read_fixture(url: str) -> bytes:
    """Resolve a fixture:// URL against the fixtures directory."""
    if not url.startswith(FIXTURE_SCHEME):
        raise ValueError(f"not a fixture URL: {url}")
    name = url[len(FIXTURE_SCHEME) :]
    path = FIXTURE_DIR / name
    if not path.is_file():
        available = ", ".join(sorted(p.name for p in FIXTURE_DIR.glob("*"))) or "none"
        raise FileNotFoundError(f"fixture {name!r} not found; available: {available}")
    return path.read_bytes()


@register("fixture")
def build(fixture_name: Optional[str] = None) -> FixtureF1Source:
    return FixtureF1Source(fixture_name=fixture_name or "f1_sample.ics")
