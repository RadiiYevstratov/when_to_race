"""Postgres implementation of the Repository protocol.

Raw SQL on purpose: db/migrations is the single source of truth for the schema,
and an ORM on the writer side would quietly become a second one. psycopg is
imported lazily so the rest of the package stays runnable without a driver.

Everything a run touches happens in one transaction. If the guard trips or a
constraint fires, nothing is written - reliability rule 1 depends on that.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .records import NormalizedEvent
from .repository import AppliedCounts
from .sync import ExistingSession, SyncPlan


class PostgresRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._connection: Optional[Any] = None

    # --- connection -------------------------------------------------------
    def _connect(self):
        if self._connection is None or getattr(self._connection, "closed", False):
            import psycopg  # lazy: only needed when actually writing

            self._connection = psycopg.connect(self.database_url, autocommit=False)
        return self._connection

    def close(self) -> None:
        if self._connection is not None and not getattr(self._connection, "closed", False):
            self._connection.close()
        self._connection = None

    def _series_id(self, cursor, series_code: str) -> int:
        cursor.execute("SELECT id FROM series WHERE code = %s", (series_code,))
        row = cursor.fetchone()
        if row is None:
            raise LookupError(f"series {series_code!r} is not seeded; run db/seed.py")
        return row[0]

    def _category_ids(self, cursor, series_id: int) -> dict[str, int]:
        cursor.execute("SELECT code, id FROM categories WHERE series_id = %s", (series_id,))
        return {code: category_id for code, category_id in cursor.fetchall()}

    def _venue_ids(self, cursor) -> dict[str, int]:
        cursor.execute("SELECT slug, id FROM venues")
        return {slug: venue_id for slug, venue_id in cursor.fetchall()}

    # --- reads ------------------------------------------------------------
    def load_existing_sessions(self, series_code: str, season: int) -> list[ExistingSession]:
        connection = self._connect()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT s.id, e.slug, c.code, s.session_type::text, s.sequence,
                       s.display_name, s.starts_at_utc, s.ends_at_utc,
                       s.scheduled_duration_minutes, s.time_status::text,
                       s.starts_at_precision::text, s.status::text, s.iana_timezone,
                       s.source_url, s.ics_sequence, s.retired_at
                  FROM sessions s
                  JOIN events e ON e.id = s.event_id
                  JOIN categories c ON c.id = s.category_id
                  JOIN series sr ON sr.id = e.series_id
                 WHERE sr.code = %s AND e.season = %s
                """,
                (series_code, season),
            )
            return [
                ExistingSession(
                    id=row[0],
                    event_slug=row[1],
                    category_code=row[2],
                    session_type=row[3],
                    sequence=row[4],
                    display_name=row[5],
                    start_utc=row[6],
                    end_utc=row[7],
                    scheduled_duration_minutes=row[8],
                    time_status=row[9],
                    start_precision=row[10],
                    status=row[11],
                    iana_timezone=row[12],
                    source_url=row[13],
                    ics_sequence=row[14],
                    retired_at=row[15],
                )
                for row in cursor.fetchall()
            ]

    # --- run logging ------------------------------------------------------
    def start_run(self, series_code: str) -> int:
        connection = self._connect()
        with connection.cursor() as cursor:
            series_id = self._series_id(cursor, series_code)
            cursor.execute(
                "INSERT INTO scrape_runs (series_id, status) VALUES (%s, 'running') RETURNING id",
                (series_id,),
            )
            run_id = cursor.fetchone()[0]
        connection.commit()  # the run row must survive a later rollback
        return run_id

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        records_found: int,
        records_changed: int,
        error_message: Optional[str] = None,
    ) -> None:
        connection = self._connect()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE scrape_runs
                   SET status = %s, finished_at = now(), records_found = %s,
                       records_changed = %s, error_message = %s
                 WHERE id = %s
                """,
                (status, records_found, records_changed, error_message, run_id),
            )
        connection.commit()

    def record_snapshots(self, run_id: int, snapshots) -> None:
        connection = self._connect()
        with connection.cursor() as cursor:
            for snapshot in snapshots:
                cursor.execute(
                    """
                    INSERT INTO scrape_snapshots
                        (scrape_run_id, url, content_hash, content_type, byte_size, storage_path)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        snapshot.url,
                        snapshot.content_hash,
                        snapshot.content_type,
                        snapshot.byte_size,
                        snapshot.storage_path,
                    ),
                )
        connection.commit()

    # --- writes -----------------------------------------------------------
    def _upsert_event(self, cursor, series_id: int, venue_ids: dict[str, int], event: NormalizedEvent) -> int:
        if event.venue_slug not in venue_ids:
            raise LookupError(f"venue {event.venue_slug!r} is not seeded; run db/seed.py")
        cursor.execute(
            """
            INSERT INTO events (series_id, season, round_number, slug, name, official_name,
                                venue_id, starts_at_utc, ends_at_utc, detail_level,
                                source_url, last_seen_at, retired_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), NULL)
            ON CONFLICT (series_id, season, slug) DO UPDATE
               SET round_number = EXCLUDED.round_number,
                   name = EXCLUDED.name,
                   official_name = EXCLUDED.official_name,
                   venue_id = EXCLUDED.venue_id,
                   starts_at_utc = EXCLUDED.starts_at_utc,
                   ends_at_utc = EXCLUDED.ends_at_utc,
                   detail_level = EXCLUDED.detail_level,
                   source_url = EXCLUDED.source_url,
                   last_seen_at = now(),
                   retired_at = NULL,
                   updated_at = now()
            RETURNING id
            """,
            (
                series_id,
                event.season,
                event.round_number,
                event.slug,
                event.name,
                event.official_name,
                venue_ids[event.venue_slug],
                event.starts_at_utc,
                event.ends_at_utc,
                event.detail_level,
                event.source_url,
            ),
        )
        return cursor.fetchone()[0]

    def apply(self, plan: SyncPlan, series_code: str, season: int, run_id: int) -> AppliedCounts:
        connection = self._connect()
        counts = AppliedCounts()
        try:
            with connection.cursor() as cursor:
                series_id = self._series_id(cursor, series_code)
                category_ids = self._category_ids(cursor, series_id)
                venue_ids = self._venue_ids(cursor)

                event_ids: dict[str, int] = {}
                for event in plan.events:
                    event_ids[event.slug] = self._upsert_event(cursor, series_id, venue_ids, event)

                for session in plan.creates:
                    if session.category_code not in category_ids:
                        raise LookupError(
                            f"category {session.category_code!r} is not seeded for {series_code}"
                        )
                    cursor.execute(
                        """
                        INSERT INTO sessions
                            (event_id, category_id, session_type, display_name, sequence,
                             starts_at_utc, ends_at_utc, scheduled_duration_minutes,
                             time_status, starts_at_precision, iana_timezone, ics_uid,
                             source_url, last_seen_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                        ON CONFLICT (event_id, category_id, session_type, sequence) DO UPDATE
                           SET display_name = EXCLUDED.display_name,
                               starts_at_utc = EXCLUDED.starts_at_utc,
                               ends_at_utc = EXCLUDED.ends_at_utc,
                               last_seen_at = now(),
                               retired_at = NULL,
                               updated_at = now()
                        """,
                        (
                            event_ids[session.event_slug],
                            category_ids[session.category_code],
                            session.session_type,
                            session.display_name,
                            session.sequence,
                            session.start_utc,
                            session.end_utc,
                            session.scheduled_duration_minutes,
                            session.time_status,
                            session.start_precision,
                            session.iana_timezone,
                            session.ics_uid,
                            session.source_url,
                        ),
                    )
                    counts.created += 1

                for update in plan.updates:
                    for change in update.changes:
                        cursor.execute(
                            """
                            INSERT INTO schedule_changes
                                (session_id, series_id, scrape_run_id, field_changed,
                                 old_value, new_value)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (
                                update.existing_id,
                                series_id,
                                run_id,
                                change.field_changed,
                                change.old_value,
                                change.new_value,
                            ),
                        )
                        counts.changes_logged += 1

                    incoming = update.incoming
                    cursor.execute(
                        """
                        UPDATE sessions
                           SET display_name = %s,
                               starts_at_utc = %s,
                               ends_at_utc = %s,
                               scheduled_duration_minutes = %s,
                               time_status = %s,
                               starts_at_precision = %s,
                               iana_timezone = %s,
                               source_url = %s,
                               ics_sequence = ics_sequence + %s,
                               last_seen_at = now(),
                               retired_at = NULL,
                               updated_at = now()
                         WHERE id = %s
                        """,
                        (
                            incoming.display_name,
                            incoming.start_utc,
                            incoming.end_utc,
                            incoming.scheduled_duration_minutes,
                            incoming.time_status,
                            incoming.start_precision,
                            incoming.iana_timezone,
                            incoming.source_url,
                            1 if update.bumps_ics_sequence else 0,
                            update.existing_id,
                        ),
                    )
                    counts.updated += 1

                for item in plan.retire:
                    # Soft delete. Rule 1 forbids destructive sync, and a session
                    # that vanishes from a feed is usually a parser problem.
                    cursor.execute(
                        "UPDATE sessions SET retired_at = now(), updated_at = now() WHERE id = %s",
                        (item.id,),
                    )
                    cursor.execute(
                        """
                        INSERT INTO schedule_changes
                            (session_id, series_id, scrape_run_id, field_changed, old_value, new_value)
                        VALUES (%s, %s, %s, 'retired', 'active', 'retired')
                        """,
                        (item.id, series_id, run_id),
                    )
                    counts.retired += 1
                    counts.changes_logged += 1

                updated_ids = {update.existing_id for update in plan.updates}
                for item in plan.revive:
                    if item.id in updated_ids:
                        continue  # the UPDATE above already cleared retired_at
                    cursor.execute(
                        "UPDATE sessions SET retired_at = NULL, updated_at = now() WHERE id = %s",
                        (item.id,),
                    )
                    counts.revived += 1

            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return counts

    def mark_series_scraped(self, series_code: str, when: datetime) -> None:
        connection = self._connect()
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE series SET last_successful_scrape = %s, updated_at = now() WHERE code = %s",
                (when.astimezone(timezone.utc), series_code),
            )
        connection.commit()
