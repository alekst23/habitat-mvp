"""SQLite connection and unit of work (technical.md Conventions, owner E11-1)."""

from __future__ import annotations

from contextlib import contextmanager
from sqlite3 import Connection
from typing import Iterator


class Database:
    """Owns the SQLite file (WAL, busy_timeout 5000, foreign keys on) and forward-only migrations."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def migrate(self) -> None:
        raise NotImplementedError("Database.migrate is not implemented (E11-1)")

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """One BEGIN IMMEDIATE transaction; commit on success, roll back on error; lock timeout is
        AiclError('unavailable')."""
        raise NotImplementedError("Database.transaction is not implemented (E11-1)")
        yield  # pragma: no cover  (makes this a generator function for typing)
