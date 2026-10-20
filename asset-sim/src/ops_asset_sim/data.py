"""asset-sim's data (T16; Plan M ruling 4): corpus-1's assets and alerts, read once at start, and the fixed rules
that derive what the tool contracts need and the files do not hold.

`data/corpus/assets.json` (authored, under the corpus-1 lock) names each asset's tenant by slug and each alert by
`kind`, `severity`, `raised_at` and `revision`; `data/corpus/meta.json` (generated) gives the tenant UUIDs and the
alerts' uuid5 IDs. Neither file is changed here: corpus-1 stays the frozen version T41 labels against. The rules,
which `asset-sim/README.md` and `docs/runbooks/asset-sim.md` state in prose:

- an alert's contract fields: `alert_id` is meta's UUID, `occurred_at` is `raised_at`, `code` is `kind`, `message`
  is `MESSAGE` filled from severity, kind and the asset's name, `revision` as authored;
- the status of an asset as of an instant T: `warning` when one of its alerts of severity `warning` or `critical`
  was raised in `[T - 24 h, T]`, else `normal`; `revision` the highest revision among its alerts raised at or before
  T, or 1; `observed_at` T; `data_source` `synthetic`. `unavailable` comes only from the test-profile fault hook.
- T is always the `as_of` instant mcp-read forwards (the database's `app.current_time()`): asset-sim has no clock of
  its own, so its answers are deterministic under the injected clock (BS:405, SA:78).
- alerts of an interval: `start_at <= occurred_at < end_at` and `occurred_at <= as_of` (no alert from the future),
  ordered by `(occurred_at, alert_id)`, paged by an opaque cursor bound to the request (ruling 10).

The module is standard library plus `ops_core.corpus`, so the rules are tested without a server.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from ops_core import corpus

# The repository's corpus directory, read in place (packaging the data for a container is T30's).
DATA: Final = Path(__file__).resolve().parents[3] / "data" / "corpus"
ASSET_ID: Final = re.compile(r"[A-Z][A-Z0-9_-]{0,31}")  # schemas/tools/get_asset_status.input.schema.json
KIND: Final = re.compile(r"[a-z][a-z0-9_]{0,79}")  # the contract's `code`: 1-80 characters
SEVERITIES: Final = frozenset({"info", "warning", "critical"})
WARNING_SEVERITIES: Final = frozenset({"warning", "critical"})
WARNING_WINDOW: Final = timedelta(hours=24)
MESSAGE: Final = "Synthetic {severity} alert: {kind} on {name}."
# RFC 3339 as the tool input schemas spell it (`Z` or `+00:00`); fromisoformat alone also takes basic format, a space
# separator, week dates and hour-only forms, none of which a contract instant may be.
INSTANT: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|\+00:00)")
CURSOR_ALPHABET: Final = re.compile(r"[A-Za-z0-9_-]+")
EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
CURSOR_VERSION: Final = 1
CURSOR_BYTES: Final = 1 + 8 + 16 + 32  # version, occurred_at in microseconds, alert UUID, request binding


class DataError(ValueError):
    """The data files cannot be served; the message names the rule, never a value from the files."""


class CursorRefused(ValueError):
    """A cursor that is malformed or was issued for another request (another tenant, asset or interval)."""


@dataclass(frozen=True)
class Asset:
    """One asset: its id, its tenant's UUID, its type and its display name."""

    asset_id: str
    tenant_id: UUID
    asset_type: str
    name: str


@dataclass(frozen=True)
class Alert:
    """One alert in the contract's terms, with the severity the status rule reads."""

    alert_id: UUID
    asset_id: str
    occurred_at: datetime
    code: str
    message: str
    revision: int
    severity: str

    @property
    def key(self) -> tuple[datetime, str]:
        """The order of an asset's alerts and the position a cursor names: (occurred_at, alert_id)."""
        return (self.occurred_at, str(self.alert_id))


