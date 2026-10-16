"""mcp-read refuses to start on a database without revision 0009 (Plan J ruling 18), as the other services refuse to
start without their revision's relation, and closes the connection it opened.

Catches: a server that resolves handles with 0007's unbound `_resolve_handle` (a dev database not yet migrated), a
check that asks the wrong function or for the wrong text, and a failed start that leaks its connection.
"""

from typing import Any

import pytest
from ops_core import persistence, settings
from ops_mcp_read import procedures, server
from starlette.testclient import TestClient

from tests.plan_j.test_mcp_read_http import FIXTURES, ISSUER, RESOURCE, KeyedVerifier


class CatalogConn:
    """Answers the two startup queries: no test clock, and whether the marker is in the stored body."""

    def __init__(self, bound: bool) -> None:
        self.bound = bound
        self.closed = False
        self.asked: list[tuple[object, ...]] = []

    async def execute(self, query: str, params: tuple[object, ...] = ()) -> "CatalogConn":
        self.asked.append(params)
        self.row = {"present": self.bound if "prosrc" in query else False}
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
    monkeypatch.setenv("PROFILE", "dev")
    state = server.State(session=None, corpora=procedures.load_corpora(FIXTURES), verifier=KeyedVerifier())
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
