"""Sessions, pre-login state, the logout jti store and the stale-sync rule (T11, Plan F rulings 2, 3, 14, 17).

Revision ID: 0005_sessions_login_logout
Revises: 0004_write_path_functions

`sessions` (BUILD_SPEC §6 shape from 0002) gains the Keycloak session id the back-channel logout revokes by, the
username `/api/v1/me` shows, and the Fernet-sealed refresh token the server-side logout spends; it is truncated first
(empty in every database today; a migration that ends every browser session is acceptable). `login_state` holds the
authorization request's state, nonce and PKCE verifier under the login cookie's hash (SA:565: authlib's state lives
in the store, never in a signed cookie). `logout_jti` is the durable replay store (T11 review note 3). The sweeper
gets SELECT beside its DELETE on all three (erratum 25: a DELETE with a WHERE needs SELECT, spike §4).
`grant_execution` is re-created with one more refusal, MEMBERSHIP_STALE, when a requester's or reviewer's row was not
stamped by the sync within 120 s (T11 review note 2, fail closed). Every cell and caller is frozen here (round-3
finding N1 of Plan E).
"""

from alembic import op
from ops_core import privileges

revision = "0005_sessions_login_logout"
down_revision = "0004_write_path_functions"
branch_labels = None
depends_on = None

HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
GRANT_COLUMNS = (
    "action_id uuid, run_id uuid, proposal_id uuid, tenant_id uuid, conversation_id uuid, payload_sha256 text,"
    " payload_canonical bytea, attempt_state text, detail jsonb"
)
TABLES = ("sessions", "login_state", "logout_jti")
MAIN_GRANTEES_0005 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
GRANTS_0005: dict[str, dict[str, privileges.Grant]] = {
    "sessions": {
        "api": privileges.Grant(sel=True, ins=True, upd=("last_seen_at", "revoked_at"), dele=True),
        "sweeper": privileges.Grant(sel=True, dele=True),
    },
    "login_state": {
        "api": privileges.Grant(sel=True, ins=True, dele=True),
        "sweeper": privileges.Grant(sel=True, dele=True),
    },
    "logout_jti": {"api": privileges.Grant(ins=True), "sweeper": privileges.Grant(sel=True, dele=True)},
}
# What 0002 granted on sessions, for the downgrade (not named GRANTS_*: the newest-revision test folds every
# GRANTS_* attribute into the live matrix check).
SESSIONS_CELLS_0002: dict[str, dict[str, privileges.Grant]] = {
    "sessions": {
        "api": privileges.Grant(sel=True, ins=True, upd=("last_seen_at", "revoked_at"), dele=True),
        "sweeper": privileges.Grant(dele=True),
    }
}

SCHEMA_CHANGES = (
    "TRUNCATE app.sessions",
    (
        "ALTER TABLE app.sessions ADD COLUMN sid text NOT NULL,"
        " ADD COLUMN username text NOT NULL DEFAULT '',"
        " ADD COLUMN refresh_token_enc bytea NOT NULL"
    ),
    "CREATE INDEX sessions_sid_idx ON app.sessions (sid)",
    "CREATE INDEX sessions_identity_idx ON app.sessions (issuer, subject)",
    (
        "CREATE TABLE app.login_state ("
        " login_sha256 text PRIMARY KEY,"
        " state_sha256 text NOT NULL UNIQUE,"
        " nonce_sha256 text NOT NULL,"
        " code_verifier text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " expires_at timestamptz NOT NULL)"
    ),
    (
        "CREATE TABLE app.logout_jti ("
        " jti text PRIMARY KEY,"
        " received_at timestamptz NOT NULL DEFAULT now(),"
        " expires_at timestamptz NOT NULL)"
    ),
    "ALTER TABLE app.login_state OWNER TO migrator",
    "ALTER TABLE app.logout_jti OWNER TO migrator",
)

