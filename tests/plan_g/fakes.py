"""In-memory stand-ins for the API's database, shared by the Plan G unit tests and (through a thin subclass) the
Plan D and Plan F API tests.

`FakeStore` inherits the real orchestration (`ops_api.store.AdmissionStore`: the advisory-lock-lookup-work-record
order, the router call, the quota, the clarify and status branches, the fault hook) and supplies only the primitive
operations, so the API tests exercise the code that runs against PostgreSQL, not a re-implementation of it. A unit
is atomic like a transaction: every table is copied at entry and restored when the unit raises, and the two
"savepoint" primitives check before they write. The persona constants mirror `data/seed-ids.json`.
"""

from __future__ import annotations

import copy
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from ops_api import store
from ops_api.idempotency import Record, Scope, Verdict
from ops_api.store import Accepted, Conflict, Decided, LoginState, NotFound, ReplyRefused, SessionRow
from ops_core.contracts import DecisionRequest, ErrorCode, StoredMessageKind
from ops_core.states import ACTIVE_STATES, Intent
from ops_core.tokens import Principal, TokenRejected

ISSUER = "http://localhost:18080/realms/ops-dev"
ALPHA, BETA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7"), UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")
LEE = UUID("abcc1200-6791-57ab-87b5-9392d356b512")
JORDAN = UUID("cb551e64-83ec-582b-9047-8dadf20e151a")
RILEY = UUID("2f73af91-4906-5b79-9144-22c0df4e2316")  # BETA's requester (the live tests' other-tenant requester)
DUAL = UUID("11111111-2222-5333-8444-555555555555")  # a subject seeded in two tenants
CASEY = UUID("22222222-3333-5444-8555-666666666666")  # a second requester of ALPHA (fake-only, like DUAL)
PERSONAS = {"alex": ALEX, "sam": SAM, "lee": LEE, "jordan": JORDAN, "riley": RILEY, "dual": DUAL, "casey": CASEY}
ROWS = {
    ALEX: [(ALPHA, "requester")],
    SAM: [(ALPHA, "reviewer")],
    LEE: [(ALPHA, "reader")],
    JORDAN: [(BETA, "reviewer")],
    RILEY: [(BETA, "requester")],
    DUAL: [(ALPHA, "requester"), (BETA, "reviewer")],
    CASEY: [(ALPHA, "requester")],
}
ACTIVE = {state.value for state in ACTIVE_STATES}
TABLES = ("conversations", "messages", "runs", "jobs", "event_log", "records", "proposals", "decided", "decision_keys")


class StubVerifier:
    """A bearer token is a persona's name; anything else is rejected (the real verifier is tested in Plan F)."""

    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        if token not in PERSONAS:
            raise TokenRejected("unit test")
        return Principal(
            subject=str(PERSONAS[token]),
            azp="ops-dev-direct",
            audiences=("ops-api",),
            expires_at=2**31,
            claims={"preferred_username": token},
        )


