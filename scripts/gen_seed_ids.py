"""Deterministic tenant and persona UUIDs shared by T05 (Keycloak realm) and T45 (fixtures). Stdlib only.

Usage: python -I scripts/gen_seed_ids.py   (writes data/seed-ids.json with LF and no BOM)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/jschnepel/MLOps/seed")
PERSONAS = {
    "alex": ("alpha", ["requester"]),
    "sam": ("alpha", ["reviewer"]),
    "lee": ("alpha", ["reader"]),
    "riley": ("beta", ["requester"]),
    "jordan": ("beta", ["reviewer"]),
}
OUT = Path("data/seed-ids.json")


def generate() -> dict:
    tenants = {slug: str(uuid.uuid5(NS, f"tenant/{slug}")) for slug in ("alpha", "beta")}
    personas = {
        name: {"user_id": str(uuid.uuid5(NS, f"user/{name}")), "tenant": tenant, "roles": roles}
        for name, (tenant, roles) in PERSONAS.items()
    }
    return {"tenants": tenants, "personas": personas}


def write_seed_ids(out: Path = OUT) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(generate(), indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write_seed_ids()
    print(f"wrote {OUT}")
