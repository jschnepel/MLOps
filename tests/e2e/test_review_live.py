"""Revision 0016's review rules as their callers meet them in PostgreSQL (OPS_LIVE=1; T21: R043, R044, R045, R046,
R057, R090, R092, R093, R100, R113, R116, R120, R125; DEV-006 to DEV-014, DEV-020, DEV-025).

Catches: a decision that authorizes another revision, hash or an expired proposal (R044, DEV-008, DEV-009); a content
author approving (R043, R093); an expiry that needs a reviewer or a live worker (R092); a grant that does not re-check
authority, cited sources, the asset observation or the asset guard (R045, R116, R125), or commits BLOCKED_REVIEW for a
refusal that must commit nothing (HASH_MISMATCH, R100); a revision after a grant (R090) or into an occupied slot
(R120); a cancel that undoes a grant (R046); a manual proposal outside the freeze rules or citing another tenant's
section (R057, note 4); feedback that changes anything but its own row and event (R113); a read that trusts a
membership the sync has not stamped (ruling 14); and a downgrade that does not restore revision 0015. Since Plan R's
round 1 also: a freeze of a payload on another asset or interval (I2); a grant that misses the guard across
conversations, the late-evidence set or the expiry, or blocks a touching interval or an abandoned action (I3); a manual
proposal that cites a real section of another tenant or names another asset (I4); and the refusals of the API's doors
(AUTHOR_LIMIT, supersession of another asset, a cancel from BLOCKED_REVIEW or at a stale version, the search) (I5).

Each run is put on an asset of its own (`asset()`), so the asset guard meets only what the test staged. Rows are
written by role connections, so every test purges its runs and memberships in `finally`.
"""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_api.idempotency import Idem, Scope, fingerprint
from ops_api.store import DbStore, Forbidden
from ops_core import persistence, settings
from ops_core.canonical import canonical_json, sha256_hex
from ops_core.contracts import (
    CancelRequest,
    DecisionRequest,
    FeedbackRequest,
    ManualProposalRequest,
    RevisionRequest,
    SearchRequest,
    load,
)
from ops_core.outcomes import ActionOutcome, Receipt, ToolOutcome
from ops_core.settings import Role, WakeupSettings
from ops_sweeper import expiry, wakeups
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_conversation, purge_run, stage_lease
from tests.e2e.test_definers_run_path_live import ALEX, ALPHA, BETA, conversation, refused, request
from tests.e2e.test_definers_write_path_live import JORDAN, SAM, drafting_run, handle_for, scope_of
from tests.e2e.test_migration_0011_live import APP_FUNCTIONS
from tests.e2e.test_wakeups_live import finish

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
CHOSEN = WakeupSettings()  # grace 60 s, cap 10 claims
WORKFLOW = "investigation-v1"
GRANT_AZP = "ops-worker"


def asset() -> str:
    """An asset no other test uses: the asset guard (SA:189) compares runs on one asset and interval only."""
    return f"R-{uuid4().hex[:10].upper()}"  # AssetId: ^[A-Z][A-Z0-9_-]{0,31}$


async def member(app_conn: persistence.Conn, *roles: str) -> UUID:
    """A new subject of ALPHA with the given roles, synced now (the issuer is the seeded rows' own)."""
    subject = uuid4()
    for role in roles:
        await app_conn.execute(
            "INSERT INTO app.memberships (tenant_id, issuer, subject, role, synced_at)"
            " SELECT %s, m.issuer, %s, %s, app.current_time() FROM app.memberships m WHERE m.tenant_id = %s LIMIT 1",
            (ALPHA, subject, role, ALPHA),
        )
    return subject


async def forget(app_conn: persistence.Conn, runs: list[UUID], subjects: list[UUID]) -> None:
    """Purge the runs, then the memberships the test added (decisions reference neither)."""
    for run in runs:
        await purge_run(app_conn, run)
    for subject in subjects:
        await app_conn.execute("DELETE FROM app.memberships WHERE subject = %s", (subject,))


async def drafting_on(
    app_conn: persistence.Conn,
    api: persistence.Conn,
    worker: persistence.Conn,
    where: str,
    *,
    days_back: int = 0,
    interval: tuple[datetime, datetime] | None = None,
    tenant: UUID = ALPHA,
) -> UUID:
    """A DRAFTING run of `tenant` on `where` over the 24 hours ending `days_back` days ago (or over `interval`), in a
    conversation of its own, with the workflow version the worker pins at its first claim and a fresh asset
    observation (R116), as a worker's retrieval would leave it."""
    run = await drafting_run(app_conn, api, worker, tenant)
    end = await app_conn.execute(
        "SELECT date_trunc('second', app.current_time()) - make_interval(days => %s) AS at", (days_back,)
    )
    at = (await end.fetchone())["at"]
    start, stop = interval or (at - timedelta(hours=24), at)
    await app_conn.execute(
        "UPDATE app.runs SET asset_id = %s, start_at = %s, end_at = %s, workflow_version = %s,"
        " asset_observed_at = app.current_time() WHERE run_id = %s",
        (where, start, stop, WORKFLOW, run),
    )
    return run


async def frozen(
    app_conn: persistence.Conn,
    worker: persistence.Conn,
    run: UUID,
    *,
    revision: int = 1,
    snapshots: list[dict[str, str]] | None = None,
    supersedes: UUID | None = None,
    tenant: UUID = ALPHA,
    fields: dict[str, Any] | None = None,
) -> tuple[persistence.Frozen, str]:
    """Freeze a validated draft of `run` as the worker, on the run's asset and interval (round 1, I2) and expiring 15
    minutes from the database clock; the result and the payload hash. The payload cites `snapshots` (none by
    default); `fields` overrides any payload field."""
    expires = (await persistence.current_time(app_conn)).replace(microsecond=0) + timedelta(minutes=15)
    cited = snapshots or []
    body = canonical_json(
        {
            "tenant_id": str(tenant),
            "run_id": str(run),
            "proposal_id": str(uuid4()),
            "revision": revision,
            "action": "create_incident",
            "destination": "synthetic-incidents",
            **await scope_of(app_conn, run),
            "title": "Review live",
            "summary": "Synthetic.",
            "evidence_refs": [s["evidence_id"] for s in cited],
            "source_snapshots": cited,
            "supersedes_run_id": None if supersedes is None else str(supersedes),
            "workflow_version": WORKFLOW,
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
            **(fields or {}),
        }
    )
    draft = uuid4()
    async with worker.transaction():
        await persistence.set_tenant(worker, tenant)
        await worker.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
            " VALUES (%s, %s, %s, %s, true, 'proposal')",
            (draft, tenant, run, sha256_hex(body)),
        )
        result = await persistence.freeze_proposal(
            worker, run_id=run, draft_id=draft, payload_canonical=body, expires_at=expires
        )
    return result, sha256_hex(body)


async def decide(
    api: persistence.Conn,
    proposal: UUID | None,
    digest: str,
    *,
    reviewer: UUID = SAM,
    revision: int = 1,
    tenant: UUID = ALPHA,
) -> persistence.Decided:
    """`record_decision` as the API, approving."""
    assert proposal is not None
    async with api.transaction():
        return await persistence.record_decision(
            api,
            tenant_id=tenant,
            proposal_id=proposal,
            reviewer=reviewer,
            expected_revision=revision,
            expected_payload_sha256=digest,
            decision="approve",
        )


async def refusal(call: Awaitable[Any]) -> str:
    """The code a refused call carries (Refused's or a decision conflict's DETAIL), or the message of a plain version
    conflict, whose `code` is None."""
    try:
        await call
    except (persistence.Refused, persistence.VersionConflict) as exc:
        return str(exc.code if exc.code is not None else exc)
    raise AssertionError("expected a refusal")


