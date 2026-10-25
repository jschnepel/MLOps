"""Revision 0016 without a database (T21; Plan R rulings 1-18; R090, R093, R100, R110's lock, R113, R116, R125).

Catches: a derived body that changes more than the revision names (a lock, a refusal or an event of the applied body
moving unseen); a definer that takes a row lock before the asset guard's advisory lock (SA:189: two conversations
could both pass the guard); a grant whose committed refusal raises instead of returning (its BLOCKED_REVIEW would
roll back, AM-10) or whose binding refusal returns (a refused handle would commit a transition); a decision checked
for staleness before independence (a non-independent reviewer would get a 409 the API records); a feedback table the
api may update, or one outside the matrix and RLS; a run author set that can exceed the proposal's eight; a read path
without the stale-sync bound; and a downgrade that leaves 0016's functions or columns behind.
"""

import re
from typing import Any

import pytest
from ops_core import locking, privileges

from tests.plan_l.test_migration_0011 import revision, statements

ROOT_DEFINERS = ("freeze_proposal", "create_manual_proposal", "prepare_manual_proposal", "grant_execution")


def rev0016() -> Any:
    return revision("0016_review_and_grant")


def bodies(module: Any) -> dict[str, str]:
    return {name: body for name, _, _, body in module.FUNCTIONS}


def test_upgrade_order_and_callers_are_the_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    module = rev0016()
    assert module.down_revision == "0015_checkpoints"
    expected = [*module.SCHEMA_CHANGES]
    expected += privileges.grant_statements(module.TABLES_0016, module.GRANTS_0016, revokees=module.MAIN_GRANTEES_0016)
    expected += privileges.rls_statements(("feedback",), module.POLICY_ROLES_0016)
    expected += [f"DROP FUNCTION app.{s}" for s in module.REPLACED]
    for name, args, callers, body in module.FUNCTIONS:
        expected += [body, *privileges.function_grant_statements(name, args=args, callers=callers)]
        if name.startswith("_"):
            assert callers == () and privileges.HELPER_FUNCTIONS[name] == args, name
        else:
            assert privileges.DEFINER_FUNCTIONS[name] == (args, callers), name
    assert statements(module, "upgrade", monkeypatch) == expected
    assert module.GRANTS_0016 == {table: privileges.GRANTS[table] for table in module.TABLES_0016}


def test_the_derived_bodies_change_only_what_the_revision_names() -> None:
    module = rev0016()
    for derived, applied, changes in (
        (module.APPEND_EVENT_HELPER, module.REV0008.APPEND_EVENT_HELPER, module.APPEND_EVENT_CHANGES),
        (module.RESOLVE_HANDLE, module.REV0009.RESOLVE_HANDLE, module.RESOLVE_CHANGES),
        (module.CREATE_RUN, module.REV0003.CREATE_RUN, module.CREATE_RUN_CHANGES),
        (module.ASSET_SCOPE, module.REV0012.ASSET_SCOPE, module.FRESH_READ),
        (module.SEARCH_PROCEDURES_SCOPED, module.REV0013.SEARCH_PROCEDURES_SCOPED, module.FRESH_READ),
    ):
        undone = derived
        for old, new in changes:
            undone = undone.replace(new, old)
        assert undone == applied
    # The cited-section check and the API's search reuse the search's own filters and query, byte for byte.
    assert module.FILTERS_0012 in module.CITED_PERMITTED and module.QUERY_0012 in module.SEARCH_PROCEDURES_API


@pytest.mark.parametrize("name", ROOT_DEFINERS)
def test_the_asset_lock_comes_before_every_row_lock(name: str) -> None:
    body = bodies(rev0016())[name]
    assert body.index("app._asset_lock(") < body.index("FOR UPDATE"), name  # SA:189: first in the lock order
    if name != "prepare_manual_proposal":
        assert "app._asset_guard(" in body, name  # SA:284: freeze, manual proposal and grant all apply the guard
    if name == "grant_execution":
        assert body.index("app._asset_lock(") < body.index("app._resolve_handle(")  # before run_lease too


def test_the_guard_reads_both_sets_across_conversations() -> None:
    guard = rev0016().ASSET_GUARD
    assert "la.state <> 'RESOLVED' AND r.state <> 'ABANDONED_UNVERIFIED'" in guard  # (a), SA:284 and SA:130
    assert "r.state = 'SUCCEEDED'" in guard and "e.type = 'action.late_evidence'" in guard  # (b), late evidence too
    assert "r.run_id IS DISTINCT FROM p_supersedes_run_id" in guard  # R125: only set (b) is excused
    assert "r.start_at < p_end_at AND p_start_at < r.end_at" in guard  # SA:283: half-open overlap
    assert "conversation_id" not in guard  # SA:288: two conversations meet here


# What the applied bodies refused, and where each refusal went in 0016's rewrites (Plan R round 1, M4): the decision's
# two version conflicts became their own codes (ruling 3), and an inactive member is now a committed refusal.
RENAMED = {
    "first decision wins": "DETAIL = 'ALREADY_DECIDED'",
    "not the active undecided revision": "DETAIL = 'STALE_REVISION'",
    "MEMBERSHIP_INACTIVE": "v_reason := 'authority_revoked'",
}


@pytest.mark.parametrize("name", ("freeze_proposal", "record_decision", "grant_execution"))
def test_every_refusal_of_the_applied_body_survives_its_rewrite(name: str) -> None:
    module = rev0016()
    applied = next(body for restored, _, _, body in module.RESTORED if restored == name)
    rewritten = bodies(module)[name]
    for detail in set(re.findall(r"DETAIL = '([^']+)'", applied)):
        assert RENAMED.get(detail, f"DETAIL = '{detail}'") in rewritten, (name, detail)


