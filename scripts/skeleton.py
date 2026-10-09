"""Walking-skeleton operations (T08, T09, T10): `migrate` both databases, `up`/`down`/`status` the six processes,
`keys` the destination-vs-grant detective check.

Reads `.env` (written by scripts/bootstrap_dev.py) for ports and the secrets directory, exports the `OPS_*` variables
every service reads (ops_core.settings), and runs the two Alembic trees programmatically with a shared connection
(Alembic cookbook: "Sharing a Connection across one or more programmatic migration commands"); the engine is built
from a `URL` object, so the password is never rendered into a string. Roles and their passwords are a bootstrap
concern, schema and grants are the migrations' (SA:395): every AM-20.1 login role is created or re-keyed from its
secret file on each run, the NOLOGIN owner roles are created, and database CONNECT is narrowed to the roles that use
each database, all before Alembic runs. The profile picks the Alembic target: only the test profile applies the
`testclock` branch (SA:529), and `up` refuses to start the dev skeleton against a database that carries it.
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
from uuid import UUID

import psycopg
from alembic import command
from alembic.config import Config
from ops_core import privileges, settings
from ops_core.settings import Profile, Role
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

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


NOLOGIN_ROLES: tuple[tuple[str, bool], ...] = (("migrator", True), ("app_definer", False), ("incident_owner", False))
TEST_ONLY_ROLES: frozenset[Role] = frozenset(Role(r) for r in privileges.TEST_ONLY_ROLES)  # SA:403; one source


def login_roles(profile: Profile) -> tuple[Role, ...]:
    """The AM-20.1 login roles a profile has: every role, or every role but the test harness."""
    return tuple(r for r in Role if profile is Profile.TEST or r not in TEST_ONLY_ROLES)


def ensure_login_role(conn: psycopg.Connection[object], name: str, password: str) -> None:
    """CREATE or re-key one LOGIN role with its secret file's value; idempotent so `migrate` can be re-run."""
    # Utility statements take no bind parameters, so the name and password travel through session settings and
    # format(%I/%L) quotes them server-side; neither appears in a Python-built SQL string.
    conn.execute(
        "SELECT set_config('ops.role_name', %s, false), set_config('ops.role_password', %s, false)", (name, password)
    )
    try:
        # A failing EXECUTE would carry the formatted statement, password included, in its CONTEXT (measured in the
        # round-1 review); the handler re-raises a message that names only the role, with the original SQLSTATE.
        conn.execute(
            """
            DO $$
            BEGIN
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_setting('ops.role_name')) THEN
                        EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS '
                                       'PASSWORD %L',
                                       current_setting('ops.role_name'), current_setting('ops.role_password'));
                    ELSE
                        EXECUTE format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS '
                                       'PASSWORD %L',
                                       current_setting('ops.role_name'), current_setting('ops.role_password'));
                    END IF;
                EXCEPTION WHEN OTHERS THEN
                    RAISE EXCEPTION 'role bootstrap failed for %', current_setting('ops.role_name')
                        USING ERRCODE = SQLSTATE;
                END;
            END
            $$
            """
        )
    finally:
        conn.execute("SELECT set_config('ops.role_name', '', false), set_config('ops.role_password', '', false)")


