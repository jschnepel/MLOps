"""Process configuration shared by every skeleton service: plain environment variables plus secret files.

Secrets never travel in environment variables (BUILD_SPEC §22; Plan B's compose test refuses a PASSWORD or SECRET key
that is not a `_FILE` path), so a service reads each secret once from `OPS_SECRETS_DIR/<name>` at start and keeps it in
memory. Everything else — hosts, ports, URLs, the model mode — is an `OPS_*` variable with a dev default that matches
the `.env` written by scripts/bootstrap_dev.py, so a process started by hand against the dev stack needs only
`OPS_SECRETS_DIR`. The MCP resource URLs are audience identifiers (what the realm's mappers put in `aud`), distinct
from the loopback listen URLs the host processes answer on; T30 makes them coincide when the servers are containerised.
Every service connects to Postgres as its own AM-20.1 role, and `PROFILE` selects the dev, test or demo profile.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from psycopg.conninfo import make_conninfo

REALM = "ops-dev"


class SettingsError(ValueError):
    """A required variable or secret file is missing or malformed. Messages name the variable or file, never a value."""


def env(name: str, default: str | None = None) -> str:
    """Return a non-empty environment variable, or the default; an empty string counts as unset."""
    value = os.environ.get(name) or default
    if not value:
        raise SettingsError(f"{name} is not set")
    return value


def env_int(name: str, default: int) -> int:
    """Return an integer environment variable or the default."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer") from exc


def secrets_dir() -> Path:
    return Path(env("OPS_SECRETS_DIR"))


def read_secret(name: str, directory: Path | None = None) -> str:
    """Read one secret file; the trailing newline an editor may add is not part of the secret."""
    path = (directory or secrets_dir()) / name
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        # The path is left out of the message on purpose: messages reach logs and HTTP bodies.
        raise SettingsError(f"secret file {name} is missing or unreadable") from exc
    if not value:
        raise SettingsError(f"secret file {name} is empty")
    return value


@dataclass(frozen=True)
class Postgres:
    host: str
    port: int
    user: str
    dbname: str
    password: str = field(repr=False)  # dataclasses would otherwise print it in every traceback

    def conninfo(self) -> str:
        # The session time zone is pinned so timestamptz values round-trip as UTC whatever the server's default.
        return make_conninfo(
            host=self.host,
            port=self.port,
            user=self.user,
            dbname=self.dbname,
            password=self.password,
            options="-c timezone=UTC",
        )


class Profile(StrEnum):
    """The three v1 profiles (SA:40); R098's "default" profile means dev and demo (SA:49)."""

    DEV = "dev"
    TEST = "test"
    DEMO = "demo"


def profile() -> Profile:
    """The process profile from `PROFILE`; dev when unset; anything else is a refusal to start."""
    raw = env("PROFILE", Profile.DEV.value)
    try:
        return Profile(raw)
    except ValueError as exc:
        raise SettingsError("PROFILE must be one of dev, test, demo") from exc


class Role(StrEnum):
    """The login roles of AM-20.1; each process connects as exactly one of them (never as the owner)."""

    API = "api"
    WORKER = "worker"
    SWEEPER = "sweeper"
    MCP_READ = "mcp_read"
    MCP_EXEC = "mcp_exec"
    OPERATOR = "operator"
    TEST_HARNESS = "test_harness"


def secret_name(role: Role) -> str:
    """The secret file that holds a role's password; scripts/bootstrap_dev.py generates one per role."""
    return f"postgres_{role.value}_password"


def _pg_host_port() -> tuple[str, int]:
    return env("OPS_PG_HOST", "127.0.0.1"), env_int("OPS_PG_PORT", 15432)


def _app_db() -> str:
    return env("OPS_PG_DB", "ops")


def superuser_postgres() -> Postgres:
    """The Compose superuser: migrations, role bootstrap and test fixtures only, never a service (SA:395, SA:521)."""
    host, port = _pg_host_port()
    return Postgres(host, port, env("OPS_PG_SUPERUSER", "ops"), _app_db(), read_secret("postgres_password"))


def app_postgres(role: Role) -> Postgres:
    """The application database as one runtime role; the role is required so no caller inherits the owner."""
    host, port = _pg_host_port()
    return Postgres(host, port, role.value, _app_db(), read_secret(secret_name(role)))


def incident_postgres() -> Postgres:
    """The destination's own database and role (BUILD_SPEC §14: separate credentials)."""
    host, port = _pg_host_port()
    return Postgres(
        host,
        port,
        env("OPS_INCIDENT_PG_USER", "incident"),
        env("OPS_INCIDENT_PG_DB", "incident"),
        read_secret("postgres_incident_password"),
    )


@dataclass(frozen=True)
class Keycloak:
    base_url: str
    issuer: str

    @property
    def jwks_url(self) -> str:
        return f"{self.base_url}/realms/{REALM}/protocol/openid-connect/certs"

    @property
    def token_url(self) -> str:
        return f"{self.base_url}/realms/{REALM}/protocol/openid-connect/token"


def keycloak() -> Keycloak:
    """Base URL for the host (`KC_HOSTNAME` makes `iss` the same for containers, SA:556)."""
    base = env("OPS_KC_BASE_URL", "http://localhost:18080").rstrip("/")
    return Keycloak(base_url=base, issuer=env("OPS_KC_ISSUER", f"{base}/realms/{REALM}"))


@dataclass(frozen=True)
class Urls:
    mcp_read_resource: str
    mcp_write_resource: str
    mcp_read: str
    mcp_write: str
    incident_sim: str


def urls() -> Urls:
    return Urls(
        mcp_read_resource=env("MCP_READ_RESOURCE_URL", "http://mcp-read:8081/mcp"),
        mcp_write_resource=env("MCP_WRITE_RESOURCE_URL", "http://mcp-write:8082/mcp"),
        mcp_read=env("OPS_MCP_READ_URL", "http://127.0.0.1:8081/mcp"),
        mcp_write=env("OPS_MCP_WRITE_URL", "http://127.0.0.1:8082/mcp"),
        incident_sim=env("OPS_INCIDENT_SIM_URL", "http://127.0.0.1:8090"),
    )


def fixtures_dir() -> Path:
    return Path(env("OPS_FIXTURES_DIR", "data/handoff-fixtures"))
