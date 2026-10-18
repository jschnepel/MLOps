"""asset-sim's data rules without a server (Plan M ruling 4, 9 and 10), on the committed corpus-1 files.

Catches: an alert whose id is not meta.json's uuid5, whose `code`, `message` or `occurred_at` is not the documented
derivation, or that is served out of `(occurred_at, alert_id)` order; a status rule that differs from the documented
one at the instants the plan states (the baseline clock 2026-10-16T12:00Z, and inside and at the edge of the 24-hour
window); an `info` alert that warns; an interval that is not half-open or an alert from after `as_of`; a page whose
`next_cursor` is set when nothing remains, or missing when something does; a cursor replayed for another tenant,
asset or interval, or a tampered one, accepted; data that does not validate against the tool-result contract; and a
malformed alert file served instead of refused at start.
"""

import base64
import json
import shutil
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ops_asset_sim import data

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
BETA = UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
SEAL_1 = "6699502e-a981-5959-9f24-6df6bd3d3ac5"  # meta.json: uuid5 of alert/A17-seal-001
SEAL_2 = "c8f91c55-7028-5492-bad4-1e5680179647"  # alert/A17-seal-002
TOOL_RESULT = Draft202012Validator(
    json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
CATALOG = data.load()


def at(text: str) -> datetime:
    return data.instant(text)


def asset(tenant: UUID, asset_id: str) -> data.Asset:
    found = CATALOG.asset(tenant, asset_id)
    assert found is not None, asset_id
    return found


def valid(tool: str, payload: dict[str, Any]) -> None:
    """The data validates as the tool's `ok` result (the envelope around it is fixed)."""
    TOOL_RESULT.validate(
        {
            "tool_name": tool,
            "request_id": "00000000-0000-4000-8000-000000000000",
            "status": "ok",
            "observed_at": "2026-10-16T12:00:00Z",
            "truncated": False,
            "data": payload,
            "error": None,
        }
    )


def test_the_catalog_is_corpus_1s_six_assets_and_seven_alerts() -> None:
    assert sorted((a.tenant_id == ALPHA, a.asset_id, a.asset_type) for a in CATALOG.assets.values()) == [
        (False, "B22", "pump"),
        (False, "B25", "compressor"),
        (False, "B31", "conveyor"),
        (True, "A17", "pump"),
        (True, "A21", "compressor"),
        (True, "A30", "conveyor"),
    ]
    assert sum(len(alerts) for alerts in CATALOG.alerts.values()) == 7
    assert [str(a.alert_id) for a in CATALOG.alerts["A17"]] == [SEAL_1, SEAL_2]  # (occurred_at, alert_id) order
    assert CATALOG.asset(ALPHA, "B22") is None and CATALOG.asset(BETA, "B22") is not None  # the tenant decides


def test_an_alert_carries_the_documented_derivation() -> None:
    first = CATALOG.alerts["A17"][0]
    assert (first.code, first.revision, first.severity) == ("seal_leak", 1, "warning")
    assert first.occurred_at == at("2026-10-05T14:00:00Z")
    assert first.message == "Synthetic warning alert: seal leak on Alpha transfer pump A17."
    assert CATALOG.alerts["A21"][0].message == (
        "Synthetic critical alert: high discharge temperature on Alpha air compressor A21."
    )


@pytest.mark.parametrize(
    ("tenant", "asset_id", "when", "state", "revision"),
    [
        (ALPHA, "A17", "2026-10-16T12:00:00Z", "normal", 2),  # the baseline clock: both seal alerts long past
        (BETA, "B22", "2026-10-16T12:00:00Z", "normal", 1),
        (ALPHA, "A17", "2026-10-06T00:00:00Z", "warning", 1),  # seal-001 (10-05 14:00) inside, seal-002 not yet
        (BETA, "B22", "2026-10-06T00:00:00Z", "warning", 1),  # vibration (10-05 11:20) inside
        (ALPHA, "A17", "2026-10-06T12:00:00Z", "warning", 2),  # both seal alerts inside
        (BETA, "B22", "2026-10-06T12:00:00Z", "normal", 1),  # vibration 40 minutes outside the window
        (ALPHA, "A30", "2026-10-03T10:00:00Z", "normal", 1),  # an info alert never warns
        (ALPHA, "A17", "2026-10-04T00:00:00Z", "normal", 1),  # before any alert: revision 1
    ],
)
def test_status_follows_the_documented_rule(tenant: UUID, asset_id: str, when: str, state: str, revision: int) -> None:
    doc = data.status(CATALOG, asset(tenant, asset_id), at(when))
    assert (doc["state"], doc["revision"], doc["observed_at"], doc["data_source"]) == (
        state,
        revision,
        when,
        "synthetic",
    )
    valid("get_asset_status", doc)


def test_the_warning_window_is_closed_at_both_ends() -> None:
    b22 = asset(BETA, "B22")  # one warning alert, raised 2026-10-05T11:20Z
    raised = at("2026-10-05T11:20:00Z")
    assert data.status(CATALOG, b22, raised - timedelta(seconds=1))["state"] == "normal"  # not raised yet
    assert data.status(CATALOG, b22, raised)["state"] == "warning"  # raised_at <= T
    assert data.status(CATALOG, b22, raised + timedelta(hours=24))["state"] == "warning"  # T - 24 h <= raised_at
    edge = data.status(CATALOG, b22, raised + timedelta(hours=24, seconds=1))
    assert (edge["state"], edge["revision"]) == ("normal", 1)  # out of the window; the revision stays


def page(target: data.Asset, start: str, end: str, *, limit: int, cursor: str | None = None) -> dict[str, Any]:
    """One page of `target`'s alerts in `[start, end)`, as of the baseline clock."""
    return data.alerts_page(
        CATALOG,
        target,
        start_at=at(start),
        end_at=at(end),
        as_of=at("2026-10-16T12:00:00Z"),
        limit=limit,
        cursor=cursor,
    )


def test_alerts_page_one_by_one_with_a_cursor_bound_to_the_request() -> None:
    a17 = asset(ALPHA, "A17")
    first = page(a17, "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z", limit=1)
    assert [a["alert_id"] for a in first["alerts"]] == [SEAL_1] and first["next_cursor"] is not None
    cursor = first["next_cursor"]
    assert len(cursor) == 76 and first["start_at"] == "2026-10-05T00:00:00Z"
    second = page(a17, "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z", limit=1, cursor=cursor)
    assert [a["alert_id"] for a in second["alerts"]] == [SEAL_2] and second["next_cursor"] is None
    whole = page(a17, "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z", limit=2)
    assert len(whole["alerts"]) == 2 and whole["next_cursor"] is None  # set exactly when more remain
    for doc in (first, second, whole):
        valid("get_recent_alerts", doc)
    assert first["alerts"][0] == {
        "alert_id": SEAL_1,
        "asset_id": "A17",
        "occurred_at": "2026-10-05T14:00:00Z",
        "code": "seal_leak",
        "message": "Synthetic warning alert: seal leak on Alpha transfer pump A17.",
        "revision": 1,
    }
    tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    for target, end, presented in (
        (a17, "2026-10-08T00:00:00Z", cursor),  # another interval
        (asset(ALPHA, "A21"), "2026-10-07T00:00:00Z", cursor),  # another asset
        (asset(BETA, "B22"), "2026-10-07T00:00:00Z", cursor),  # another tenant
        (a17, "2026-10-07T00:00:00Z", tampered),
        (a17, "2026-10-07T00:00:00Z", "!!"),
    ):
        with pytest.raises(data.CursorRefused):
            page(target, "2026-10-05T00:00:00Z", end, limit=1, cursor=presented)


def test_the_interval_is_half_open_and_no_alert_comes_from_after_as_of() -> None:
    a17 = asset(ALPHA, "A17")
    seal_2 = at("2026-10-06T08:30:00Z")

    def ids(start: str, end: datetime, as_of: datetime) -> list[str]:
        page = data.alerts_page(CATALOG, a17, start_at=at(start), end_at=end, as_of=as_of, limit=100, cursor=None)
        return [a["alert_id"] for a in page["alerts"]]

    assert ids("2026-10-05T14:00:00Z", seal_2, at("2026-10-16T12:00:00Z")) == [SEAL_1]  # start in, end out
    assert ids("2026-10-05T00:00:00Z", at("2026-10-07T00:00:00Z"), seal_2 - timedelta(seconds=1)) == [SEAL_1]
    assert ids("2026-10-05T00:00:00Z", at("2026-10-07T00:00:00Z"), seal_2) == [SEAL_1, SEAL_2]  # at as_of: in


def test_a_malformed_alert_file_is_refused_at_start(tmp_path: Path) -> None:
    for name in ("assets.json", "meta.json"):
        shutil.copy(data.DATA / name, tmp_path / name)
    original = json.loads((tmp_path / "assets.json").read_text(encoding="utf-8"))
    for field, value in (("severity", "urgent"), ("raised_at", "2026-10-05T16:00:00+02:00"), ("kind", "Seal Leak")):
        broken = json.loads(json.dumps(original))
        broken["alerts"][0][field] = value
        (tmp_path / "assets.json").write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(data.DataError):
            data.load(tmp_path)
    (tmp_path / "assets.json").write_text(json.dumps(original), encoding="utf-8")
    assert len(data.load(tmp_path).assets) == 6  # the unbroken copy loads: the refusals were the edits'


def forged(micros: int, a17: data.Asset, *, end: str = "2026-10-07T00:00:00Z") -> str:
    """A cursor with a valid binding for the request (the binding is an unkeyed hash of known values) and any position."""
    bound = data.binding(a17.tenant_id, a17.asset_id, at("2026-10-05T00:00:00Z"), at(end))
    raw = struct.pack(">Bq", data.CURSOR_VERSION, micros) + UUID(SEAL_1).bytes + bound
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_a_forged_or_non_canonical_cursor_is_refused_not_an_error() -> None:
    a17 = asset(ALPHA, "A17")
    for micros in (2**63 - 1, -(2**63), 2**62, -(2**62)):  # outside datetime's range, though the binding holds
        with pytest.raises(data.CursorRefused):
            page(a17, "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z", limit=1, cursor=forged(micros, a17))
    sane = forged(0, a17)  # a position inside the range is a valid (if odd) cursor: it selects, it does not crash
    assert page(a17, "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z", limit=1, cursor=sane)["alerts"]
    real = page(a17, "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z", limit=1)["next_cursor"]
    assert real is not None
    for spelling in (real + "=", real + "\n", real[:10] + "*" + real[10:], real.replace("-", "+").replace("_", "/")):
        if spelling == real:  # the replacement is a no-op when the cursor has neither character
            continue
        with pytest.raises(data.CursorRefused):
            page(a17, "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z", limit=1, cursor=spelling)


@pytest.mark.parametrize(
    "text",
    [
        "20261006T000000Z",  # basic format
        "2026-10-06 00:00:00Z",  # space separator
        "2026-W41-2T00:00:00Z",  # ISO week date
        "2026-10-06T00Z",  # hour only
        "2026-10-06T00:00:00,5Z",  # comma decimal
        "2026-10-06T00:00:00",  # no offset
        "2026-10-06T02:00:00+02:00",  # not UTC
    ],
)
def test_an_instant_must_be_rfc_3339_utc(text: str) -> None:
    with pytest.raises(ValueError):
        data.instant(text)
    assert data.instant("2026-10-06T00:00:00.5+00:00") == datetime(2026, 10, 6, 0, 0, 0, 500000, tzinfo=UTC)


def test_a_page_of_no_alerts_is_refused() -> None:
    with pytest.raises(ValueError):
        page(asset(ALPHA, "A17"), "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z", limit=0)