def ensure_nologin_role(conn: psycopg.Connection[object], name: str, bypassrls: bool) -> None:
    """CREATE a NOLOGIN role (owner or definer) and pin its BYPASSRLS attribute either way."""
    conn.execute("SELECT set_config('ops.role_name', %s, false)", (name,))
    conn.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_setting('ops.role_name')) THEN
                EXECUTE format('CREATE ROLE %I NOLOGIN', current_setting('ops.role_name'));
            END IF;
        END
        $$
        """
    )
    attribute = sql.SQL("BYPASSRLS") if bypassrls else sql.SQL("NOBYPASSRLS")
    conn.execute(
        sql.SQL("ALTER ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE {}").format(sql.Identifier(name), attribute)
    )
    conn.execute("SELECT set_config('ops.role_name', '', false)")


def narrow_connect(conn: psycopg.Connection[object], database: str, roles: tuple[str, ...]) -> None:
    """Exactly the named roles may connect to `database` (BS:246; spike §3 measured the revoke on `incident`).

    Roles are cluster-wide, so a test-profile migrate must not leave `test_harness` (or any role of another profile)
    able to reach a dev database: CONNECT is also revoked from every other existing login role of ours.
    """
    conn.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
    ours = [*(r.value for r in Role), "incident"]
    # A REVOKE that names a missing role errors, so only roles that exist are named.
    present = {row[0] for row in conn.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (ours,))}
    for other in sorted(present - set(roles)):
        conn.execute(
            sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(sql.Identifier(database), sql.Identifier(other))
        )
    grantees = sql.SQL(", ").join(sql.Identifier(r) for r in roles)
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), grantees))


def ensure_roles(superuser: settings.Postgres, app_db: str, incident_db: str, profile: Profile) -> None:
    """Every AM-20.1 role of the profile with its password and CONNECT, before any migration runs (ruling 3)."""
    roles = login_roles(profile)
    with psycopg.connect(superuser.conninfo(), autocommit=True) as conn:
        # Bind parameters must never reach the server log: the passwords below travel as set_config parameters, and
        # log_statement = 'all' or a logged error would otherwise record them (final review M12). Both settings are
        # superuser-only and last for this connection alone; the _on_error twin covers a failed statement.
        conn.execute("SET log_parameter_max_length = 0")
        conn.execute("SET log_parameter_max_length_on_error = 0")
        conn.execute("SET log_statement = 'none'")
        for name, bypassrls in NOLOGIN_ROLES:
            ensure_nologin_role(conn, name, bypassrls)
        for role in roles:
            ensure_login_role(conn, role.value, settings.read_secret(settings.secret_name(role)))
        ensure_login_role(conn, "incident", settings.read_secret("postgres_incident_password"))
        narrow_connect(conn, app_db, tuple(r.value for r in roles))
        narrow_connect(conn, incident_db, ("incident",))


def _config(tree: str, connection: object) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS[tree]))
    cfg.attributes["connection"] = connection
    return cfg


def _engine(pg: settings.Postgres) -> Engine:
    url = URL.create(
        "postgresql+psycopg", username=pg.user, password=pg.password, host=pg.host, port=pg.port, database=pg.dbname
    )
    return create_engine(url)


def upgrade(tree: str, pg: settings.Postgres, target: str) -> None:
    """Upgrade one tree to `target` (`app@head`, `heads`, or a revision id) inside one transaction."""
    engine = _engine(pg)
    with engine.begin() as connection:
        command.upgrade(_config(tree, connection), target)
    engine.dispose()


def downgrade(tree: str, pg: settings.Postgres, target: str) -> None:
    """Downgrade one tree to `target` (a revision id, `<label>@base` or `base`); R006's up/down evidence."""
    engine = _engine(pg)
    with engine.begin() as connection:
        command.downgrade(_config(tree, connection), target)
    engine.dispose()


def migrate_target(profile: Profile) -> str:
    """`heads` applies the labelled `testclock` branch too; every other profile stops at the `app` main line."""
    return "heads" if profile is Profile.TEST else "app@head"


def migrate(profile: Profile | None = None) -> int:
    """Roles first, then both trees; the profile (default `PROFILE`, else dev) decides if the test clock exists."""
    export_environment(load_dotenv(ROOT / ".env"))
    profile = profile or settings.profile()
    superuser = settings.superuser_postgres()
    incident_db = settings.env("OPS_INCIDENT_PG_DB", "incident")
    incident_as_superuser = settings.Postgres(
        superuser.host, superuser.port, superuser.user, incident_db, superuser.password
    )
    ensure_roles(superuser, superuser.dbname, incident_db, profile)
    target = migrate_target(profile)
    upgrade("app", superuser, target)
    upgrade("incident", incident_as_superuser, "head")
    print(f"MIGRATE: app at {target}, incident at head (profile {profile.value})")
    return 0


