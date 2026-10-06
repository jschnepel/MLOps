# Target contracts, not implemented endpoints

These JSON Schema 2020-12 documents define the reviewed target shape. Existing reference endpoints still use smaller historical contracts. Implement Pydantic/API adapters and compare generated schemas in M01/M03. Do not remove the old control invariants while migrating.

Run `python scripts/verify_handoff.py --contracts` with `jsonschema` available to validate the schemas and positive/negative examples. This is a schema check, not a test of model quality, authentication, authorization, timestamp ordering, proposal canonicalization policy, source access or database atomicity.

Every example uses synthetic IDs and fixed times. Negative examples are explicitly expected to fail. Schema-valid authority records still require application-origin checks; never deserialize arbitrary user/model output as a trusted proposal, decision or destination receipt.
