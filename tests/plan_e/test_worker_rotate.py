"""The worker's tenant rotation (ruling 18): a different first tenant each poll so none starves, and never a lost or
duplicated tenant, whatever the poll counter reads."""

from uuid import UUID

import pytest
from ops_worker.main import rotate

T = [UUID(int=i) for i in range(1, 5)]


@pytest.mark.parametrize(
    ("start", "expected"),
    [(0, [1, 2, 3, 4]), (1, [2, 3, 4, 1]), (3, [4, 1, 2, 3]), (4, [1, 2, 3, 4]), (6, [3, 4, 1, 2])],
)
def test_rotate_wraps_and_start_beyond_the_length_is_modular(start: int, expected: list[int]) -> None:
    assert rotate(T, start) == [UUID(int=i) for i in expected]


def test_rotate_of_nothing_is_nothing() -> None:
    assert rotate([], 7) == []


@pytest.mark.parametrize("start", range(11))
def test_every_offset_is_a_permutation_of_the_input(start: int) -> None:
    assert sorted(rotate(T, start)) == sorted(T)
