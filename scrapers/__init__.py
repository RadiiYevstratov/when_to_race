"""Motorsport schedule scrapers.

Stage boundaries, in order: fetch (http.py) -> snapshot (snapshots.py) ->
parse (sources/) -> normalize (normalize.py) -> validate (validate.py) ->
upsert (sync.py plans it, repository.py / db.py execute it).
"""

__version__ = "0.1.0"
