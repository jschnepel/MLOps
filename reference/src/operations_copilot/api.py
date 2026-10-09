"""Local-only reference API. No OIDC, queue or multi-replica claim is made here."""
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from typing import Annotated
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field
from .domain import DomainError, Forbidden, InvalidInput, require
from .models import OllamaModel
from .service import ControlService
from .store import Store
from .synthetic import SyntheticOperations

class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class CreateRun(StrictBody):
    message: str = Field(min_length=1, max_length=4000)
    asset_id: str | None = Field(default=None, min_length=1, max_length=32)
    hours: int | None = Field(default=None, ge=1, le=168)

class Clarification(StrictBody):
    asset_id: str = Field(min_length=1, max_length=32)
    hours: int = Field(ge=1, le=168)
    expected_version: int = Field(ge=1)

class Decision(StrictBody):
    proposal_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_version: int = Field(ge=1)
    decision: str = Field(pattern=r"^(approve|reject)$")

class Cancel(StrictBody):
    expected_version: int = Field(ge=1)


def create_app(service: ControlService | None = None, tokens: dict[str, str] | None = None) -> FastAPI:
    if os.environ.get("APP_MODE", "reference") != "reference":
        raise RuntimeError("This package is a reference demo. Implement the production milestones before enabling another mode.")
    if service is None:
        data = Path(os.environ.get("OPS_DATA_DIR", "runtime"))
        auth_file = data / "auth.json"
        if not auth_file.is_file():
            raise RuntimeError("Initialize local data and credentials with scripts/init_demo.py first.")
        tokens = json.loads(auth_file.read_text())
        model = None
        if os.environ.get("MODEL_MODE", "deterministic") == "ollama":
            model = OllamaModel(os.environ.get("OLLAMA_MODEL", ""), os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
        elif os.environ.get("MODEL_MODE", "deterministic") != "deterministic":
            raise RuntimeError("Unknown model mode. No automatic provider fallback is configured.")
        service = ControlService(Store(data / "app.sqlite3"), SyntheticOperations(data / "destination.sqlite3"), model)
    assert tokens is not None
    svc = service
    app = FastAPI(title="Operations Copilot — local reference", version="0.1.0", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver", "api"])

    @app.middleware("http")
    async def browser_headers(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            expected = f'{request.url.scheme}://{request.headers.get("host", "")}'
            if origin != expected:
                return JSONResponse({"detail": "Cross-origin mutation is not permitted."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    def identity(authorization: Annotated[str | None, Header()] = None) -> str:
        from fastapi import HTTPException
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer token required.", headers={"WWW-Authenticate": "Bearer"})
        candidate = hashlib.sha256(authorization[7:].encode()).hexdigest()
        actor_id = next((actor for hashed, actor in tokens.items() if secrets.compare_digest(hashed, candidate)), None)
        if actor_id is None:
            raise HTTPException(401, "Invalid bearer token.", headers={"WWW-Authenticate": "Bearer"})
        with svc.store.tx() as db:
            actor = svc.store.actor(db, actor_id)
            require(actor, actor.team)
        return actor_id
    Identity = Annotated[str, Depends(identity)]

    @app.get("/health/live")
    def live():
        return {"status": "alive", "mode": "reference"}

    @app.get("/health/ready")
    def ready():
        with closing(svc.store.connect()) as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ready"}

    @app.get("/api/me")
    def me(actor_id: Identity):
        with svc.store.tx() as db:
            actor = svc.store.actor(db, actor_id)
        return {"id": actor.id, "team": actor.team, "role": actor.role, "model_mode": type(svc.model).__name__}

    @app.post("/api/runs", status_code=201)
    def create(body: CreateRun, actor_id: Identity, idempotency_key: Annotated[str, Header(min_length=8, max_length=128)]):
        return svc.create(actor_id, body.message, body.asset_id, body.hours, idempotency_key)

    @app.get("/api/runs/{run_id}")
    def get(run_id: str, actor_id: Identity):
        return svc.get(actor_id, run_id)

    @app.post("/api/runs/{run_id}/clarify")
    def clarify(run_id: str, body: Clarification, actor_id: Identity):
        return svc.clarify(actor_id, run_id, body.asset_id, body.hours, body.expected_version)

    @app.post("/api/runs/{run_id}/prepare")
    def prepare(run_id: str, actor_id: Identity):
        return svc.prepare(actor_id, run_id)

    @app.post("/api/runs/{run_id}/decision")
    def decision(run_id: str, body: Decision, actor_id: Identity):
        return svc.decide(actor_id, run_id, body.proposal_hash, body.expected_version, body.decision)

    @app.post("/api/runs/{run_id}/execute")
    def execute(run_id: str, actor_id: Identity):
        # The deliberate response-loss fault is available in CLI/tests, not over this API.
        return svc.execute(actor_id, run_id)

    @app.post("/api/runs/{run_id}/reconcile")
    def reconcile(run_id: str, actor_id: Identity):
        return svc.reconcile(actor_id, run_id)

    @app.post("/api/runs/{run_id}/cancel")
    def cancel(run_id: str, body: Cancel, actor_id: Identity):
        return svc.cancel(actor_id, run_id, body.expected_version)

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str, actor_id: Identity, after: int = 0):
        return svc.events(actor_id, run_id, after)

    @app.get("/api/runs/{run_id}/stream")
    async def stream(run_id: str, actor_id: Identity, request: Request,
                     after: int = 0, last_event_id: Annotated[str | None, Header()] = None):
        svc.get(actor_id, run_id)  # Authorize BEFORE sending any response body.
        try:
            cursor = max(after, int(last_event_id or 0))
        except ValueError as exc:
            raise InvalidInput("Invalid event cursor.") from exc
        if cursor < 0:
            raise InvalidInput("Invalid event cursor.")
        async def generate():
            nonlocal cursor
            end = time.monotonic() + 55
            while time.monotonic() < end and not await request.is_disconnected():
                try:
                    batch = svc.events(actor_id, run_id, cursor)  # Recheck current access every batch.
                except DomainError:
                    yield 'event: access.revoked\ndata: {"message":"Access ended."}\n\n'
                    return
                for item in batch:
                    cursor = item["id"]
                    yield f'id: {cursor}\nevent: activity\ndata: {json.dumps(item)}\n\n'
                if not batch:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(0.5)
        return StreamingResponse(generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    web_dir = Path(__file__).parent / "web"
    if web_dir.exists():
        app.mount("/static", StaticFiles(directory=web_dir), name="static")
        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(web_dir / "index.html")
    return app
