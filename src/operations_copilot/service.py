"""Executable control reference: clarify -> draft -> approve -> commit/reconcile.

This intentionally uses a small synchronous SQLite design. It is NOT the target
multi-worker PostgreSQL implementation. See the explicit production milestones.
"""
from __future__ import annotations
import time
import uuid
from typing import Callable
from .domain import Conflict, Forbidden, InvalidInput, UncertainOutcome, canonical, digest, require, validate_draft, validate_hours, validate_text
from .store import Store
from .synthetic import SyntheticOperations
from .models import DeterministicModel, DraftModel

class ControlService:
    def __init__(self, store: Store, operations: SyntheticOperations,
                 model: DraftModel | None = None, clock: Callable[[], float] = time.time):
        self.store, self.ops = store, operations
        self.model, self.clock = model or DeterministicModel(), clock

    def create(self, actor_id: str, message: str, asset_id: str | None, hours: int | None,
               request_key: str) -> dict:
        message = validate_text(message)
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 128:
            raise InvalidInput("A request idempotency key of 8 to 128 characters is required.")
        if hours is not None:
            validate_hours(hours)
        if asset_id is not None and (not isinstance(asset_id, str) or not 1 <= len(asset_id) <= 32):
            raise InvalidInput("Invalid asset identifier.")
        req_hash = digest({"message": message, "asset_id": asset_id, "hours": hours})
        with self.store.tx() as db:
            actor = self.store.actor(db, actor_id)
            require(actor, actor.team, ("operator", "approver"))
            previous = db.execute("SELECT * FROM requests WHERE owner=? AND request_key=?", (actor_id, request_key)).fetchone()
            if previous:
                if previous["request_hash"] != req_hash:
                    raise Conflict("Request key was already used for a different request.")
                return self.store.run(db, previous["run_id"])
            if asset_id:
                self.ops.asset(asset_id, actor.team)
            run = {"id": str(uuid.uuid4()), "team": actor.team, "owner": actor.id,
                   "message": message, "asset_id": asset_id, "hours": hours,
                   "status": "READY_TO_DRAFT" if asset_id and hours else "AWAITING_INPUT",
                   "version": 1, "proposal": None, "approval": None, "result": None,
                   "created_at": self.clock(), "model_mode": type(self.model).__name__}
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (run["id"], run["team"], run["owner"], run["status"], run["version"], canonical(run)))
            db.execute("INSERT INTO requests VALUES(?,?,?,?)", (actor_id, request_key, req_hash, run["id"]))
            self.store.event(db, run, "run.created", {"status": run["status"], "actor": actor.id}, self.clock())
            return run

    def get(self, actor_id: str, run_id: str) -> dict:
        with self.store.tx() as db:
            run = self.store.run(db, run_id)
            require(self.store.actor(db, actor_id), run["team"])
            return run

    def events(self, actor_id: str, run_id: str, after: int = 0) -> list[dict]:
        import json
        if type(after) is not int or after < 0:
            raise InvalidInput("Event cursor must be a nonnegative integer.")
        with self.store.tx() as db:
            run = self.store.run(db, run_id)
            require(self.store.actor(db, actor_id), run["team"])
            rows = db.execute("SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id LIMIT 100", (run_id, after)).fetchall()
            return [{"id": row["id"], "kind": row["kind"], "created_at": row["created_at"], "payload": json.loads(row["body"])} for row in rows]

    def clarify(self, actor_id: str, run_id: str, asset_id: str, hours: int, expected_version: int) -> dict:
        validate_hours(hours)
        with self.store.tx() as db:
            run = self.store.run(db, run_id)
            actor = self.store.actor(db, actor_id)
            require(actor, run["team"], ("operator", "approver"))
            if actor.id != run["owner"]:
                raise Forbidden("Only the requester can resolve this clarification.")
            if run["status"] != "AWAITING_INPUT" or run["version"] != expected_version:
                raise Conflict("The clarification is no longer current.")
            self.ops.asset(asset_id, run["team"])
            run.update(asset_id=asset_id, hours=hours, status="READY_TO_DRAFT")
            self.store.save(db, run)
            self.store.event(db, run, "clarification.accepted", {"asset_id": asset_id, "hours": hours}, self.clock())
            return run

    def prepare(self, actor_id: str, run_id: str) -> dict:
        with self.store.tx() as db:
            run = self.store.run(db, run_id)
            actor = self.store.actor(db, actor_id)
            require(actor, run["team"], ("operator", "approver"))
            if run["status"] in {"AWAITING_APPROVAL", "INSUFFICIENT_EVIDENCE"}:
                return run
            if run["status"] != "READY_TO_DRAFT":
                raise Conflict("Run is not ready for drafting.")
            expected_version = run["version"]
        # Never hold the application transaction while a model generates.
        evidence = self.ops.snapshot(run["asset_id"], run["team"], run["hours"])
        if not evidence["documents"]:
            draft = None
        else:
            refs = {f'{d["document_id"]}:v{d["version"]}:{d["section"]}' for d in evidence["documents"]}
            draft = validate_draft(self.model.draft(run["message"], evidence), refs)
        with self.store.tx() as db:
            current = self.store.run(db, run_id)
            require(self.store.actor(db, actor_id), current["team"], ("operator", "approver"))
            if current["version"] != expected_version or current["status"] != "READY_TO_DRAFT":
                raise Conflict("Run changed during generation; generated content was discarded.")
            if draft is None:
                current["status"] = "INSUFFICIENT_EVIDENCE"
                self.store.save(db, current)
                self.store.event(db, current, "evidence.insufficient", {"reason": "No approved permitted procedure."}, self.clock())
                return current
            body = {"action": "create_incident", "destination": "synthetic-operations",
                    "team": run["team"], "asset_id": run["asset_id"], "hours": run["hours"],
                    "draft": draft, "evidence": evidence,
                    "evidence_hash": self.ops.fingerprint(evidence),
                    "workflow_version": "reference-v1", "prompt_version": "draft-v1"}
            current["proposal"] = {"body": body, "hash": digest(body), "expires_at": self.clock() + 900}
            current["status"] = "AWAITING_APPROVAL"
            self.store.save(db, current)
            self.store.event(db, current, "proposal.created", {"proposal_hash": current["proposal"]["hash"], "action_executed": False}, self.clock())
            return current

    def decide(self, actor_id: str, run_id: str, proposal_hash: str,
               expected_version: int, decision: str) -> dict:
        if decision not in {"approve", "reject"}:
            raise InvalidInput("Decision must be approve or reject.")
        with self.store.tx() as db:
            run = self.store.run(db, run_id)
            actor = self.store.actor(db, actor_id)
            require(actor, run["team"], ("approver",))
            if actor.id == run["owner"]:
                raise Forbidden("The requester cannot approve their own action.")
            proposal = run["proposal"]
            if not proposal or proposal["hash"] != proposal_hash:
                raise Conflict("Proposal does not match the reviewed action.")
            # A duplicate identical decision is safe and does not create another event.
            previous = run["approval"]
            if previous and previous["actor"] == actor_id and previous["decision"] == decision and previous["proposal_hash"] == proposal_hash:
                return run
            if run["version"] != expected_version or run["status"] != "AWAITING_APPROVAL":
                raise Conflict("The action has changed or already received a decision.")
            if self.clock() >= proposal["expires_at"]:
                raise Conflict("Proposal expired. Prepare a new run for review.")
            if digest(proposal["body"]) != proposal["hash"]:
                raise Conflict("Proposal integrity check failed.")
            run["approval"] = {"actor": actor_id, "decision": decision, "proposal_hash": proposal_hash,
                               "decided_at": self.clock(), "expires_at": proposal["expires_at"]}
            run["status"] = "APPROVED" if decision == "approve" else "REJECTED"
            self.store.save(db, run)
            self.store.event(db, run, "approval.recorded", {"actor": actor_id, "decision": decision, "proposal_hash": proposal_hash}, self.clock())
            return run

    def execute(self, actor_id: str, run_id: str, lose_response: bool = False) -> dict:
        with self.store.tx() as db:
            run = self.store.run(db, run_id)
            require(self.store.actor(db, actor_id), run["team"], ("operator", "approver"))
            if run["status"] == "SUCCEEDED":
                return run
            if run["status"] in {"EXECUTING", "OUTCOME_UNKNOWN"}:
                raise Conflict("Execution needs reconciliation, not another write.")
            if run["status"] != "APPROVED":
                raise Forbidden("An approved action is required before execution.")
            approval, proposal = run["approval"], run["proposal"]
            approver = self.store.actor(db, approval["actor"])
            requester = self.store.actor(db, run["owner"])
            require(approver, run["team"], ("approver",))
            require(requester, run["team"], ("operator", "approver"))
            if approver.id == requester.id or approval["decision"] != "approve":
                raise Forbidden("Invalid approval.")
            if self.clock() >= approval["expires_at"]:
                raise Conflict("Approval expired before execution.")
            if digest(proposal["body"]) != proposal["hash"] or approval["proposal_hash"] != proposal["hash"]:
                raise Conflict("Action changed after review.")
            snapshot = self.ops.snapshot(run["asset_id"], run["team"], run["hours"])
            if self.ops.fingerprint(snapshot) != proposal["body"]["evidence_hash"]:
                raise Conflict("Evidence changed after review. A new review is required.")
            run["status"] = "EXECUTING"
            run["action_key"] = "incident:" + run["id"] + ":" + proposal["hash"]
            self.store.save(db, run)
            self.store.event(db, run, "action.started", {"action_key": run["action_key"]}, self.clock())
        # No cross-database transaction: the destination owns its own idempotency key.
        try:
            result = self.ops.create_incident(run["action_key"], proposal["body"], lose_response)
        except UncertainOutcome:
            with self.store.tx() as db:
                current = self.store.run(db, run_id)
                current["status"] = "OUTCOME_UNKNOWN"
                self.store.save(db, current)
                self.store.event(db, current, "action.outcome_unknown", {"message": "Reconcile before retrying."}, self.clock())
                return current
        return self._record_success(run_id, result)

    def _record_success(self, run_id: str, result: dict) -> dict:
        with self.store.tx() as db:
            run = self.store.run(db, run_id)
            if result["payload_hash"] != run["proposal"]["hash"] or result["action_key"] != run["action_key"]:
                raise Conflict("Destination receipt does not match the approved action.")
            if run["status"] == "SUCCEEDED":
                return run
            if run["status"] not in {"EXECUTING", "OUTCOME_UNKNOWN"}:
                raise Conflict("Unexpected state for a committed action.")
            run.update(status="SUCCEEDED", result=result)
            self.store.save(db, run)
            self.store.event(db, run, "action.committed", result, self.clock())
            return run

    def reconcile(self, actor_id: str, run_id: str) -> dict:
        run = self.get(actor_id, run_id)
        with self.store.tx() as db:
            require(self.store.actor(db, actor_id), run["team"], ("operator", "approver"))
        if run["status"] == "SUCCEEDED":
            return run
        if run["status"] not in {"EXECUTING", "OUTCOME_UNKNOWN"}:
            raise Conflict("This run does not need reconciliation.")
        result = self.ops.lookup(run["action_key"])
        if result is None:
            # Absence is not proof of failure in a general external system.
            raise UncertainOutcome("No authoritative result is available; do not blindly retry.")
        return self._record_success(run_id, result)

    def cancel(self, actor_id: str, run_id: str, expected_version: int) -> dict:
        with self.store.tx() as db:
            run = self.store.run(db, run_id)
            actor = self.store.actor(db, actor_id)
            require(actor, run["team"], ("operator", "approver"))
            if actor.id != run["owner"] and actor.role != "approver":
                raise Forbidden("Only the requester or an approver may cancel.")
            if run["status"] == "CANCELLED":
                return run
            if run["version"] != expected_version:
                raise Conflict("Run changed; refresh before cancelling.")
            if run["status"] not in {"AWAITING_INPUT", "READY_TO_DRAFT", "AWAITING_APPROVAL", "APPROVED"}:
                raise Conflict("Cancellation cannot undo an action that may have committed.")
            run["status"] = "CANCELLED"
            self.store.save(db, run)
            self.store.event(db, run, "run.cancelled", {"actor": actor_id}, self.clock())
            return run
