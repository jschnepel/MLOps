"""A definer function's DETAIL code becomes the HTTP class BUILD_SPEC §16 names (403 for an independence or
membership refusal, 409 for a lost race or a stale version); nothing else leaks from the database."""

import pytest
from ops_api import store
from ops_core import persistence


@pytest.mark.parametrize(
    ("code", "expected", "http_code"),
    [
        ("NOT_REVIEWER", store.Forbidden, None),
        ("SELF_REVIEW", store.Forbidden, None),
        ("MEMBERSHIP_INACTIVE", store.Forbidden, None),
        ("SLOT_OCCUPIED", store.Conflict, "SLOT_OCCUPIED"),
        ("ANYTHING_ELSE", store.Conflict, "VERSION_CONFLICT"),
    ],
)
def test_map_refusal(code: str, expected: type[Exception], http_code: str | None) -> None:
    mapped = store.map_refusal(persistence.Refused(code))
    assert isinstance(mapped, expected)
    if http_code is not None:
        assert isinstance(mapped, store.Conflict) and mapped.code == http_code
