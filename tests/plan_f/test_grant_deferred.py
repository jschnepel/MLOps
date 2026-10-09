"""A stale sync defers execution instead of failing it (ruling 14): mcp-write maps MEMBERSHIP_STALE to the
retryable tool error GRANT_DEFERRED and the worker re-queues such an envelope the way it re-queues a transport
failure; every other refusal stays GRANT_REFUSED and final."""

from ops_mcp_write.server import refusal_error
from ops_worker.handlers import is_deferred


def test_stale_membership_is_the_one_deferred_refusal() -> None:
    deferred = refusal_error("MEMBERSHIP_STALE")
    assert deferred == {"code": "GRANT_DEFERRED", "message": "grant deferred: MEMBERSHIP_STALE", "retryable": True}
    for code in ("MEMBERSHIP_INACTIVE", "NO_APPROVAL", "CANCELLED", "OTHER_PROPOSAL"):
        refused = refusal_error(code)
        assert refused["code"] == "GRANT_REFUSED" and refused["retryable"] is False and code in refused["message"]


def test_worker_recognises_a_deferred_envelope_only() -> None:
    assert is_deferred({"status": "error", "error": {"code": "GRANT_DEFERRED", "retryable": True}})
    assert not is_deferred({"status": "error", "error": {"code": "GRANT_REFUSED", "retryable": False}})
    assert not is_deferred({"status": "ok", "data": {"status": "SUCCEEDED"}})
    assert not is_deferred({"status": "outcome", "data": {"status": "UNKNOWN"}, "error": None})
