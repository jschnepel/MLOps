"""`python -m ops_asset_sim`: serve on 127.0.0.1:OPS_ASSET_SIM_PORT (default 8091)."""

import asyncio
import sys

import uvicorn
from ops_core import redaction
from ops_core.settings import env_int
from starlette.types import ASGIApp

from ops_asset_sim.app import production_app


def serve_app(app: ASGIApp, port: int) -> None:
    """Serve with uvicorn programmatically on a selector loop, as incident-sim does (`uvicorn.run` picks the Proactor
    loop on Windows)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    # The redaction filter must sit on the root handler before the first log line (T11 note 4).
    redaction.install()
    serve_app(production_app(), env_int("OPS_ASSET_SIM_PORT", 8091))
