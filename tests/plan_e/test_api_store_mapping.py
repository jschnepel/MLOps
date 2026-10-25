"""A definer function's DETAIL code becomes the HTTP class BUILD_SPEC §16 names (403 for an independence or
membership refusal, 409 for a lost race or a stale version); nothing else leaks from the database. T21's units record
a refusal of the run's state under its own code and never record one of the caller's (Plan R rulings 2, 4, 6 and 7)."""

import pytest
from ops_api import store
from ops_core import persistence
from ops_core.contracts import ErrorCode


@pytest.mark.parametrize(
    ("code", "expected", "http_code"),
    [
        ("NOT_REVIEWER", store.Forbidden, None),
        ("SELF_REVIEW", store.Forbidden, None),
        ("MEMBERSHIP_INACTIVE", store.Forbidden, None),
        ("NOT_REQUESTER", store.Forbidden, None),
        ("NOT_CANCELLER", store.Forbidden, None),
        ("NOT_AUTHOR", store.Forbidden, None),
        ("SLOT_OCCUPIED", store.Conflict, "SLOT_OCCUPIED"),
        ("GRANT_EXISTS", store.Conflict, "GRANT_EXISTS"),
        ("AUTHOR_LIMIT", store.Conflict, "AUTHOR_LIMIT"),
        ("INVALID_ARGUMENT", store.Internal, None),
        ("ANYTHING_ELSE", store.Conflict, "VERSION_CONFLICT"),
    ],
)
def test_map_refusal(code: str, expected: type[Exception], http_code: str | None) -> None:
    mapped = store.map_refusal(persistence.Refused(code))
    assert isinstance(mapped, expected)
    if http_code is not None:
        assert isinstance(mapped, store.Conflict) and mapped.code == http_code


@pytest.mark.parametrize("code", ["NOT_REQUESTER", "NOT_CANCELLER", "NOT_AUTHOR", "NOT_REVIEWER"])
def test_a_refusal_of_the_caller_stays_forbidden_and_is_never_recorded(code: str) -> None:
    mapped = store.recorded_refusal(persistence.Refused(code))
    assert isinstance(mapped, store.Forbidden) and not isinstance(mapped, store.Recorded)


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("SLOT_OCCUPIED", ErrorCode.SLOT_OCCUPIED),
        ("GRANT_EXISTS", ErrorCode.GRANT_EXISTS),
        ("AUTHOR_LIMIT", ErrorCode.AUTHOR_LIMIT),
        ("ANYTHING_ELSE", ErrorCode.VERSION_CONFLICT),
    ],
)
def test_a_refusal_of_the_runs_state_becomes_the_409_the_unit_records(code: str, error: ErrorCode) -> None:
    mapped = store.recorded_refusal(persistence.Refused(code))
    assert isinstance(mapped, store.Recorded)
    assert (mapped.status, mapped.code, mapped.message) == (409, error, store.CONFLICT_MESSAGES[error])
