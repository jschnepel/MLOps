"""The pure parts of ops_api.auth: hashing and constant-time comparison of the opaque tokens, the origin rule
(BUILD_SPEC §9 origin verification; spike §4 for what browsers and TestClient send), discovery checks (ruling 25),
the sealed refresh token (BUILD_SPEC §9 provider tokens at rest) and the cookie attributes (ruling 6)."""

from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from ops_api import auth
from ops_core import settings
from starlette.responses import Response

KC = settings.Keycloak(
    base_url="http://localhost:18080",
    issuer="http://localhost:18080/realms/ops-dev",
    server_url="http://127.0.0.1:18080",
)
DOC = {
    "issuer": "http://localhost:18080/realms/ops-dev",
    "authorization_endpoint": "http://localhost:18080/realms/ops-dev/protocol/openid-connect/auth",
    "token_endpoint": "http://localhost:18080/realms/ops-dev/protocol/openid-connect/token",
    "end_session_endpoint": "http://localhost:18080/realms/ops-dev/protocol/openid-connect/logout",
    "jwks_uri": "http://localhost:18080/realms/ops-dev/protocol/openid-connect/certs",
    "backchannel_logout_supported": True,
    "backchannel_logout_session_supported": True,
    "code_challenge_methods_supported": ["plain", "S256"],
}


def test_tokens_are_hashed_and_compared_in_constant_time() -> None:
    token = auth.new_token()
    assert len(token) >= 43 and auth.digest(token) != token and len(auth.digest(token)) == 64
    assert auth.matches(token, auth.digest(token)) and not auth.matches(token + "x", auth.digest(token))
    assert auth.new_token() != token


@pytest.mark.parametrize(
    ("headers", "ok"),
    [
        ({"origin": "http://localhost:8000"}, True),
        ({"origin": "http://localhost:8000", "referer": "http://evil.example/"}, True),  # Origin wins when present
        ({"referer": "http://localhost:8000/app/page?x=1"}, True),  # Referer's origin is the fallback
        ({}, False),
        ({"origin": "null"}, False),
        ({"origin": "http://localhost:8001"}, False),
        ({"origin": "https://localhost:8000"}, False),
        ({"origin": "http://evil.example", "referer": "http://localhost:8000/"}, False),
        ({"referer": "localhost:8000"}, False),
    ],
)
def test_same_origin_rule(headers: dict[str, str], ok: bool) -> None:
    assert auth.same_origin(headers, "http://localhost:8000") is ok


@pytest.mark.parametrize(
    ("host", "base", "ok"),
    [
        ("localhost:8000", "http://localhost:8000", True),
        ("LOCALHOST:8000", "http://localhost:8000", True),
        ("127.0.0.1:8000", "http://localhost:8000", False),
        ("localhost", "http://localhost:80", True),  # an explicit default port equals an omitted one (no redirect loop)
        ("ops.example.com", "https://ops.example.com:443", True),
        ("ops.example.com:8443", "https://ops.example.com", False),
        ("", "http://localhost:8000", False),
        ("localhost:notaport", "http://localhost:8000", False),
        ("[::1:8000", "http://localhost:8000", False),
        ("user@localhost:8000", "http://localhost:8000", False),
    ],
)
def test_same_host_rule(host: str, base: str, ok: bool) -> None:
    assert auth.same_host(host, base) is ok


def test_discovery_is_checked_and_rewritten_for_server_use() -> None:
    d = auth.Discovery.from_document(DOC, KC)
    assert d.authorization_endpoint.startswith("http://localhost:18080/")  # browser-facing: the registered host
    assert d.token_endpoint == "http://127.0.0.1:18080/realms/ops-dev/protocol/openid-connect/token"
    assert d.end_session_endpoint.startswith("http://127.0.0.1:18080/") and d.jwks_uri.startswith("http://127.0.0.1")
    for bad in (
        {**DOC, "issuer": "http://evil/realms/ops-dev"},
        {**DOC, "backchannel_logout_session_supported": False},
        {**DOC, "code_challenge_methods_supported": ["plain"]},
        {**DOC, "code_challenge_methods_supported": "S256x"},
        {**DOC, "backchannel_logout_session_supported": "false"},
        {**DOC, "authorization_endpoint": "http://127.0.0.1:18080/realms/ops-dev/protocol/openid-connect/auth"},
        {k: v for k, v in DOC.items() if k != "end_session_endpoint"},
    ):
        with pytest.raises(ValueError):
            auth.Discovery.from_document(bad, KC)


@pytest.mark.parametrize("name", ["authorization_endpoint", "token_endpoint", "end_session_endpoint", "jwks_uri"])
def test_discovery_refuses_a_third_host_for_every_endpoint(name: str) -> None:
    path = str(DOC[name]).removeprefix("http://localhost:18080")
    with pytest.raises(ValueError):
        auth.Discovery.from_document({**DOC, name: "http://evil.example" + path}, KC)


@pytest.mark.asyncio
async def test_the_authorization_url_asks_for_the_idle_limit_as_max_age() -> None:
    """Final review I1: Keycloak re-prompts when its SSO authentication is older than `max_age`."""
    async with httpx2.AsyncClient() as http:
        oidc = auth.AuthlibOidc(
            discovery=auth.Discovery.from_document(DOC, KC),
            client_secret="unit-test-secret",
            redirect_uri="http://localhost:8000/auth/callback",
            http=http,
            max_age=1800,
        )
        try:
            url = oidc.authorization_url(state="s", nonce="n", code_verifier="v" * 43)
        finally:
            await oidc.aclose()
    query = parse_qs(urlsplit(url).query)
    assert query["max_age"] == ["1800"] and query["code_challenge_method"] == ["S256"] and query["nonce"] == ["n"]


def test_tokens_hide_secrets_in_repr() -> None:
    assert "refresh-token-value" not in repr(auth.Tokens("id", "refresh-token-value"))


def test_token_box_round_trips_and_refuses_another_key() -> None:
    box, other = auth.TokenBox("key-material-one"), auth.TokenBox("key-material-two")
    sealed = box.seal("refresh-token-value")
    assert b"refresh-token-value" not in sealed and box.open(sealed) == "refresh-token-value"
    with pytest.raises(ValueError):
        other.open(sealed)
    with pytest.raises(ValueError):
        box.open(b"not-a-fernet-token")


def test_cookie_attributes() -> None:
    policy = auth.CookiePolicy(secure=False, login_max_age=600)
    response = Response()
    policy.set_session(response, "s-value", "c-value")
    policy.set_login(response, "l-value")
    lines = [v.lower() for k, v in response.raw_headers if k == b"set-cookie" for v in [v.decode()]]
    session = next(line for line in lines if line.startswith("ops_session="))
    csrf = next(line for line in lines if line.startswith("ops_csrf="))
    login = next(line for line in lines if line.startswith("ops_login="))
    assert "httponly" in session and "samesite=lax" in session and "path=/" in session and "max-age" not in session
    assert "httponly" not in csrf and "samesite=lax" in csrf  # readable by the web app, echoed in X-CSRF-Token
    assert "httponly" in login and "max-age=600" in login
    assert all("secure" not in line for line in lines)
    secure = Response()
    auth.CookiePolicy(secure=True, login_max_age=600).set_session(secure, "s", "c")
    assert all(b"secure" in v.lower() for k, v in secure.raw_headers if k == b"set-cookie")
    cleared = Response()
    policy.clear_session(cleared)
    policy.clear_login(cleared)
    gone = [v.decode().lower() for k, v in cleared.raw_headers if k == b"set-cookie"]
    assert len(gone) == 3 and all("max-age=0" in line for line in gone)
