# incident-sim

Synthetic incident destination with its own database

## Owns
The atomic `action_key` table and incidents

## Trusts
Only mcp-write's token and `azp`

## Never
Deleting keys; trusting a caller-supplied hash

## Runs (T08)

`python -m ops_incident_sim` on 127.0.0.1:8090 (`OPS_INCIDENT_SIM_PORT`), database `incident` as role `incident`
(`postgres_incident_password`). `POST /internal/incidents` and `GET /internal/actions/{id}`; abort and faults arrive
with T10.
