"""SQLite reference store. Target PostgreSQL design is in docs/IMPLEMENTATION.md.

Each write uses BEGIN IMMEDIATE. This is deliberately NOT a distributed worker queue.
Do not share this file over a network filesystem or scale the reference deployment.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from typing import Iterator
from .domain import Actor, NotFound, canonical

class ClosingConnection(sqlite3.Connection):
    """sqlite3 normally leaves context-managed connections open; close explicitly."""
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()

class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS actors (
                  id TEXT PRIMARY KEY, team TEXT NOT NULL, role TEXT NOT NULL,
                  active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, team TEXT NOT NULL, owner TEXT NOT NULL,
                  status TEXT NOT NULL, version INTEGER NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id TEXT NOT NULL REFERENCES runs(id), kind TEXT NOT NULL,
                  created_at REAL NOT NULL, body TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_by_run ON events(run_id, id);
                CREATE TABLE IF NOT EXISTS requests (
                  owner TEXT NOT NULL, request_key TEXT NOT NULL,
                  request_hash TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(id),
                  PRIMARY KEY(owner, request_key)
                );
            """)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def seed_actors(self) -> None:
        with self.tx() as db:
            db.executemany("INSERT OR IGNORE INTO actors(id,team,role) VALUES(?,?,?)", [
                ("alex", "alpha", "operator"), ("sam", "alpha", "approver"),
                ("lee", "alpha", "reader"), ("riley", "beta", "operator"),
                ("jordan", "beta", "approver"),
            ])

    @staticmethod
    def actor(db: sqlite3.Connection, actor_id: str) -> Actor:
        row = db.execute("SELECT * FROM actors WHERE id=?", (actor_id,)).fetchone()
        if row is None:
            raise NotFound("Identity not found.")
        return Actor(row["id"], row["team"], row["role"], bool(row["active"]))

    @staticmethod
    def run(db: sqlite3.Connection, run_id: str) -> dict:
        row = db.execute("SELECT body FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise NotFound("Run not found.")
        return json.loads(row["body"])

    @staticmethod
    def save(db: sqlite3.Connection, run: dict) -> None:
        run["version"] += 1
        db.execute("UPDATE runs SET status=?,version=?,body=? WHERE id=?",
                   (run["status"], run["version"], canonical(run), run["id"]))

    @staticmethod
    def event(db: sqlite3.Connection, run: dict, kind: str, payload: dict, now: float) -> None:
        db.execute("INSERT INTO events(run_id,kind,created_at,body) VALUES(?,?,?,?)",
                   (run["id"], kind, now, canonical(payload)))
