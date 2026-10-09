"""R011 (invalid callback context), R012 (sessions and CSRF), R013 (current membership wins) and R086's API half
(disabled user → 401, back-channel logout, replay) against the FastAPI app with fakes for Keycloak and the store.

Catches: a callback without the login cookie or with a foreign state logging someone in (login CSRF), the wrong
`iss`, a refused exchange turned into a 500, a cookie session mutating without Origin or token, a bearer caller
asked for a CSRF token, a session surviving idle or absolute expiry, revocation or logout, a login that keeps the
previous session alive (no rotation), a logout token replayed, a disabled user still deciding, and Keycloak's
outage read as "enabled".
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_api.auth import IdClaims, LogoutClaims, Tokens

from tests.plan_d.test_api import ALEX, ALPHA, BETA, DUAL, SAM, SHA, FakeStore, StubVerifier, auth, seed_proposal
from tests.plan_f.auth_fakes import ISSUER, ORIGIN, fake_auth, login_as


@pytest.fixture
def world():
    deps = fake_auth()
    fake = FakeStore()
    app = create_app(StubVerifier(), store_factory=lambda: fake, auth_factory=lambda: deps)
    with TestClient(app, base_url="http://localhost:8000") as c:  # the public host: /auth/login redirects any other
        yield c, fake, deps


def browser(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf, **extra}


def test_login_redirect_shape(world) -> None:
    c, fake, deps = world
    elsewhere = c.get("/auth/login", follow_redirects=False, headers={"Host": "127.0.0.1:8000"})
    assert elsewhere.status_code == 303 and elsewhere.headers["location"] == "http://localhost:8000/auth/login"
    assert not fake.logins and "ops_login" not in c.cookies  # nothing started on the wrong host
    r = c.get("/auth/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("https://idp.test/auth?")
    assert r.headers["cache-control"] == "no-store"
    cookie = next(v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("ops_login="))
    assert "HttpOnly" in cookie and "Max-Age=600" in cookie
    assert len(fake.logins) == 1 and deps.oidc.started[-1]["state"] not in str(fake.logins)  # stored hashed
    assert c.get("/").json() == {"status": "ok", "login_url": "/auth/login"}


def test_callback_logs_in_rotates_and_sets_the_session(world) -> None:
    c, fake, deps = world
    first = login_as(c, deps, ALEX)
    me = c.get("/api/v1/me").json()
    assert me["subject"] == str(ALEX) and me["tenant_id"] == str(ALPHA) and me["auth"] == "session"
    assert me["username"] == "alex" and me["roles"] == ["requester"]
    first_hash = next(iter(fake.sessions))
    second = login_as(c, deps, ALEX, sid="sid-2")
    assert second != first and fake.sessions[first_hash]["revoked"] is True  # rotation at login (BUILD_SPEC §9)
    assert len(fake.sessions) == 2 and not fake.logins  # the login row was consumed
    assert "ops_login" not in c.cookies


def test_callback_refuses_a_missing_login_cookie_and_a_foreign_state(world) -> None:
    c, fake, deps = world
    started = c.get("/auth/login", follow_redirects=False)
    state = started.headers["location"].split("state=")[1].split("&")[0]
    deps.oidc.codes["good"] = Tokens("id-good", "refresh-good")
    deps.id_tokens.tokens["id-good"] = (IdClaims(ALEX, "sid-1", "alex"), deps.oidc.started[-1]["nonce"])
    # Another browser (no login cookie) presents the victim's callback URL: refused before any exchange.
    other = TestClient(c.app, base_url="http://localhost:8000")
    r = other.get("/auth/callback", params={"code": "good", "state": state, "iss": ISSUER}, follow_redirects=False)
    assert r.status_code == 401 and "good" in deps.oidc.codes  # the code was not spent
    # The right browser with the wrong state: refused, and the login row is consumed (one shot).
    r = c.get("/auth/callback", params={"code": "good", "state": "x" * 43, "iss": ISSUER}, follow_redirects=False)
    assert r.status_code == 401 and not fake.logins and "good" in deps.oidc.codes
    r = c.get("/auth/callback", params={"code": "good", "state": state, "iss": ISSUER}, follow_redirects=False)
    assert r.status_code == 401  # no login in progress any more
    assert "ops_session" not in c.cookies


@pytest.mark.parametrize(
    ("tamper", "status"),
    [
        ({"iss": "http://evil/realms/ops-dev"}, 401),
        ({"error": "access_denied", "error_description": "x"}, 401),
        ({"code": "unknown"}, 401),
        ({"nonce": "wrong"}, 401),
        ({"unavailable": True}, 503),
        ({"subject": "nobody"}, 401),
        ({"subject": "dual"}, 401),
    ],
)
def test_callback_negatives(world, tamper: dict[str, Any], status: int) -> None:
    c, fake, deps = world
    started = c.get("/auth/login", follow_redirects=False)
    state = started.headers["location"].split("state=")[1].split("&")[0]
    deps.oidc.codes["good"] = Tokens("id-good", "refresh-good")
    subject = {"nobody": uuid4(), "dual": DUAL}.get(tamper.get("subject", ""), ALEX)
    nonce = tamper.get("nonce", deps.oidc.started[-1]["nonce"])
    deps.id_tokens.tokens["id-good"] = (IdClaims(subject, "sid-1", "x"), nonce)
    deps.oidc.unavailable = bool(tamper.get("unavailable"))
    params = {"code": tamper.get("code", "good"), "state": state, "iss": tamper.get("iss", ISSUER)}
    if "error" in tamper:
        params = {"error": tamper["error"], "error_description": tamper["error_description"], "state": state}
    r = c.get("/auth/callback", params=params, follow_redirects=False)
    assert r.status_code == status, r.text
    assert "ops_session" not in c.cookies and not fake.sessions
    if status == 503:
        assert r.json()["retryable"] is True
    assert "x" not in r.text or "error_description" not in r.text  # the provider's text is never echoed


def test_browser_mutations_need_origin_and_csrf_token(world) -> None:
    c, _fake, deps = world
    csrf = login_as(c, deps, ALEX)
    assert c.post("/api/v1/conversations").status_code == 403  # no Origin, no token
    assert c.post("/api/v1/conversations", headers={"Origin": ORIGIN}).status_code == 403
    assert c.post("/api/v1/conversations", headers={"Origin": ORIGIN, "X-CSRF-Token": "x" * 43}).status_code == 403
    assert c.post("/api/v1/conversations", headers=browser(csrf, Origin="http://evil.example")).status_code == 403
    assert c.post("/api/v1/conversations", headers=browser(csrf, Origin="null")).status_code == 403
    ok = c.post("/api/v1/conversations", headers=browser(csrf))
    assert ok.status_code == 201
    referer_only = c.post("/api/v1/conversations", headers={"Referer": ORIGIN + "/app", "X-CSRF-Token": csrf})
    assert referer_only.status_code == 201
    assert c.get("/api/v1/me").status_code == 200  # reads need neither
    # The bearer path is exempt from both (BUILD_SPEC §7: CSRF/origin protection in cookie mode).
    assert c.post("/api/v1/conversations", headers=auth("alex")).status_code == 201


def test_session_expiry_revocation_and_logout(world) -> None:
    c, fake, deps = world
    csrf = login_as(c, deps, ALEX)
    key = next(iter(fake.sessions))
    fake.sessions[key]["last_seen"] -= 1801  # idle (30 min)
    r = c.get("/api/v1/me")
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHENTICATED"
    assert "ops_session" not in c.cookies and "ops_csrf" not in c.cookies  # cleared by the response
    before = set(fake.sessions)
    login_as(c, deps, ALEX)
    key = next(k for k in fake.sessions if k not in before)  # the new row, not the idle-expired one
    fake.sessions[key]["expires"] -= 28801  # absolute (8 h) even with recent activity
    assert c.get("/api/v1/me").status_code == 401
    csrf = login_as(c, deps, ALEX)
    assert c.post("/auth/logout").status_code == 403  # a mutation: CSRF and Origin apply
    out = c.post("/auth/logout", headers=browser(csrf))
    assert out.status_code == 204 and deps.oidc.ended == ["refresh-code-3"]  # the sealed refresh token was opened once
    assert c.get("/api/v1/me").status_code == 401 and "ops_session" not in c.cookies
    assert c.post("/auth/logout", headers=browser(csrf)).status_code == 401  # idempotent: nothing to log out
    assert c.post("/auth/logout", headers=auth("alex")).status_code == 403  # a bearer caller has no session


def test_logout_survives_a_provider_outage(world) -> None:
    c, _fake, deps = world
    csrf = login_as(c, deps, ALEX)
    deps.oidc.unavailable = True
    assert c.post("/auth/logout", headers=browser(csrf)).status_code == 204
    assert c.get("/api/v1/me").status_code == 401


def test_revoked_membership_ends_the_session_and_the_bearer(world) -> None:
    c, fake, deps = world
    login_as(c, deps, ALEX)
    assert c.get("/api/v1/me").status_code == 200
    from tests.plan_d import test_api as plan_d

    rows = dict(plan_d.ROWS)
    plan_d.ROWS[ALEX] = []  # the sync deactivated alex
    try:
        r = c.get("/api/v1/me")
        assert r.status_code == 401 and "ops_session" not in c.cookies
        assert all(e["revoked"] for e in fake.sessions.values())
        assert c.get("/api/v1/me", headers=auth("alex")).status_code == 401  # bearer path: same answer (ruling 21)
        plan_d.ROWS[ALEX] = [(BETA, "requester")]  # moved tenant: the session's tenant no longer matches
        login_as(c, deps, ALEX)
        plan_d.ROWS[ALEX] = [(ALPHA, "requester")]
        assert c.get("/api/v1/me").status_code == 401
    finally:
        plan_d.ROWS.clear()
        plan_d.ROWS.update(rows)


def test_backchannel_logout_revokes_by_sid_once(world) -> None:
    c, fake, deps = world
    login_as(c, deps, ALEX, sid="kc-sid")
    other = TestClient(c.app, base_url="http://localhost:8000")
    login_as(other, deps, SAM, sid="kc-sid", username="sam")  # same Keycloak session, second browser tab/app session
    third = TestClient(c.app, base_url="http://localhost:8000")
    login_as(third, deps, ALEX, sid="another-sid")
    exp = int((datetime.now(UTC) + timedelta(minutes=2)).timestamp())
    deps.logout_tokens.tokens["lt-1"] = LogoutClaims(sid="kc-sid", subject=ALEX, jti="j-1", expires_at=exp)
    r = c.post("/auth/backchannel-logout", data={"logout_token": "lt-1"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert c.get("/api/v1/me").status_code == 401 and other.get("/api/v1/me").status_code == 401
    assert third.get("/api/v1/me").status_code == 200  # another sid is untouched
    replay = c.post("/auth/backchannel-logout", data={"logout_token": "lt-1"})
    assert replay.status_code == 400 and replay.json()["code"] == "INVALID_INPUT"
    assert c.post("/auth/backchannel-logout", data={"logout_token": "forged"}).status_code == 400
    assert c.post("/auth/backchannel-logout", data={}).status_code == 400
    assert c.post("/auth/backchannel-logout", json={"logout_token": "lt-1"}).status_code == 400
    assert "j-1" in fake.jtis


def test_backchannel_logout_store_failure_is_a_503_and_the_session_survives(world, monkeypatch) -> None:
    c, fake, deps = world
    login_as(c, deps, ALEX, sid="kc-sid")
    exp = int((datetime.now(UTC) + timedelta(minutes=2)).timestamp())
    deps.logout_tokens.tokens["lt-2"] = LogoutClaims(sid="kc-sid", subject=ALEX, jti="j-2", expires_at=exp)

    async def broken(jti: str, *, expires_at: datetime, sid: str) -> int | None:
        raise psycopg.OperationalError("connection lost")

    monkeypatch.setattr(fake, "record_logout", broken)
    r = c.post("/auth/backchannel-logout", data={"logout_token": "lt-2"})
    # Keycloak never retries (spike §2): the 503 is honest, the session lives on until its own limits (ruling 16).
    assert r.status_code == 503 and r.json()["retryable"] is True
    assert c.get("/api/v1/me").status_code == 200 and "j-2" not in fake.jtis


def test_disabled_user_is_401_and_the_session_is_revoked(world) -> None:
    c, fake, deps = world
    pid = seed_proposal(fake)
    body = {"expected_revision": 1, "expected_payload_sha256": SHA, "decision": "approve", "reason": "ok"}
    csrf = login_as(c, deps, SAM, username="sam")
    deps.admin.disabled.add(SAM)
    r = c.post(f"/api/v1/proposals/{pid}/decisions", headers=browser(csrf), json=body)
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHENTICATED"
    assert "ops_session" not in c.cookies and all(e["revoked"] for e in fake.sessions.values())
    assert pid not in fake.decided  # nothing was decided
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json=body).status_code == 401
    deps.admin.disabled.clear()
    assert c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json=body).status_code == 200
    assert deps.admin.calls == 3  # one check per decision attempt, none for the reads or the login


def test_decision_is_503_retryable_when_keycloak_is_unavailable(world) -> None:
    c, fake, deps = world
    pid = seed_proposal(fake)
    body = {"expected_revision": 1, "expected_payload_sha256": SHA, "decision": "approve", "reason": "ok"}
    deps.admin.unavailable = True
    r = c.post(f"/api/v1/proposals/{pid}/decisions", headers=auth("sam"), json=body)
    assert r.status_code == 503 and r.json()["code"] == "UNAVAILABLE" and r.json()["retryable"] is True
    assert pid not in fake.decided
    assert c.get(f"/api/v1/proposals/{pid}", headers=auth("sam")).status_code == 200  # reads do not ask Keycloak
    assert c.post("/api/v1/conversations", headers=auth("alex")).status_code == 201  # admission is not decision-class


def test_bearer_and_cookie_do_not_mix(world) -> None:
    c, _fake, deps = world
    login_as(c, deps, ALEX)
    me = c.get("/api/v1/me", headers=auth("sam")).json()
    assert me["subject"] == str(SAM) and me["auth"] == "bearer"  # the explicit credential wins
    assert c.get("/api/v1/me", headers=auth("nobody")).status_code == 401  # a bad bearer is not rescued by the cookie
