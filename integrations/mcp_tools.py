"""MCP SDK v2 tool factory. Transport authentication is the host's responsibility.

This file does NOT launch a network server. resolve_identity MUST obtain identity
from validated transport credentials, not an MCP argument or a model message.
A fixed identity resolver is permissible ONLY in an in-process contract test.
"""
from typing import Callable
from mcp.server import MCPServer, Context
from operations_copilot.domain import require, validate_hours
from operations_copilot.service import ControlService


def build_mcp(service: ControlService, resolve_identity: Callable[[Context], str]) -> MCPServer:
    server=MCPServer('operations-copilot-tools')

    def principal(ctx: Context):
        actor_id=resolve_identity(ctx)
        with service.store.tx() as db:
            actor=service.store.actor(db,actor_id)
            require(actor,actor.team)
        return actor

    @server.tool()
    def get_asset_status(asset_id: str, ctx: Context) -> dict:
        """Read an authorized synthetic asset. Does not change equipment."""
        actor=principal(ctx)
        return service.ops.asset(asset_id,actor.team)

    @server.tool()
    def search_procedures(query: str, ctx: Context) -> dict:
        """Return approved team-visible synthetic procedure excerpts."""
        actor=principal(ctx)
        if not 1<=len(query)<=500:raise ValueError('Bounded search query required.')
        return {'documents':service.ops.procedures(actor.team),
                'retrieval_mode':'small-fixture-filter-not-vector-search'}

    @server.tool()
    def get_recent_alerts(asset_id: str, hours: int, ctx: Context) -> dict:
        """Read a bounded alert window for an authorized synthetic asset."""
        actor=principal(ctx)
        return service.ops.alerts(asset_id,actor.team,validate_hours(hours))

    @server.tool()
    def create_incident(proposal_id: str, ctx: Context) -> dict:
        """Submit an already approved immutable proposal. Cannot grant approval."""
        actor=principal(ctx)
        # In the reference, one run holds one proposal; proposal_id is that run ID.
        # The target schema separates proposal_id and run_id; see database/target_schema.sql.
        return service.execute(actor.id,proposal_id)

    return server
