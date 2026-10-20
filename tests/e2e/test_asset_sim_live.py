"""asset-sim over a real socket with Keycloak's own tokens (OPS_LIVE=1; T16 DoD 2, R028's asset-sim half, R098;
Plan M rulings 5, 6 and 8).

The service is `production_app()` under uvicorn on a free loopback port in the test's own loop (the `asset_sim`
fixture), under the session's test profile. Catches: a worker, mcp-write, persona ("api", erratum 81's browser
stand-in) or `ops-view-users` token that reaches data, or a refusal that is not 401/403; mcp-read's own workload token
refused; alpha's tenant reading beta's B22, or told apart from an unknown asset; and the fault hooks missing under the
test profile (the dev profile's absence is tests/plan_m/test_asset_sim_app.py). Writes
reports/asset-sim/t16-asset-sim.txt (names and status codes only, never a token).
"""

import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx2
import pytest
from ops_core import settings
from ops_core.tokens import WorkloadTokenSource

from tests.plan_b.live import kc

pytestmark = pytest.mark.asyncio

ALPHA = "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"
BETA = "5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201"
EVIDENCE = Path("reports/asset-sim/t16-asset-sim.txt")
EXPECTED_LINES = 3  # one per test below


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T16 asset-sim — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def workload_token(secret: Callable[[str], str], client_id: str, secret_name: str) -> str:
    source = WorkloadTokenSource(
        token_url=settings.keycloak().token_url, client_id=client_id, client_secret=secret(secret_name)
    )
    return await source.token()


async def mcp_read_token(secret: Callable[[str], str]) -> str:
    return await workload_token(secret, "ops-mcp-read", "kc_client_secret_ops_mcp_read")


def context(token: str, tenant: str = ALPHA, as_of: str = "2026-10-06T00:00:00Z") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Ops-Tenant-Id": tenant, "X-Ops-As-Of": as_of}


async def test_dod2_asset_sim_serves_mcp_read_alone(
    asset_sim: str, secret: Callable[[str], str], lines: list[str]
) -> None:
    kcs = settings.keycloak()
    foreign = {
        "worker (ops-worker)": await workload_token(secret, "ops-worker", "kc_client_secret_ops_worker"),
        "mcp-write (ops-mcp-write)": await workload_token(secret, "ops-mcp-write", "kc_client_secret_ops_mcp_write"),
        "api (persona alex via ops-dev-direct, aud ops-api)": kc.token_password(
            kcs.base_url, "ops-dev-direct", "alex", secret("kc_persona_alex_password")
        )["access_token"],
        "api (ops-view-users service account)": await workload_token(
            secret, "ops-view-users", "kc_client_secret_ops_view_users"
        ),
    }
    answers: dict[str, int] = {}
    async with httpx2.AsyncClient(base_url=asset_sim) as http:
        for name, token in foreign.items():
            answer = await http.get("/assets/A17/status", headers=context(token))
            assert "state" not in answer.json(), name  # no foreign token reaches data
            answers[name] = answer.status_code
        served = await http.get("/assets/A17/status", headers=context(await mcp_read_token(secret)))
    # A token that carries another audience is 403; the view-users token's audience is the realm's choice (it may
    # carry none), so it may be 401 instead; either way it is refused.
    assert all(code == 403 for name, code in answers.items() if "view-users" not in name), answers
    assert answers["api (ops-view-users service account)"] in (401, 403)
    assert served.status_code == 200 and served.json()["state"] == "warning"  # A17 at 2026-10-06T00:00Z
    lines.append(f"DoD 2: refused {answers}; ops-mcp-read 200")


async def test_r028_the_forwarded_tenant_decides_and_an_existence_oracle_is_absent(
    asset_sim: str, secret: Callable[[str], str], lines: list[str]
) -> None:
    token = await mcp_read_token(secret)
    async with httpx2.AsyncClient(base_url=asset_sim) as http:
        foreign = await http.get("/assets/B22/status", headers=context(token, ALPHA))
        unknown = await http.get("/assets/Z99/status", headers=context(token, ALPHA))
        own = await http.get("/assets/B22/status", headers=context(token, BETA))
    assert (foreign.status_code, unknown.status_code, own.status_code) == (404, 404, 200)
    assert {k: v for k, v in foreign.json().items() if k != "request_id"} == {
        k: v for k, v in unknown.json().items() if k != "request_id"
    }  # alpha cannot tell beta's B22 from an asset that does not exist
    lines.append("R028 at asset-sim: alpha -> B22 404 (as Z99), beta -> B22 200")


async def test_the_fault_hooks_answer_under_the_test_profile(
    asset_sim: str, secret: Callable[[str], str], lines: list[str]
) -> None:
    token = await mcp_read_token(secret)
    async with httpx2.AsyncClient(base_url=asset_sim) as http:
        armed = await http.post("/internal/faults/asset_unavailable", headers=context(token), json={"count": 1})
        state = (await http.get("/assets/A17/status", headers=context(token))).json()["state"]
        await http.post("/internal/faults/drop_before_commit", headers=context(token), json={"count": 1})
        dropped = await http.get("/assets/A17/status", headers=context(token))
        after = await http.get("/assets/A17/status", headers=context(token))
    assert armed.status_code == 200 and state == "unavailable"
    assert dropped.status_code == 503 and after.json()["state"] == "warning"  # one occurrence each
    lines.append(
        "faults (test profile): asset_unavailable -> unavailable, drop_before_commit -> 503, then served again"
    )
