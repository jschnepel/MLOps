"""Drive the real Keycloak login form and the API's auth routes from a test, without a browser (spike §1).

Keycloak 26 marks its cookies `Secure` even over plain http on localhost, so httpx2's jar never sends them back on an
http URL (a browser treats http://localhost as a secure context and does); the helper forwards them by hand. Tokens,
codes, cookie values and passwords never appear in an assertion operand or in the evidence file.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx2

FORM_ACTION = re.compile(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', re.DOTALL)
HIDDEN = re.compile(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', re.DOTALL)
API = "http://127.0.0.1:8000"
ORIGIN = "http://localhost:8000"
PUBLIC_HOST = "localhost:8000"


def cookie_header(client: httpx2.Client) -> str:
    return "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)


@dataclass
class Session:
    """One application session as the browser holds it: the API client with its cookies and the CSRF token."""

    api: httpx2.Client
    csrf: str

    def mutation_headers(self) -> dict[str, str]:
        return {"Origin": ORIGIN, "X-CSRF-Token": self.csrf}


class Browser:
    """Two httpx2 clients standing in for one browser: one for the API origin, one for Keycloak's origin."""

    def __init__(self) -> None:
        # Dial the loopback address (no 2 s `::1` detour) but present the public host: /auth/login redirects any
        # other Host to the public base URL, and Keycloak only redirects back to `localhost:8000` (spike §1).
        self.api = httpx2.Client(base_url=API, headers={"Host": PUBLIC_HOST}, timeout=15.0, follow_redirects=False)
        self.kc = httpx2.Client(timeout=15.0, follow_redirects=False)

    def close(self) -> None:
        self.api.close()
        self.kc.close()

    def kc_cookies(self) -> dict[str, str]:
        """The Cookie header for Keycloak's origin (empty when the jar is empty)."""
        header = cookie_header(self.kc)
        return {"Cookie": header} if header else {}

    def start_login(self) -> str:
        """GET /auth/login; the Location (the Keycloak authorization URL)."""
        started = self.api.get("/auth/login")
        assert started.status_code == 303, started.status_code
        location = started.headers["location"]
        assert not location.endswith("/auth/login"), "the API bounced us to the public host: check PUBLIC_HOST"
        return location

    def keycloak_login(self, auth_url: str, username: str, password: str) -> str:
        """Submit the form (or ride an existing SSO cookie) and return the callback URL Keycloak redirects to."""
        page = self.kc.get(auth_url, headers=self.kc_cookies())
        if page.status_code == 302:
            return page.headers["location"]  # an SSO session already exists: no form
        assert page.status_code == 200, page.status_code
        match = FORM_ACTION.search(page.text)
        assert match, "login form not found"
        fields = {k: html.unescape(v) for k, v in HIDDEN.findall(page.text)}
        fields.update(username=username, password=password, credentialId="")
        done = self.kc.post(html.unescape(match.group(1)), data=fields, headers=self.kc_cookies())
        assert done.status_code == 302, done.status_code
        return done.headers["location"]

    def finish_login(self, callback_url: str) -> Session:
        """Present the callback to the API (same path and query, on the API's loopback address)."""
        parts = urlsplit(callback_url)
        assert parts.path == "/auth/callback", parts.path
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        done = self.api.get("/auth/callback", params=query)
        assert done.status_code == 303, done.status_code
        csrf = self.api.cookies.get("ops_csrf")
        assert csrf
        return Session(self.api, csrf)

    def login(self, username: str, password: str) -> Session:
        return self.finish_login(self.keycloak_login(self.start_login(), username, password))


class TestAdmin:
    """The dev/test-only `ops-test-admin` service account (ruling 18): enable, disable, log out a persona."""

    __test__ = False  # not a test class

    def __init__(self, base_url: str, token: str) -> None:
        self._client = httpx2.Client(base_url=f"{base_url}/admin/realms/ops-dev", timeout=15.0)
        self._client.headers["Authorization"] = f"Bearer {token}"

    def close(self) -> None:
        self._client.close()

    def set_enabled(self, user_id: str, enabled: bool) -> int:
        return self._client.put(f"/users/{user_id}", json={"enabled": enabled}).status_code

    def enabled(self, user_id: str) -> bool:
        body = self._client.get(f"/users/{user_id}").json()
        return bool(body["enabled"])
