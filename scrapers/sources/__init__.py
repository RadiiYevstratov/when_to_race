"""Source adapters.

Importing this package registers every adapter. Adding a championship means
adding a module here and an entry in config/series.toml - no schema change and
no frontend change.

Series still awaiting discovery (wrc, imsa) deliberately have no module yet. The runner reports them as unimplemented rather
than pretending to scrape, which keeps `--series all` honest. MotoGP has a module
but is held at status = "unverified" pending a Terms-of-Use decision (see
docs/sources.md#motogp), so the runner still refuses it without --allow-unverified.
"""

from . import f1, fixture, indycar, motogp, nascar, wec, wsbk  # noqa: F401  - imported for the register() side effect
from .base import (  # noqa: F401
    FetchedDocument,
    Source,
    get_source,
    register,
    registered_adapters,
    resolve_venue,
)

__all__ = [
    "FetchedDocument",
    "Source",
    "get_source",
    "register",
    "registered_adapters",
    "resolve_venue",
]
