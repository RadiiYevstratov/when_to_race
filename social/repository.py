"""Reading the schedule, and remembering what was said about it.

The only module in the package that knows Postgres exists. Selection stays a
pure function of records so a season can be replayed in memory; this is where
those records come from.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Optional, Sequence

from .selection import EventFact, PostRecord, SessionFact


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. The social job reads the same database the "
            "scrapers write to."
        )
    return url


def connect():
    import psycopg  # imported here so selection stays importable without a driver

    return psycopg.connect(database_url())


# --------------------------------------------------------------------------
# the schedule
# --------------------------------------------------------------------------

_EVENTS_SQL = """
select e.id, s.code, s.short_name, e.season, e.slug, e.name,
       v.name, v.city, v.country_code, v.iana_timezone,
       e.starts_at_utc, e.ends_at_utc
from events e
join series s on s.id = e.series_id
join venues v on v.id = e.venue_id
where e.retired_at is null
  and s.is_active
  and e.ends_at_utc >= %(from)s
  and e.starts_at_utc <= %(to)s
order by e.starts_at_utc
"""

_SESSIONS_SQL = """
select x.event_id, x.id, x.session_type, x.display_name, x.starts_at_utc,
       c.code, c.short_name, c.is_headline
from sessions x
join categories c on c.id = x.category_id
where x.retired_at is null
  and x.event_id = any(%(ids)s)
order by x.starts_at_utc, c.sort_order, x.sequence
"""


def load_events(connection, window_from: datetime, window_to: datetime) -> list[EventFact]:
    """Every event overlapping the window, with its sessions attached.

    Two queries rather than one join: a weekend can carry seventeen sessions and
    fanning the event columns out across all of them, then de-duplicating in
    Python, is more code and more rows for no gain.
    """
    with connection.cursor() as cursor:
        cursor.execute(_EVENTS_SQL, {"from": window_from, "to": window_to})
        rows = cursor.fetchall()
        if not rows:
            return []

        events = {
            row[0]: {
                "event_id": row[0],
                "series_code": row[1],
                "series_short_name": row[2],
                "season": row[3],
                "slug": row[4],
                "name": row[5],
                "venue_name": row[6],
                "venue_city": row[7],
                "venue_country": row[8],
                "venue_timezone": row[9],
                "starts_at_utc": row[10],
                "ends_at_utc": row[11],
                "sessions": [],
            }
            for row in rows
        }

        cursor.execute(_SESSIONS_SQL, {"ids": list(events)})
        for event_id, sid, stype, name, starts, ccode, cshort, headline in cursor.fetchall():
            events[event_id]["sessions"].append(
                SessionFact(
                    session_id=sid,
                    session_type=stype,
                    display_name=name,
                    starts_at_utc=starts,
                    category_code=ccode,
                    category_short_name=cshort,
                    is_headline_class=headline,
                )
            )

    return [
        EventFact(**{**data, "sessions": tuple(data["sessions"])})
        for data in events.values()
    ]


# --------------------------------------------------------------------------
# the history
# --------------------------------------------------------------------------


def load_history(connection, since: datetime) -> list[PostRecord]:
    """Recent decisions, for the rules that stop the account repeating itself.

    Skipped days are excluded: staying quiet about an event is not the same as
    having covered it, and counting it would suppress the post it was waiting
    for.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select decided_at, event_id, session_id, series_code, post_kind
            from social_posts
            where decided_at >= %s and outcome in ('published', 'dry_run')
            order by decided_at
            """,
            (since,),
        )
        return [PostRecord(*row) for row in cursor.fetchall()]


def record(
    connection,
    *,
    decided_for: date,
    outcome: str,
    post_kind: Optional[str] = None,
    event_id: Optional[int] = None,
    session_id: Optional[int] = None,
    series_code: Optional[str] = None,
    category_code: Optional[str] = None,
    event_name: Optional[str] = None,
    session_type: Optional[str] = None,
    session_starts_at_utc: Optional[datetime] = None,
    score: Optional[int] = None,
    reasons: Optional[Sequence[str]] = None,
    caption: Optional[str] = None,
    hashtags: Optional[Sequence[str]] = None,
    media_path: Optional[str] = None,
    media_url: Optional[str] = None,
    instagram_post_id: Optional[str] = None,
    error_message: Optional[str] = None,
) -> int:
    """Write the decision down, whatever it was."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into social_posts (
                decided_for, outcome, post_kind, event_id, session_id, series_code,
                category_code, event_name, session_type, session_starts_at_utc,
                score, reasons, caption, hashtags, media_path, media_url,
                instagram_post_id, error_message
            ) values (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s
            ) returning id
            """,
            (
                decided_for, outcome, post_kind, event_id, session_id, series_code,
                category_code, event_name, session_type, session_starts_at_utc,
                score, json.dumps(list(reasons)) if reasons else None,
                caption, list(hashtags) if hashtags else None, media_path, media_url,
                instagram_post_id, error_message,
            ),
        )
        new_id = cursor.fetchone()[0]
    connection.commit()
    return new_id


def already_published(connection, day: date) -> bool:
    """Has a live post already gone out for this local day?"""
    with connection.cursor() as cursor:
        cursor.execute(
            "select 1 from social_posts where decided_for = %s and outcome = 'published'",
            (day,),
        )
        return cursor.fetchone() is not None
