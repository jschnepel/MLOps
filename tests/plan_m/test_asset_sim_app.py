"""asset-sim's HTTP surface in-process, with the production verifier's wiring and Plan D's synthetic signing key
(Plan M rulings 5, 6, 8-10; T16 DoD 2; R098).

Catches: a token for another audience or client (the worker's, mcp-write's, a persona's) served, or refused with a
code that does not tell a foreign token (403) from a bad one (401 with `WWW-Authenticate: Bearer`); an ID or refresh
token accepted; another tenant's asset told apart from an unknown one (an existence oracle); a request without the
forwarded tenant or instant answered from a default; a status, an asset type or a page that is not the data rule's; a
cursor replayed for another interval accepted; an error body that echoes the request; and fault routes reachable
outside the test profile, or accepting a fault this service never consumes. The live version, with Keycloak's own
tokens, is tests/e2e/test_asset_sim_live.py.
"""

import base64
import struct
from typing import Any
from uuid import UUID

import pytest
from ops_asset_sim import app as asset_app
from ops_asset_sim import data
from ops_core.settings import Keycloak, Profile
from starlette.testclient import TestClient

from tests.plan_d.test_tokens import ISSUER, JWK1, mint

ALPHA = "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"
BETA = "5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201"
KC = Keycloak(base_url="http://localhost:18080", issuer=ISSUER, server_url="http://127.0.0.1:18080")
MCP_READ = {"aud": ["asset-sim", "account"], "azp": "ops-mcp-read"}  # the realm's ops-mcp-read token, synthetic
BASE = "http://127.0.0.1:8091"


def client(profile: Profile = Profile.DEV) -> TestClient:
    verifier = asset_app.verifier_for(KC)
    verifier.install_keys({"keys": [JWK1]})  # ready: the lifespan loads nothing
    return TestClient(asset_app.create_app(verifier, catalog=data.load(), profile=profile), base_url=BASE)


def headers(tenant: str = ALPHA, as_of: str | None = "2026-10-06T00:00:00Z", **token: Any) -> dict[str, str]:
    out = {"Authorization": f"Bearer {mint(**(token or MCP_READ))}", "X-Ops-Tenant-Id": tenant}
    if as_of is not None:
        out["X-Ops-As-Of"] = as_of
    return out


def test_only_mcp_reads_access_token_is_served() -> None:
    foreign = {
        "the worker's (aud mcp-read)": ({}, 403),  # mint()'s default: aud mcp-read's resource, azp ops-worker
        "mcp-write's (aud incident-sim)": ({"aud": ["incident-sim"], "azp": "ops-mcp-write"}, 403),
        "a persona's (aud ops-api)": ({"aud": "ops-api", "azp": "ops-dev-direct"}, 403),
        "the worker client with asset-sim's audience": ({"aud": ["asset-sim"], "azp": "ops-worker"}, 403),
        "an ID token of mcp-read": ({**MCP_READ, "typ": "ID"}, 401),
        "a refresh token of mcp-read": ({**MCP_READ, "typ": "Refresh"}, 401),
        "no audience at all": ({"aud": None, "azp": "ops-mcp-read"}, 401),
    }
    with client() as http:
        for why, (claims, status) in foreign.items():
            token = mint(**claims) if claims else mint()
            answer = http.get("/assets/A17/status", headers={**headers(), "Authorization": f"Bearer {token}"})
            assert answer.status_code == status, why
            assert "state" not in answer.json(), why  # none reaches data
        bare = http.get("/assets/A17/status", headers={"X-Ops-Tenant-Id": ALPHA, "X-Ops-As-Of": "2026-10-06T00:00:00Z"})
        assert bare.status_code == 401 and bare.headers["www-authenticate"] == "Bearer"
        served = http.get("/assets/A17/status", headers=headers())
        assert served.status_code == 200 and served.json()["state"] == "warning"


def test_another_tenants_asset_and_an_unknown_one_get_the_same_404() -> None:
    with client() as http:
        foreign = http.get("/assets/B22/status", headers=headers(ALPHA))  # R028: alpha asks for beta's B22
        unknown = http.get("/assets/Z99/status", headers=headers(ALPHA))
        malformed = http.get("/assets/a17/status", headers=headers(ALPHA))
        answers = [foreign, unknown, malformed]
        assert [a.status_code for a in answers] == [404, 404, 404]
        assert len({tuple(sorted((k, v) for k, v in a.json().items() if k != "request_id")) for a in answers}) == 1
        assert http.get("/assets/B22/status", headers=headers(BETA)).json()["state"] == "warning"  # beta's own
        assert http.get("/assets/B22", headers=headers(ALPHA)).status_code == 404
        no_tenant = http.get(
            "/assets/A17/status", headers={k: v for k, v in headers().items() if k != "X-Ops-Tenant-Id"}
        )
        no_instant = http.get("/assets/A17/status", headers=headers(as_of=None))
        local_time = http.get("/assets/A17/status", headers=headers(as_of="2026-10-06T02:00:00+02:00"))
        for answer in (no_tenant, no_instant, local_time):
            assert answer.status_code == 400 and answer.json()["code"] == "INVALID_INPUT"
            assert "+02:00" not in answer.text  # never echoed