def test_the_freeze_binds_the_payload_to_the_runs_asset_and_interval() -> None:
    freeze = bodies(rev0016())["freeze_proposal"]
    binding = freeze.index("DETAIL = 'PAYLOAD_RUN_MISMATCH'")
    for field in (
        "(v_payload->>'asset_id') IS DISTINCT FROM v_run.asset_id",
        "(v_payload->>'start_at')::timestamptz IS DISTINCT FROM v_run.start_at",
        "(v_payload->>'end_at')::timestamptz IS DISTINCT FROM v_run.end_at",
    ):
        assert freeze.index(field) < binding, field  # SA:154, round 1 I2: the guard judges what the payload acts on
    assert binding < freeze.index("app._asset_guard(")


def test_the_grant_reads_each_member_in_its_role_and_refuses_a_future_observation() -> None:
    grant = rev0016().GRANT_EXECUTION
    assert grant.count("m.subject = v_run.requester") == grant.count("AND m.role = 'requester'") == 2  # round 1, M6
    assert "v_run.asset_observed_at > app.current_time()" in grant  # round 1, M2: a future stamp is stale too


def test_the_grant_commits_its_review_refusals_and_raises_the_rest() -> None:
    grant = rev0016().GRANT_EXECUTION
    raised = set(re.findall(r"DETAIL = '([A-Z_]+)'", grant))
    assert raised == {
        "INVALID_ARGUMENT",
        "OTHER_PROPOSAL",
        "PROPOSAL_NOT_IN_RUN",
        "NOT_ACTIVE_APPROVED",
        "NO_APPROVAL",
        "HASH_MISMATCH",
        "CANCELLED",
        "MEMBERSHIP_STALE",
    }
    committed = set(re.findall(r"v_reason := '([a-z_]+)'", grant))
    assert committed == {"expired", "authority_revoked", "stale_evidence"}  # plus the guard's two, from _asset_guard
    assert "'BLOCKED_REVIEW', 'grant_execution', v_reason" in grant and "refusal text" in grant
    assert "interval '5 minutes'" in grant and "app._cited_permitted(" in grant  # R116, BS:425
    # The stale-sync deferral is raised before any committed transition of its branch can happen.
    assert grant.index("'MEMBERSHIP_STALE'") < grant.index("v_reason := 'stale_evidence'")


def test_a_decision_checks_independence_first_then_each_rule_under_the_lock() -> None:
    decision = rev0016().RECORD_DECISION
    order = [
        decision.index(f"DETAIL = '{code}'")
        for code in ("NOT_REVIEWER", "SELF_REVIEW", "ALREADY_DECIDED", "STALE_REVISION", "STALE_HASH", "EXPIRED")
    ]
    assert order == sorted(order)
    assert decision.index("FOR UPDATE") < order[0]
    assert "p_expected_revision integer" in decision  # erratum 131


def test_revisions_cancels_and_manual_proposals_keep_their_rules() -> None:
    every = bodies(rev0016())
    revise = every["create_revision"]
    assert revise.index("'GRANT_EXISTS'") < revise.index("'SLOT_OCCUPIED'")  # R090 first, then R120
    assert "checkpoint_id = NULL" in revise and "format('%s:%s', p_run_id, v_next)" in revise  # ruling 1
    assert "runs_one_active_per_conversation" in revise  # the index stays the backstop (ruling 6)
    for name in ("create_revision", "prepare_manual_proposal", "create_manual_proposal"):
        assert "cardinality(v_authors) > 8" in every[name], name  # ruling 4: Proposal.authored_by holds eight
    assert "v_run.authors, p_expires_at" in every["freeze_proposal"]  # authored_by from runs (erratum 132)
    assert "interval '16 minutes'" in every["freeze_proposal"]  # ruling 5: the payload's expiry, bounded
    assert "'BLOCKED_REVIEW')" in every["request_cancel"]  # erratum 139: a blocked run can be cancelled
    for name in ("asset_scope", "search_procedures_scoped"):
        assert "DETAIL = 'MEMBERSHIP_STALE'" in every[name], name  # ruling 14


def test_feedback_is_api_insert_only_and_a_tenant_table() -> None:
    assert privileges.GRANTS["feedback"] == {"api": privileges.Grant(sel=True, ins=True)}  # R113: no UPDATE anywhere
    assert "feedback" in privileges.RLS_TABLES and "feedback" in locking.NEVER_LOCKED
    ddl = next(s for s in rev0016().SCHEMA_CHANGES if s.startswith("CREATE TABLE app.feedback"))
    assert "char_length(text) <= 2000" in ddl and "reviewed boolean NOT NULL DEFAULT false" in ddl


def test_downgrade_drops_what_it_created_and_restores_the_applied_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    module = rev0016()
    seen = statements(module, "downgrade", monkeypatch)
    assert seen[: len(module.CREATED)] == [f"DROP FUNCTION app.{s}" for s in module.CREATED]
    created = {s.partition("(")[0] for s in module.CREATED}
    replaced = {s.partition("(")[0] for s in module.REPLACED}  # dropped by both directions, re-created by each
    assert {name for name, *_ in module.FUNCTIONS} - created | replaced == {name for name, *_ in module.RESTORED}
    for _, _, _, body in module.RESTORED:
        assert body in seen
    cells = privileges.grant_statements(("runs", "drafts"), module.RESTORED_CELLS, revokees=module.MAIN_GRANTEES_0016)
    assert seen[-len(module.DOWNGRADE_SCHEMA) - len(cells) :] == [*module.DOWNGRADE_SCHEMA, *cells]
