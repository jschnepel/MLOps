"""Both MCP servers refuse to start on a database without revision 0009 (Plan J ruling 18; mcp-write since the final
review), as the other services refuse to start without their revision's relation, and close the connection they opened.

Catches: a server that resolves handles with 0007's unbound `_resolve_handle` (a dev database not yet migrated, such as
one the owner left at 0008), a check that asks the wrong function or for the wrong text, a failed start that leaks its
connection, and mcp-read's re-export drifting from the value in core that mcp-write checks.
"""

from typing import Any

import pytest
from ops_core import persistence, settings
from ops_mcp_read import server
from ops_mcp_write import server as write_server
from starlette.testclient import TestClient

from tests.plan_j.test_mcp_read_http import ISSUER, RESOURCE, KeyedVerifier


class CatalogConn:
    """Answers the startup queries: no test clock, 0007's relation present, and whether the marker is in the stored
    body."""

    def __init__(self, bound: bool) -> None:
        self.bound = bound
        self.closed = False
        self.asked: list[tuple[object, ...]] = []

    async def execute(self, query: str, params: tuple[object, ...] = ()) -> "CatalogConn":
        self.asked.append(params)
        self.row = {"present": self.bound if "prosrc" in query else False, "missing": False}
        return self

    async def fetchone(self) -> dict[str, Any]:
        return self.row

    async def close(self) -> None:
        self.closed = True


def start(monkeypatch: pytest.MonkeyPatch, conn: CatalogConn) -> None:
    async def connect(_pg: Any) -> CatalogConn:
        return conn

    monkeypatch.setattr(persistence, "connect", connect)
    monkeypatch.setattr(settings, "app_postgres", lambda role: role)
    monkeypatch.setattr(settings, "read_secret", lambda name: "unit-test")  # the asset-sim token source's (T16)
    monkeypatch.setenv("PROFILE", "dev")
    state = server.State(session=None, verifier=KeyedVerifier())
    app = server.build_app(server.build_server(state, issuer=ISSUER, resource_url=RESOURCE), state)
    with TestClient(app, base_url="http://127.0.0.1:8081") as client:
        assert client.get("/health/live").status_code == 200


def test_a_database_before_0009_is_refused_and_the_connection_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = CatalogConn(bound=False)
    with pytest.raises(persistence.PersistenceError, match="predates this service"):
        start(monkeypatch, conn)
    assert conn.closed
    assert conn.asked[-1] == (server.HANDLE_BINDING[1], "app._resolve_handle(text, text, text)")


def test_a_database_at_0009_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = CatalogConn(bound=True)
    start(monkeypatch, conn)
    assert conn.closed  # the lifespan's own close at shutdown


def test_mcp_read_re_exports_cores_marker() -> None:
    assert server.HANDLE_BINDING is persistence.HANDLE_BINDING


def start_write(monkeypatch: pytest.MonkeyPatch, conn: CatalogConn) -> None:
    async def connect(_pg: Any) -> CatalogConn:
        return conn

    monkeypatch.setattr(persistence, "connect", connect)
    monkeypatch.setattr(settings, "app_postgres", lambda role: role)
    monkeypatch.setattr(settings, "read_secret", lambda name: "unit-test")  # the destination token source's secret
    monkeypatch.setenv("PROFILE", "dev")
    state = write_server.State(deps=None, verifier=KeyedVerifier())
    app = write_server.build_app(
        write_server.build_server(state, issuer=ISSUER, resource_url="http://mcp-write:8082/mcp"), state
    )
    with TestClient(app, base_url="http://127.0.0.1:8082") as client:
        assert client.get("/health/live").status_code == 200


def test_mcp_write_refuses_a_database_before_0009_and_closes_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = CatalogConn(bound=False)
    with pytest.raises(persistence.PersistenceError, match="predates this service"):
        start_write(monkeypatch, conn)
    assert conn.closed
    assert conn.asked[-1] == (persistence.HANDLE_BINDING[1], "app._resolve_handle(text, text, text)")
    assert ("app.model_permit",) in conn.asked  # 0007's check still runs before it


def test_mcp_write_starts_on_a_database_at_0009(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = CatalogConn(bound=True)
    start_write(monkeypatch, conn)
    assert (persistence.HANDLE_BINDING[1], "app._resolve_handle(text, text, text)") in conn.asked
    assert conn.closed  # the lifespan's own close at shutdown