# grant_execution as 0004 installed it, with the stale-sync rule inserted after MEMBERSHIP_INACTIVE (ruling 14).
GRANT_EXECUTION = f"""
CREATE OR REPLACE FUNCTION app.grant_execution(p_raw_handle text, p_proposal_id uuid)
RETURNS TABLE ({GRANT_COLUMNS})
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_run runs%ROWTYPE;
    v_proposal proposals%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
    v_action_id uuid;
BEGIN
    PERFORM app._authority('grant_execution', ARRAY['mcp_exec']);
    IF p_proposal_id IS NULL THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, 'ops-worker', 'write');
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_handle.run_id FOR UPDATE;
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = v_handle.run_id;
    IF FOUND THEN
        -- UNIQUE (run_id): one grant per run, ever (SA:167); a replay finds the grant it already has.
        IF v_grant.proposal_id IS DISTINCT FROM p_proposal_id THEN
            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'OTHER_PROPOSAL';
        END IF;
        RETURN QUERY SELECT * FROM app._grant_row(v_grant.action_id);
        RETURN;
    END IF;
    SELECT * INTO v_proposal FROM proposals p WHERE p.proposal_id = p_proposal_id AND p.run_id = v_handle.run_id
                                                AND p.tenant_id = v_handle.tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PROPOSAL_NOT_IN_RUN';
    END IF;
    IF v_run.state <> 'APPROVED' OR v_run.active_proposal_id IS DISTINCT FROM p_proposal_id THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_ACTIVE_APPROVED';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM decisions d WHERE d.proposal_id = p_proposal_id AND d.decision = 'approve') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NO_APPROVAL';
    END IF;
    IF v_run.cancel_requested THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'CANCELLED';
    END IF;
    -- The §13 gate re-reads current membership (BS:472): requester and reviewer must still be active members.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                     AND m.subject = v_run.requester AND m.active)
       OR NOT EXISTS (SELECT 1 FROM decisions d JOIN memberships m ON m.tenant_id = v_handle.tenant_id
                                                                      AND m.subject = d.reviewer
                      AND m.role = 'reviewer' AND m.active WHERE d.proposal_id = p_proposal_id) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_INACTIVE';
    END IF;
    -- T11 review note 2: active is only as good as the last sync; without one in 120 s the gate fails closed.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                     AND m.subject = v_run.requester AND m.active
                                                     AND m.synced_at >= app.current_time() - interval '120 seconds')
       OR NOT EXISTS (SELECT 1 FROM decisions d JOIN memberships m ON m.tenant_id = v_handle.tenant_id
                                                                      AND m.subject = d.reviewer
                      AND m.role = 'reviewer' AND m.active
                      AND m.synced_at >= app.current_time() - interval '120 seconds'
                      WHERE d.proposal_id = p_proposal_id) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_STALE';
    END IF;
    -- TODO(T21): asset freshness (5 min) and the asset guard; TODO(T13): the lease fence.
    v_action_id := gen_random_uuid();  -- random inside the gate (SA:168), never derived from the proposal
    INSERT INTO execution_grant (action_id, tenant_id, run_id, proposal_id, payload_sha256, granted_at)
    VALUES (v_action_id, v_handle.tenant_id, v_handle.run_id, p_proposal_id, v_proposal.payload_sha256,
            app.current_time());
    INSERT INTO action_attempt (tenant_id, action_id, attempt_no, created_at)
    VALUES (v_handle.tenant_id, v_action_id, 1, app.current_time());
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, at)
    VALUES (v_handle.tenant_id, v_action_id, 1, 1, 'INTENT', app.current_time());
    PERFORM app._transition(v_handle.run_id, 'EXECUTING', 'grant_execution', NULL, NULL, 'action.granted',
                            jsonb_build_object('action_id', v_action_id, 'proposal_id', p_proposal_id));
    RETURN QUERY SELECT * FROM app._grant_row(v_action_id);
END
$fn$;
ALTER FUNCTION app.grant_execution(text, uuid) OWNER TO app_definer;
"""

# The 0004 body, frozen here so the downgrade restores exactly what 0004 installed (the two bodies differ by the
# MEMBERSHIP_STALE block only; a unit test asserts that).
GRANT_EXECUTION_0004 = GRANT_EXECUTION.replace(
    """    -- T11 review note 2: active is only as good as the last sync; without one in 120 s the gate fails closed.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id
                                                     AND m.subject = v_run.requester AND m.active
                                                     AND m.synced_at >= app.current_time() - interval '120 seconds')
       OR NOT EXISTS (SELECT 1 FROM decisions d JOIN memberships m ON m.tenant_id = v_handle.tenant_id
                                                                      AND m.subject = d.reviewer
                      AND m.role = 'reviewer' AND m.active
                      AND m.synced_at >= app.current_time() - interval '120 seconds'
                      WHERE d.proposal_id = p_proposal_id) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_STALE';
    END IF;
""",
    "",
)
assert GRANT_EXECUTION_0004 != GRANT_EXECUTION  # the replace must have matched

# (name, argument types, callers, body): frozen here (N1); the newest-revision test reads this tuple.
FUNCTIONS = (("grant_execution", "text, uuid", ("mcp_exec",), GRANT_EXECUTION),)

DOWNGRADE = (
    f"REVOKE ALL ON app.login_state, app.logout_jti FROM {', '.join(MAIN_GRANTEES_0005)}",
    "DROP TABLE app.logout_jti",
    "DROP TABLE app.login_state",
    "DROP INDEX app.sessions_identity_idx",
    "DROP INDEX app.sessions_sid_idx",
    "TRUNCATE app.sessions",
    "ALTER TABLE app.sessions DROP COLUMN refresh_token_enc, DROP COLUMN username, DROP COLUMN sid",
)


def upgrade() -> None:
    """Schema first, then the frozen grants, then the re-created gate with its grants (REVOKE lands on the new body)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES, GRANTS_0005, revokees=MAIN_GRANTEES_0005):
        op.execute(statement)
    for name, args, callers, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name, args=args, callers=callers):
            op.execute(statement)


def downgrade() -> None:
    """Restore 0004's gate and 0002's sessions, drop the two tables."""
    op.execute(GRANT_EXECUTION_0004)
    for statement in privileges.function_grant_statements("grant_execution", args="text, uuid", callers=("mcp_exec",)):
        op.execute(statement)
    for statement in DOWNGRADE:
        op.execute(statement)
    for statement in privileges.grant_statements(("sessions",), SESSIONS_CELLS_0002, revokees=MAIN_GRANTEES_0005):
        op.execute(statement)