class FakeUnit:
    """`ops_api.store.Unit` over the fake's tables, under one tenant."""

    def __init__(self, fake: FakeStore, tenant_id: UUID) -> None:
        self.fake = fake
        self.tenant_id = tenant_id

    async def lock_scope(self, lock_key: str) -> None:
        self.fake.locks.append(lock_key)  # one process: the lock is a record that it was taken first

    async def find_record(self, scope: Scope) -> Record | None:
        row = self.fake.records.get(scope)
        if row is None or row["expires"] <= self.fake.clock():
            return None
        return Record(row["fingerprint"], row["status"], copy.deepcopy(row["body"]))

    async def save_record(self, scope: Scope, fingerprint: str, verdict: Verdict, ttl_seconds: int) -> bool:
        if scope in self.fake.records:  # the primary key, expired or not
            return False
        self.fake.records[scope] = {
            "fingerprint": fingerprint,
            "status": verdict.status,
            "body": copy.deepcopy(verdict.body),
            "expires": self.fake.clock() + ttl_seconds,
        }
        return True

    async def now(self) -> datetime:
        return datetime.fromtimestamp(self.fake.clock(), UTC)

    async def conversation_exists(self, conversation_id: UUID) -> bool:
        return self.fake.conversations.get(conversation_id) == self.tenant_id

    async def insert_conversation(self, created_by: UUID) -> UUID:
        cid = uuid4()
        self.fake.conversations[cid] = self.tenant_id
        return cid

    async def queued_count(self) -> int:
        return sum(1 for r in self.fake.runs.values() if r["tenant_id"] == self.tenant_id and r["state"] == "QUEUED")

    def _runs_of(self, conversation_id: UUID) -> list[dict[str, Any]]:
        return [r for r in self.fake.runs.values() if r["conversation_id"] == conversation_id]

    async def active_run(self, conversation_id: UUID) -> bool:
        return any(r["state"] in ACTIVE for r in self._runs_of(conversation_id))

    async def latest_run(self, conversation_id: UUID) -> dict[str, Any] | None:
        runs = self._runs_of(conversation_id)
        if not runs:
            return None
        row = max(runs, key=lambda r: r["created_at"])
        return {"run_id": row["run_id"], "state": row["state"], "state_version": row["state_version"]}

    async def latest_event(self, run_id: UUID) -> dict[str, Any] | None:
        events = [e for e in self.fake.event_log if e["run_id"] == run_id]
        return None if not events else {"type": events[-1]["type"], "occurred_at": events[-1]["occurred_at"]}

    async def insert_message(
        self,
        *,
        conversation_id: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any] | None,
        author: UUID | None,
    ) -> UUID:
        if (author is None) != (kind in (StoredMessageKind.STATUS_ANSWER, StoredMessageKind.CLARIFICATION_QUESTION)):
            raise AssertionError(f"revision 0006's author CHECK would refuse a {kind.value} row")
        message_id = uuid4()
        self.fake.messages.append(
            {
                "message_id": message_id,
                "tenant_id": self.tenant_id,
                "conversation_id": conversation_id,
                "kind": kind.value,
                "text": text,
                "context": copy.deepcopy(context),
                "author": author,
            }
        )
        return message_id

    async def start_run(
        self,
        *,
        conversation_id: UUID,
        requester: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any],
        intent: Intent,
        asset_id: str,
        start_at: datetime,
        end_at: datetime,
        supersedes_run_id: UUID | None,
    ) -> Accepted:
        # The checks create_run makes, before anything is written (the savepoint's effect in DbUnit).
        sup = supersedes_run_id
        if sup is not None and (sup not in self.fake.runs or self.fake.runs[sup]["conversation_id"] != conversation_id):
            raise NotFound
        if self.fake.slot_occupied or await self.active_run(conversation_id):
            raise Conflict("SLOT_OCCUPIED")
        message_id = await self.insert_message(
            conversation_id=conversation_id, kind=kind, text=text, context=context, author=requester
        )
        run_id = uuid4()
        now = datetime.fromtimestamp(self.fake.clock(), UTC)
        self.fake.runs[run_id] = {
            "run_id": run_id,
            "tenant_id": self.tenant_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "requester": requester,
            "intent": intent.value,
            "state": "QUEUED",
            "state_version": 1,
            "active_proposal_id": None,
            "asset_id": asset_id,
            "start_at": start_at,
            "end_at": end_at,
            "created_at": now + timedelta(microseconds=len(self.fake.runs)),  # strictly increasing per run
        }
        self.fake.jobs.append({"type": "investigate", "run_id": run_id, "dedup_key": f"{run_id}:1"})
        self.fake.event_log.append({"run_id": run_id, "type": "run.accepted", "occurred_at": now, "payload": {}})
        return Accepted(conversation_id, message_id, run_id, "QUEUED", 1)

    async def record_reply(
        self,
        *,
        run_id: UUID,
        requester: UUID,
        question_id: UUID,
        expected_version: int,
        text: str,
        context: dict[str, Any],
    ) -> Accepted:
        self.fake.locks.append(f"run {run_id}")  # DbUnit's FOR UPDATE: taken before any check or write
        row = self.fake.runs.get(run_id)
        mine = None if row is None or row["tenant_id"] != self.tenant_id else dict(row)
        run = store.check_reply_run(mine, requester=requester, expected_version=expected_version)
        asked = [
            e["event_id"]
            for e in self.fake.event_log
            if e["run_id"] == run_id and e["type"] == "clarification.requested"
        ]
        store.check_reply_question(asked, question_id)
        key = f"{run_id}:{question_id}"
        if any(j["dedup_key"] == key for j in self.fake.jobs):
            raise ReplyRefused(409, ErrorCode.VERSION_CONFLICT, "the clarification was already answered")
        message_id = await self.insert_message(
            conversation_id=run["conversation_id"],
            kind=StoredMessageKind.CLARIFICATION_REPLY,
            text=text,
            context=context,
            author=requester,
        )
        self.fake.jobs.append({"type": "resume_input", "run_id": run_id, "dedup_key": key})
        self.fake.event_log.append(
            {
                "run_id": run_id,
                "type": "clarification.received",
                "occurred_at": datetime.fromtimestamp(self.fake.clock(), UTC),
                "payload": {"question_id": str(question_id), "message_id": str(message_id)},
            }
        )
        return Accepted(run["conversation_id"], message_id, run_id, run["state"], run["state_version"])

    async def proposal(self, proposal_id: UUID) -> dict[str, Any] | None:
        row = self.fake.proposals.get(proposal_id)
        return row if row and row["tenant_id"] == self.tenant_id else None

    async def record_decision(
        self, *, proposal_id: UUID, reviewer: UUID, request: DecisionRequest, key: str
    ) -> Decided:
        row = await self.proposal(proposal_id)
        if row is None:
            raise NotFound
        if row["payload_sha256"] != request.expected_payload_sha256 or proposal_id in self.fake.decided:
            raise Conflict("VERSION_CONFLICT")  # a stale hash, or the first decision already won
        self.fake.decided.add(proposal_id)
        self.fake.decision_keys[proposal_id] = key
        status = "APPROVED" if request.decision == "approve" else "REJECTED"
        return Decided(proposal_id, row["run_id"], request.decision, status, 5)


