"""T11 live (OPS_LIVE=1): the real Keycloak login form through the skeleton's API, server-side sessions with CSRF and
origin, idle expiry, logout that ends the Keycloak session, the back-channel logout Keycloak sends to the host API
(two application sessions on one Keycloak session), a forged logout token, and the disable path through the sync
(R011, R012, R013, R086). Writes redacted evidence to reports/auth/ (status codes and counts only).
"""

import asyncio
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import jwt
import psycopg
import pytest
from ops_core import persistence, settings

from scripts.skeleton import Skeleton
from tests.e2e.kc_browser import API, ORIGIN, Browser, TestAdmin
from tests.plan_b.live import kc
from tests.plan_d.test_tokens import PEM1

pytestmark = pytest.mark.sweeper_stamps  # this module's skeleton sweeper stamps synced_at; the autouse fixture must not
EVIDENCE = Path("reports/auth/t11-sessions-revocation.txt")
ALEX = "2fc05986-c7ec-544c-b628-fdb112bbf18a"
SAM = "03f7eb09-e18d-5f33-bf75-12c57d5aaa54"


SENT_KEYS: list[str] = []  # every Idempotency-Key this module sent, so its clean-up deletes exactly their records


def sent_key() -> str:
    """A fresh Idempotency-Key (required on every /api/v1 mutation since T12), remembered for the clean-up."""
    key = str(uuid4())
    SENT_KEYS.append(key)
    return key


@pytest.fixture(scope="module", autouse=True)
def forget_sent_keys(migrated: None) -> Iterator[None]:
    """Delete the idempotency records of this module's keys after it, whatever the outcome."""
    try:
        yield
    finally:
        if SENT_KEYS:
            with psycopg.connect(settings.superuser_postgres().conninfo(), autocommit=True) as conn:
                conn.execute("DELETE FROM app.idempotency_request WHERE key = ANY(%s)", (SENT_KEYS,))
        SENT_KEYS.clear()


STAMP: dict[str, datetime] = {}  # min(synced_at) right after the skeleton came up: only its sweeper writes it here


@pytest.fixture(scope="module")
def skeleton(migrated: None) -> Iterator[Skeleton]:
    """Six processes for the module (this module is opted out of the autouse stamp, so every later `synced_at` is the
    sweeper's). After they stop, sam's row is restored with no sweeper left to race the restore (a sync that listed
    sam as disabled could otherwise commit after the test's own restore), and `permission_version` goes back to 1 for
    the modules that run later in the session."""
    sk = Skeleton()
    sk.start()
    try:
        with psycopg.connect(settings.superuser_postgres().conninfo(), autocommit=True) as conn:
            STAMP["t0"] = conn.execute("SELECT min(synced_at) FROM app.memberships").fetchone()[0]
        yield sk
    finally:
        sk.stop()
        with psycopg.connect(settings.superuser_postgres().conninfo(), autocommit=True) as conn:
            conn.execute(
                "UPDATE app.memberships SET active = true, permission_version = 1, synced_at = app.current_time()"
                " WHERE subject = %s",
                (UUID(SAM),),
            )


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T11 sessions and revocation — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def browser() -> Iterator[Browser]:
    b = Browser()
    try:
        yield b
    finally:
        b.close()


@pytest.fixture
def admin(secret) -> Iterator[TestAdmin]:
    kcs = settings.keycloak()
    token = kc.token_client_credentials(kcs.base_url, "ops-test-admin", secret("kc_client_secret_ops_test_admin"))
    a = TestAdmin(kcs.base_url, token["access_token"])
    try:
        yield a
    finally:
        a.close()


async def count_sessions(app_conn: persistence.Conn, where: str = "revoked_at IS NULL") -> int:
    """How many app.sessions rows match the (test-authored) WHERE clause."""
    cur = await app_conn.execute(f"SELECT count(*) AS n FROM app.sessions WHERE {where}")
    return int((await cur.fetchone())["n"])


