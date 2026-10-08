"""Keycloak token helpers for live tests (stdlib only). Tokens never leave the test process.

Stdlib-only on purpose: the live tests must run in the plain project environment without an OIDC client library, and
decoding a JWT payload for assertions needs no signature check because the token came straight from the issuer.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request

REALM = "ops-dev"


def _post_form(url: str, fields: dict[str, str]) -> dict:
    """POST form fields and return the decoded JSON body; an HTTP error status raises `urllib.error.HTTPError`."""
    data = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def token_url(base_url: str) -> str:
    """The realm's OIDC token endpoint under `base_url` (for example `http://localhost:18080`)."""
    return f"{base_url}/realms/{REALM}/protocol/openid-connect/token"


def token_client_credentials(base_url: str, client_id: str, client_secret: str) -> dict:
    """Mint a workload token with the client-credentials grant (service-account clients only)."""
    return _post_form(
        token_url(base_url),
        {"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
    )


def token_password(base_url: str, client_id: str, username: str, password: str) -> dict:
    """Mint a persona token with the password grant; only the dev-only `ops-dev-direct` client allows it."""
    return _post_form(
        token_url(base_url),
        {"grant_type": "password", "client_id": client_id, "username": username, "password": password},
    )


def claims(access_token: str) -> dict:
    """Decode the payload of a JWT without verifying it; for assertions on tokens we just received."""
    payload = access_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)  # JWTs strip base64 padding; urlsafe_b64decode needs it back
    return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
