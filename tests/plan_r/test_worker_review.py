"""The worker and the sweeper around T21's review (Plan R rulings 1, 5, 7, 9, 13 and 18; R023, R057, R092, R116), on
LangGraph's in-memory saver and Plan H's fakes.

Catches: a revision drafted on the old revision's thread or frozen as revision 1; an investigate job for an older
revision that runs the graph again; a freeze whose expiry is the worker's wall clock, or whose unit takes the asset
guard's lock after the fence; a model outage that fails the run instead of leaving it for a person's proposal, a
manual-path run whose stored checkpoint stays (the manual proposal would refuse), or a later job that fails or
re-drafts such a run; an execute job that does not read the asset status again before its grant; a lost lease after
the decision that resumes with another decision than the accepted one, or grants twice (R023); and a sweeper tick that
does not expire overdue proposals or record its minute.
"""

import asyncio
import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from langgraph.types import Command
from ops_core import persistence
from ops_core.jobs import JobType
from ops_core.lease import Lease, LeaseLost
from ops_core.outcomes import EventType
from ops_core.states import RunState
from ops_sweeper import expiry, wakeups
from ops_sweeper import main as sweeper
from ops_worker import main
from ops_worker.drafting import ModelUnavailable
from ops_worker.graph import build, nodes

from tests.plan_h.test_worker_units import JOB, NOW, RUN, RUN_ID, make
from tests.plan_q.test_graph_flow import REFUSED, Answering, Scripted, approve, job, world

SUCCEEDED = {"status": "outcome", "data": {"status": "SUCCEEDED"}, "error": None}


def frozen_payloads(monkeypatch: pytest.MonkeyPatch, w: Any) -> list[dict[str, Any]]:
    """Every payload `freeze_proposal` was given, with the expiry it was handed (Plan H's recorder freezes on)."""
    seen: list[dict[str, Any]] = []
    freeze = persistence.freeze_proposal

    async def keep(*args: Any, **kwargs: Any) -> Any:
        seen.append({**json.loads(kwargs["payload_canonical"]), "passed_expiry": kwargs["expires_at"]})
        return await freeze(*args, **kwargs)

    monkeypatch.setattr(persistence, "freeze_proposal", keep)
    return seen


def test_a_revision_is_its_own_thread_and_freezes_its_own_number(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch, {**RUN, "revision": 2})
    payloads = frozen_payloads(monkeypatch, w)
    job(w, Scripted(), dedup_key=f"{RUN_ID}:2")
    (payload,) = payloads
    assert payload["revision"] == 2 and w.run["state"] == "AWAITING_APPROVAL"
    assert list(w.saver.list(build.config(build.thread_id(RUN_ID, 2), None)))  # ruling 1: the thread run_id:2
    assert not list(w.saver.list(build.config(build.thread_id(RUN_ID, 1), None)))
    # Ruling 5: the expiry counts from the application clock read in the freeze unit, inside the hashed payload.
    assert payload["expires_at"] == "2026-10-15T12:15:00Z" and payload["passed_expiry"] == NOW + timedelta(minutes=15)


def test_the_frozen_payload_names_the_runs_asset_and_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan R round 1, I2: `freeze_proposal` refuses a payload whose asset or interval is not the run's, so the worker
    builds it from the run row it read in the freeze unit."""
    w = world(monkeypatch)
    payloads = frozen_payloads(monkeypatch, w)
    job(w, Scripted())
    (payload,) = payloads
    assert (payload["asset_id"], payload["start_at"], payload["end_at"]) == (
        RUN["asset_id"],
        RUN["start_at"].isoformat().replace("+00:00", "Z"),
        RUN["end_at"].isoformat().replace("+00:00", "Z"),
    )


def revise(w: Any) -> None:
    """What `create_revision` commits (ruling 1): QUEUED, the active proposal and the stored id cleared, a new
    revision (one more `proposal.revised`)."""
    w.run.update(state="QUEUED", active_proposal_id=None, checkpoint_id=None, revision=w.run.get("revision", 1) + 1)


class RevisedMeanwhile(Answering):
    """mcp-write's answers, with the requester's revision committing after the asset re-read and before the write
    call (the API holds no lease, SA:186)."""

    def __init__(self, w: Any, *docs: dict[str, Any]) -> None:
        super().__init__(w.log, *docs)
        self.w = w

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == "create_incident":
            revise(self.w)
        return await super().call(url, handle=handle, tool=tool, arguments=arguments)


def test_a_revision_during_an_execute_job_leaves_the_old_thread_and_starts_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan R round 1, I1: the old execute job's grant is refused (NOT_ACTIVE_APPROVED) and its graph run ends quietly
    without storing its thread's checkpoint over the cleared column; the revision's job starts thread run_id:2."""
    w = world(monkeypatch)
    job(w, Scripted())
    approve(w)
    job(w, Scripted(), "execute", mcp=RevisedMeanwhile(w, REFUSED))
    assert w.run["state"] == "QUEUED" and w.run["checkpoint_id"] is None
    assert w.log.entries[-1] == "release_lease"
    payloads = frozen_payloads(monkeypatch, w)
    job(w, Scripted(), dedup_key=f"{RUN_ID}:2")
    assert w.run["state"] == "AWAITING_APPROVAL" and [p["revision"] for p in payloads] == [2]
    assert list(w.saver.list(build.config(build.thread_id(RUN_ID, 2), None)))