async def grant(
    app_conn: persistence.Conn, mcp_exec: persistence.Conn, run: UUID, proposal: UUID | None, *, expires_in: int = 600
) -> Any:
    """`grant_execution` as mcp-write would call it, through a write handle of the run's execute job (its stored
    expiry is wall-clock; `expires_in` outlasts a moved database clock)."""
    assert proposal is not None
    handle = await handle_for(app_conn, run, "execute", expires_in=expires_in)
    async with mcp_exec.transaction():
        return await persistence.grant_execution(mcp_exec, handle=handle, azp=GRANT_AZP, proposal_id=proposal)


async def state_of(app_conn: persistence.Conn, run: UUID) -> tuple[str, str | None]:
    row = await persistence.run_row(app_conn, run)
    return row["state"], row["reason"]


async def permitted_section(app_conn: persistence.Conn, tenant: UUID = ALPHA) -> dict[str, str]:
    """One permitted section of the tenant's ingested corpus as a snapshot (evidence id, content hash, version)."""
    cur = await app_conn.execute(
        "SELECT evidence_id, content_sha256, version FROM app._cited_permitted(%s,"
        " ARRAY(SELECT evidence_id FROM app.chunks WHERE tenant_id = %s)) ORDER BY evidence_id LIMIT 1",
        (tenant, tenant),
    )
    row = await cur.fetchone()
    assert row is not None, f"{tenant} has no permitted section"
    return dict(row)


async def commit_incident(app_conn: persistence.Conn, mcp_exec: persistence.Conn, run: UUID, granted: Any) -> None:
    """The run's incident commits, as mcp-write records it: SENT, then SUCCEEDED with the destination's receipt."""
    handle = await handle_for(app_conn, run, "execute", expires_in=600)
    receipt = Receipt(receipt_id=uuid4(), incident_id=f"INC-{uuid4().hex[:8]}", committed_at=datetime.now(UTC))
    outcome = ActionOutcome(
        status=ToolOutcome.SUCCEEDED,
        action_id=granted.action_id,
        payload_sha256=granted.payload_sha256,
        receipt=receipt,
        tombstone=None,
        reason=None,
    )
    async with mcp_exec.transaction():
        await persistence.mark_sent(mcp_exec, handle=handle, azp=GRANT_AZP, action_id=granted.action_id)
    async with mcp_exec.transaction():
        await persistence.record_outcome(
            mcp_exec, handle=handle, azp=GRANT_AZP, action_id=granted.action_id, outcome=outcome
        )
    assert await state_of(app_conn, run) == ("SUCCEEDED", None)


async def count(app_conn: persistence.Conn, table: str, run: UUID | None = None) -> int:
    """Rows of one app table (the test's own table names only), or of one run's rows in it."""
    where, args = ("", ()) if run is None else (" WHERE run_id = %s", (run,))
    cur = await app_conn.execute(f"SELECT count(*) AS n FROM app.{table}{where}", args)
    return int((await cur.fetchone())["n"])


async def stamp_memberships(app_conn: persistence.Conn) -> None:
    """Every membership stamped at the database clock, as the sweeper's sync would (round 1, M8: run again after a
    clock move is undone, so no row stays stamped in the future for the tests that follow)."""
    await app_conn.execute("UPDATE app.memberships SET synced_at = app.current_time()")


