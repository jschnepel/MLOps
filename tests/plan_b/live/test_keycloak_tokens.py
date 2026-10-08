"""T05 DoD: workload tokens carry the expected aud/azp, persona sub equals the seeded ID, iss is identical.

"Both sides" means the host and a container on the Docker network. A wrong audience would let a token minted for one
downstream be replayed against another, and an `iss` that differs between the host and the network would make every
token validated inside a container fail. Only redacted claims are written to `reports/bootstrap/keycloak-claims.txt`;
tokens and secrets never are.
"""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from tests.plan_b.live import kc

SEEDS = json.loads(Path("data/seed-ids.json").read_text(encoding="utf-8"))
HELPER_IMAGE = "python:3.13-slim@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c"
EVIDENCE = Path("reports/bootstrap/keycloak-claims.txt")


def host_base(env: dict[str, str]) -> str:
    """Keycloak's host-side base URL; `localhost` so it matches the issuer the stack advertises."""
    return f"http://localhost:{env['KC_HTTP_PORT']}"


def redact(c: dict) -> dict:
    """Keep only the non-secret claims worth recording as evidence."""
    return {k: c[k] for k in ("iss", "aud", "azp", "sub", "preferred_username", "typ") if k in c}


def audiences(c: dict) -> set[str]:
    """The token's aud set without Keycloak's default `account` audience; exact comparisons catch audience confusion."""
    aud = c["aud"] if isinstance(c["aud"], list) else [c["aud"]]
    return set(aud) - {"account"}


def test_worker_token_carries_exactly_the_two_mcp_audiences(env, secret: Callable[[str], str]) -> None:
    tok = kc.token_client_credentials(host_base(env), "ops-worker", secret("kc_client_secret_ops_worker"))
    c = kc.claims(tok["access_token"])
    assert audiences(c) == {env["MCP_READ_RESOURCE_URL"], env["MCP_WRITE_RESOURCE_URL"]}, c["aud"]
    assert c["azp"] == "ops-worker"
    assert c["iss"] == f"{host_base(env)}/realms/{kc.REALM}"
    _record("ops-worker (host)", redact(c))


def test_mcp_workload_tokens_carry_exactly_their_single_audience(env, secret: Callable[[str], str]) -> None:
    for client, expected in (("ops-mcp-read", "asset-sim"), ("ops-mcp-write", "incident-sim")):
        tok = kc.token_client_credentials(
            host_base(env), client, secret(f"kc_client_secret_{client.replace('-', '_')}")
        )
        c = kc.claims(tok["access_token"])
        assert audiences(c) == {expected}, (client, c["aud"])  # mcp-read never gets incident-sim, and vice versa
        assert c["azp"] == client
        _record(f"{client} (host)", redact(c))


def test_persona_token_sub_equals_seed_id(env, secret: Callable[[str], str]) -> None:
    for name in ("alex", "sam"):
        tok = kc.token_password(host_base(env), "ops-dev-direct", name, secret(f"kc_persona_{name}_password"))
        c = kc.claims(tok["access_token"])
        assert c["sub"] == SEEDS["personas"][name]["user_id"], name  # the join key to the seeded PostgreSQL rows
        assert c["azp"] == "ops-dev-direct" and c["preferred_username"] == name
        _record(f"persona {name} (host)", redact(c))


def test_iss_is_identical_from_host_and_container(env, secret: Callable[[str], str]) -> None:
    host_iss = kc.claims(
        kc.token_client_credentials(host_base(env), "ops-worker", secret("kc_client_secret_ops_worker"))["access_token"]
    )["iss"]
    # The container mints its own token through the Docker network name and prints only `iss`. The secret file is
    # mounted read-only instead of passed as an argument so it never appears on a command line or in `docker ps`.
    script = (
        "import json,sys,urllib.parse,urllib.request,base64;"
        "d=urllib.parse.urlencode({'grant_type':'client_credentials','client_id':'ops-worker',"
        "'client_secret':open('/run/s','r').read()}).encode();"
        "t=json.loads(urllib.request.urlopen('http://keycloak:8080/realms/ops-dev/protocol/openid-connect/token',"
        "d,timeout=20).read())['access_token'];"
        "p=t.split('.')[1];p+='='*(-len(p)%4);print(json.loads(base64.urlsafe_b64decode(p))['iss'])"
    )
    secret_path = Path(env["OPS_SECRETS_DIR"]) / "kc_client_secret_ops_worker"
    out = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "ops-dev-net",
            "-v",
            f"{secret_path.as_posix()}:/run/s:ro",
            HELPER_IMAGE,
            "python",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout.strip()
    assert out == host_iss, (out, host_iss)
    _record("iss host vs container", {"host": host_iss, "container": out})


def _record(label: str, data: dict) -> None:
    """Append one redacted evidence line; LF newlines keep the committed file identical across platforms."""
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    with EVIDENCE.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(f"{label}: {json.dumps(data, sort_keys=True)}\n")