def test_a_revision_after_the_freeze_ends_the_old_graph_run_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan R round 1, I1: a revision that commits between the freeze and the wait's reread ends the old investigate
    job's graph run (no "freezing failed", no FAILED); the revision's own job drafts and freezes revision 2."""
    w = world(monkeypatch)
    freeze = persistence.freeze_proposal

    async def freeze_then_revise(*args: Any, **kwargs: Any) -> Any:
        frozen = await freeze(*args, **kwargs)
        revise(w)  # the requester's revision commits right after the freeze unit
        return frozen

    monkeypatch.setattr(persistence, "freeze_proposal", freeze_then_revise)
    job(w, Scripted())
    after = w.log.entries[w.log.entries.index("freeze_proposal") :]
    assert "transition_run" not in after and w.run["state"] == "QUEUED" and w.run["checkpoint_id"] is None
    assert w.log.entries[-1] == "release_lease"
    monkeypatch.setattr(persistence, "freeze_proposal", freeze)  # no second revision
    payloads = frozen_payloads(monkeypatch, w)
    job(w, Scripted(), dedup_key=f"{RUN_ID}:2")
    assert w.run["state"] == "AWAITING_APPROVAL" and [p["revision"] for p in payloads] == [2]


def test_an_investigate_job_of_an_older_revision_ends_without_a_graph_run(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch, {**RUN, "revision": 2})
    job(w, Scripted(), dedup_key=f"{RUN_ID}:1")
    assert "store_checkpoint_id" not in w.log.entries and w.run["state"] == "QUEUED"
    assert w.log.entries[-1] == "release_lease"


def test_the_freeze_unit_takes_the_asset_lock_before_its_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted())
    (freeze,) = [u for u in w.log.units() if "freeze_proposal" in u]
    assert freeze[:3] == ["set_tenant", "lock_asset", "fenced"]  # SA:189: advisory:asset, run_lease, runs


def test_a_model_outage_leaves_the_run_for_a_manual_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted(ModelUnavailable("no reply")))
    assert w.run["state"] == "DRAFTING" and w.run["checkpoint_id"] is None  # erratum 134: what the manual path needs
    assert "freeze_proposal" not in w.log.entries and "clear_checkpoint_id" in w.log.entries
    assert w.contexts[0].trace[-3:] == ["draft_with_langchain", "route_request", "publish_state"]
    # A job that wakes the run again (a re-armed or reclaimed one) leaves it waiting: no failure, no second draft.
    moves = w.log.entries.count("transition_run")
    explanation = [(uuid4(), {"message": nodes.MANUAL_PATH})]
    w.run["events"][EventType.EXPLANATION_READY] = (
        explanation  # what manual_path journalled (Plan H's recorder drops it)
    )
    generator = Scripted()
    job(w, generator)
    assert w.log.entries.count("transition_run") == moves and generator.requests == []
    assert w.run["state"] == "DRAFTING"


def test_an_answer_only_model_outage_still_fails_the_run_with_no_manual_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan R round 1, I2: the `manual` route row carries the investigate gate (revision 0016 refuses a manual proposal
    on any other intent), so an answer_only run whose model fails ends FAILED as it did before T21."""
    w = world(monkeypatch, {**RUN, "intent": "answer_only"})
    job(w, Scripted(ModelUnavailable("no reply")))
    assert w.run["state"] == "FAILED"
    assert "clear_checkpoint_id" not in w.log.entries and "freeze_proposal" not in w.log.entries
    assert EventType.EXPLANATION_READY not in w.run["events"]  # no manual-path explanation


