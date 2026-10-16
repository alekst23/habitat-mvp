"""SQLite connection and unit of work (technical.md Conventions, owner E11-1)."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection
from typing import Iterator

from aicl.control.errors import AiclError

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def to_iso(value: datetime) -> str:
    """Fixed-width UTC text, so string comparison orders instants."""
    return value.astimezone(timezone.utc).strftime(_TIME_FORMAT)


def from_iso(text: str) -> datetime:
    return datetime.strptime(text, _TIME_FORMAT).replace(tzinfo=timezone.utc) if "." in text else \
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Database:
    """Owns the SQLite file (WAL, busy_timeout 5000, foreign keys on) and forward-only migrations.

    One connection per outermost `transaction()` per thread; a nested call on the same thread joins it
    through a SAVEPOINT. The most recently migrated Database is the process default used by repositories
    constructed without a handle (the committed tests build them with no arguments).
    """

    _default: "Database | None" = None

    def __init__(self, database_url: str) -> None:
        if not database_url.startswith("sqlite:///") or len(database_url) <= len("sqlite:///"):
            raise ValueError("AICL_DATABASE_URL: only sqlite:///path is supported")
        self.database_url = database_url
        self.path = database_url[len("sqlite:///"):]
        self._local = threading.local()

    @classmethod
    def current(cls) -> "Database":
        if cls._default is None:
            raise AiclError("unavailable", "no database has been migrated")
        return cls._default

    def _connect(self) -> Connection:
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def migrate(self) -> None:
        Path(self.path).resolve().parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migration "
                         "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
            applied = {r[0] for r in conn.execute("SELECT version FROM schema_migration")}
            for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if sql_file.stem in applied:
                    continue
                script = (f"BEGIN IMMEDIATE;\n{sql_file.read_text()}\n"
                          f"INSERT INTO schema_migration (version, applied_at) "
                          f"VALUES ('{sql_file.stem}', '{to_iso(datetime.now(timezone.utc))}');\nCOMMIT;")
                try:
                    conn.executescript(script)
                except BaseException:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
        finally:
            conn.close()
        Database._default = self

    @contextmanager
    def reader(self) -> Iterator[Connection]:
        """A connection for reads: the open unit of work on this thread, else a short-lived one."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            yield conn
            return
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """One BEGIN IMMEDIATE transaction; commit on success, roll back on error; lock timeout is
        AiclError('unavailable'). An exception with `commit_on_error` True still commits (a durable
        audit record of a refused operation) before propagating."""
        outer = getattr(self._local, "conn", None)
        if outer is not None:
            depth = self._local.depth
            name = f"aicl_sp_{depth}"
            self._local.depth = depth + 1
            outer.execute(f"SAVEPOINT {name}")
            try:
                yield outer
            except BaseException as exc:
                if not getattr(exc, "commit_on_error", False):
                    outer.execute(f"ROLLBACK TO {name}")
                outer.execute(f"RELEASE {name}")
                raise
            else:
                outer.execute(f"RELEASE {name}")
            finally:
                self._local.depth = depth
            return
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            conn.close()
            raise AiclError("unavailable", "database is locked") from exc
        self._local.conn, self._local.depth = conn, 0
        try:
            yield conn
        except BaseException as exc:
            if getattr(exc, "commit_on_error", False):
                conn.execute("COMMIT")
            else:
                conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
        finally:
            self._local.conn = None
            conn.close()


class LazyDatabase:
    """Proxy resolving the process-default Database at use (ports are built before any unit of work)."""

    def __getattr__(self, name: str):
        return getattr(Database.current(), name)