def clock_guard(superuser: settings.Postgres, profile: Profile) -> None:
    """Refuse to run the dev or demo skeleton against a database that carries app.test_clock (SA:529)."""
    if profile is Profile.TEST:
        return
    with psycopg.connect(superuser.conninfo(), autocommit=True) as conn:
        row = conn.execute("SELECT to_regclass('app.test_clock') IS NOT NULL").fetchone()
    if row is not None and row[0]:
        raise RuntimeError(f"app.test_clock exists in {superuser.dbname}; the {profile.value} profile refuses to start")


def orphan_keys(keys: list[tuple[UUID, str]], grants: set[tuple[UUID, str]]) -> list[tuple[UUID, str]]:
    """Destination keys whose (action_id, payload_sha256) no execution grant carries (T10 review note 3)."""
    return [key for key in keys if key not in grants]


def keys() -> int:
    """The detective check: every incident.action_key must match a grant hash; exit 1 and list the ones that do not."""
    export_environment(load_dotenv(ROOT / ".env"))
    superuser = settings.superuser_postgres()
    incident_db = settings.env("OPS_INCIDENT_PG_DB", "incident")
    destination = settings.Postgres(superuser.host, superuser.port, superuser.user, incident_db, superuser.password)
    with psycopg.connect(superuser.conninfo(), autocommit=True) as app_conn:
        grants = {
            (row[0], row[1]) for row in app_conn.execute("SELECT action_id, payload_sha256 FROM app.execution_grant")
        }
    with psycopg.connect(destination.conninfo(), autocommit=True) as dest_conn:
        found = [
            (row[0], row[1]) for row in dest_conn.execute("SELECT action_id, payload_sha256 FROM incident.action_key")
        ]
    orphans = orphan_keys(found, grants)
    print(f"KEYS: {len(found)} destination keys, {len(grants)} grants, {len(orphans)} without a matching grant hash")
    for action_id, digest in orphans:
        print(f"  orphan action_id={action_id} payload_sha256={digest}")
    return 1 if orphans else 0


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
    Process("sweeper", "ops_sweeper", 8071),
)
LOGS = ROOT / "runtime" / "skeleton"  # git-ignored (runtime/)


def process_environment() -> dict[str, str]:
    """The environment every child inherits: .env-derived OPS_* variables plus the port defaults."""
    export_environment(load_dotenv(ROOT / ".env"))
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PROFILE", Profile.DEV.value)
    env.setdefault("OPS_PG_DB", "ops")
    env.setdefault("OPS_INCIDENT_PG_DB", "incident")
    env.setdefault("MODEL_MODE", "fake")
    env.setdefault("OPS_API_PORT", "8000")
    env.setdefault("OPS_WORKER_HEALTH_PORT", "8070")
    env.setdefault("OPS_SWEEPER_HEALTH_PORT", "8071")
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
    """The six host processes as children of this one; logs under runtime/skeleton/ (never committed)."""

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
    """Start the six processes and record their pids for `down`; they outlive this script. Refuses a second set."""
    export_environment(load_dotenv(ROOT / ".env"))
    try:
        clock_guard(settings.superuser_postgres(), settings.profile())
    except (RuntimeError, settings.SettingsError) as error:
        print(f"UP: refused — {error}")
        return 2
    except psycopg.OperationalError:
        print("UP: refused — database not reachable")  # no connection details in the message
        return 2
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
    commands = {"migrate": migrate, "up": up, "down": down, "status": status, "keys": keys}
    if len(argv) == 2 and argv[1] in commands:
        return commands[argv[1]]()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
