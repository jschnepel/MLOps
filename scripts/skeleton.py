"""Walking-skeleton operations (T08): `migrate` both databases to head; Task 9 adds `up`, `down`, `status`.

Reads `.env` (written by scripts/bootstrap_dev.py) for ports and the secrets directory, exports the `OPS_*` variables
every service reads (ops_core.settings), and runs the two Alembic trees programmatically with a shared connection
(Alembic cookbook: "Sharing a Connection across one or more programmatic migration commands"); the engine is built
from a `URL` object, so the password is never rendered into a string. The `incident` role is created or re-keyed
from its secret file on every run; role credentials are a bootstrap concern, schema is the migration's.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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


def main(argv: list[str]) -> int:
    if argv[1:] == ["migrate"]:
        return migrate()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
