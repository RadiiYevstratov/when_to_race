"""Raw response storage.

When a parser breaks you need the exact input that broke it, so every fetched
body is written to disk before anything tries to understand it. Keeps the last
30 runs per series and prunes the rest.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "snapshots"
RUNS_KEPT_PER_SERIES = 30

_MIME_EXTENSIONS = {
    "text/calendar": "ics",
    "application/json": "json",
    "text/html": "html",
    "application/xml": "xml",
    "text/xml": "xml",
}


@dataclass
class SnapshotRecord:
    url: str
    content_hash: str
    content_type: Optional[str]
    byte_size: int
    storage_path: str
    fetched_at: str


def content_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)[:80]


class SnapshotStore:
    def __init__(self, root: Optional[Path] = None, runs_kept: int = RUNS_KEPT_PER_SERIES):
        self.root = Path(root) if root else DEFAULT_ROOT
        self.runs_kept = runs_kept

    def run_dir(self, series_code: str, run_started: datetime) -> Path:
        stamp = run_started.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return self.root / _safe(series_code) / stamp

    def write(
        self,
        series_code: str,
        run_started: datetime,
        url: str,
        body: bytes,
        content_type: Optional[str] = None,
    ) -> SnapshotRecord:
        digest = content_hash(body)
        extension = _MIME_EXTENSIONS.get((content_type or "").split(";")[0].strip(), "txt")
        directory = self.run_dir(series_code, run_started)
        directory.mkdir(parents=True, exist_ok=True)

        path = directory / f"{digest[:16]}.{extension}"
        path.write_bytes(body)

        record = SnapshotRecord(
            url=url,
            content_hash=digest,
            content_type=content_type,
            byte_size=len(body),
            storage_path=str(path),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        index = directory / "index.json"
        entries = json.loads(index.read_text()) if index.exists() else []
        entries.append(asdict(record))
        index.write_text(json.dumps(entries, indent=2))
        return record

    def prune(self, series_code: str) -> list[Path]:
        """Drop all but the most recent runs. Returns what was removed."""
        series_dir = self.root / _safe(series_code)
        if not series_dir.exists():
            return []
        runs = sorted((path for path in series_dir.iterdir() if path.is_dir()), key=lambda p: p.name)
        removed: list[Path] = []
        for stale in runs[: max(0, len(runs) - self.runs_kept)]:
            for child in sorted(stale.rglob("*"), reverse=True):
                child.unlink() if child.is_file() else child.rmdir()
            stale.rmdir()
            removed.append(stale)
        return removed
