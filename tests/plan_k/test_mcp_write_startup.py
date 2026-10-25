"""mcp-write refuses to start on a database without revision 0010 (Plan K ruling 25), as it does without 0009, and
closes the connection it opened.

Catches: a server that calls the definers with the token's `azp` on a database whose functions still take two
arguments (every call would fail with "function does not exist" at run time instead of at start), a check that asks the
wrong function or for the wrong text, and a failed start that leaks its connection. mcp-read checks nothing of 0010's:
it calls none of the functions 0010 changes (`resolve_invocation` keeps its signature); since T17 it asks for 0011's
corpus function instead (tests/plan_l/test_migration_0011.py).
"""

from typing import Any

import pytest
from ops_core import persistence

from tests.plan_j.test_mcp_read_startup import start, start_write


class MarkerConn:
    """Answers the startup queries: no test clock, 0007's relation present, and each marker present or not."""

    def __init__(self, present: set[str]) -> None:
        self.present = present
        self.closed = False
        self.asked: list[tuple[object, ...]] = []

    async def execute(self, query: str, params: tuple[object, ...] = ()) -> "MarkerConn":
        self.asked.append(params)
        found = "prosrc" in query and bool(params) and params[0] in self.present
        self.row = {"present": found, "missing": False}
        return self

    async def fetchone(self) -> dict[str, Any]:
        return self.row

    async def close(self) -> None:
        self.closed = True


# Since T21 a started mcp-write also finds revision 0016's guarded grant (Plan R ruling 16).
BOTH = {persistence.HANDLE_BINDING[1], persistence.WRITE_PATH[1], persistence.GRANT_GUARD[1]}


def test_mcp_write_refuses_a_database_at_0009_and_closes_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    conn: Any = MarkerConn({persistence.HANDLE_BINDING[1]})  # 0009's binding is there, 0010's write path is not
    with pytest.raises(persistence.PersistenceError, match="predates this service"):
        start_write(monkeypatch, conn)
    assert conn.closed
    assert conn.asked[-1] == (persistence.WRITE_PATH[1], "app.request_abort(text, text, uuid)")


def test_mcp_write_starts_on_a_database_at_0010(monkeypatch: pytest.MonkeyPatch) -> None:
    conn: Any = MarkerConn(BOTH)
    start_write(monkeypatch, conn)
    assert (persistence.WRITE_PATH[1], "app.request_abort(text, text, uuid)") in conn.asked
    assert conn.closed  # the lifespan's own close at shutdown


def test_mcp_read_does_not_ask_for_0010(monkeypatch: pytest.MonkeyPatch) -> None:
    present = (
        persistence.HANDLE_BINDING,
        persistence.GOVERNED_CORPUS,
        persistence.ASSET_SCOPE,
        persistence.SEARCH_INSTANT,
        persistence.VECTOR_SEARCH,
        persistence.READ_FRESHNESS,  # T21: revision 0016's stale-sync deferral (Plan R ruling 14)
    )
    conn: Any = MarkerConn({marker for _, marker in present})  # every mcp-read revision through 0016 (T21)
    start(monkeypatch, conn)
    assert all(persistence.WRITE_PATH[1] not in asked for asked in conn.asked)
    for signature, marker in present:  # mcp-read asks for each of its own revisions' markers, 0013's included
        assert (marker, signature) in conn.asked