class FakeStore(store.AdmissionStore):
    """The API's store in memory: the real orchestration over `FakeUnit`, plus the reads and T11's sessions."""

    def __init__(self) -> None:
        self.conversations: dict[UUID, UUID] = {}  # conversation -> tenant
        self.messages: list[dict[str, Any]] = []
        self.runs: dict[UUID, dict[str, Any]] = {}
        self.jobs: list[dict[str, Any]] = []
        self.event_log: list[dict[str, Any]] = []  # app.events rows (`events` is the read method)
        self.records: dict[Scope, dict[str, Any]] = {}
        self.proposals: dict[UUID, dict[str, Any]] = {}
        self.decided: set[UUID] = set()
        self.decision_keys: dict[UUID, str] = {}
        self.locks: list[str] = []
        self.slot_occupied = False  # force create_run's own refusal, as a concurrent admission would
        self.logins: dict[str, tuple[LoginState, float]] = {}  # login hash -> (state, expiry)
        self.sessions: dict[str, dict[str, Any]] = {}  # session hash -> row fields + last_seen, expires, revoked
        self.jtis: set[str] = set()
        self.clock = time.time  # tests replace it to age sessions and records

    @asynccontextmanager
    async def unit(self, tenant_id: UUID) -> AsyncIterator[store.Unit]:
        """All-or-nothing like a transaction: the tables are restored when the unit raises."""
        saved = {name: copy.deepcopy(getattr(self, name)) for name in TABLES}
        try:
            yield FakeUnit(self, tenant_id)
        except BaseException:
            for name, value in saved.items():
                setattr(self, name, value)
            raise

    def seed_question(self, run_id: UUID) -> UUID:
        """Put a run where the worker would (AWAITING_INPUT with a `clarification.requested` event); the event id."""
        event_id = uuid4()
        run = self.runs[run_id]
        run["state"], run["state_version"] = "AWAITING_INPUT", run["state_version"] + 2
        self.event_log.append(
            {
                "event_id": event_id,
                "run_id": run_id,
                "type": "clarification.requested",
                "occurred_at": datetime.fromtimestamp(self.clock(), UTC),
                "payload": {},
            }
        )
        return event_id

    async def membership(self, issuer: str, subject: UUID) -> store.Membership | None:
        return store.single_tenant(ROWS.get(subject, [])) if issuer == ISSUER else None

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        row = self.runs.get(run_id)
        return row if row and row["tenant_id"] == tenant_id else None

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        row = self.proposals.get(proposal_id)
        return row if row and row["tenant_id"] == tenant_id else None

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        return [] if await self.run(tenant_id, run_id) is None else [{"sequence": 1, "type": "run.accepted"}]

    async def begin_login(
        self, *, login_sha256: str, state_sha256: str, nonce_sha256: str, code_verifier: str, ttl_seconds: int
    ) -> None:
        self.logins[login_sha256] = (LoginState(state_sha256, nonce_sha256, code_verifier), self.clock() + ttl_seconds)

    async def take_login(self, login_sha256: str) -> LoginState | None:
        entry = self.logins.pop(login_sha256, None)
        return None if entry is None or entry[1] <= self.clock() else entry[0]

    async def create_session(
        self,
        *,
        session_sha256: str,
        issuer: str,
        subject: UUID,
        tenant_id: UUID,
        sid: str,
        username: str,
        csrf_secret_sha256: str,
        refresh_token_enc: bytes,
        absolute_seconds: int,
    ) -> None:
        self.sessions[session_sha256] = {
            "row": SessionRow(
                session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256, refresh_token_enc
            ),
            "last_seen": self.clock(),
            "expires": self.clock() + absolute_seconds,
            "revoked": False,
        }

    async def live_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        entry = self.sessions.get(session_sha256)
        now = self.clock()
        if entry is None or entry["revoked"] or entry["expires"] <= now or entry["last_seen"] <= now - idle_seconds:
            return None
        entry["last_seen"] = now
        row: SessionRow = entry["row"]
        return row

    async def revoke_session(self, session_sha256: str) -> SessionRow | None:
        entry = self.sessions.get(session_sha256)
        if entry is None or entry["revoked"]:
            return None
        entry["revoked"] = True
        row: SessionRow = entry["row"]
        return row

    async def expire_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        entry = self.sessions.get(session_sha256)
        now = self.clock()
        if entry is None or entry["revoked"]:
            return None
        if entry["expires"] > now and entry["last_seen"] > now - idle_seconds:
            return None  # still live: not this method's to revoke
        entry["revoked"] = True
        row: SessionRow = entry["row"]
        return row

    async def record_logout(self, jti: str, *, expires_at: datetime, sid: str) -> int | None:
        if jti in self.jtis:
            return None
        self.jtis.add(jti)
        hit = [e for e in self.sessions.values() if e["row"].sid == sid and not e["revoked"]]
        for entry in hit:
            entry["revoked"] = True
        return len(hit)
