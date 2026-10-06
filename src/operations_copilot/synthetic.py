"""Synthetic destination with its OWN idempotency boundary and persistent receipts.

This is a separate SQLite file to model an independent destination. A lost-response
fault can be injected AFTER the destination commits. No real equipment is controlled.
"""
from __future__ import annotations
from pathlib import Path
import json
import sqlite3
import time
import uuid
from .domain import Conflict, NotFound, UncertainOutcome, canonical, digest

from .store import ClosingConnection

class SyntheticOperations:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts(
                  action_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
                  incident_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
                  created_at REAL NOT NULL
                );
            """)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        return db

    def seed(self) -> None:
        with self.connect() as db:
            for asset, team in [("A17", "alpha"), ("B22", "beta")]:
                body = {"asset_id": asset, "team": team, "revision": 1,
                        "state": "warning", "alert_code": "INSPECTION_DEVIATION",
                        "observed_at": time.time(), "synthetic": True}
                db.execute("INSERT OR IGNORE INTO assets VALUES(?,?)", (asset, canonical(body)))
            for ident, team in [("SOP-014", "alpha"), ("SOP-022", "beta")]:
                body = {"document_id": ident, "version": 1, "team": team,
                        "section": "4.2", "status": "approved", "synthetic": True,
                        "text": "For a repeated inspection-deviation warning, review the alert record and prepare an incident for authorized review. Do not change equipment settings."}
                db.execute("INSERT OR IGNORE INTO documents VALUES(?,?)", (ident, canonical(body)))

    def asset(self, asset_id: str, team: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT body FROM assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise NotFound("No permitted asset found.")
        body = json.loads(row["body"])
        if body["team"] != team:
            raise NotFound("No permitted asset found.")
        return body

    def procedures(self, team: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT body FROM documents ORDER BY id").fetchall()
        # Reference corpus is tiny. PostgreSQL filtering/ranking is a later milestone.
        bodies = [json.loads(row["body"]) for row in rows]
        return [d for d in bodies if d["team"] == team and d["status"] == "approved"]

    def alerts(self, asset_id: str, team: str, hours: int) -> dict:
        asset = self.asset(asset_id, team)
        return {"asset_id": asset_id, "window_hours": hours, "synthetic": True,
                "revision": asset["revision"], "count": 3 if asset["state"] == "warning" else 0}

    def snapshot(self, asset_id: str, team: str, hours: int) -> dict:
        asset = self.asset(asset_id, team)
        docs = self.procedures(team)
        return {"asset": asset, "alerts": self.alerts(asset_id, team, hours), "documents": docs}

    def fingerprint(self, snapshot: dict) -> str:
        return digest(snapshot)

    def create_incident(self, action_key: str, payload: dict, lose_response: bool = False) -> dict:
        body_hash = digest(payload)
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM receipts WHERE action_key=?", (action_key,)).fetchone()
            if row:
                if row["payload_hash"] != body_hash:
                    raise Conflict("Destination rejected reuse of an idempotency key with different content.")
                result = dict(row)
            else:
                result = {"action_key": action_key, "payload_hash": body_hash,
                          "incident_id": "INC-" + uuid.uuid4().hex[:12],
                          "payload": canonical(payload), "created_at": time.time()}
                db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)", tuple(result.values()))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        if lose_response:
            raise UncertainOutcome("Synthetic fault: destination committed; response was lost.")
        return {"incident_id": result["incident_id"], "payload_hash": result["payload_hash"],
                "action_key": action_key}

    def lookup(self, action_key: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT incident_id,payload_hash,action_key FROM receipts WHERE action_key=?", (action_key,)).fetchone()
        return dict(row) if row else None

    def count_incidents(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM receipts").fetchone()[0]

    def change_asset_revision_for_test(self, asset_id: str, team: str) -> None:
        body = self.asset(asset_id, team)
        body["revision"] += 1
        with self.connect() as db:
            db.execute("UPDATE assets SET body=? WHERE id=?", (canonical(body), asset_id))