@dataclass(frozen=True)
class Catalog:
    """Every asset by (tenant UUID, asset id), and each asset's alerts in `Alert.key` order."""

    assets: dict[tuple[UUID, str], Asset]
    alerts: dict[str, tuple[Alert, ...]]

    def asset(self, tenant_id: UUID, asset_id: str) -> Asset | None:
        """The tenant's asset, or None for an unknown one and another tenant's alike (no existence oracle)."""
        return self.assets.get((tenant_id, asset_id))


def instant(text: str) -> datetime:
    """An RFC 3339 UTC instant (`Z` or `+00:00`, erratum 6) as an aware datetime.

    Raises:
        ValueError: not an instant, or not in UTC.
    """
    if not INSTANT.fullmatch(text):
        raise ValueError("an instant must be RFC 3339 UTC")
    value = datetime.fromisoformat(text)
    if value.utcoffset() != timedelta(0):
        raise ValueError("an instant must be UTC")
    return value.astimezone(UTC)


def rfc3339(value: datetime) -> str:
    """The `Z` spelling the contracts use, with microseconds only when the instant has them."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def load(root: Path = DATA) -> Catalog:
    """Read `assets.json` (through `ops_core.corpus.load_assets`) and `meta.json` once, and derive the catalog.

    Raises:
        corpus.CorpusError: `assets.json` is malformed.
        DataError: `meta.json` lacks a tenant or an alert, or an alert has an unknown severity, a malformed kind or a
            `raised_at` that is not a UTC instant.
    """
    data = corpus.load_assets(root)
    try:
        meta = json.loads((root / corpus.META).read_text(encoding="utf-8"))
        tenants = {slug: UUID(value) for slug, value in meta["tenants"].items()}
        alert_ids = {entry["id"]: UUID(entry["alert_id"]) for entry in meta["alerts"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise DataError("meta.json cannot be read as tenants and alert ids") from exc
    assets: dict[tuple[UUID, str], Asset] = {}
    for entry in data["assets"]:
        if entry["tenant"] not in tenants:
            raise DataError("an asset's tenant has no UUID in meta.json")
        asset = Asset(entry["asset_id"], tenants[entry["tenant"]], entry["asset_type"], entry["name"])
        assets[(asset.tenant_id, asset.asset_id)] = asset
    # Names and alerts are keyed by asset_id alone. That is safe only because `corpus.load_assets` requires asset ids
    # to be unique across all tenants; if a corpus ever allowed one id in two tenants, both would need the tenant in
    # their key, or one tenant's alerts would reach the other's status after the tenant filter had already passed.
    names = {asset.asset_id: asset.name for asset in assets.values()}
    by_asset: dict[str, list[Alert]] = {}
    for entry in data["alerts"]:
        severity, kind, raised = entry.get("severity"), entry.get("kind"), entry.get("raised_at")
        if severity not in SEVERITIES or not isinstance(kind, str) or not KIND.fullmatch(kind):
            raise DataError("an alert has an unknown severity or a malformed kind")
        if entry["id"] not in alert_ids or not isinstance(raised, str):
            raise DataError("an alert has no UUID in meta.json or no raised_at")
        try:
            occurred_at = instant(raised)
        except ValueError as exc:
            raise DataError("an alert's raised_at is not a UTC instant") from exc
        text = MESSAGE.format(severity=severity, kind=kind.replace("_", " "), name=names[entry["asset_id"]])
        alert = Alert(alert_ids[entry["id"]], entry["asset_id"], occurred_at, kind, text, entry["revision"], severity)
        by_asset.setdefault(alert.asset_id, []).append(alert)
    alerts = {asset_id: tuple(sorted(found, key=lambda a: a.key)) for asset_id, found in by_asset.items()}
    return Catalog(assets, alerts)


def status(catalog: Catalog, asset: Asset, at: datetime) -> dict[str, Any]:
    """The asset's status as of `at` by the documented rule; exactly the `get_asset_status` result's `data`."""
    seen = [alert for alert in catalog.alerts.get(asset.asset_id, ()) if alert.occurred_at <= at]
    warning = any(a.severity in WARNING_SEVERITIES and a.occurred_at >= at - WARNING_WINDOW for a in seen)
    return {
        "asset_id": asset.asset_id,
        "state": "warning" if warning else "normal",
        "revision": max((alert.revision for alert in seen), default=1),
        "observed_at": rfc3339(at),
        "data_source": "synthetic",
    }


def binding(tenant_id: UUID, asset_id: str, start_at: datetime, end_at: datetime) -> bytes:
    """The SHA-256 a cursor carries: it ties the cursor to one tenant, asset and interval (ruling 10). No secret is
    needed: a cursor only selects a position inside a set that the request's own filters already decided."""
    text = "\n".join((str(tenant_id), asset_id, rfc3339(start_at), rfc3339(end_at)))
    return hashlib.sha256(text.encode("utf-8")).digest()