@pytest.mark.asyncio
async def test_login_csrf_idle_expiry_and_logout(
    skeleton: Skeleton, browser: Browser, secret, app_conn: persistence.Conn, lines: list[str]
) -> None:
    kcs = settings.keycloak()
    location = browser.start_login()
    at_keycloak = location.startswith(kcs.base_url + "/realms/ops-dev/protocol/openid-connect/auth?")
    assert at_keycloak
    pkce = "code_challenge_method=S256" in location
    login_cookie = "ops_login" in {c.name for c in browser.api.cookies.jar}
    assert pkce and login_cookie
    session = browser.finish_login(browser.keycloak_login(location, "alex", secret("kc_persona_alex_password")))
    names = {c.name for c in browser.api.cookies.jar}  # names only: a jar's repr would print the values
    assert "ops_login" not in names and "ops_session" in names
    me = session.api.get("/api/v1/me")
    assert me.status_code == 200 and me.json()["auth"] == "session" and me.json()["username"] == "alex"
    # CSRF and origin (R012): nothing, Origin only, wrong token, wrong origin, then the real thing.
    refused = [
        session.api.post("/api/v1/conversations").status_code,
        session.api.post("/api/v1/conversations", headers={"Origin": ORIGIN}).status_code,
        session.api.post("/api/v1/conversations", headers={"Origin": ORIGIN, "X-CSRF-Token": "x" * 43}).status_code,
        session.api.post(
            "/api/v1/conversations", headers={"Origin": "http://evil.example", "X-CSRF-Token": session.csrf}
        ).status_code,
    ]
    assert refused == [403, 403, 403, 403], refused
    created = session.api.post(
        "/api/v1/conversations", headers={**session.mutation_headers(), "Idempotency-Key": sent_key()}
    )
    assert created.status_code == 201
    lines.append(f"login: me=200 csrf_refusals={refused} mutation_with_token={created.status_code}")
    # A callback replayed by another client (no login cookie) is refused before any exchange (review focus 1).
    other = Browser()
    try:
        replay = other.api.get("/auth/callback", params={"code": "x", "state": "y", "iss": kcs.issuer})
        assert replay.status_code == 401
    finally:
        other.close()
    # Idle expiry: age the row with the superuser; the next request is 401 and the cookies are cleared.
    await app_conn.execute("UPDATE app.sessions SET last_seen_at = last_seen_at - interval '31 minutes'")
    expired = session.api.get("/api/v1/me")
    names = {c.name for c in session.api.cookies.jar}
    assert expired.status_code == 401 and "ops_session" not in names
    # The expiry ended the Keycloak session too (final review I1): the next login asks for the password again
    # instead of riding the 8 h SSO session.
    relogin = browser.kc.get(browser.start_login(), headers=browser.kc_cookies())
    relogin_form = "kc-form-login" in relogin.text
    assert relogin.status_code == 200 and relogin_form
    lines.append(f"idle expiry: me={expired.status_code}; keycloak shows the login form again: {relogin_form}")
    # Logout ends the application session and the Keycloak session: the next login shows the form again.
    session = browser.login("alex", secret("kc_persona_alex_password"))
    out = session.api.post("/auth/logout", headers=session.mutation_headers())
    assert out.status_code == 204 and session.api.get("/api/v1/me").status_code == 401
    again = browser.kc.get(browser.start_login(), headers=browser.kc_cookies())
    form_back = "kc-form-login" in again.text  # no SSO ride: the form is back
    assert again.status_code == 200 and form_back
    lines.append(f"logout: {out.status_code}; keycloak shows the login form again: {again.status_code == 200}")


@pytest.mark.asyncio
async def test_backchannel_logout_revokes_the_sibling_session(
    skeleton: Skeleton, browser: Browser, secret, app_conn: persistence.Conn, lines: list[str]
) -> None:
    """Two application sessions on one Keycloak session (the second /auth/login rides the SSO cookie, same sid);
    logging the second out ends the Keycloak session, Keycloak POSTs the logout token to the host API through
    host.docker.internal, and the first session is gone without ever calling /auth/logout."""
    first_browser = browser
    first = first_browser.login("alex", secret("kc_persona_alex_password"))
    second_browser = Browser()
    second_browser.kc.close()
    second_browser.kc = first_browser.kc  # the same SSO cookies: Keycloak answers /auth with a code and no form
    try:
        second = second_browser.finish_login(second_browser.keycloak_login(second_browser.start_login(), "", ""))
        cur = await app_conn.execute("SELECT count(DISTINCT sid) AS n FROM app.sessions WHERE revoked_at IS NULL")
        assert (await cur.fetchone())["n"] == 1  # one Keycloak session, two application sessions
        before = await count_sessions(app_conn, "revoked_at IS NULL")
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.logout_jti")
        jtis_before = int((await cur.fetchone())["n"])
        out = second.api.post("/auth/logout", headers=second.mutation_headers())
        assert out.status_code == 204
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and first.api.get("/api/v1/me").status_code == 200:
            await asyncio.sleep(0.25)  # ruff ASYNC251: never time.sleep in a coroutine
        gone = first.api.get("/api/v1/me")
        assert gone.status_code == 401  # revoked by the back-channel logout, not by its own logout
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.logout_jti")
        assert int((await cur.fetchone())["n"]) == jtis_before + 1
        assert await count_sessions(app_conn, "revoked_at IS NULL") == before - 2
        lines.append(f"back-channel logout: sibling me={gone.status_code}, jti rows +1, sessions revoked 2")
        # The sweeper, not the fixture, keeps the rows fresh: min(synced_at) moves past the value recorded at start.
        started = time.monotonic()
        while time.monotonic() - started < 45:
            cur = await app_conn.execute("SELECT min(synced_at) AS t FROM app.memberships")
            if (await cur.fetchone())["t"] > STAMP["t0"]:
                break
            await asyncio.sleep(1.0)
        else:
            raise AssertionError("the sweeper did not re-stamp memberships.synced_at within 45 s")
        lines.append(f"sweeper re-stamped synced_at after {round(time.monotonic() - started, 1)}s")
    finally:
        second_browser.api.close()


