# incident-sim

Synthetic incident destination with its own database

## Owns
The atomic `action_key` table and incidents

## Trusts
Only mcp-write's token and `azp`

## Never
Deleting keys; trusting a caller-supplied hash
