"""The published lock order (AM-12 SA:188 as extended by Plan H ruling 14, erratum 52) and every transaction of the
system checked against it, without a database.

Catches: a table that exists in the privilege matrix but has no place in the order (a new table must be placed
before it ships), a table placed twice, an own-unit table (model_permit, sessions, ...) locked together with a run
table, a documented transaction that steps back in the order (the deadlock the stress test hunts for live), and an
order that no longer starts with the advisory locks or ends with the idempotency record.
"""

import pytest
from ops_core import locking, privileges


def test_every_table_is_placed_exactly_once() -> None:
    ordered = {locking.table_of(entry) for entry in locking.LOCK_ORDER} - {None}
    groups = (ordered, set(locking.OWN_UNIT), set(locking.NEVER_LOCKED))
    for table in privileges.GRANTS:
        assert sum(table in group for group in groups) == 1, table
    named = ordered | locking.OWN_UNIT | locking.NEVER_LOCKED
    assert named - set(privileges.GRANTS) <= locking.NOT_YET_CREATED, sorted(named - set(privileges.GRANTS))


def test_the_order_starts_with_the_advisory_locks_and_ends_with_the_record() -> None:
    assert locking.LOCK_ORDER[:2] == ("advisory:idempotency", "advisory:asset")  # erratum 37, then SA:189
    assert locking.LOCK_ORDER[-1] == "idempotency_request"  # SA:188: written last, before commit
    assert locking.rank("jobs:claim") < locking.rank("run_lease") < locking.rank("runs") < locking.rank("jobs:finish")
    assert locking.rank("memberships") < locking.rank("execution_grant") < locking.rank("invocation_context")
    assert len(set(locking.LOCK_ORDER)) == len(locking.LOCK_ORDER)


def test_follows_order_allows_repeats_and_refuses_a_step_back() -> None:
    assert locking.follows_order(("run_lease", "runs", "runs", "events"))  # a lock already held is taken again
    assert not locking.follows_order(("runs", "run_lease"))
    assert not locking.follows_order(("invocation_context", "runs"))  # revoking handles before locking the run
    with pytest.raises(ValueError):
        locking.follows_order(("sessions",))  # an own-unit table has no rank


@pytest.mark.parametrize("unit", sorted(locking.OBSERVED_UNITS))
def test_the_documented_units_are_consistent_with_the_order(unit: str) -> None:
    assert locking.follows_order(locking.OBSERVED_UNITS[unit]), unit


@pytest.mark.parametrize("unit", sorted(locking.OWN_UNITS))
def test_own_units_never_touch_a_run_table(unit: str) -> None:
    # The sweeper's purge deletes expired idempotency records in the same unit as the session tables; it touches no
    # run table, so it cannot meet a run transaction in a cycle.
    assert set(locking.OWN_UNITS[unit]) <= locking.OWN_UNIT | {"idempotency_request"}, unit


def test_not_yet_created_tables_are_absent_from_the_matrix() -> None:
    assert not locking.NOT_YET_CREATED & set(privileges.GRANTS)
