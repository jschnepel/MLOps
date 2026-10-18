"""`search_procedures` on the run's own asset type (Plan M rulings 3, 12 and 15), in-process, the database calls and
asset-sim replaced.

Catches: a caller's asset type that differs from the run's searched instead of refused, or refused only after the
definer ran; an unreachable asset-sim that lets the search run without the run's type (it must fail closed); the
real client asking asset-sim for anything but the run's asset with mcp-read's own token, or passing on an answer that
names another asset; and a search answer whose `observed_at` is the wall clock rather than the definer's instant.
"""

import httpx2
import pytest
from ops_core import persistence
from ops_mcp_read import assets

from tests.plan_l.test_mcp_read_corpus import SCOPE, Database, RunType, UnitConn, call
from tests.plan_m.test_mcp_read_assets import Tokens

pytestmark = pytest.mark.asyncio

QUERY = {"query": "seal", "limit": 3, "mode": "lexical"}


async def test_a_caller_type_that_is_not_the_runs_is_refused_before_the_definer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database(UnitConn())
    refused = await call(monkeypatch, db, {**QUERY, "asset_type": "compressor"}, RunType("pump"))
    assert [name for name, _, _ in db.calls] == ["resolve", "scope"]  # the definer never ran
    doc = refused.structured_content
    assert doc is not None and doc["error"]["code"] == "ASSET_TYPE_OUT_OF_SCOPE" and doc["data"] is None
    assert doc["observed_at"] == "2026-10-16T12:00:00Z"  # the scope's as_of, not the wall clock
    for spelling in ("Pump", "PUMP"):  # the comparison is exact: another case is another type
        cased = Database(UnitConn())
        result = await call(monkeypatch, cased, {**QUERY, "asset_type": spelling}, RunType("pump"))
        assert [name for name, _, _ in cased.calls] == ["resolve", "scope"]
        assert result.structured_content is not None
        assert result.structured_content["error"]["code"] == "ASSET_TYPE_OUT_OF_SCOPE"
    same = Database(UnitConn())
    await call(monkeypatch, same, {**QUERY, "asset_type": "pump"}, RunType("pump"))  # repeating it is allowed
    assert same.calls[2][2]["asset_type"] == "pump"


async def test_an_unreachable_asset_sim_fails_the_search_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(UnitConn())
    result = await call(monkeypatch, db, QUERY, RunType(assets.Unavailable("asset-sim could not be reached")))
    assert [name for name, _, _ in db.calls] == ["resolve", "scope"]
    doc = result.structured_content
    assert doc is not None and doc["error"] == {
        "code": "UNAVAILABLE",
        "message": "asset-sim could not be reached",
        "retryable": True,
    }


async def test_an_invalid_type_lookup_or_no_client_never_reaches_the_definer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database(UnitConn())
    result = await call(
        monkeypatch, db, QUERY, RunType(assets.UpstreamInvalid("asset-sim answered outside the contract"))
    )
    assert [name for name, _, _ in db.calls] == ["resolve", "scope"]
    doc = result.structured_content
    assert doc is not None and doc["data"] is None and doc["observed_at"] == "2026-10-16T12:00:00Z"
    assert doc["error"]["code"] == "UPSTREAM_INVALID" and doc["error"]["retryable"] is False
    bare = Database(UnitConn())
    result = await call(monkeypatch, bare, QUERY, configured=False)  # no asset-sim client at all
    assert [name for name, _, _ in bare.calls] == ["resolve", "scope"]
    doc = result.structured_content
    assert doc is not None and doc["data"] is None and doc["observed_at"] == "2026-10-16T12:00:00Z"
    assert doc["error"]["code"] == "UNAVAILABLE" and doc["error"]["retryable"] is True


async def test_the_answer_is_stamped_with_the_definers_instant(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await call(monkeypatch, Database(UnitConn()), QUERY)
    doc = result.structured_content
    assert doc is not None and doc["status"] == "ok"
    assert doc["observed_at"] == doc["data"]["results"][0]["retrieved_at"] == "2026-10-16T12:00:00Z"


async def test_the_real_client_asks_for_the_runs_asset_with_its_own_token() -> None:
    seen: list[httpx2.Request] = []
    answers = iter(
        [
            httpx2.Response(200, json={"asset_id": "A17", "asset_type": "pump"}),
            httpx2.Response(404, json={"code": "NOT_FOUND"}),
            httpx2.Response(200, json={"asset_id": "B22", "asset_type": "pump"}),  # another asset's answer
        ]
    )

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return next(answers)

    client = assets.HttpAssetSim("http://asset-sim.test", Tokens(), transport=httpx2.MockTransport(answer))
    try:
        assert await client.asset_type(SCOPE) == "pump"
        assert await client.asset_type(SCOPE) is None  # unknown to asset-sim: the caller's type or none
        with pytest.raises(assets.UpstreamInvalid):
            await client.asset_type(SCOPE)
        odd = persistence.AssetScope(**{**SCOPE.__dict__, "asset_id": "../internal/faults/x"})
        assert await client.asset_type(odd) is None  # a run's asset text that is no asset id is never sent
    finally:
        await client.aclose()
    assert [r.url.path for r in seen] == ["/assets/A17"] * 3
    assert {r.headers["authorization"] for r in seen} == {"Bearer mcp-read-token"}
    assert {r.headers["x-ops-as-of"] for r in seen} == {"2026-10-16T12:00:00Z"}
