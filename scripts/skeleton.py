"""Walking-skeleton operations (T08): `migrate` both databases to head;
`up`, `down` and `status` run the five processes.

Reads `.env` (written by scripts/bootstrap_dev.py) for ports and the secrets directory, exports the `OPS_*` variables
every service reads (ops_core.settings), and runs the two Alembic trees programmatically with a shared connection
(Alembic cookbook: "Sharing a Connection across one or more programmatic migration commands"); the engine is built
from a `URL` object, so the password is never rendered into a string. The `incident` role is created or re-keyed
from its secret file on every run; role credentials are a bootstrap concern, schema is the migration's.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import psycopg
from alembic import command
from alembic.config import Config
from ops_core import settings
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = {"app": ROOT / "migrations" / "app", "incident": ROOT / "migrations" / "incident"}


def load_dotenv(path: Path = Path(".env")) -> dict[str, str]:
    """Parse the KEY=VALUE lines of .env; the file holds paths, ports and URLs only (never a secret)."""
    if not path.exists():
        raise SystemExit("no .env: run `uv run python scripts/bootstrap_dev.py secrets` first")
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if line and "=" in line)
    return {k.strip(): v.strip() for k, v in pairs if not k.startswith("#")}


def export_environment(dotenv: dict[str, str]) -> None:
    """Derive the OPS_* variables from .env without overriding anything the caller already set."""
    base = f"http://localhost:{dotenv['KC_HTTP_PORT']}"
    derived = {
        "OPS_SECRETS_DIR": dotenv["OPS_SECRETS_DIR"],
        "OPS_PG_PORT": dotenv["PG_PORT"],
        "OPS_KC_BASE_URL": base,
        "OPS_KC_ISSUER": f"{base}/realms/{settings.REALM}",
        "MCP_READ_RESOURCE_URL": dotenv["MCP_READ_RESOURCE_URL"],
        "MCP_WRITE_RESOURCE_URL": dotenv["MCP_WRITE_RESOURCE_URL"],
    }
    for key, value in derived.items():
        os.environ.setdefault(key, value)


def ensure_incident_role(superuser: settings.Postgres, password: str) -> None:
    """CREATE or re-key role `incident` with the secret file's value; idempotent so `migrate` can be re-run."""
    with psycopg.connect(superuser.conninfo(), autocommit=True) as conn:
        # Utility statements take no bind parameters, so the password travels through a session setting and
        # format(%L) quotes it server-side; it never appears in a Python-built SQL string.
        conn.execute("SELECT set_config('ops.incident_password', %s, false)", (password,))
        conn.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'incident') THEN
                    EXECUTE format('CREATE ROLE incident LOGIN PASSWORD %L', current_setting('ops.incident_password'));
                ELSE
                    EXECUTE format('ALTER ROLE incident PASSWORD %L', current_setting('ops.incident_password'));
                END IF;
            END
            $$
            """
        )
        conn.execute("GRANT CONNECT ON DATABASE incident TO incident")
        # The secret must not linger in the session setting.
        conn.execute("SELECT set_config('ops.incident_password', '', false)")


def upgrade(tree: str, pg: settings.Postgres) -> None:
    url = URL.create(
        "postgresql+psycopg", username=pg.user, password=pg.password, host=pg.host, port=pg.port, database=pg.dbname
    )
    engine = create_engine(url)
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS[tree]))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    engine.dispose()


def migrate() -> int:
    export_environment(load_dotenv(ROOT / ".env"))
    app_pg = settings.app_postgres()
    incident_as_superuser = settings.Postgres(app_pg.host, app_pg.port, app_pg.user, "incident", app_pg.password)
    ensure_incident_role(incident_as_superuser, settings.read_secret("postgres_incident_password"))
    upgrade("app", app_pg)
    upgrade("incident", incident_as_superuser)
    print("MIGRATE: app and incident at head")
    return 0


@dataclass(frozen=True)
class Process:
    """One skeleton process: its name, `python -m` module and loopback port."""

    name: str
    module: str
    port: int

    @property
    def health_url(self) -> str:
        """The process's own readiness URL on loopback."""
        return f"http://127.0.0.1:{self.port}/health/ready"


PROCESSES: tuple[Process, ...] = (
    Process("incident-sim", "ops_incident_sim", 8090),
    Process("mcp-read", "ops_mcp_read", 8081),
    Process("mcp-write", "ops_mcp_write", 8082),
    Process("api", "ops_api", 8000),
    Process("worker", "ops_worker", 8070),
)
LOGS = ROOT / "runtime" / "skeleton"  # git-ignored (runtime/)


