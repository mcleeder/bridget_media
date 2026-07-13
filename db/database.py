from __future__ import annotations

import sqlite3
from pathlib import Path


class DatabaseError(Exception):
    pass


_SCHEMA = """
CREATE TABLE IF NOT EXISTS feeds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    url          TEXT    NOT NULL UNIQUE,
    last_fetched TEXT
);

CREATE TABLE IF NOT EXISTS episodes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id           INTEGER NOT NULL REFERENCES feeds(id),
    title             TEXT    NOT NULL,
    audio_url         TEXT    NOT NULL,
    published_at      TEXT,
    duration_sec      INTEGER,
    played            INTEGER NOT NULL DEFAULT 0,
    play_position_sec INTEGER NOT NULL DEFAULT 0,
    UNIQUE(feed_id, audio_url)
);

CREATE TABLE IF NOT EXISTS queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL UNIQUE REFERENCES episodes(id),
    added_at   TEXT    NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        try:
            self._conn = sqlite3.connect(
                str(path),
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._init_schema()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to open database at {path}") from exc

    def _init_schema(self) -> None:
        try:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise DatabaseError("Failed to initialise schema") from exc

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