def test_an_execute_job_reads_the_asset_status_again_before_its_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted())
    approve(w)
    start = len(w.log.entries)
    job(w, Scripted(), "execute", mcp=Answering(w.log, SUCCEEDED))
    after = w.log.entries[start:]
    assert (
        after.index("mcp:get_asset_status")
        < after.index("record_asset_observation")
        < after.index("mcp:create_incident")
    )
    assert w.run["asset_observed_at"].isoformat() == "2026-10-08T12:00:00+00:00"  # the read's own observed_at


def test_r023_a_lost_lease_after_the_decision_resumes_exactly_the_accepted_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling 13 on the fakes: the execute job loses its lease at the store of the resumed wait's checkpoint, so the
    stored id is still the interrupt; the next execute job resumes it with the same approval.recorded id, and the write
    tool runs once, for the approved proposal. (Live, the stop comes after that store: tests/e2e.)"""
    w = world(monkeypatch)
    job(w, Scripted())
    approve(w)
    accepted = w.run["events"][EventType.APPROVAL_RECORDED][-1][0]
    inputs: list[Any] = []
    drive = build.run_graph

    async def spy(ctx: Any, graph_input: Any, **kwargs: Any) -> None:
        inputs.append(graph_input)
        await drive(ctx, graph_input, **kwargs)

    monkeypatch.setattr(build, "run_graph", spy)
    fences = [0]

    async def fenced(_conn: Any, held: Lease) -> None:
        w.log.entries.append("fenced")
        fences[0] += 1
        if fences[0] == 2:  # the job's first unit passes; the store of the resumed wait's checkpoint loses
            held.mark_lost("the fence moved")
            raise LeaseLost("run lease lost")

    monkeypatch.setattr(persistence, "fenced", fenced)
    deps, lease = make(w.log)
    deps.saver = w.saver
    asyncio.run(main.run_job(deps, persistence.Claimed({**JOB, "type": "execute"}, lease)))  # handed back
    assert "mcp:create_incident" not in w.log.entries  # stopped before the write tool
    calls = Answering(w.log, SUCCEEDED)
    job(w, Scripted(), "execute", mcp=calls)
    resumes = [i.resume for i in inputs if isinstance(i, Command)]
    assert resumes == [str(accepted), str(accepted)]  # exactly the accepted event, both times
    assert w.log.entries.count("mcp:create_incident") == 1


def test_the_investigate_wake_up_is_the_current_revisions_job() -> None:
    """Plan R round 1, M1: the sweep picks and re-arms only the investigate job whose key names the run's current
    revision, never an older revision's job that finished later."""
    current = "jj.dedup_key = " + wakeups.CURRENT_KEY
    assert current in wakeups.LOST
    assert "j.dedup_key = " + wakeups.CURRENT_KEY in wakeups.REARM
    assert "'proposal.revised'" in wakeups.CURRENT_KEY  # the rule of `_run_revision` (erratum 140)


def test_the_sweeper_expires_every_tenants_overdue_proposals_and_records_its_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, overdue, decided = uuid4(), uuid4(), uuid4()
    asked: list[Any] = []

    iterated: list[Any] = []

    async def each_tenant(_conn: Any, _work: Any, *, tenants: Any = None) -> dict[Any, list[Any]]:
        iterated.append(tenants)  # Plan R round 1, M10: the sweep asks for every tenant, never a fixed list
        return {tenant: [overdue, decided]}

    async def in_tenant(conn: Any, _tenant: Any, work: Any) -> Any:
        return await work(conn)

    async def expire_proposal(_conn: Any, run_id: Any) -> RunState:
        asked.append(run_id)  # a decision got to `decided` first: the definer leaves it as it is
        return RunState.BLOCKED_REVIEW if run_id == overdue else RunState.APPROVED

    recorded: list[JobType] = []

    async def record(_deps: Any, job_type: JobType) -> None:
        recorded.append(job_type)

    monkeypatch.setattr(expiry, "for_each_tenant", each_tenant)
    monkeypatch.setattr(expiry, "in_tenant", in_tenant)
    monkeypatch.setattr(persistence, "expire_proposal", expire_proposal)
    monkeypatch.setattr(sweeper, "record", record)
    none: Any = None
    deps = sweeper.Deps(conn=none, admin=none, issuer="iss", tick_seconds=30.0, worker_name="sweeper:test")
    asyncio.run(sweeper.expire_proposals(deps))
    assert asked == [overdue, decided] and recorded == [JobType.EXPIRE_PROPOSALS]
    assert asyncio.run(expiry.expire(none)) == [overdue]
    assert iterated == [None, None]
