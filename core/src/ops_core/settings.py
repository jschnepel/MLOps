"""Process configuration shared by every skeleton service: plain environment variables plus secret files.

Secrets never travel in environment variables (BUILD_SPEC §22; Plan B's compose test refuses a PASSWORD or SECRET key
that is not a `_FILE` path), so a service reads each secret once from `OPS_SECRETS_DIR/<name>` at start and keeps it
in memory. Everything else — hosts, ports, URLs, the model mode — is an `OPS_*` variable with a dev default that matches
the `.env` written by scripts/bootstrap_dev.py, so a process started by hand against the dev stack needs only
`OPS_SECRETS_DIR`. The MCP resource URLs are audience identifiers (what the realm's mappers put in `aud`), distinct
from the loopback listen URLs the host processes answer on; T30 makes them coincide when the servers are containerised.
Every service connects to Postgres as its own AM-20.1 role, and `PROFILE` selects the dev, test or demo profile.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

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
    """Where Keycloak is: `base_url` is the public host the browser and the token `iss` use; `server_url` is what this
    process dials. On the dev machine `localhost` resolves to `::1` first and the port is published on IPv4 only, so
    every new connection through `localhost` costs about 2 s (spike §3), which alone would exhaust the admin check's
    2 s budget; `127.0.0.1` answers in milliseconds and `KC_HOSTNAME` keeps `iss` the same."""

    base_url: str
    issuer: str
    server_url: str

    @property
    def jwks_url(self) -> str:
        """The realm's signing keys (server side)."""
        return f"{self.server_url}/realms/{REALM}/protocol/openid-connect/certs"

    @property
    def token_url(self) -> str:
        """The token endpoint (server side)."""
        return f"{self.server_url}/realms/{REALM}/protocol/openid-connect/token"

    @property
    def discovery_url(self) -> str:
        """The OIDC metadata document (server side)."""
        return f"{self.server_url}/realms/{REALM}/.well-known/openid-configuration"

    @property
    def end_session_url(self) -> str:
        """The RP-initiated logout endpoint (server side)."""
        return f"{self.server_url}/realms/{REALM}/protocol/openid-connect/logout"

    @property
    def admin_users_url(self) -> str:
        """The admin API's users collection (server side; `view-users` reads it)."""
        return f"{self.server_url}/admin/realms/{REALM}/users"

    def server_side(self, url: str) -> str:
        """A discovered endpoint rewritten for this process: the public base swapped for `server_url`."""
        return self.server_url + url[len(self.base_url) :] if url.startswith(self.base_url + "/") else url


def _loopback(base: str) -> str:
    """`base` with a host of exactly `localhost` swapped for `127.0.0.1`, scheme and port kept (not `localhost.x.y`)."""
    parts = urlsplit(base)
    if parts.hostname != "localhost":
        return base
    return parts._replace(netloc=parts.netloc.replace("localhost", "127.0.0.1", 1)).geturl()


def keycloak() -> Keycloak:
    """Base URL for the host (`KC_HOSTNAME` makes `iss` the same for containers, SA:556) and the dial address."""
    base = env("OPS_KC_BASE_URL", "http://localhost:18080").rstrip("/")
    server = env("OPS_KC_SERVER_URL", _loopback(base)).rstrip("/")
    return Keycloak(base_url=base, issuer=env("OPS_KC_ISSUER", f"{base}/realms/{REALM}"), server_url=server)


@dataclass(frozen=True)
class SessionSettings:
    """Browser-session settings (BUILD_SPEC §9): the one origin the API trusts and the lifetimes."""

    public_base_url: str
    idle_seconds: int
    absolute_seconds: int
    login_seconds: int

    @property
    def origin(self) -> str:
        """The one `Origin` a browser mutation may carry."""
        return self.public_base_url

    @property
    def redirect_uri(self) -> str:
        """The registered callback (exact match at Keycloak)."""
        return f"{self.public_base_url}/auth/callback"

    @property
    def cookie_secure(self) -> bool:
        """Secure cookies iff the public base is https (BUILD_SPEC §9)."""
        return self.public_base_url.startswith("https://")


