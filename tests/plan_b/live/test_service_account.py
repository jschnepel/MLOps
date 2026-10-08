"""T43 DoD: the view-users service account can read a user's `enabled` flag and nothing more; the admin is gone.

The account exists so the API can fail closed on a disabled user (AM-20.7) without holding any write power over the
realm: the first test pins both halves, the allowed read and the three refused calls. The second proves the temporary
master-realm admin is unusable and records that as evidence (the password is never written or echoed).
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from tests.plan_b.live import kc

SEEDS = json.loads(Path("data/seed-ids.json").read_text(encoding="utf-8"))
EVIDENCE = Path("reports/bootstrap/bootstrap-admin.txt")


def _admin(base: str, token: str, path: str, method: str = "GET", body: dict | None = None) -> int:
    """Call the realm Admin API and return the HTTP status; an error status is returned, not raised."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{base}/admin/realms/{kc.REALM}/{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_view_users_account_cannot_write_or_list_clients(env, secret: Callable[[str], str]) -> None:
    base = f"http://localhost:{env['KC_HTTP_PORT']}"
    token = kc.token_client_credentials(base, "ops-view-users", secret("kc_client_secret_ops_view_users"))[
        "access_token"
    ]
    alex = SEEDS["personas"]["alex"]["user_id"]
    req = urllib.request.Request(
        f"{base}/admin/realms/{kc.REALM}/users/{alex}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read())
    assert body["enabled"] is True and body["id"] == alex
    assert _admin(base, token, f"users/{alex}", "PUT", {"enabled": True}) == 403
    assert _admin(base, token, "clients") == 403
    assert _admin(base, token, "users", "POST", {"username": "intruder", "enabled": True}) == 403


def test_bootstrap_admin_is_absent(env, secret: Callable[[str], str]) -> None:
    base = f"http://localhost:{env['KC_HTTP_PORT']}"
    form = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "tmpadmin",
            "password": secret("kc_bootstrap_admin_password"),
        }
    ).encode("ascii")
    try:
        urllib.request.urlopen(f"{base}/realms/master/protocol/openid-connect/token", form, timeout=20)
        status = 200
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status in (400, 401), status  # 400 invalid_grant on Keycloak 26.8 (measured); 401 tolerated
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    with EVIDENCE.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(f"tmpadmin password grant after bootstrap: HTTP {status} (rejected)\n")