async def test_a_revision_is_reviewed_again_and_never_by_its_author(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """R043, R044, R093, DEV-006, DEV-009: revision 2 clears revision 1's approval path; the old proposal cannot be
    decided, the requester who revised it cannot approve it, and another reviewer can, exactly once."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    pat = await member(app_conn, "requester", "reviewer")  # both scopes on one identity (R043)
    run = await drafting_on(app_conn, api, worker, asset())
    try:
        first, first_hash = await frozen(app_conn, worker, run)
        assert (first.state.value, first.revision) == ("AWAITING_APPROVAL", 1)
        async with api.transaction():
            revised = await persistence.create_revision(
                api, tenant_id=ALPHA, run_id=run, expected_version=4, author=pat, supersedes_run_id=None
            )
        assert (revised.revision, revised.state_version) == (2, 5)
        row = await persistence.run_row(app_conn, run)
        assert (row["state"], row["active_proposal_id"], row["checkpoint_id"]) == ("QUEUED", None, None)
        assert row["authors"] == [ALEX, pat]  # ruling 4: the reviser joins the content authors
        cur = await app_conn.execute(
            "SELECT dedup_key FROM app.jobs WHERE run_id = %s AND type = 'investigate' ORDER BY dedup_key", (run,)
        )
        assert [r["dedup_key"] for r in await cur.fetchall()] == [f"{run}:1", f"{run}:2"]  # SA:455: run_id:revision
        # The stale version is refused, and revision 1 can no longer be decided (DEV-009: sam clicks revision 1).
        async with api.transaction():
            stale = refusal(
                persistence.create_revision(
                    api, tenant_id=ALPHA, run_id=run, expected_version=4, author=pat, supersedes_run_id=None
                )
            )
            assert await stale == f"version_conflict: run {run} is QUEUED at version 5"
        assert await refusal(decide(api, first.proposal_id, first_hash)) == "STALE_REVISION"
        async with worker.transaction():
            await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 5, '{}')", (run,))
            await worker.execute("SELECT app.transition_run(%s, 'RETRIEVING', 'DRAFTING', NULL, 6, '{}')", (run,))
        second, second_hash = await frozen(app_conn, worker, run, revision=2)
        assert (second.state.value, second.revision) == ("AWAITING_APPROVAL", 2)
        cur = await app_conn.execute(
            "SELECT revision, authored_by FROM app.proposals WHERE run_id = %s ORDER BY revision", (run,)
        )
        assert [(r["revision"], r["authored_by"]) for r in await cur.fetchall()] == [(1, [ALEX]), (2, [ALEX, pat])]
        # Independence (BS:466): the reviser is refused whatever else is right; the revision and the hash are each
        # checked under the run's lock; then sam approves, once.
        assert await refusal(decide(api, second.proposal_id, second_hash, reviewer=pat, revision=2)) == "SELF_REVIEW"
        assert await refusal(decide(api, second.proposal_id, second_hash, reviewer=ALEX, revision=2)) == "NOT_REVIEWER"
        assert await refusal(decide(api, second.proposal_id, second_hash, revision=1)) == "STALE_REVISION"
        assert await refusal(decide(api, second.proposal_id, "0" * 64, revision=2)) == "STALE_HASH"
        decided = await decide(api, second.proposal_id, second_hash, revision=2)
        assert decided.state.value == "APPROVED"
        assert await refusal(decide(api, second.proposal_id, second_hash, revision=2)) == "ALREADY_DECIDED"
    finally:
        await forget(app_conn, [run], [pat])


async def test_an_expired_proposal_is_blocked_by_the_sweeper_and_refused_to_the_reviewer(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """R092, DEV-008: sixteen minutes on the database clock; the decision is refused EXPIRED and commits nothing, the
    sweeper's routine over every tenant (no worker, no reviewer) moves the run to BLOCKED_REVIEW(expired) once and
    leaves BETA's run, which is not due, untouched (round 1, M10), and the decision stays refused. A freeze whose
    expiry is past the 15 minutes is refused before anything is written."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    harness, sweeper = await role_conn(Role.TEST_HARNESS), await role_conn(Role.SWEEPER)
    run = await drafting_on(app_conn, api, worker, asset())
    runs = [run]
    try:
        result, digest = await frozen(app_conn, worker, run)
        try:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '16 minutes'")
            await stamp_memberships(app_conn)  # the sync's stamp at the moved clock
            beta = await drafting_on(app_conn, api, worker, asset(), tenant=BETA)
            runs.append(beta)
            await frozen(app_conn, worker, beta, tenant=BETA)  # frozen at the moved clock: due in 15 minutes
            assert await refusal(decide(api, result.proposal_id, digest)) == "EXPIRED"
            assert await state_of(app_conn, run) == ("AWAITING_APPROVAL", None)  # the 409 extends nothing
            expired = await expiry.expire(sweeper)  # every tenant, as the sweeper's tick runs it
            assert run in expired and beta not in expired
            assert await state_of(app_conn, run) == ("BLOCKED_REVIEW", "expired")
            assert await state_of(app_conn, beta) == ("AWAITING_APPROVAL", None)
            assert run not in await expiry.expire(sweeper)  # nothing is due twice
            cur = await app_conn.execute(
                "SELECT count(*) AS n FROM app.events WHERE run_id = %s AND type = 'review.blocked'", (run,)
            )
            assert (await cur.fetchone())["n"] == 1
            assert await refusal(decide(api, result.proposal_id, digest)) == "EXPIRED"
        finally:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
            await stamp_memberships(app_conn)  # round 1, M8: no row stays stamped in the future
        other = await drafting_on(app_conn, api, worker, asset())
        runs.append(other)
        far = (await persistence.current_time(app_conn)).replace(microsecond=0) + timedelta(minutes=20)
        draft, body = uuid4(), far_body(other, far, await scope_of(app_conn, other))
        async with worker.transaction():
            await persistence.set_tenant(worker, ALPHA)
            await worker.execute(
                "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
                " VALUES (%s, %s, %s, %s, true, 'proposal')",
                (draft, ALPHA, other, sha256_hex(body)),
            )
            too_far = refusal(
                persistence.freeze_proposal(
                    worker, run_id=other, draft_id=draft, payload_canonical=body, expires_at=far
                )
            )
            assert await too_far == "EXPIRY"
    finally:
        await forget(app_conn, runs, [])


def far_body(run: UUID, expires: Any, scope: dict[str, str]) -> bytes:
    """A revision-1 payload of `run` on its asset and interval, expiring at `expires` (the freeze refuses more than 15
    minutes, ruling 5)."""
    return canonical_json(
        {
            "tenant_id": str(ALPHA),
            "run_id": str(run),
            "proposal_id": str(uuid4()),
            "revision": 1,
            **scope,
            "supersedes_run_id": None,
            "workflow_version": WORKFLOW,
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
        }
    )


async def test_the_grant_re_checks_authority_sources_observation_and_binding(
    app_conn: persistence.Conn, role_conn: RoleConn, ingested: None
) -> None:
    """R045, R116, R100, DEV-010, DEV-020: each committed refusal moves the run to BLOCKED_REVIEW with its reason and
    grants nothing; the binding refusals (another run's proposal, an approval of other bytes) raise and commit
    nothing. Then a clean approval is granted once, and a revision after it is refused (R090)."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    pat = await member(app_conn, "reviewer")
    section = await permitted_section(app_conn)
    runs: list[UUID] = []

    async def approved(*, reviewer: UUID = SAM, snapshots: list[dict[str, str]] | None = None) -> tuple[UUID, UUID]:
        run = await drafting_on(app_conn, api, worker, asset())
        runs.append(run)
        result, digest = await frozen(app_conn, worker, run, snapshots=snapshots)
        await decide(api, result.proposal_id, digest, reviewer=reviewer)
        assert result.proposal_id is not None
        return run, result.proposal_id

    try:
        # R045 / DEV-010: the reviewer is deactivated by the sync after approving.
        run, proposal = await approved(reviewer=pat)
        await app_conn.execute("UPDATE app.memberships SET active = false WHERE subject = %s", (pat,))
        blocked = await grant(app_conn, mcp_exec, run, proposal)
        assert isinstance(blocked, persistence.Blocked) and blocked.reason.value == "authority_revoked"
        assert await state_of(app_conn, run) == ("BLOCKED_REVIEW", "authority_revoked")
        # DEV-020: the proposal froze a hash of the cited section that the corpus no longer has.
        stale = {**section, "content_sha256": "0" * 64}
        run, proposal = await approved(snapshots=[stale])
        blocked = await grant(app_conn, mcp_exec, run, proposal)
        assert isinstance(blocked, persistence.Blocked) and blocked.reason.value == "stale_evidence"
        # R116: the asset status was observed more than five minutes ago.
        run, proposal = await approved(snapshots=[section])
        await app_conn.execute(
            "UPDATE app.runs SET asset_observed_at = app.current_time() - interval '6 minutes' WHERE run_id = %s",
            (run,),
        )
        blocked = await grant(app_conn, mcp_exec, run, proposal)
        assert isinstance(blocked, persistence.Blocked) and blocked.reason.value == "stale_evidence"
        assert await state_of(app_conn, run) == ("BLOCKED_REVIEW", "stale_evidence")
        # The binding refusals: another run's proposal through this run's handle (R100), then an approval whose hash
        # is not the proposal's (staged by the superuser: record_decision never stores one). Neither commits.
        run, proposal = await approved(snapshots=[section])
        other, other_proposal = await approved(snapshots=[section])
        assert await refusal(grant(app_conn, mcp_exec, run, other_proposal)) == "PROPOSAL_NOT_IN_RUN"
        await app_conn.execute(
            "UPDATE app.decisions SET expected_payload_sha256 = %s WHERE proposal_id = %s", ("f" * 64, proposal)
        )
        assert await refusal(grant(app_conn, mcp_exec, run, proposal)) == "HASH_MISMATCH"
        assert await state_of(app_conn, run) == ("APPROVED", None)
        # A clean approval is granted, once per run; a revision after it is refused whatever its version (R090).
        granted = await grant(app_conn, mcp_exec, other, other_proposal)
        assert isinstance(granted, persistence.Grant) and granted.proposal_id == other_proposal
        version = (await persistence.run_row(app_conn, other))["state_version"]
        async with api.transaction():
            after = refusal(
                persistence.create_revision(
                    api, tenant_id=ALPHA, run_id=other, expected_version=version, author=ALEX, supersedes_run_id=None
                )
            )
            assert await after == "GRANT_EXISTS"
    finally:
        await forget(app_conn, runs, [pat])


async def test_the_asset_guard_blocks_a_second_action_unless_it_supersedes(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """AM-13, R125 (T21 half), DEV-025: on one asset and interval, a run whose action is unresolved blocks a second
    freeze (asset_action_unresolved); a disjoint interval does not; once the first incident is SUCCEEDED, the second
    is blocked (asset_incident_exists) until a revision names the first run as superseded."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    where = asset()
    runs: list[UUID] = []
    try:
        first = await drafting_on(app_conn, api, worker, where)
        runs.append(first)
        result, digest = await frozen(app_conn, worker, first)
        await decide(api, result.proposal_id, digest)
        granted = await grant(app_conn, mcp_exec, first, result.proposal_id)
        assert isinstance(granted, persistence.Grant)
        second = await drafting_on(app_conn, api, worker, where)
        runs.append(second)
        blocked, _ = await frozen(app_conn, worker, second)
        assert (blocked.state.value, blocked.reason and blocked.reason.value, blocked.proposal_id) == (
            "BLOCKED_REVIEW",
            "asset_action_unresolved",
            None,
        )
        cur = await app_conn.execute(
            "SELECT payload FROM app.events WHERE run_id = %s AND type = 'review.blocked'", (second,)
        )
        assert (await cur.fetchone())["payload"]["message"] == f"blocked by run {first}"  # ruling 10
        disjoint = await drafting_on(app_conn, api, worker, where, days_back=3)
        runs.append(disjoint)
        assert (await frozen(app_conn, worker, disjoint))[0].state.value == "AWAITING_APPROVAL"
        # The first incident commits, as mcp-write records it: SENT, then SUCCEEDED with the destination's receipt.
        handle = await handle_for(app_conn, first, "execute", expires_in=600)
        receipt = Receipt(receipt_id=uuid4(), incident_id="INC-T21-0001", committed_at=datetime.now(UTC))
        outcome = ActionOutcome(
            status=ToolOutcome.SUCCEEDED,
            action_id=granted.action_id,
            payload_sha256=granted.payload_sha256,
            receipt=receipt,
            tombstone=None,
            reason=None,
        )
        async with mcp_exec.transaction():
            await persistence.mark_sent(mcp_exec, handle=handle, azp=GRANT_AZP, action_id=granted.action_id)
        async with mcp_exec.transaction():
            await persistence.record_outcome(
                mcp_exec, handle=handle, azp=GRANT_AZP, action_id=granted.action_id, outcome=outcome
            )
        assert await state_of(app_conn, first) == ("SUCCEEDED", None)
        version = (await persistence.run_row(app_conn, second))["state_version"]
        async with api.transaction():
            await persistence.create_revision(
                api, tenant_id=ALPHA, run_id=second, expected_version=version, author=ALEX, supersedes_run_id=None
            )
        async with worker.transaction():
            await worker.execute(
                "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, %s, '{}')", (second, version + 1)
            )
            await worker.execute(
                "SELECT app.transition_run(%s, 'RETRIEVING', 'DRAFTING', NULL, %s, '{}')", (second, version + 2)
            )
        again, _ = await frozen(app_conn, worker, second, revision=2)
        assert (again.state.value, again.reason and again.reason.value) == ("BLOCKED_REVIEW", "asset_incident_exists")
        # R125: only a request that names the first run proceeds, and the payload carries the run's supersession.
        version = (await persistence.run_row(app_conn, second))["state_version"]
        async with api.transaction():
            await persistence.create_revision(
                api, tenant_id=ALPHA, run_id=second, expected_version=version, author=ALEX, supersedes_run_id=first
            )
        async with worker.transaction():
            await worker.execute(
                "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, %s, '{}')", (second, version + 1)
            )
            await worker.execute(
                "SELECT app.transition_run(%s, 'RETRIEVING', 'DRAFTING', NULL, %s, '{}')", (second, version + 2)
            )
        superseding, _ = await frozen(app_conn, worker, second, revision=3, supersedes=first)
        assert superseding.state.value == "AWAITING_APPROVAL"
    finally:
        await forget(app_conn, runs, [])


async def test_cancel_before_and_after_the_grant(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """R046 (T21 half), DEV-014: before a grant the run's requester cancels at once (BLOCKED_REVIEW included); after
    one only the flag is set and the attempt's state reported, never an undo; a stranger is refused."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    runs: list[UUID] = []
    try:
        run = await drafting_on(app_conn, api, worker, asset())
        runs.append(run)

        async def cancel(target: UUID, actor: UUID, version: int) -> persistence.Cancelled:
            async with api.transaction():
                return await persistence.request_cancel(
                    api, tenant_id=ALPHA, run_id=target, expected_version=version, actor=actor
                )

        assert await refusal(cancel(run, uuid4(), 3)) == "NOT_CANCELLER"
        cancelled = await cancel(run, ALEX, 3)
        assert (cancelled.state.value, cancelled.grant_exists, cancelled.attempt_state) == ("CANCELLED", False, None)
        executing = await drafting_on(app_conn, api, worker, asset())
        runs.append(executing)
        result, digest = await frozen(app_conn, worker, executing)
        await decide(api, result.proposal_id, digest)
        assert isinstance(await grant(app_conn, mcp_exec, executing, result.proposal_id), persistence.Grant)
        version = (await persistence.run_row(app_conn, executing))["state_version"]
        after = await cancel(executing, SAM, version)  # any reviewer of the tenant may ask (ruling 12)
        assert (after.state.value, after.grant_exists, after.attempt_state and after.attempt_state.value) == (
            "EXECUTING",
            True,
            "INTENT",
        )
        row = await persistence.run_row(app_conn, executing)
        assert (row["state"], row["cancel_requested"]) == ("EXECUTING", True)
    finally:
        await forget(app_conn, runs, [])


def idem(route: str, subject: UUID, body: dict[str, Any], path: dict[str, str] | None = None) -> Idem:
    """A fresh idempotency scope for one DbStore mutation."""
    return Idem(Scope(ALPHA, subject, route, f"t21-{uuid4()}"), fingerprint(path or {}, body), 86400, uuid4())


async def test_a_manual_proposal_takes_the_same_review_and_feedback_changes_nothing_else(
    app_conn: persistence.Conn, role_conn: RoleConn, ingested: None
) -> None:
    """R057, R093, note 4, R113: a person's proposal for a run the model could not draft for is frozen through the
    freeze rules with `prompt_version` "manual" and a draft row of source `manual`; a section of another tenant is
    404 with nothing written; its author cannot approve it. Feedback writes one row and one `feedback.recorded`
    event with three keys and nothing else."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    store = DbStore(api)
    reviewer = await member(app_conn, "reviewer")  # a reviewer may author a manual proposal (SA:542)
    section = await permitted_section(app_conn)
    run = await drafting_on(app_conn, api, worker, asset())
    try:
        row = await persistence.run_row(app_conn, run)
        body = {
            "run_id": str(run),
            "asset_id": row["asset_id"],
            "start_at": row["start_at"].isoformat().replace("+00:00", "Z"),
            "end_at": row["end_at"].isoformat().replace("+00:00", "Z"),
            "title": "Manual incident",
            "summary": "Written by a person while the model was unavailable.",
            "evidence_refs": [section["evidence_id"]],
            "assumptions": [],
            "limitations": ["manual"],
        }
        # Note 4 (round 1, I4): a real permitted section of BETA, cited from ALPHA, is 404 with nothing written.
        foreign = {**body, "evidence_refs": [(await permitted_section(app_conn, BETA))["evidence_id"]]}
        missing = await store.manual_once(
            idem=idem("POST /api/v1/manual-proposals", reviewer, foreign),
            tenant_id=ALPHA,
            author=reviewer,
            request=load(ManualProposalRequest, json.dumps(foreign)),
        )
        assert missing.status == 404
        assert (await count(app_conn, "drafts", run), await count(app_conn, "proposals", run)) == (0, 0)
        assert (await persistence.run_row(app_conn, run))["authors"] == [ALEX]  # nobody joined the authors
        # The definer's own check, without the API's pre-check: a payload naming another asset (B22, BETA's) is 404
        # `asset` with nothing written.
        other_asset = canonical_json(
            {
                "tenant_id": str(ALPHA),
                "run_id": str(run),
                "proposal_id": str(uuid4()),
                "revision": 1,
                "action": "create_incident",
                "destination": "synthetic-incidents",
                **await scope_of(app_conn, run),
                "asset_id": "B22",
            }
        )
        with pytest.raises(persistence.NotFound, match="asset"):
            async with api.transaction():
                await persistence.create_manual_proposal(
                    api, tenant_id=ALPHA, run_id=run, payload_canonical=other_asset, author=reviewer
                )
        assert (await count(app_conn, "drafts", run), await count(app_conn, "proposals", run)) == (0, 0)
        made = await store.manual_once(
            idem=idem("POST /api/v1/manual-proposals", reviewer, body),
            tenant_id=ALPHA,
            author=reviewer,
            request=load(ManualProposalRequest, json.dumps(body)),
        )
        assert made.status == 201 and made.body["status"] == "AWAITING_APPROVAL", made
        cur = await app_conn.execute(
            "SELECT p.payload, p.payload_sha256, p.authored_by, d.source FROM app.proposals p"
            " JOIN app.drafts d ON d.id = p.draft_id WHERE p.proposal_id = %s",
            (UUID(made.body["proposal_id"]),),
        )
        frozen_row = await cur.fetchone()
        assert frozen_row["payload"]["prompt_version"] == "manual" and frozen_row["source"] == "manual"
        assert frozen_row["payload"]["source_snapshots"] == [section]
        assert frozen_row["authored_by"] == [ALEX, reviewer]  # the run's requester, then the person (ruling 4)
        digest = frozen_row["payload_sha256"]
        assert await refusal(decide(api, UUID(made.body["proposal_id"]), digest, reviewer=reviewer)) == "SELF_REVIEW"
        # Feedback (R113): only its row and its event change; the run, its proposal and its jobs stay as they were,
        # and no other table gains or loses a row (round 1, M11).
        before = await persistence.run_row(app_conn, run)
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.jobs WHERE run_id = %s", (run,))
        jobs = (await cur.fetchone())["n"]
        tables = ("proposals", "decisions", "memberships", "messages", "drafts", "runs", "jobs", "outbox")
        counted = {table: await count(app_conn, table) for table in (*tables, "feedback", "events")}
        note = {"subject_kind": "proposal", "subject_id": made.body["proposal_id"], "category": "unclear", "text": "?"}
        recorded = await store.feedback_once(
            idem=idem("POST /api/v1/runs/{run_id}/feedback", ALEX, note, {"run_id": str(run)}),
            tenant_id=ALPHA,
            run_id=run,
            author=ALEX,
            request=load(FeedbackRequest, json.dumps(note)),
        )
        assert recorded.status == 201
        cur = await app_conn.execute("SELECT category, text, author FROM app.feedback WHERE run_id = %s", (run,))
        assert [dict(r) for r in await cur.fetchall()] == [{"category": "unclear", "text": "?", "author": ALEX}]
        cur = await app_conn.execute(
            "SELECT payload FROM app.events WHERE run_id = %s AND type = 'feedback.recorded'", (run,)
        )
        assert [r["payload"] for r in await cur.fetchall()] == [
            {"subject_kind": "proposal", "subject_id": made.body["proposal_id"], "category": "unclear"}
        ]  # the text stays in the row (erratum 136)
        after = await persistence.run_row(app_conn, run)
        assert {k: after[k] for k in ("state", "state_version", "active_proposal_id")} == {
            k: before[k] for k in ("state", "state_version", "active_proposal_id")
        }
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.jobs WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["n"] == jobs
        assert {table: await count(app_conn, table) for table in (*tables, "feedback", "events")} == {
            **{table: counted[table] for table in tables},
            "feedback": counted["feedback"] + 1,
            "events": counted["events"] + 1,
        }
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # the api role may insert feedback, never edit it
            async with api.transaction():
                await persistence.set_tenant(api, ALPHA)
                await api.execute("UPDATE app.feedback SET reviewed = true WHERE run_id = %s", (run,))
    finally:
        await forget(app_conn, [run], [reviewer])


async def test_a_revision_into_an_occupied_slot_is_refused(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """R120 (T21 half): a BLOCKED_REVIEW run freed its conversation's slot; once another run holds it, a revision of
    the blocked run is refused SLOT_OCCUPIED and the run stays as it was."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    runs: list[UUID] = []
    try:
        blocked = await drafting_on(app_conn, api, worker, asset())
        runs.append(blocked)
        result, digest = await frozen(app_conn, worker, blocked)
        await decide(api, result.proposal_id, digest)
        await app_conn.execute(
            "UPDATE app.runs SET asset_observed_at = app.current_time() - interval '6 minutes' WHERE run_id = %s",
            (blocked,),
        )
        mcp_exec = await role_conn(Role.MCP_EXEC)
        assert isinstance(await grant(app_conn, mcp_exec, blocked, result.proposal_id), persistence.Blocked)
        row = await persistence.run_row(app_conn, blocked)
        assert (row["state"], row["slot_held"]) == ("BLOCKED_REVIEW", False)
        cur = await app_conn.execute(
            "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, author)"
            " VALUES (%s, %s, %s, 'investigate', 'x', %s) RETURNING message_id",
            (uuid4(), ALPHA, row["conversation_id"], ALEX),
        )
        message = (await cur.fetchone())["message_id"]
        async with api.transaction():
            cur = await api.execute(
                "SELECT * FROM app.create_run(%s, %s, %s, 'investigate', NULL)",
                (
                    ALPHA,
                    row["conversation_id"],
                    Jsonb(
                        {
                            "message_id": str(message),
                            "requester": str(ALEX),
                            "asset_id": asset(),
                            "start_at": row["start_at"].isoformat(),
                            "end_at": row["end_at"].isoformat(),
                        }
                    ),
                ),
            )
            runs.append((await cur.fetchone())["run_id"])
        async with api.transaction():
            occupied = refusal(
                persistence.create_revision(
                    api,
                    tenant_id=ALPHA,
                    run_id=blocked,
                    expected_version=row["state_version"],
                    author=ALEX,
                    supersedes_run_id=None,
                )
            )
            assert await occupied == "SLOT_OCCUPIED"
        assert await state_of(app_conn, blocked) == ("BLOCKED_REVIEW", "stale_evidence")
    finally:
        # The second run and a second message share the blocked run's conversation, so the whole conversation goes.
        for run in runs[:1]:
            cur = await app_conn.execute("SELECT conversation_id FROM app.runs WHERE run_id = %s", (run,))
            found = await cur.fetchone()
            if found is not None:
                await purge_conversation(app_conn, found["conversation_id"])


async def test_the_read_path_refuses_a_membership_the_sync_has_not_stamped(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 14 (erratum 105): `asset_scope` and the search defer (MEMBERSHIP_STALE) when the run's requester row
    was last stamped more than 120 s ago, as the grant does; a stamped row reads again."""
    api, worker, mcp_read = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    run = await drafting_on(app_conn, api, worker, asset())
    try:
        fence = await stage_lease(app_conn, run)
        raw = f"handle-{uuid4().hex}"
        cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'investigate'", (run,))
        job = (await cur.fetchone())["id"]
        await app_conn.execute(
            "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, fence, expires_at)"
            " VALUES (%s, %s, %s, 'read', %s, %s, now() + interval '10 minutes')",
            (sha256_hex(raw.encode()), run, job, GRANT_AZP, fence),
        )
        await app_conn.execute(
            "UPDATE app.memberships SET synced_at = app.current_time() - interval '121 seconds'"
            " WHERE tenant_id = %s AND subject = %s",
            (ALPHA, ALEX),
        )
        with pytest.raises(persistence.Refused, match="MEMBERSHIP_STALE"):
            await persistence.asset_scope(mcp_read, handle=raw, azp=GRANT_AZP)
        with pytest.raises(persistence.Refused, match="MEMBERSHIP_STALE"):
            await persistence.search_procedures(
                mcp_read, handle=raw, azp=GRANT_AZP, query="turbine", asset_type=None, limit=8
            )
        await app_conn.execute("UPDATE app.memberships SET synced_at = app.current_time() WHERE subject = %s", (ALEX,))
        assert (await persistence.asset_scope(mcp_read, handle=raw, azp=GRANT_AZP)).run_id == run
    finally:
        await purge_run(app_conn, run)


async def test_the_grant_applies_the_guard_across_conversations_and_its_own_expiry(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Round 1, I3 (AM-13 SA:283-288, R110's case, R125 at the grant, R092 at the grant): three runs on one asset and
    interval, each in its own conversation, freeze and are approved while no action exists; the first is granted, the
    second's grant is refused asset_action_unresolved and the third's, once the first incident committed,
    asset_incident_exists, each with BLOCKED_REVIEW and no grant row. A touching interval (c = b) is no overlap, one
    second more is; an action.late_evidence SUCCEEDED counts as an incident; an ABANDONED_UNVERIFIED run's unresolved
    action blocks nothing; and a grant past the expiry commits BLOCKED_REVIEW(expired) with one review.blocked."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    harness = await role_conn(Role.TEST_HARNESS)
    runs: list[UUID] = []

    async def approved(where: str, **on: Any) -> tuple[UUID, UUID]:
        run = await drafting_on(app_conn, api, worker, where, **on)
        runs.append(run)
        result, digest = await frozen(app_conn, worker, run)
        assert result.proposal_id is not None, result
        await decide(api, result.proposal_id, digest)
        return run, result.proposal_id

    async def blocked_by(run: UUID, proposal: UUID, reason: str) -> None:
        verdict = await grant(app_conn, mcp_exec, run, proposal)
        assert isinstance(verdict, persistence.Blocked) and verdict.reason.value == reason, verdict
        assert await state_of(app_conn, run) == ("BLOCKED_REVIEW", reason)
        assert await count(app_conn, "execution_grant", run) == 0

    async def frozen_state(run: UUID) -> tuple[str, str | None]:
        result, _ = await frozen(app_conn, worker, run)
        return result.state.value, result.reason and result.reason.value

    try:
        where = asset()
        first, first_proposal = await approved(where)
        second, second_proposal = await approved(where)
        third, third_proposal = await approved(where)
        granted = await grant(app_conn, mcp_exec, first, first_proposal)
        assert isinstance(granted, persistence.Grant)
        await blocked_by(second, second_proposal, "asset_action_unresolved")
        await commit_incident(app_conn, mcp_exec, first, granted)
        await blocked_by(third, third_proposal, "asset_incident_exists")
        # SA:283: [a, b) and [c, d) overlap when a < d and c < b, so a touching interval is free.
        touched = asset()
        cur = await app_conn.execute("SELECT date_trunc('second', app.current_time()) AS at")
        at = (await cur.fetchone())["at"]
        held_start = at - timedelta(hours=24)
        held, held_proposal = await approved(touched, interval=(held_start, at))
        assert isinstance(await grant(app_conn, mcp_exec, held, held_proposal), persistence.Grant)
        touching = await drafting_on(app_conn, api, worker, touched, interval=(at - timedelta(hours=48), held_start))
        runs.append(touching)
        assert await frozen_state(touching) == ("AWAITING_APPROVAL", None)
        overlapping = await drafting_on(
            app_conn, api, worker, touched, interval=(at - timedelta(hours=48), held_start + timedelta(seconds=1))
        )
        runs.append(overlapping)
        assert await frozen_state(overlapping) == ("BLOCKED_REVIEW", "asset_action_unresolved")
        # Set (b) also holds an incident that only late evidence reported (R6-H5), staged on a failed run.
        late = asset()
        reported = await drafting_on(app_conn, api, worker, late)
        runs.append(reported)
        await app_conn.execute("UPDATE app.runs SET state = 'FAILED', slot_held = false WHERE run_id = %s", (reported,))
        await app_conn.execute(
            "INSERT INTO app.events (event_id, tenant_id, conversation_id, run_id, sequence, type, occurred_at, source,"
            " payload) SELECT gen_random_uuid(), r.tenant_id, r.conversation_id, r.run_id,"
            " (SELECT coalesce(max(e.sequence), 0) + 1 FROM app.events e WHERE e.run_id = r.run_id),"
            " 'action.late_evidence', app.current_time(), 'destination', %s FROM app.runs r WHERE r.run_id = %s",
            (Jsonb({"outcome": "SUCCEEDED"}), reported),
        )
        after_late = await drafting_on(app_conn, api, worker, late)
        runs.append(after_late)
        assert await frozen_state(after_late) == ("BLOCKED_REVIEW", "asset_incident_exists")
        # SA:130: an operator-acknowledged abandoned action blocks nothing, its attempt unresolved or not.
        abandoned_on = asset()
        abandoned, abandoned_proposal = await approved(abandoned_on)
        assert isinstance(await grant(app_conn, mcp_exec, abandoned, abandoned_proposal), persistence.Grant)
        await app_conn.execute(
            "UPDATE app.runs SET state = 'ABANDONED_UNVERIFIED', slot_held = false WHERE run_id = %s", (abandoned,)
        )
        after_abandoned = await drafting_on(app_conn, api, worker, abandoned_on)
        runs.append(after_abandoned)
        assert await frozen_state(after_abandoned) == ("AWAITING_APPROVAL", None)
        # The grant expires an overdue approval itself (SA:140, SA:457), journalling one review.blocked.
        late_grant, late_proposal = await approved(asset())
        try:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '16 minutes'")
            verdict = await grant(app_conn, mcp_exec, late_grant, late_proposal, expires_in=3600)
            assert isinstance(verdict, persistence.Blocked) and verdict.reason.value == "expired", verdict
        finally:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
            await stamp_memberships(app_conn)
        assert await state_of(app_conn, late_grant) == ("BLOCKED_REVIEW", "expired")
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM app.events WHERE run_id = %s AND type = 'review.blocked'", (late_grant,)
        )
        assert (await cur.fetchone())["n"] == 1 and await count(app_conn, "execution_grant", late_grant) == 0
    finally:
        await forget(app_conn, runs, [])


async def test_the_review_doors_refuse_what_they_must(
    app_conn: persistence.Conn, role_conn: RoleConn, ingested: None
) -> None:
    """Round 1, I2 and I5, against PostgreSQL: a freeze of a payload on another asset or interval; a ninth content
    author (AUTHOR_LIMIT); a supersession of a run on another asset at admission and at a revision (404), and of the
    asset's run in another conversation (accepted); a cancel from BLOCKED_REVIEW and at a stale version; the API's
    revision and cancel units with their codes (`DbStore`); and the search, bounded and the tenant's own."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    store = DbStore(api)
    pat = await member(app_conn, "requester")
    runs: list[UUID] = []
    keys: list[str] = []

    def keyed(route: str, subject: UUID, body: dict[str, Any], run: UUID) -> Idem:
        made = idem(route, subject, body, {"run_id": str(run)})
        keys.append(made.scope.key)
        return made

    try:
        # I2: the payload's asset and interval are the run's (SA:154), or the freeze refuses and writes nothing.
        run = await drafting_on(app_conn, api, worker, asset())
        runs.append(run)
        assert await refusal(frozen(app_conn, worker, run, fields={"asset_id": "A17"})) == "PAYLOAD_RUN_MISMATCH"
        shifted = (await persistence.run_row(app_conn, run))["end_at"] + timedelta(seconds=1)
        later = {"end_at": shifted.astimezone(UTC).isoformat().replace("+00:00", "Z")}
        assert await refusal(frozen(app_conn, worker, run, fields=later)) == "PAYLOAD_RUN_MISMATCH"
        assert await count(app_conn, "proposals", run) == 0
        result, _ = await frozen(app_conn, worker, run)
        assert result.state.value == "AWAITING_APPROVAL"
        # AUTHOR_LIMIT: seven more authors staged, so the reviser would be the ninth (Proposal.authored_by holds 8).
        await app_conn.execute(
            "UPDATE app.runs SET authors = authors || %s::uuid[] WHERE run_id = %s", ([uuid4() for _ in range(7)], run)
        )
        version = (await persistence.run_row(app_conn, run))["state_version"]
        revise = {"expected_version": version}
        ninth = await store.revise_once(
            idem=keyed("POST /api/v1/runs/{run_id}/revisions", pat, revise, run),
            tenant_id=ALPHA,
            run_id=run,
            author=pat,
            request=load(RevisionRequest, json.dumps(revise)),
        )
        assert (ninth.status, ninth.body["code"]) == (409, "AUTHOR_LIMIT")
        # Supersession (erratum 138): a run of the tenant on another asset is no target, at admission or revision.
        elsewhere = await drafting_on(app_conn, api, worker, asset())
        runs.append(elsewhere)
        same_asset = await drafting_on(app_conn, api, worker, "A17")  # create_run's request names A17
        runs.append(same_asset)
        conv, msg = await conversation(app_conn, ALPHA)
        admit = "SELECT * FROM app.create_run(%s, %s, %s, 'investigate', %s)"
        assert await refused(api, admit, (ALPHA, conv, request(msg), elsewhere)) == "OC002"
        async with api.transaction():
            cur = await api.execute(admit, (ALPHA, conv, request(msg), same_asset))  # another conversation's run
            admitted = (await cur.fetchone())["run_id"]
        runs.append(admitted)
        assert (await persistence.run_row(app_conn, admitted))["supersedes_run_id"] == same_asset
        with pytest.raises(persistence.NotFound, match="supersedes_run_id"):
            async with api.transaction():
                await persistence.create_revision(
                    api, tenant_id=ALPHA, run_id=run, expected_version=version, author=ALEX, supersedes_run_id=elsewhere
                )
        # The API's revision unit: a stale version is its recorded 409, the current one a 202 with revision 2.
        await app_conn.execute("UPDATE app.runs SET authors = ARRAY[requester] WHERE run_id = %s", (run,))
        stale = {"expected_version": version - 1}
        conflict = await store.revise_once(
            idem=keyed("POST /api/v1/runs/{run_id}/revisions", ALEX, stale, run),
            tenant_id=ALPHA,
            run_id=run,
            author=ALEX,
            request=load(RevisionRequest, json.dumps(stale)),
        )
        assert (conflict.status, conflict.body["code"]) == (409, "VERSION_CONFLICT")
        revised = await store.revise_once(
            idem=keyed("POST /api/v1/runs/{run_id}/revisions", ALEX, revise, run),
            tenant_id=ALPHA,
            run_id=run,
            author=ALEX,
            request=load(RevisionRequest, json.dumps(revise)),
        )
        assert (revised.status, revised.body["revision"], revised.body["status"]) == (202, 2, "QUEUED")
        # Cancel from BLOCKED_REVIEW (erratum 139) through the API's unit: a stranger is refused unrecorded, a stale
        # version is 409, the run's requester cancels.
        blocked = await drafting_on(app_conn, api, worker, asset())
        runs.append(blocked)
        held, digest = await frozen(app_conn, worker, blocked)
        await decide(api, held.proposal_id, digest)
        await app_conn.execute(
            "UPDATE app.runs SET asset_observed_at = app.current_time() - interval '6 minutes' WHERE run_id = %s",
            (blocked,),
        )
        assert isinstance(await grant(app_conn, mcp_exec, blocked, held.proposal_id), persistence.Blocked)
        version = (await persistence.run_row(app_conn, blocked))["state_version"]
        cancel, stale_cancel = {"expected_version": version}, {"expected_version": version - 1}
        with pytest.raises(Forbidden):
            await store.cancel_once(
                idem=keyed("POST /api/v1/runs/{run_id}/cancel", JORDAN, cancel, blocked),
                tenant_id=ALPHA,
                run_id=blocked,
                actor=JORDAN,  # BETA's reviewer: no member of ALPHA (NOT_CANCELLER)
                request=load(CancelRequest, json.dumps(cancel)),
            )
        late = await store.cancel_once(
            idem=keyed("POST /api/v1/runs/{run_id}/cancel", ALEX, stale_cancel, blocked),
            tenant_id=ALPHA,
            run_id=blocked,
            actor=ALEX,
            request=load(CancelRequest, json.dumps(stale_cancel)),
        )
        assert (late.status, late.body["code"]) == (409, "VERSION_CONFLICT")
        done = await store.cancel_once(
            idem=keyed("POST /api/v1/runs/{run_id}/cancel", ALEX, cancel, blocked),
            tenant_id=ALPHA,
            run_id=blocked,
            actor=ALEX,
            request=load(CancelRequest, json.dumps(cancel)),
        )
        assert (done.status, done.body["status"], done.body["grant_exists"]) == (200, "CANCELLED", False)
        # The search (erratum 135): at most `limit` hits, every one a section of the caller's tenant.
        cur = await app_conn.execute(
            "SELECT c.section FROM app.chunks c WHERE c.tenant_id = %s AND c.evidence_id = %s",
            (ALPHA, (await permitted_section(app_conn))["evidence_id"]),
        )
        query = {"query": (await cur.fetchone())["section"], "limit": 3}
        found = await store.search(ALPHA, load(SearchRequest, json.dumps(query)))
        cur = await app_conn.execute("SELECT evidence_id FROM app.chunks WHERE tenant_id = %s", (ALPHA,))
        own = {r["evidence_id"] for r in await cur.fetchall()}
        hits = [hit["evidence_id"] for hit in found["results"]]
        assert 1 <= len(hits) <= 3 and set(hits) <= own, found
    finally:
        await app_conn.execute("DELETE FROM app.idempotency_request WHERE key = ANY(%s)", (keys,))
        await forget(app_conn, runs, [pat])


async def test_the_guard_counts_an_escalated_run_until_the_operator_abandons_it(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Task 2 review I1 (SA:284): a run that reached ESCALATED through a CONFLICT outcome has a RESOLVED attempt yet
    the destination may hold an incident, so it still blocks: the grant of an approved second run and the freeze of
    a third are refused asset_action_unresolved, BLOCKED_REVIEW naming the first run, with no proposal and no grant
    written. Once the operator abandons the first run (ABANDONED_UNVERIFIED, SA:130) a fourth run freezes."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    where = asset()
    runs: list[UUID] = []

    async def approved() -> tuple[UUID, UUID]:
        run = await drafting_on(app_conn, api, worker, where)
        runs.append(run)
        result, digest = await frozen(app_conn, worker, run)
        assert result.proposal_id is not None, result
        await decide(api, result.proposal_id, digest)
        return run, result.proposal_id

    async def blocking_messages(run: UUID) -> list[str]:
        cur = await app_conn.execute(
            "SELECT payload->>'message' AS message FROM app.events WHERE run_id = %s AND type = 'review.blocked'",
            (run,),
        )
        return [row["message"] for row in await cur.fetchall()]

    try:
        first, first_proposal = await approved()
        second, second_proposal = await approved()  # approved while no action exists, granted after the escalation
        granted = await grant(app_conn, mcp_exec, first, first_proposal)
        assert isinstance(granted, persistence.Grant)
        # Staged as the superuser: the CONFLICT outcome resolved the attempt and escalated the run (SA:130, SA:284).
        await app_conn.execute(
            "INSERT INTO app.action_attempt_state (tenant_id, action_id, attempt_no, seq, state, outcome, at)"
            " SELECT g.tenant_id, g.action_id, 1, 2, 'RESOLVED', 'CONFLICT', app.current_time()"
            " FROM app.execution_grant g WHERE g.run_id = %s",
            (first,),
        )
        await app_conn.execute("UPDATE app.runs SET state = 'ESCALATED' WHERE run_id = %s", (first,))
        verdict = await grant(app_conn, mcp_exec, second, second_proposal)
        assert isinstance(verdict, persistence.Blocked), verdict
        assert verdict.reason.value == "asset_action_unresolved"
        assert await state_of(app_conn, second) == ("BLOCKED_REVIEW", "asset_action_unresolved")
        assert await count(app_conn, "execution_grant", second) == 0
        assert await blocking_messages(second) == [f"blocked by run {first}"]
        third = await drafting_on(app_conn, api, worker, where)
        runs.append(third)
        refused_freeze, _ = await frozen(app_conn, worker, third)
        assert (refused_freeze.state.value, refused_freeze.reason and refused_freeze.reason.value) == (
            "BLOCKED_REVIEW",
            "asset_action_unresolved",
        )
        assert refused_freeze.proposal_id is None
        assert await blocking_messages(third) == [f"blocked by run {first}"]
        assert (await count(app_conn, "proposals", third), await count(app_conn, "execution_grant", third)) == (0, 0)
        await app_conn.execute(
            "UPDATE app.runs SET state = 'ABANDONED_UNVERIFIED', slot_held = false WHERE run_id = %s", (first,)
        )
        fourth = await drafting_on(app_conn, api, worker, where)
        runs.append(fourth)
        after_abandoned, _ = await frozen(app_conn, worker, fourth)
        assert after_abandoned.state.value == "AWAITING_APPROVAL"
    finally:
        await forget(app_conn, runs, [])


async def test_a_committed_grant_verdict_replays_without_writing(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Task 2 fix round 1: a retry of a grant whose BLOCKED_REVIEW verdict committed (its response lost) gets that
    verdict again from the reason the run keeps: the same reason, and no grant row, no attempt row and no second
    `review.blocked` event, the run still BLOCKED_REVIEW."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    where = asset()
    runs: list[UUID] = []
    try:
        first = await drafting_on(app_conn, api, worker, where)
        runs.append(first)
        result, digest = await frozen(app_conn, worker, first)
        await decide(api, result.proposal_id, digest)
        second = await drafting_on(app_conn, api, worker, where)
        runs.append(second)
        again, again_digest = await frozen(app_conn, worker, second)
        await decide(api, again.proposal_id, again_digest)
        assert isinstance(await grant(app_conn, mcp_exec, first, result.proposal_id), persistence.Grant)
        assert again.proposal_id is not None
        handle = await handle_for(app_conn, second, "execute", expires_in=600)

        async def call() -> Any:
            async with mcp_exec.transaction():
                return await persistence.grant_execution(
                    mcp_exec, handle=handle, azp=GRANT_AZP, proposal_id=again.proposal_id
                )

        committed = await call()
        assert isinstance(committed, persistence.Blocked) and committed.reason.value == "asset_action_unresolved"
        before = {table: await count(app_conn, table) for table in ("execution_grant", "action_attempt", "events")}
        replayed = await call()
        assert isinstance(replayed, persistence.Blocked), replayed
        assert (replayed.run_id, replayed.proposal_id, replayed.reason) == (
            committed.run_id,
            committed.proposal_id,
            committed.reason,
        )
        assert await state_of(app_conn, second) == ("BLOCKED_REVIEW", "asset_action_unresolved")
        assert await count(app_conn, "execution_grant", second) == 0
        assert {table: await count(app_conn, table) for table in before} == before
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM app.events WHERE run_id = %s AND type = 'review.blocked'", (second,)
        )
        assert (await cur.fetchone())["n"] == 1
    finally:
        await forget(app_conn, runs, [])


async def test_the_decision_route_commits_the_expiry_in_its_own_unit(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Task 4 review I2 (DEV-008, `DbStore.expire_due`): the API's decision on an expired proposal answers 409 EXPIRED,
    and the expiry has committed in a unit of its own anyway: read separately, the run is BLOCKED_REVIEW(expired)
    with exactly one `review.blocked` event."""
    api, worker, harness = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.TEST_HARNESS)
    store = DbStore(api)
    run = await drafting_on(app_conn, api, worker, asset())
    key = None
    try:
        result, digest = await frozen(app_conn, worker, run)
        assert result.proposal_id is not None
        body = {"expected_revision": 1, "expected_payload_sha256": digest, "decision": "approve"}
        made = idem(
            "POST /api/v1/proposals/{proposal_id}/decisions", SAM, body, {"proposal_id": str(result.proposal_id)}
        )
        key = made.scope.key
        try:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '16 minutes'")
            await stamp_memberships(app_conn)  # the sync's stamp at the moved clock
            answer = await store.decide_once(
                idem=made,
                tenant_id=ALPHA,
                proposal_id=result.proposal_id,
                reviewer=SAM,
                roles=frozenset({"reviewer"}),
                request=load(DecisionRequest, json.dumps(body)),
            )
        finally:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
            await stamp_memberships(app_conn)  # round 1, M8: no row stays stamped in the future
        assert (answer.status, answer.body["code"]) == (409, "EXPIRED"), answer
        # A separate read: the 409 did not take the expiry back.
        assert await state_of(app_conn, run) == ("BLOCKED_REVIEW", "expired")
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM app.events WHERE run_id = %s AND type = 'review.blocked'", (run,)
        )
        assert (await cur.fetchone())["n"] == 1
    finally:
        if key is not None:
            await app_conn.execute("DELETE FROM app.idempotency_request WHERE key = %s", (key,))
        await forget(app_conn, [run], [])


async def test_the_wakeup_sweep_re_arms_the_current_revisions_job(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Task 5 re-review advisory (R023, Plan R round 1, M1) on PostgreSQL: a run revised to revision 2 whose current
    investigate job is done and lost has its `run_id:2` job re-armed (open and unclaimed), never revision 1's, although
    revision 1's job finished more recently."""
    api, worker, sweeper = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.SWEEPER)
    run = await drafting_on(app_conn, api, worker, asset())
    try:
        await frozen(app_conn, worker, run)
        version = (await persistence.run_row(app_conn, run))["state_version"]
        async with api.transaction():
            await persistence.create_revision(
                api, tenant_id=ALPHA, run_id=run, expected_version=version, author=ALEX, supersedes_run_id=None
            )
        cur = await app_conn.execute(
            "SELECT id, dedup_key FROM app.jobs WHERE run_id = %s AND type = 'investigate'", (run,)
        )
        jobs = {row["dedup_key"]: row["id"] for row in await cur.fetchall()}
        assert set(jobs) == {f"{run}:1", f"{run}:2"}
        # Both past the grace; revision 1's finished later, so a sweep that did not key on the revision would pick it.
        await finish(app_conn, jobs[f"{run}:1"], seconds_ago=CHOSEN.grace_seconds + 10, attempts=1)
        await finish(app_conn, jobs[f"{run}:2"], seconds_ago=CHOSEN.grace_seconds + 240, attempts=1)
        found = [w for w in await wakeups.sweep(sweeper, CHOSEN, tenants=[ALPHA]) if w.run_id == run]
        assert [(w.job_id, w.job_type, w.rearmed) for w in found] == [(jobs[f"{run}:2"], "investigate", True)]
        cur = await app_conn.execute(
            "SELECT dedup_key, done_at IS NULL AS open FROM app.jobs WHERE run_id = %s AND type = 'investigate'", (run,)
        )
        assert {row["dedup_key"]: row["open"] for row in await cur.fetchall()} == {f"{run}:1": False, f"{run}:2": True}
        # The re-armed row is the run's own `run_id:2` job, reopened and unclaimed, ready for the next claim; the
        # claim itself is not made here, because `claim_next` takes whatever ALPHA job is due, not this run's.
        cur = await app_conn.execute(
            "SELECT claimed_by, claimed_at, attempts FROM app.jobs WHERE id = %s", (jobs[f"{run}:2"],)
        )
        assert dict(await cur.fetchone()) == {"claimed_by": None, "claimed_at": None, "attempts": 1}
    finally:
        await forget(app_conn, [run], [])


async def test_the_round_trip_restores_0015(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Revision 0016 down and up: its functions, columns and the feedback table go, 0015's `record_decision` and its
    grant come back, and the head is identical afterwards (function text, owner, ACL)."""
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    head = await snapshot(app_conn)
    new = {"app.create_revision(", "app.request_cancel(", "app.create_manual_proposal(", "app._asset_guard("}
    assert all(any(s.startswith(n) for s in head) for n in new)
    try:
        downgrade("app", superuser, "0015_checkpoints")
        after = await snapshot(app_conn)
        assert not any(s.startswith(n) for s in after for n in new)
        assert "app.record_decision(uuid,uuid,uuid,text,text,text,text)" in after
        cur = await app_conn.execute(
            "SELECT to_regclass('app.feedback') IS NULL AS gone, NOT EXISTS (SELECT 1 FROM information_schema.columns"
            " WHERE table_schema = 'app' AND table_name = 'runs' AND column_name = 'authors') AS no_authors"
        )
        assert dict(await cur.fetchone()) == {"gone": True, "no_authors": True}
    finally:
        assert migrate(settings.Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head


async def snapshot(conn: persistence.Conn) -> dict[str, dict[str, Any]]:
    cur = await conn.execute(APP_FUNCTIONS)
    return {row["signature"]: {k: v for k, v in row.items() if k != "signature"} for row in await cur.fetchall()}
