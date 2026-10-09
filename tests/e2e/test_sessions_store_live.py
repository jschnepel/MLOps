"""The session store under the api role's real grants (OPS_LIVE=1): the login one-shot and its expiry, liveness
decided by the one UPDATE … RETURNING (idle and absolute), revocation, and the atomic jti-plus-revoke of the
back-channel logout (a rolled-back revocation does not consume the token, spike §5).

Catches: a statement the api cells do not cover (42501 would surface here, not in Task 6), a session that stays live
past a limit, a replayed jti that revokes again.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from ops_api import store as st
from ops_core import persistence
from ops_core.settings import Role

pytestmark = pytest.mark.asyncio

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
ISSUER = "http://localhost:18080/realms/ops-dev"


async def test_revision_guard_names_the_missing_relation(role_conn) -> None:
    api = await role_conn(Role.API)
    await persistence.assert_relation(api, "app.login_state")  # present: a no-op
    with pytest.raises(persistence.PersistenceError) as refusal:
        await persistence.assert_relation(api, "app.no_such_table")
    assert "app.no_such_table is missing" in str(refusal.value) and "skeleton.py migrate" in str(refusal.value)


async def test_login_state_is_one_shot_and_expires(app_conn: persistence.Conn, role_conn) -> None:
    db = st.DbStore(await role_conn(Role.API))
    key = uuid4().hex
    await db.begin_login(login_sha256=key, state_sha256="s", nonce_sha256="n", code_verifier="v", ttl_seconds=600)
    taken = await db.take_login(key)
    assert taken == st.LoginState("s", "n", "v") and await db.take_login(key) is None
    expired = uuid4().hex
    await db.begin_login(login_sha256=expired, state_sha256="s", nonce_sha256="n", code_verifier="v", ttl_seconds=600)
    await app_conn.execute(
        "UPDATE app.login_state SET expires_at = app.current_time() - interval '1 second' WHERE login_sha256 = %s",
        (expired,),
    )
    assert await db.take_login(expired) is None  # consumed and refused in one statement
    cur = await app_conn.execute("SELECT count(*) AS n FROM app.login_state WHERE login_sha256 = %s", (expired,))
    assert (await cur.fetchone())["n"] == 0


async def new_session(db: st.DbStore, sid: str = "sid-live") -> str:
    key = uuid4().hex
    await db.create_session(
        session_sha256=key,
        issuer=ISSUER,
        subject=ALEX,
        tenant_id=ALPHA,
        sid=sid,
        username="alex",
        csrf_secret_sha256="c",
        refresh_token_enc=b"sealed",
        absolute_seconds=28800,
    )
    return key


async def test_liveness_is_decided_by_the_update(app_conn: persistence.Conn, role_conn) -> None:
    db = st.DbStore(await role_conn(Role.API))
    key = await new_session(db)
    try:
        row = await db.live_session(key, idle_seconds=1800)
        assert row is not None and row.subject == ALEX and row.sid == "sid-live" and row.refresh_token_enc == b"sealed"
        await app_conn.execute(
            "UPDATE app.sessions SET last_seen_at = last_seen_at - interval '31 minutes' WHERE session_sha256 = %s",
            (key,),
        )
        assert await db.live_session(key, idle_seconds=1800) is None  # idle
        await app_conn.execute(
            "UPDATE app.sessions SET last_seen_at = app.current_time(),"
            " expires_at = app.current_time() - interval '1 second' WHERE session_sha256 = %s",
            (key,),
        )
        assert await db.live_session(key, idle_seconds=1800) is None  # absolute, despite the fresh touch
        await app_conn.execute(
            "UPDATE app.sessions SET expires_at = app.current_time() + interval '1 hour' WHERE session_sha256 = %s",
            (key,),
        )
        assert await db.live_session(key, idle_seconds=1800) is not None
        revoked = await db.revoke_session(key)
        assert revoked is not None and await db.revoke_session(key) is None
        assert await db.live_session(key, idle_seconds=1800) is None
    finally:
        await app_conn.execute("DELETE FROM app.sessions WHERE session_sha256 = %s", (key,))


async def test_record_logout_is_atomic_and_replay_safe(app_conn: persistence.Conn, role_conn) -> None:
    db = st.DbStore(await role_conn(Role.API))
    sid = f"sid-{uuid4().hex[:8]}"
    keys = [await new_session(db, sid), await new_session(db, sid), await new_session(db, "other")]
    jti = f"jti-{uuid4().hex}"
    until = datetime.now(UTC) + timedelta(days=1)
    try:
        # Atomicity (spike §5): the jti insert and the revocation that roll back together leave the token unconsumed.
        api_conn = await role_conn(Role.API)
        async with api_conn.transaction(force_rollback=True):
            await api_conn.execute(
                "INSERT INTO app.logout_jti (jti, expires_at) VALUES (%s, %s) ON CONFLICT DO NOTHING", (jti, until)
            )
            await api_conn.execute("UPDATE app.sessions SET revoked_at = app.current_time() WHERE sid = %s", (sid,))
        assert all([await db.live_session(k, idle_seconds=1800) is not None for k in keys[:2]])  # a list, see below
        assert await db.record_logout(jti, expires_at=until, sid=sid) == 2  # the rolled-back jti was not consumed
        assert await db.record_logout(jti, expires_at=until, sid=sid) is None  # replay
        assert await db.live_session(keys[2], idle_seconds=1800) is not None  # the other sid is untouched
        # A list, not a generator: `await` inside a genexp handed to all() is a TypeError.
        assert all([await db.live_session(k, idle_seconds=1800) is None for k in keys[:2]])
    finally:
        await app_conn.execute("DELETE FROM app.sessions WHERE session_sha256 = ANY(%s)", (keys,))
        await app_conn.execute("DELETE FROM app.logout_jti WHERE jti = %s", (jti,))
