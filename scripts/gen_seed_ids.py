"""Deterministic tenant and persona UUIDs shared by T05 (Keycloak realm) and T45 (fixtures). Stdlib only.

Usage: python -I scripts/gen_seed_ids.py   (writes data/seed-ids.json with LF and no BOM)

The IDs are derived, not random, so the Keycloak realm and the test fixtures can be generated independently and
still agree. Changing NS or any name below changes every ID; tests/plan_a/test_seed_ids.py pins golden values to
catch that, because external systems store these IDs.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

# uuid5 (a hash of namespace + name) gives the same UUID on every machine and run, unlike uuid4. The namespace is
# derived from this project's own URL so the IDs cannot collide with another project's. Do not edit this string.
NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/jschnepel/MLOps/seed")
# persona -> (tenant slug, roles); alpha and beta are the two tenants that tenant-isolation tests compare.
PERSONAS = {
    "alex": ("alpha", ["requester"]),
    "sam": ("alpha", ["reviewer"]),
    "lee": ("alpha", ["reader"]),
    "riley": ("beta", ["requester"]),
    "jordan": ("beta", ["reviewer"]),
}
OUT = Path("data/seed-ids.json")


def generate() -> dict:
    """Return {"tenants": {slug: uuid}, "personas": {name: {user_id, tenant, roles}}}, identical on every call."""
    tenants = {slug: str(uuid.uuid5(NS, f"tenant/{slug}")) for slug in ("alpha", "beta")}
    personas = {
        name: {"user_id": str(uuid.uuid5(NS, f"user/{name}")), "tenant": tenant, "roles": roles}
        for name, (tenant, roles) in PERSONAS.items()
    }
    return {"tenants": tenants, "personas": personas}


def write_seed_ids(out: Path = OUT) -> None:
    """Write the generated IDs to `out` as indented JSON with LF line endings and no BOM."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(generate(), indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write_seed_ids()
    print(f"wrote {OUT}")
