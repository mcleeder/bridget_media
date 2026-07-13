from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from db.database import Database, DatabaseError
from db.models import Episode, Feed, QueueEntry


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _fmt_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


class FeedRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, name: str, url: str) -> Feed:
        try:
            self._db.connection.execute(
                "INSERT INTO feeds (name, url) VALUES (?, ?)"
                " ON CONFLICT(url) DO UPDATE SET name = excluded.name",
                (name, url),
            )
            self._db.connection.commit()
            row = self._db.connection.execute(
                "SELECT id, name, url, last_fetched FROM feeds WHERE url = ?",
                (url,),
            ).fetchone()
            return _row_to_feed(row)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to upsert feed '{url}'") from exc

    def get_all(self) -> list[Feed]:
        try:
            rows = self._db.connection.execute(
                "SELECT id, name, url, last_fetched FROM feeds ORDER BY name"
            ).fetchall()
            return [_row_to_feed(r) for r in rows]
        except sqlite3.Error as exc:
            raise DatabaseError("Failed to fetch feeds") from exc

    def get_by_id(self, feed_id: int) -> Feed | None:
        try:
            row = self._db.connection.execute(
                "SELECT id, name, url, last_fetched FROM feeds WHERE id = ?",
                (feed_id,),
            ).fetchone()
            return _row_to_feed(row) if row is not None else None
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to fetch feed {feed_id}") from exc

    def update_last_fetched(self, feed_id: int, when: datetime) -> None:
        try:
            self._db.connection.execute(
                "UPDATE feeds SET last_fetched = ? WHERE id = ?",
                (_fmt_dt(when), feed_id),
            )
            self._db.connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to update last_fetched for feed {feed_id}") from exc

    def delete(self, feed_id: int) -> None:
        # No ON DELETE CASCADE is declared on episodes/queue, and foreign_keys
        # is ON, so referencing rows must be removed explicitly first.
        try:
            self._db.connection.execute(
                "DELETE FROM queue WHERE episode_id IN"
                " (SELECT id FROM episodes WHERE feed_id = ?)",
                (feed_id,),
            )
            self._db.connection.execute("DELETE FROM episodes WHERE feed_id = ?", (feed_id,))
            self._db.connection.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
            self._db.connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to delete feed {feed_id}") from exc


class EpisodeRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(
        self,
        feed_id: int,
        title: str,
        audio_url: str,
        published_at: datetime | None = None,
        duration_sec: int | None = None,
    ) -> Episode:
        try:
            self._db.connection.execute(
                """
                INSERT INTO episodes (feed_id, title, audio_url, published_at, duration_sec)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(feed_id, audio_url) DO UPDATE SET
                    title        = excluded.title,
                    published_at = excluded.published_at,
                    duration_sec = excluded.duration_sec
                """,
                (feed_id, title, audio_url, _fmt_dt(published_at), duration_sec),
            )
            self._db.connection.commit()
            row = self._db.connection.execute(
                "SELECT * FROM episodes WHERE feed_id = ? AND audio_url = ?",
                (feed_id, audio_url),
            ).fetchone()
            return _row_to_episode(row)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to upsert episode '{audio_url}'") from exc

    def get_for_feed(self, feed_id: int) -> list[Episode]:
        try:
            rows = self._db.connection.execute(
                "SELECT * FROM episodes WHERE feed_id = ? ORDER BY published_at DESC",
                (feed_id,),
            ).fetchall()
            return [_row_to_episode(r) for r in rows]
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to fetch episodes for feed {feed_id}") from exc

    def mark_played(self, episode_id: int) -> None:
        try:
            self._db.connection.execute(
                "UPDATE episodes SET played = 1 WHERE id = ?",
                (episode_id,),
            )
            self._db.connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to mark episode {episode_id} as played") from exc

    def update_play_position(self, episode_id: int, position_sec: int) -> None:
        try:
            self._db.connection.execute(
                "UPDATE episodes SET play_position_sec = ? WHERE id = ?",
                (position_sec, episode_id),
            )
            self._db.connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(
                f"Failed to update play position for episode {episode_id}"
            ) from exc


class QueueRepository:
    """FIFO episode queue. Entries are removed when an episode finishes, not when it starts."""

    _SELECT_ENTRIES = """
        SELECT q.id AS queue_id, q.added_at, f.name AS feed_name, e.*
        FROM queue q
        JOIN episodes e ON e.id = q.episode_id
        JOIN feeds f ON f.id = e.feed_id
        ORDER BY q.id
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, episode_id: int) -> None:
        try:
            # OR IGNORE: queueing an already-queued episode is a harmless no-op
            self._db.connection.execute(
                "INSERT OR IGNORE INTO queue (episode_id, added_at) VALUES (?, ?)",
                (episode_id, _fmt_dt(datetime.now(UTC))),
            )
            self._db.connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to queue episode {episode_id}") from exc

    def remove(self, episode_id: int) -> None:
        try:
            self._db.connection.execute(
                "DELETE FROM queue WHERE episode_id = ?",
                (episode_id,),
            )
            self._db.connection.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to unqueue episode {episode_id}") from exc

    def get_entries(self) -> list[QueueEntry]:
        try:
            rows = self._db.connection.execute(self._SELECT_ENTRIES).fetchall()
            return [_row_to_queue_entry(r) for r in rows]
        except sqlite3.Error as exc:
            raise DatabaseError("Failed to fetch queue entries") from exc

    def first_entry(self) -> QueueEntry | None:
        try:
            row = self._db.connection.execute(self._SELECT_ENTRIES + " LIMIT 1").fetchone()
            return _row_to_queue_entry(row) if row is not None else None
        except sqlite3.Error as exc:
            raise DatabaseError("Failed to fetch queue head") from exc

    def queued_episode_ids(self) -> set[int]:
        try:
            rows = self._db.connection.execute("SELECT episode_id FROM queue").fetchall()
            return {row["episode_id"] for row in rows}
        except sqlite3.Error as exc:
            raise DatabaseError("Failed to fetch queued episode ids") from exc


def _row_to_feed(row: sqlite3.Row) -> Feed:
    return Feed(
        id=row["id"],
        name=row["name"],
        url=row["url"],
        last_fetched=_parse_dt(row["last_fetched"]),
    )


def _row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=row["id"],
        feed_id=row["feed_id"],
        title=row["title"],
        audio_url=row["audio_url"],
        published_at=_parse_dt(row["published_at"]),
        duration_sec=row["duration_sec"],
        played=bool(row["played"]),
        play_position_sec=row["play_position_sec"],
    )


def _row_to_queue_entry(row: sqlite3.Row) -> QueueEntry:
    return QueueEntry(
        id=row["queue_id"],
        episode=_row_to_episode(row),
        feed_name=row["feed_name"],
        added_at=datetime.fromisoformat(row["added_at"]).replace(tzinfo=UTC),
    )