def test_the_routes_answer_the_data_rules() -> None:
    with client() as http:
        assert http.get("/assets/A17", headers=headers()).json() == {"asset_id": "A17", "asset_type": "pump"}
        status = http.get("/assets/A17/status", headers=headers(as_of="2026-10-06T12:00:00Z")).json()
        assert status == {
            "asset_id": "A17",
            "state": "warning",
            "revision": 2,
            "observed_at": "2026-10-06T12:00:00Z",
            "data_source": "synthetic",
        }
        query = {"start_at": "2026-10-05T00:00:00Z", "end_at": "2026-10-07T00:00:00+00:00", "limit": "1"}
        first = http.get("/assets/A17/alerts", headers=headers(as_of="2026-10-16T12:00:00Z"), params=query).json()
        assert len(first["alerts"]) == 1 and first["end_at"] == "2026-10-07T00:00:00Z" and first["next_cursor"]
        second = http.get(
            "/assets/A17/alerts",
            headers=headers(as_of="2026-10-16T12:00:00Z"),
            params={**query, "cursor": first["next_cursor"]},
        ).json()
        assert [a["revision"] for a in first["alerts"] + second["alerts"]] == [1, 2] and second["next_cursor"] is None
        replayed = http.get(
            "/assets/A17/alerts",
            headers=headers(as_of="2026-10-16T12:00:00Z"),
            params={**query, "end_at": "2026-10-08T00:00:00Z", "cursor": first["next_cursor"]},
        )
        assert replayed.status_code == 400  # a cursor of another interval
        for bad in ({"limit": "101"}, {"limit": "0"}, {"end_at": "2026-10-05T00:00:00Z"}, {"start_at": "yesterday"}):
            answer = http.get("/assets/A17/alerts", headers=headers(), params={**query, **bad})
            assert answer.status_code == 400, bad


@pytest.mark.parametrize("profile", [p for p in Profile if p is not Profile.TEST])
def test_no_fault_route_exists_outside_the_test_profile(profile: Profile) -> None:
    """R098 for every profile but test: no kind can be armed, and no read ever answers a fault."""
    with client(profile) as http:
        for kind in asset_app.FAULTS:
            assert http.post(f"/internal/faults/{kind.value}", headers=headers(), json={"count": 1}).status_code == 404
        assert http.get("/assets/A17/status", headers=headers()).json()["state"] == "warning"  # never `unavailable`


def test_fault_routes_answer_under_the_test_profile() -> None:
    arm = {"count": 1}
    with client(Profile.TEST) as http:
        assert http.post("/internal/faults/asset_unavailable", headers=headers(), json=arm).status_code == 200
        assert http.get("/assets/A17/status", headers=headers()).json()["state"] == "unavailable"
        assert http.get("/assets/A17/status", headers=headers()).json()["state"] == "warning"  # one occurrence only
        assert http.post("/internal/faults/drop_before_commit", headers=headers(), json=arm).status_code == 200
        assert http.get("/assets/A17", headers=headers()).status_code == 503
        assert http.post("/internal/faults/malformed_response", headers=headers(), json=arm).status_code == 200
        assert "data_source" not in http.get("/assets/A17/status", headers=headers()).json()
        never_taken = http.post("/internal/faults/reject_next", headers=headers(), json=arm)
        assert never_taken.status_code == 422  # a destination fault asset-sim never consumes
        timed = http.post("/internal/faults/malformed_response", headers=headers(), json={"count": 1, "seconds": 2})
        assert timed.status_code == 422
        foreign = http.post("/internal/faults/asset_unavailable", headers=headers(azp="ops-worker"), json=arm)
        assert foreign.status_code == 403  # only mcp-read's token arms a fault
        assert UUID(http.get("/assets/Z99", headers=headers()).json()["request_id"])  # a safe error, nothing armed


def test_a_malformed_tenant_or_cursor_is_a_400_never_a_500() -> None:
    query = {"start_at": "2026-10-05T00:00:00Z", "end_at": "2026-10-07T00:00:00Z", "limit": "1"}
    alerts_headers = headers(as_of="2026-10-16T12:00:00Z")
    with client() as http:
        for tenant in ("not-a-uuid", "", "3ea79c95-914c-52cb-9d10-c4e19dda8ff7x"):
            answer = http.get("/assets/A17/status", headers={**headers(), "X-Ops-Tenant-Id": tenant})
            assert answer.status_code == 400 and answer.json()["code"] == "INVALID_INPUT", tenant
        first_page = http.get("/assets/A17/alerts", headers=alerts_headers, params=query).json()
        real = first_page["next_cursor"]
        bound = data.binding(UUID(ALPHA), "A17", data.instant(query["start_at"]), data.instant(query["end_at"]))
        raw = struct.pack(">Bq", data.CURSOR_VERSION, 2**63 - 1) + UUID(int=0).bytes + bound
        forged = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        for cursor in ("!!", real + "=", forged):  # malformed, non-canonical, and bound but out of range
            answer = http.get("/assets/A17/alerts", headers=alerts_headers, params={**query, "cursor": cursor})
            assert answer.status_code == 400 and answer.json()["code"] == "INVALID_INPUT", cursor
            assert cursor not in answer.text  # never echoed