def _origin(raw: str) -> str:
    """Normalise `OPS_PUBLIC_BASE_URL` to an origin: lowercase, default port dropped, nothing but scheme+host."""
    refusal = SettingsError("OPS_PUBLIC_BASE_URL must be an origin: scheme and host only")
    if "?" in raw or "#" in raw:  # urlsplit hides an empty query or fragment, but the Origin comparison would not
        raise refusal
    parts = urlsplit(raw.rstrip("/"))
    try:
        port = parts.port  # an out-of-range or non-numeric port raises here
    except ValueError as exc:
        raise refusal from exc
    host = parts.hostname
    if parts.scheme.lower() not in ("http", "https") or not host or parts.path or "@" in parts.netloc:
        raise refusal
    scheme = parts.scheme.lower()
    if scheme == "http" and host not in ("localhost", "127.0.0.1"):
        raise SettingsError("OPS_PUBLIC_BASE_URL may use http for localhost only; other hosts need https")
    shown = f"[{host}]" if ":" in host else host
    if port is not None and port != (443 if scheme == "https" else 80):
        shown += f":{port}"
    return f"{scheme}://{shown}"


def sessions() -> SessionSettings:
    """`OPS_PUBLIC_BASE_URL` must be a bare origin; `http` is for localhost only (BUILD_SPEC §9's exception)."""
    origin = _origin(env("OPS_PUBLIC_BASE_URL", "http://localhost:8000"))
    result = SessionSettings(
        public_base_url=origin,
        idle_seconds=env_int("OPS_SESSION_IDLE_SECONDS", 1800),
        absolute_seconds=env_int("OPS_SESSION_ABSOLUTE_SECONDS", 28800),
        login_seconds=env_int("OPS_SESSION_LOGIN_SECONDS", 600),
    )
    if result.idle_seconds <= 0 or result.login_seconds <= 0 or result.absolute_seconds < result.idle_seconds:
        raise SettingsError("session lifetimes must be positive and the absolute lifetime at least the idle one")
    return result


def admin_check_timeout() -> float:
    """The whole-call budget of the Keycloak admin-API enabled check (SA:544: 2 s)."""
    raw = os.environ.get("OPS_ADMIN_CHECK_TIMEOUT_SECONDS") or "2.0"
    try:
        value = float(raw)
    except ValueError as exc:
        raise SettingsError("OPS_ADMIN_CHECK_TIMEOUT_SECONDS must be a number of seconds") from exc
    if not math.isfinite(value) or value <= 0:
        raise SettingsError("OPS_ADMIN_CHECK_TIMEOUT_SECONDS must be a positive finite number")
    return value


@dataclass(frozen=True)
class AdmissionSettings:
    """The admission limits (BUILD_SPEC §17: starting defaults in validated configuration, BS:542).

    The key bounds are constants, not environment: they are part of the API contract a client codes against
    (Plan G ruling 1), while the body limit, the replay window and the tenant quota are deployment choices.
    """

    max_body_bytes: int = 65536  # BS:546: 64 KiB inbound body
    idempotency_ttl_seconds: int = 86400  # SA:297: the 24 h request-dedup replay window
    idempotency_key_min: int = 8
    idempotency_key_max: int = 128
    tenant_queue_quota: int = 100  # BS:550: queued work, as a per-tenant bound (ruling 18)


def _bounded(name: str, default: int, low: int, high: int) -> int:
    """An integer variable inside [low, high]; the message names the bounds, never the value."""
    value = env_int(name, default)
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}")
    return value


def admission() -> AdmissionSettings:
    """`OPS_MAX_BODY_BYTES`, `OPS_IDEMPOTENCY_TTL_SECONDS` and `OPS_TENANT_QUEUE_QUOTA`, each bounded (ruling 27)."""
    return AdmissionSettings(
        max_body_bytes=_bounded("OPS_MAX_BODY_BYTES", 65536, 1024, 1048576),
        idempotency_ttl_seconds=_bounded("OPS_IDEMPOTENCY_TTL_SECONDS", 86400, 60, 604800),
        tenant_queue_quota=_bounded("OPS_TENANT_QUEUE_QUOTA", 100, 1, 10000),
    )


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
