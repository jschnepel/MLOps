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
    global_queue_limit: int = 100  # BS:550: "100 total" across tenants, checked after the quota (Plan H ruling 13)


def _bounded(name: str, default: int, low: int, high: int) -> int:
    """An integer variable inside [low, high]; the message names the bounds, never the value."""
    value = env_int(name, default)
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}")
    return value


def admission() -> AdmissionSettings:
    """`OPS_MAX_BODY_BYTES`, `OPS_IDEMPOTENCY_TTL_SECONDS`, `OPS_TENANT_QUEUE_QUOTA` (Plan G ruling 27) and
    `OPS_GLOBAL_QUEUE_LIMIT` (Plan H ruling 13), each bounded."""
    return AdmissionSettings(
        max_body_bytes=_bounded("OPS_MAX_BODY_BYTES", 65536, 1024, 1048576),
        idempotency_ttl_seconds=_bounded("OPS_IDEMPOTENCY_TTL_SECONDS", 86400, 60, 604800),
        tenant_queue_quota=_bounded("OPS_TENANT_QUEUE_QUOTA", 100, 1, 10000),
        global_queue_limit=_bounded("OPS_GLOBAL_QUEUE_LIMIT", 100, 1, 100000),
    )


@dataclass(frozen=True)
class LeaseSettings:
    """The run lease and its heartbeat (BS:557, SA:193-195) and the two renewal gates of T13 review note 4: the event
    loop's stall limit and the compute budget (BS:555), as validated configuration (BS:542, Plan H ruling 20)."""

    lease_seconds: int = 30  # BS:557
    heartbeat_seconds: int = 10  # BS:557
    loop_stall_seconds: int = 28  # above DoD 3's 25 s blocked loop, below a lease plus a heartbeat
    compute_budget_seconds: int = 90  # BS:555: active compute per run


# The worker stops starting effects 5 s before its lease ends (SA:195) and its heartbeat thread looks once a second.
RENEWAL_MARGIN_SECONDS = 6


def check_leases(chosen: LeaseSettings) -> None:
    """Refuse a combination that would lose healthy leases or keep dead ones (Plan H ruling 20, review round 1 I5).

    Two heartbeats plus RENEWAL_MARGIN_SECONDS must fit in one lease: the local deadline is the last renewal's start
    plus the lease minus 5 s, so with less room one failed or slow renewal passes it and a healthy job is abandoned.
    A loop silent for a whole lease plus a heartbeat is treated as dead, so the stall gate stays below that; a budget
    shorter than one lease would end every job before its first renewal.

    Raises:
        SettingsError: naming the rule, never a value.
    """
    if chosen.heartbeat_seconds * 2 + RENEWAL_MARGIN_SECONDS >= chosen.lease_seconds:
        raise SettingsError("OPS_HEARTBEAT_SECONDS must be less than half of (OPS_LEASE_SECONDS - 6)")
    if chosen.loop_stall_seconds >= chosen.lease_seconds + chosen.heartbeat_seconds:
        raise SettingsError("OPS_LOOP_STALL_SECONDS must be less than OPS_LEASE_SECONDS plus OPS_HEARTBEAT_SECONDS")
    if chosen.compute_budget_seconds < chosen.lease_seconds:
        raise SettingsError("OPS_COMPUTE_BUDGET_SECONDS must be at least OPS_LEASE_SECONDS")


def leases() -> LeaseSettings:
    """`OPS_LEASE_SECONDS`, `OPS_HEARTBEAT_SECONDS`, `OPS_LOOP_STALL_SECONDS` and `OPS_COMPUTE_BUDGET_SECONDS`, each
    bounded, then checked together (`check_leases`); the worker refuses to start on a refusal."""
    chosen = LeaseSettings(
        lease_seconds=_bounded("OPS_LEASE_SECONDS", 30, 10, 900),
        heartbeat_seconds=_bounded("OPS_HEARTBEAT_SECONDS", 10, 1, 300),
        loop_stall_seconds=_bounded("OPS_LOOP_STALL_SECONDS", 28, 2, 900),
        compute_budget_seconds=_bounded("OPS_COMPUTE_BUDGET_SECONDS", 90, 10, 3600),
    )
    check_leases(chosen)
    return chosen


