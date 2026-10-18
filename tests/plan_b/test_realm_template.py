"""Static checks on the committed realm import file, with no Keycloak running.

They protect the properties that must hold before the realm is ever imported: secrets and passwords are only
`${OPS_KC_*}` placeholders (a literal would leak into git), each workload client can mint only its own audiences
(audience confusion between mcp-read and mcp-write), the browser client keeps an exact redirect allowlist with PKCE,
and the persona IDs match `data/seed-ids.json` so a token's `sub` joins to the seeded rows. The realm JSON cannot
carry comments, so the reasons for its shape are recorded here and in `docs/runbooks/dev-topology.md`.
"""

import json
import re
import sys
from pathlib import Path

import pytest

REALM = Path("deploy/dev/keycloak/realm-ops-dev.json")
SEEDS = json.loads(Path("data/seed-ids.json").read_text(encoding="utf-8"))
PLACEHOLDER = re.compile(r"^\$\{OPS_KC_[A-Z0-9_]+\}$")


def load() -> dict:
    """Parse the realm import file."""
    return json.loads(REALM.read_text(encoding="utf-8"))


def clients() -> dict[str, dict]:
    """Realm clients keyed by clientId."""
    return {c["clientId"]: c for c in load()["clients"]}


def users() -> dict[str, dict]:
    """Realm users keyed by username."""
    return {u["username"]: u for u in load()["users"]}


def audiences(client: dict) -> set[str]:
    """The custom audiences a client's audience mappers add to its access tokens."""
    return {
        m["config"]["included.custom.audience"]
        for m in client.get("protocolMappers", [])
        if m["protocolMapper"] == "oidc-audience-mapper"
    }


def test_realm_name_and_roles():
    doc = load()
    assert doc["realm"] == "ops-dev" and doc["enabled"] is True
    assert {r["name"] for r in doc["roles"]["realm"]} >= {"requester", "reviewer", "reader"}


def test_every_secret_and_password_is_a_placeholder():
    # Pytest's assertion rewriting appends the evaluated operands to a failure even when a custom message is given,
    # so `assert PLACEHOLDER.match(secret), name` would print the very literal this test exists to catch into the
    # terminal or CI log. Each check therefore collects identifiers only and asserts on that list; the values never
    # appear in an asserted expression. `test_placeholder_failure_message_never_prints_the_literal` proves it.
    bad_clients = [
        cid for cid, c in clients().items() if not c.get("publicClient", False) and not PLACEHOLDER.match(c["secret"])
    ]
    assert not bad_clients, f"client secrets that are not placeholders: {bad_clients}"
    bad_users = [
        name
        for name, u in users().items()
        for cred in u.get("credentials", [])
        if cred["type"] != "password" or not PLACEHOLDER.match(cred["value"])
    ]
    assert not bad_users, f"users whose credentials[].value is not a placeholder: {bad_users}"


def test_placeholder_failure_message_never_prints_the_literal(tmp_path, monkeypatch):
    # Proof for the redaction claim: tamper a copy of the realm with a literal secret and show that the failure text
    # names the client but does not contain the literal. Under the old `assert PLACEHOLDER.match(v), (cid, ...)`
    # form pytest's rewriting appended the operand and this test failed.
    literal = "LITERAL-SECRET-DO-NOT-PRINT-7f3a"
    doc = load()
    target = next(c for c in doc["clients"] if not c.get("publicClient", False))
    target["secret"] = literal
    tampered = tmp_path / "realm.json"
    tampered.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "REALM", tampered)
    with pytest.raises(AssertionError) as excinfo:
        test_every_secret_and_password_is_a_placeholder()
    assert literal not in str(excinfo.value)
    assert target["clientId"] in str(excinfo.value)


def test_workload_clients_are_service_accounts_with_audiences():
    c = clients()
    assert audiences(c["ops-worker"]) == {"${MCP_READ_RESOURCE_URL}", "${MCP_WRITE_RESOURCE_URL}"}
    assert audiences(c["ops-mcp-read"]) == {"asset-sim"}
    assert audiences(c["ops-mcp-write"]) == {"incident-sim"}
    for cid in ("ops-worker", "ops-mcp-read", "ops-mcp-write"):
        assert c[cid]["serviceAccountsEnabled"] is True, cid
        assert c[cid]["standardFlowEnabled"] is False and c[cid]["directAccessGrantsEnabled"] is False, cid
        assert c[cid]["publicClient"] is False, cid


def test_browser_client_uses_code_flow_with_pkce():
    web = clients()["ops-web"]
    assert web["standardFlowEnabled"] is True and web["directAccessGrantsEnabled"] is False
    assert web["serviceAccountsEnabled"] is False and web["publicClient"] is False
    assert web["attributes"]["pkce.code.challenge.method"] == "S256"
    # Exact allowlist (BUILD_SPEC §9), no wildcard.
    assert web["redirectUris"] == ["http://localhost:8000/auth/callback"]
    assert web["attributes"]["post.logout.redirect.uris"] == "http://localhost:8000/"


def test_direct_grant_client_is_public_and_dev_only():
    d = clients()["ops-dev-direct"]
    assert d["publicClient"] is True and d["directAccessGrantsEnabled"] is True
    assert d["standardFlowEnabled"] is False and d["serviceAccountsEnabled"] is False
    # The description is the only in-file warning that the password grant is a test aid.
    assert "dev-only" in d["description"]


def test_realm_users_carry_seed_ids():
    u = users()
    for name, persona in SEEDS["personas"].items():
        assert u[name]["id"] == persona["user_id"], name
        assert u[name]["realmRoles"] == persona["roles"], name
        assert u[name]["enabled"] is True
        assert "attributes" not in u[name]  # tenant membership lives in PostgreSQL (BUILD_SPEC §9), not in Keycloak
    # Every non-service-account user is a seeded persona: no stray login can exist in the realm.
    assert {n for n in u if not n.startswith("service-account-")} == set(SEEDS["personas"])


def test_view_users_service_account_has_exactly_one_client_role():
    # Least privilege for the Admin-API reader (AM-20.7): only view-users, no realm roles, no interactive grant.
    c = clients()["ops-view-users"]
    assert c["serviceAccountsEnabled"] is True and c["publicClient"] is False
    assert c["standardFlowEnabled"] is False and c["directAccessGrantsEnabled"] is False
    sa = users()["service-account-ops-view-users"]
    assert sa["serviceAccountClientId"] == "ops-view-users"
    assert sa["clientRoles"] == {"realm-management": ["view-users"]}
    assert "realmRoles" not in sa or sa["realmRoles"] == []


def test_file_is_lf_utf8_without_bom():
    raw = REALM.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw
