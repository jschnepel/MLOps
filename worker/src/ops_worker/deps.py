"""What a job handler and the graph's nodes need (`handlers.Deps` re-exports it): one module both import, so the graph
package does not import the handlers that drive it."""

from __future__ import annotations

from dataclasses import dataclass, field

from langgraph.checkpoint.base import BaseCheckpointSaver
from ops_core import persistence
from ops_core.settings import LeaseSettings, Urls

from ops_worker.drafting import DraftGenerator
from ops_worker.heartbeat import Heartbeat
from ops_worker.mcp import McpCaller


@dataclass
class Deps:
    """What a handler needs: the loop's connection, the MCP client, the model route, the server URLs, the worker's
    name (the lease owner), the workload client its tokens are issued to (the `azp` a handle is bound to), the lease
    settings, the heartbeat that renews the lease while a job runs, and the checkpoint saver the graph persists to.

    The saver is required, so a `Deps` built without one cannot silently lose durability: the worker passes the Postgres
    saver on its own connection (`main._main`, SA:559-562), and unit tests pass LangGraph's in-memory one."""

    conn: persistence.Conn
    mcp: McpCaller
    generator: DraftGenerator
    urls: Urls
    worker_name: str
    workload_azp: str  # the token source's client id (Plan J ruling 17): _resolve_handle compares it with the token's
    saver: BaseCheckpointSaver[str]
    leases: LeaseSettings = field(default_factory=LeaseSettings)
    heartbeat: Heartbeat | None = None  # main.run_job hands it each claimed lease; tests may run without one
