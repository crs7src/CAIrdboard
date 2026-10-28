"""SQLite storage shared by every per-card store (plans, runs, feedback, test settings)."""

import re
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel

CARD_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    kind TEXT NOT NULL,
    card_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    state TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, card_key, version)
);
CREATE TABLE IF NOT EXISTS comments (
    card_key TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (card_key, id)
);
CREATE TABLE IF NOT EXISTS test_configs (
    project TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_approvals (
    card_key TEXT PRIMARY KEY,
    approved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS archived_cards (
    card_key TEXT PRIMARY KEY,
    archived_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jira_projects (
    project_key TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gitlab_projects (
    project TEXT PRIMARY KEY,
    path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS github_projects (
    project TEXT PRIMARY KEY,
    path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS github_issue_repos (
    slug TEXT PRIMARY KEY,
    path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

SCHEMA_VERSION = "1"


def now() -> str:
    return datetime.now(UTC).isoformat()


def check_key(key: str) -> str:
    if not CARD_KEY_RE.match(key):
        raise ValueError(f"Invalid card key: {key}")
    return key


class Database:
    """A SQLite file. Each call uses its own short-lived connection, so it is safe to
    use from request threads and background tasks alike."""

    _open: ClassVar[dict[Path, Database]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        init = sqlite3.connect(path, timeout=30, isolation_level=None)
        try:
            init.execute("PRAGMA journal_mode=WAL")
        finally:
            init.close()
        with self.connect() as conn:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    conn.execute(statement)
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )

    @classmethod
    def at(cls, path: Path) -> Database:
        """One initialised Database per file for the life of the process."""
        resolved = path.resolve()
        with cls._lock:
            db = cls._open.get(resolved)
            if db is None or not resolved.exists():
                db = cls._open[resolved] = cls(resolved)
            return db

    @contextmanager
    def connect(self, exclusive: bool = False) -> Iterator[sqlite3.Connection]:
        """A transaction: committed on success, rolled back on error. `exclusive` takes
        the write lock up front, for read-then-write sequences."""
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE" if exclusive else "BEGIN")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    def meta(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


class RunStore[M: BaseModel]:
    """Versioned runs of one kind per card (1, 2, 3, ...), stored as JSON rows."""

    kind: ClassVar[str]
    model: type[M]
    # A change to the card's branch withdraws the manual-test approval.
    clears_approval_on_create: ClassVar[bool] = False
    clears_approval_on_states: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, db: Database):
        self.db = db

    def versions(self, key: str) -> list[M]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT data FROM runs WHERE kind = ? AND card_key = ? ORDER BY version",
                (self.kind, check_key(key)),
            ).fetchall()
        return [self.model.model_validate_json(r[0]) for r in rows]

    def latest(self, key: str) -> M | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT data FROM runs WHERE kind = ? AND card_key = ? "
                "ORDER BY version DESC LIMIT 1",
                (self.kind, check_key(key)),
            ).fetchone()
        return self.model.model_validate_json(row[0]) if row else None

    def create_run(self, key: str, build: Callable[[int, str], M]) -> M:
        """Store a new run with the next free version. `build(version, timestamp)` makes
        it; picking the version and inserting happen under one write lock."""
        stamp = now()
        with self.db.connect(exclusive=True) as conn:
            row = conn.execute(
                "SELECT MAX(version) FROM runs WHERE kind = ? AND card_key = ?",
                (self.kind, check_key(key)),
            ).fetchone()
            run = build((row[0] or 0) + 1, stamp)
            insert_run(conn, self.kind, run)
            if self.clears_approval_on_create:
                conn.execute("DELETE FROM test_approvals WHERE card_key = ?", (key,))
        return run

    def save(self, run: M) -> M:
        run.updated_at = now()  # type: ignore[attr-defined]
        put_run(self.db, self.kind, run)
        if run.state in self.clears_approval_on_states:  # type: ignore[attr-defined]
            Approvals(self.db).clear(run.card_key)  # type: ignore[attr-defined]
        return run

    def card_keys(self) -> list[str]:
        """Every card that has at least one run of this kind."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT card_key FROM runs WHERE kind = ? ORDER BY card_key",
                (self.kind,),
            ).fetchall()
        return [r[0] for r in rows]


def put_run(db: Database, kind: str, run: BaseModel) -> None:
    with db.connect() as conn:
        insert_run(conn, kind, run)


def insert_run(conn: sqlite3.Connection, kind: str, run: BaseModel) -> None:
    conn.execute(
        "INSERT INTO runs (kind, card_key, version, state, data, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(kind, card_key, version) DO UPDATE SET "
        "state = excluded.state, data = excluded.data, updated_at = excluded.updated_at",
        (
            kind,
            check_key(run.card_key),  # type: ignore[attr-defined]
            run.version,  # type: ignore[attr-defined]
            run.state,  # type: ignore[attr-defined]
            run.model_dump_json(),
            run.created_at,  # type: ignore[attr-defined]
            run.updated_at,  # type: ignore[attr-defined]
        ),
    )


class Approvals:
    """Cards whose manual test the user has approved."""

    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT approved_at FROM test_approvals WHERE card_key = ?",
                (check_key(key),),
            ).fetchone()
        return row[0] if row else None

    def approve(self, key: str) -> str:
        stamp = now()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO test_approvals (card_key, approved_at) VALUES (?, ?) "
                "ON CONFLICT(card_key) DO UPDATE SET approved_at = excluded.approved_at",
                (check_key(key), stamp),
            )
        return stamp

    def clear(self, key: str) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM test_approvals WHERE card_key = ?", (check_key(key),)
            )
        return cur.rowcount > 0

    def keys(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT card_key FROM test_approvals ORDER BY card_key"
            ).fetchall()
        return [r[0] for r in rows]


class JiraProjects:
    """Jira project keys seen on cards. Additive only: nothing is ever removed."""

    def __init__(self, db: Database):
        self.db = db

    def remember(self, keys: Iterable[str]) -> None:
        wanted = dict.fromkeys(k.strip().upper() for k in keys if k and k.strip())
        if not wanted:
            return
        stamp = now()
        with self.db.connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO jira_projects (project_key, seen_at) "
                "VALUES (?, ?)",
                [(k, stamp) for k in wanted],
            )

    def keys(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT project_key FROM jira_projects ORDER BY project_key"
            ).fetchall()
        return [r[0] for r in rows]


class Archive:
    """Cards the user has moved out of the Home and project views."""

    def __init__(self, db: Database):
        self.db = db

    def add(self, key: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO archived_cards (card_key, archived_at) "
                "VALUES (?, ?)",
                (check_key(key), now()),
            )

    def remove(self, key: str) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM archived_cards WHERE card_key = ?", (check_key(key),)
            )
        return cur.rowcount > 0

    def keys(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT card_key FROM archived_cards ORDER BY card_key"
            ).fetchall()
        return [r[0] for r in rows]
