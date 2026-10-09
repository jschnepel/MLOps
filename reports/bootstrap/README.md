# Dev bootstrap evidence (T05, T43, T44)

Captured on this machine with `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/plan_b/live -q`. Files hold decoded claims and command output only; `tests/plan_b/test_evidence.py` rejects any token or secret value here.

- `keycloak-claims.txt` — redacted claims (`iss`, `aud`, `azp`, `sub`, `preferred_username`, `typ`) for the workload clients and personas, plus the host-vs-container `iss` comparison.
- `bootstrap-admin.txt` — the bootstrap admin's password grant after removal, and after a restart (Task 3).
- `compose-ps.txt` — `docker compose --profile dev ps` showing only `127.0.0.1` bindings (Task 3 adds it).
- `ollama-bridge.txt` — a container reaching the host's Ollama (Task 4).
