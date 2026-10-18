# core (library)

## Owns
Domain rules (transition table, route tables, reason enum, canonical JSON), application use cases, adapter interfaces and Pydantic contracts.

## Trusts
Nothing at runtime: it has no credentials and opens no connections. Services inject adapters.

## Never
Runs as a process; holds a secret; talks to a network.
