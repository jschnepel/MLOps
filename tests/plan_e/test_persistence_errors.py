"""The database-free parts of the rewritten persistence layer: SQLSTATE class OC → typed exceptions (ruling 20), the
tool allowlist that stayed in Python (ruling 21), and the hashed handle.

Catches: a code mapped to the wrong class, a non-OC error swallowed, a DETAIL code lost, a tool allowed for the
wrong job type, and a handle stored raw.
"""

from types import SimpleNamespace

import psycopg
import pytest
from ops_core import persistence as p
from ops_core.canonical import sha256_hex
from ops_core.jobs import JobType, Tool
from ops_core.outcomes import EventRuleViolation
from ops_core.states import IllegalTransition


def error(sqlstate: str, detail: str | None = None) -> psycopg.Error:
    """A server error with a chosen SQLSTATE and DETAIL; psycopg's `diag` is a property, so a subclass overrides it."""
    diag = SimpleNamespace(message_detail=detail, message_primary="x")
    cls = type("FakeError", (psycopg.DatabaseError,), {"diag": property(lambda self: diag)})
    exc = cls("x")
    exc.sqlstate = sqlstate
    return exc


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("OC001", p.AuthorityViolation),
        ("OC002", p.NotFound),
        ("OC003", p.VersionConflict),
        ("OC004", IllegalTransition),
        ("OC005", p.Refused),
        ("OC006", EventRuleViolation),
        ("OC007", p.HashMismatch),
        ("OC008", p.HandleRejected),
    ],
)
def test_oc_codes_map_to_typed_exceptions(code: str, expected: type[Exception]) -> None:
    mapped = p.translate(error(code, "DETAIL"))
    assert isinstance(mapped, expected)
    assert "x" not in str(mapped) or code != "OC008"  # the handle refusal never echoes the server's text


def test_refused_carries_the_detail_code_and_other_errors_pass_through() -> None:
    mapped = p.translate(error("OC005", "SLOT_OCCUPIED"))
    assert isinstance(mapped, p.Refused) and mapped.code == "SLOT_OCCUPIED"
    assert p.translate(error("42501")) is None
    assert p.translate(error("40001")) is None


@pytest.mark.parametrize(
    ("job_type", "tool", "ok"),
    [
        (JobType.INVESTIGATE, Tool.SEARCH_PROCEDURES, True),
        (JobType.INVESTIGATE, Tool.CREATE_INCIDENT, False),
        (JobType.EXECUTE, Tool.CREATE_INCIDENT, True),
        (JobType.EXECUTE, Tool.SEARCH_PROCEDURES, False),
        (JobType.RECOVER, Tool.ABORT_INCIDENT, True),
    ],
)
def test_allowed_tool(job_type: JobType, tool: Tool, ok: bool) -> None:
    if ok:
        p.allowed_tool(job_type, tool)
    else:
        with pytest.raises(p.HandleRejected):
            p.allowed_tool(job_type, tool)


def test_handle_hash_is_the_canonical_sha256_of_the_utf8_bytes() -> None:
    assert p.handle_hash("abc") == sha256_hex(b"abc")
    assert len(p.handle_hash("x" * 43)) == 64