def test_forged_logout_token_is_refused(skeleton: Skeleton, lines: list[str]) -> None:
    kcs = settings.keycloak()
    forged = jwt.encode(
        {
            "iss": kcs.issuer,
            "aud": "ops-web",
            "sub": ALEX,
            "sid": "x",
            "jti": "forged-1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 120,
            "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
        },
        PEM1,
        algorithm="RS256",
        headers={"kid": "not-a-realm-key", "typ": "logout+jwt"},
    )
    with httpx2.Client(base_url=API, timeout=15.0) as c:
        r = c.post("/auth/backchannel-logout", data={"logout_token": forged})
        assert r.status_code == 400 and r.json()["code"] == "INVALID_INPUT"
        assert c.post("/auth/backchannel-logout", data={}).status_code == 400
    lines.append(f"forged logout token: {r.status_code}")


@pytest.mark.asyncio
async def test_disabled_user_is_refused_and_synced_within_60s(
    skeleton: Skeleton, browser: Browser, secret, admin: TestAdmin, app_conn: persistence.Conn, lines: list[str]
) -> None:
    """R086: disable sam in Keycloak; sam's next decision-class mutation is 401 at once (admin-API check), the sync
    deactivates sam's membership within 60 s, and sam's still-valid bearer token then fails every protected read.
    The finally block re-enables sam at Keycloak; the module fixture restores the row once the sweeper is gone."""
    kcs = settings.keycloak()
    sam_token = kc.token_password(kcs.base_url, "ops-dev-direct", "sam", secret("kc_persona_sam_password"))
    headers = {"Authorization": f"Bearer {sam_token['access_token']}"}
    body = {"expected_revision": 1, "expected_payload_sha256": "0" * 64, "decision": "approve"}
    decision_url = f"/api/v1/proposals/{UUID(int=1)}/decisions"
    try:
        with httpx2.Client(base_url=API, timeout=15.0) as c:
            # Positive controls (final review I2): the bearer token works and the enabled check passes for an enabled
            # sam, so the later 401s are the disable and the sync, not a token that never worked.
            me_enabled = c.get("/api/v1/me", headers=headers).status_code
            keyed = {**headers, "Idempotency-Key": sent_key()}  # every /api/v1 mutation carries one (T12)
            decided_enabled = c.post(decision_url, headers=keyed, json=body).status_code
            assert me_enabled == 200 and decided_enabled == 404, (me_enabled, decided_enabled)
            disabled = admin.set_enabled(SAM, False)
            # Before the sync: the membership is still active, so a read still works (R013 attribution below).
            me_unsynced = c.get("/api/v1/me", headers=headers).status_code
            assert disabled == 204 and admin.enabled(SAM) is False
            assert me_unsynced == 200, me_unsynced
            # A decision on a random proposal: the enabled check runs before any lookup, so a disabled user is 401,
            # never 404 (the check is a dependency, T11 review note 2).
            decided = c.post(decision_url, headers={**headers, "Idempotency-Key": sent_key()}, json=body)
            decided_code, decided_body = decided.status_code, decided.json()
            assert decided_code == 401, decided_code
            refusal = (decided_body["code"], decided_body["message"])
            assert refusal == ("UNAUTHENTICATED", "identity disabled"), refusal
            started = time.monotonic()
            deadline = started + 75
            while time.monotonic() < deadline:
                cur = await app_conn.execute(
                    "SELECT bool_and(NOT active) AS off, max(permission_version) AS pv FROM app.memberships"
                    " WHERE subject = %s",
                    (UUID(SAM),),
                )
                row = await cur.fetchone()
                if row["off"]:
                    break
                await asyncio.sleep(1.0)
            synced_after = round(time.monotonic() - started, 1)
            assert row["off"] and row["pv"] == 2, row
            assert synced_after <= 60.0, synced_after
            me = c.get("/api/v1/me", headers=headers)
            assert me.status_code == 401  # no active membership: the session/token is otherwise valid (R013)
            lines.append(
                f"disabled user: before me={me_enabled} decision={decided_enabled}; after disable me={me_unsynced}"
                f" decision={decided_code} ({refusal[1]}); synced_after={synced_after}s me={me.status_code}"
            )
    finally:
        # Re-enable unconditionally and record the status; an assert here would hide the original failure. The row is
        # restored by the module fixture, after the sweeper stops.
        lines.append(f"sam re-enabled at keycloak: {admin.set_enabled(SAM, True)}")