@dataclass(frozen=True)
class OutboxSettings:
    """The notification outbox's delivery loop (BS:524, Plan I rulings 15 and 16) as validated configuration (BS:542):
    how long a claimed row is leased, how many rows a tenant's claim takes per tick, the capped exponential backoff
    between failed attempts and the attempt whose failure dead-letters the row."""

    lease_seconds: int = 30  # a delivery still unanswered after this is claimed again (at least once, BS:76)
    batch: int = 10
    backoff_base_seconds: int = 2  # the first retry waits about this long, then twice as long each time
    backoff_cap_seconds: int = 300  # BS:562: the backoff is capped
    max_attempts: int = 5  # the fifth failure is final: the row is dead-lettered


def check_outbox(chosen: OutboxSettings) -> None:
    """Refuse a backoff whose cap sits below its base (every retry would wait the cap, and the base would mean nothing).

    Raises:
        SettingsError: naming the rule, never a value.
    """
    if chosen.backoff_cap_seconds < chosen.backoff_base_seconds:
        raise SettingsError("OPS_OUTBOX_BACKOFF_CAP_SECONDS must be at least OPS_OUTBOX_BACKOFF_BASE_SECONDS")


def outbox() -> OutboxSettings:
    """`OPS_OUTBOX_LEASE_SECONDS`, `OPS_OUTBOX_BATCH`, `OPS_OUTBOX_BACKOFF_BASE_SECONDS`,
    `OPS_OUTBOX_BACKOFF_CAP_SECONDS` and `OPS_OUTBOX_MAX_ATTEMPTS`, each bounded, then checked together."""
    chosen = OutboxSettings(
        lease_seconds=_bounded("OPS_OUTBOX_LEASE_SECONDS", 30, 5, 3600),
        batch=_bounded("OPS_OUTBOX_BATCH", 10, 1, 1000),
        backoff_base_seconds=_bounded("OPS_OUTBOX_BACKOFF_BASE_SECONDS", 2, 1, 3600),
        backoff_cap_seconds=_bounded("OPS_OUTBOX_BACKOFF_CAP_SECONDS", 300, 2, 86400),
        max_attempts=_bounded("OPS_OUTBOX_MAX_ATTEMPTS", 5, 1, 100),
    )
    check_outbox(chosen)
    return chosen


@dataclass(frozen=True)
class WakeupSettings:
    """The wake-up sweep (BS:340, Plan I rulings 7, 8 and 20): how long a consumed wake-up may sit without its run
    moving before it is re-armed, how many claims a job may have had before the sweep stops re-arming it, and how long
    a finished maintenance row is kept."""

    grace_seconds: int = 60  # a job done this long ago whose run still waits in the job's state was lost
    max_attempts: int = 10  # a job claimed this often is not re-armed again; the sweep logs it instead
    maintenance_retention_hours: int = 24  # finished sweeper rows older than this are deleted (run jobs never are)


def wakeups() -> WakeupSettings:
    """`OPS_WAKEUP_GRACE_SECONDS`, `OPS_WAKEUP_MAX_ATTEMPTS` and `OPS_MAINTENANCE_RETENTION_HOURS`, each bounded."""
    return WakeupSettings(
        grace_seconds=_bounded("OPS_WAKEUP_GRACE_SECONDS", 60, 10, 86400),
        max_attempts=_bounded("OPS_WAKEUP_MAX_ATTEMPTS", 10, 1, 1000),
        maintenance_retention_hours=_bounded("OPS_MAINTENANCE_RETENTION_HOURS", 24, 1, 8760),
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