def process_environment() -> dict[str, str]:
    """The environment every child inherits: .env-derived OPS_* variables plus the port defaults."""
    export_environment(load_dotenv(ROOT / ".env"))
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("MODEL_MODE", "fake")
    env.setdefault("OPS_API_PORT", "8000")
    env.setdefault("OPS_WORKER_HEALTH_PORT", "8070")
    env.setdefault("OPS_MCP_READ_PORT", "8081")
    env.setdefault("OPS_MCP_WRITE_PORT", "8082")
    env.setdefault("OPS_INCIDENT_SIM_PORT", "8090")
    return env


def healthy(url: str) -> bool:
    """True when the loopback health URL answers 200."""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # loopback health URL only
            return bool(response.status == 200)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


class Skeleton:
    """The five host processes as children of this one; logs under runtime/skeleton/ (never committed)."""

    def __init__(self) -> None:
        self.children: dict[str, subprocess.Popen[bytes]] = {}
        self.logs: list[IO[bytes]] = []

    def start(self, timeout: float = 90.0) -> None:
        """Start every process and wait for each /health/ready; stop all and raise if one dies or is late."""
        if any(healthy(p.health_url) for p in PROCESSES):
            raise RuntimeError("skeleton processes already running; run down first")
        LOGS.mkdir(parents=True, exist_ok=True)
        env = process_environment()
        for proc in PROCESSES:
            log = open(LOGS / f"{proc.name}.log", "ab")  # noqa: SIM115  -- closed in stop(); the child writes to it
            self.logs.append(log)
            self.children[proc.name] = subprocess.Popen(
                [sys.executable, "-m", proc.module], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT
            )
        deadline = time.monotonic() + timeout
        pending = {p.name: p for p in PROCESSES}
        while pending and time.monotonic() < deadline:
            for name, proc in list(pending.items()):
                if self.children[name].poll() is not None:
                    self.stop()
                    raise RuntimeError(f"{name} exited early; see runtime/skeleton/{name}.log")
                if healthy(proc.health_url):
                    del pending[name]
            time.sleep(0.25)
        if pending:
            self.stop()
            raise RuntimeError(f"not ready in {timeout}s: {sorted(pending)}; see runtime/skeleton/*.log")

    def stop(self) -> None:
        """Terminate every child, kill any that outlives 15 s, and close the log handles."""
        for child in self.children.values():
            if child.poll() is None:
                child.terminate()  # TerminateProcess on Windows: no lifespan shutdown, which the skeleton tolerates
        for child in self.children.values():
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
            if child.stdout is not None:
                child.stdout.close()
        for handle in self.logs:
            handle.close()
        self.logs.clear()
        self.children.clear()


def up() -> int:
    """Start the five processes and record their pids for `down`; they outlive this script. Refuses a second set."""
    if (LOGS / "pids.json").exists() or any(healthy(p.health_url) for p in PROCESSES):
        print("UP: refused — processes already running (see status); run down first")
        return 2
    skeleton = Skeleton()
    try:
        skeleton.start()
    except RuntimeError as error:
        print(f"UP: failed — {error}")
        return 1
    (LOGS / "pids.json").write_text(json.dumps({n: c.pid for n, c in skeleton.children.items()}), encoding="utf-8")
    print("UP: " + ", ".join(f"{p.name}:{p.port}" for p in PROCESSES))
    return 0


def down() -> int:
    """Terminate the pids `up` recorded."""
    pids_path = LOGS / "pids.json"
    if not pids_path.exists():
        print("DOWN: nothing recorded")
        return 0
    for name, pid in json.loads(pids_path.read_text(encoding="utf-8")).items():
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        print(f"DOWN: {name} ({pid})")
    pids_path.unlink()
    return 0


def status() -> int:
    """Print each process's readiness; a worker whose poll loop died has exited (non-zero) and shows `down`."""
    for proc in PROCESSES:
        print(f"{proc.name:13s} {'ready' if healthy(proc.health_url) else 'down':6s} 127.0.0.1:{proc.port}")
    return 0


def main(argv: list[str]) -> int:
    commands = {"migrate": migrate, "up": up, "down": down, "status": status}
    if len(argv) == 2 and argv[1] in commands:
        return commands[argv[1]]()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
