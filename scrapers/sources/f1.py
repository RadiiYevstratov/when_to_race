"""Formula 1, including F2, F3 and F1 Academy.

All four categories share a race weekend and must land on the same `event`, so
this source emits them from one feed with different category codes. That is what
makes the unified weekend view possible.

Discovery status: UNVERIFIED. No endpoint has been confirmed - see
docs/sources.md#formula-1 for the procedure and for what to record. Set
`source.url` and `source.status = "live"` in config/series.toml once it is done.
The parsing below is exercised against scrapers/fixtures/f1_sample.ics, so the
shape it expects is explicit and checkable rather than assumed.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from ..config import SeriesConfig
from ..ics import IcsEvent
from .base import register
from .ics_source import IcsSource

# Ordered: "F1 ACADEMY" must be tested before "F1", or Academy sessions land in
# the F1 category and silently double the Grand Prix schedule.
_CATEGORY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(f1\s*academy|formula\s*1\s*academy)\b", re.IGNORECASE), "f1a"),
    (re.compile(r"\b(formula\s*3|f3)\b", re.IGNORECASE), "f3"),
    (re.compile(r"\b(formula\s*2|f2)\b", re.IGNORECASE), "f2"),
    (re.compile(r"\b(formula\s*(1|one)|f1|grand\s*prix|gran\s*premio|gp)\b", re.IGNORECASE), "f1"),
)

_CATEGORY_PREFIX = re.compile(
    r"^\s*(fia\s+)?(f1\s*academy|formula\s*1\s*academy|formula\s*3|formula\s*2|"
    r"formula\s*(1|one)|f3|f2|f1)\b[\s:–—-]*",
    re.IGNORECASE,
)

# Sponsor noise that appears in official event titles. Removed from `name`,
# preserved in `official_name`.
_SPONSOR_NOISE = re.compile(
    r"\b(pirelli|rolex|heineken|aramco|qatar\s+airways|msc\s+cruises|lenovo|"
    r"louis\s+vuitton|stc|gulf\s+air|crypto\.com|aws)\b",
    re.IGNORECASE,
)


def strip_decoration(value: str) -> str:
    """Remove emoji and other pictographs from a feed's display strings.

    Some feeds decorate every entry - flags on the event, a wrench on practice,
    a chequered flag on the race. Useful in a calendar app, noise in a database:
    it would end up in display_name, in the slug, and in the calendar UID.
    Category "So" covers pictographs and regional-indicator flag letters;
    "Cf" and the variation selectors cover the invisible modifiers that follow
    them.
    """
    cleaned = "".join(
        char
        for char in value
        if unicodedata.category(char) not in ("So", "Cf") and char not in ("\ufe0f", "\ufe0e")
    )
    return re.sub(r"\s{2,}", " ", cleaned).strip()


class FormulaOneSource(IcsSource):
    series_code = "f1"

    # Free-text locations from the source mapped onto the venue registry.
    # Site-specific knowledge belongs here, never in normalize.
    venue_aliases = {
        "bahrain": "sakhir",
        "sakhir": "sakhir",
        "saudi arabia": "jeddah",
        "jeddah": "jeddah",
        "australia": "melbourne",
        "albert park": "melbourne",
        "melbourne": "melbourne",
        "japan": "suzuka",
        "suzuka": "suzuka",
        "china": "shanghai",
        "shanghai": "shanghai",
        "miami": "miami",
        "emilia-romagna": "imola",
        "emilia romagna": "imola",
        "imola": "imola",
        "monaco": "monaco",
        "monte carlo": "monaco",
        "canada": "montreal",
        "montreal": "montreal",
        "barcelona": "barcelona",
        "catalunya": "barcelona",
        # Spain has two rounds from 2026: Barcelona and the new Madrid circuit.
        # "spain" alone is ambiguous, so it is deliberately not an alias.
        "madrid": "madrid",
        "madring": "madrid",
        "austria": "red_bull_ring",
        "spielberg": "red_bull_ring",
        "great britain": "silverstone",
        "british": "silverstone",
        "silverstone": "silverstone",
        "hungary": "hungaroring",
        "budapest": "hungaroring",
        "belgium": "spa",
        "spa-francorchamps": "spa",
        "netherlands": "zandvoort",
        "zandvoort": "zandvoort",
        "italy": "monza",
        "italia": "monza",
        "monza": "monza",
        "azerbaijan": "baku",
        "baku": "baku",
        "singapore": "singapore",
        "united states": "cota",
        "austin": "cota",
        "circuit of the americas": "cota",
        "mexico": "mexico_city",
        "brazil": "interlagos",
        "sao paulo": "interlagos",
        "são paulo": "interlagos",
        "interlagos": "interlagos",
        "las vegas": "las_vegas",
        "qatar": "lusail",
        "lusail": "lusail",
        "abu dhabi": "yas_marina",
        "yas marina": "yas_marina",
    }

    def category_for(self, summary: str, series: SeriesConfig) -> Optional[str]:
        for pattern, code in _CATEGORY_PATTERNS:
            if pattern.search(summary):
                return code
        # An entry we cannot attribute is dropped rather than guessed into F1.
        return None

    def split_summary(self, summary: str) -> tuple[str, str]:
        text = strip_decoration(summary)
        for separator in (" - ", " – ", " — ", ": "):
            if separator in text:
                head, _, tail = text.rpartition(separator)
                return head.strip(), tail.strip()
        return text, text

    def clean_event_name(self, event_name: str, season: int) -> str:
        text = _CATEGORY_PREFIX.sub("", strip_decoration(event_name))
        text = _SPONSOR_NOISE.sub("", text)
        text = text.replace(str(season), "")
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip(" -–—:")

    def round_for(self, event: IcsEvent) -> Optional[int]:
        for field in (event.get("DESCRIPTION", ""), event.summary):
            match = re.search(r"\bround\s*(\d{1,2})\b", field or "", re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    def skip(self, event: IcsEvent) -> bool:
        if not event.summary.strip():
            return True
        summary = event.summary.lower()
        # Feeds routinely carry non-session entries. Keeping them would inflate
        # session counts and defeat the validation floor.
        return any(word in summary for word in ("tickets", "fan zone", "concert", "paddock club"))


@register("f1")
def build(feed_url: Optional[str] = None) -> FormulaOneSource:
    return FormulaOneSource(feed_url=feed_url)