def encode_cursor(alert: Alert, bound: bytes) -> str:
    """An opaque base64url token naming the last alert returned, under the request's binding (76 characters)."""
    micros = (alert.occurred_at - EPOCH) // timedelta(microseconds=1)
    raw = struct.pack(">Bq", CURSOR_VERSION, micros) + alert.alert_id.bytes + bound
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(text: str, bound: bytes) -> tuple[datetime, str]:
    """The (occurred_at, alert_id) position a cursor names.

    Raises:
        CursorRefused: not a cursor of this format, or bound to another request.
    """
    try:
        if not CURSOR_ALPHABET.fullmatch(text):  # b64decode would silently skip anything outside the alphabet
            raise ValueError("outside the base64url alphabet")
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != text:  # one spelling per cursor
            raise ValueError("not canonical")
    except (ValueError, binascii.Error) as exc:
        raise CursorRefused("malformed cursor") from exc
    if len(raw) != CURSOR_BYTES or raw[0] != CURSOR_VERSION or not hmac.compare_digest(raw[25:], bound):
        raise CursorRefused("cursor does not belong to this request")
    (micros,) = struct.unpack(">q", raw[1:9])
    try:
        # The binding is an unkeyed hash of values the caller knows, so a forged cursor can pass it with any micros.
        when = EPOCH + timedelta(microseconds=micros)
    except (OverflowError, ValueError) as exc:
        raise CursorRefused("cursor names an instant out of range") from exc
    return (when, str(UUID(bytes=raw[9:25])))


def alerts_page(
    catalog: Catalog,
    asset: Asset,
    *,
    start_at: datetime,
    end_at: datetime,
    as_of: datetime,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    """One page of the asset's alerts in `[start_at, end_at)` raised at or before `as_of`; exactly the
    `get_recent_alerts` result's `data`. `next_cursor` is set exactly when alerts remain after this page.

    Raises:
        CursorRefused: the cursor is malformed or another request's.
        ValueError: `limit` is below 1 (the route refuses it first; this keeps the data rule total).
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    bound = binding(asset.tenant_id, asset.asset_id, start_at, end_at)
    window = [
        alert
        for alert in catalog.alerts.get(asset.asset_id, ())
        if start_at <= alert.occurred_at < end_at and alert.occurred_at <= as_of
    ]
    if cursor is not None:
        after = decode_cursor(cursor, bound)
        window = [alert for alert in window if alert.key > after]
    page = window[:limit]
    return {
        "asset_id": asset.asset_id,
        "start_at": rfc3339(start_at),
        "end_at": rfc3339(end_at),
        "alerts": [
            {
                "alert_id": str(alert.alert_id),
                "asset_id": alert.asset_id,
                "occurred_at": rfc3339(alert.occurred_at),
                "code": alert.code,
                "message": alert.message,
                "revision": alert.revision,
            }
            for alert in page
        ],
        "next_cursor": encode_cursor(page[-1], bound) if len(window) > limit else None,
    }
