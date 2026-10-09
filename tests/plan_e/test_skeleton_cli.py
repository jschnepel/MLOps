"""The pure parts of scripts/skeleton.py: the Alembic target per profile (SA:529), and the detective check's set
arithmetic (T10 review note 3). The database-touching parts are proved live in tests/e2e."""

import sys
from pathlib import Path
from uuid import UUID

from ops_core.settings import Profile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.skeleton import migrate_target, orphan_keys  # ruff allows an import after a sys.path edit


def test_only_the_test_profile_applies_the_testclock_branch() -> None:
    assert migrate_target(Profile.TEST) == "heads"
    assert migrate_target(Profile.DEV) == "app@head"
    assert migrate_target(Profile.DEMO) == "app@head"


def test_orphan_keys_are_destination_keys_without_a_matching_grant_hash() -> None:
    a, b, c = UUID(int=1), UUID(int=2), UUID(int=3)
    keys = [(a, "h1"), (b, "h2"), (c, "h3")]
    grants = {(a, "h1"), (b, "other-hash")}
    assert orphan_keys(keys, grants) == [(b, "h2"), (c, "h3")]
    assert orphan_keys([], grants) == []
