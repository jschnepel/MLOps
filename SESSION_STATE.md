# Session state — initial build handoff

**Specification:** OPS-BUILD-1.0  
**Current milestone:** M00 — reproduce in the builder's environment  
**Next task:** T01, then T02  
**Repository remote/commit:** Not created or assumed by handoff assembly.

## Completed by handoff author

Consolidated the build specification, original local reference, corrected stage charts, typed target schema examples, task DAG, acceptance requirements, synthetic source fixtures and development scenario cards. Reran the reference tests and recovery CLI; see the current handoff verification report for the exact evidence. No target cloud, model, MCP, browser, Docker or Kubernetes success is implied.

## First builder commands

```bash
python scripts/verify_handoff.py --manifest --reference-code
PYTHONPATH=src python -m operations_copilot.cli
python -m pytest -q
```

If required test dependencies are missing, record that fact and perform isolated dependency resolution in M01; do not turn the missing suite into a pass. After baseline capture, inspect schemas/tasks and implement the first tested contract/toolchain slice.

## External inputs not yet authorized or known

Actual target machine/GPU and chosen installed model; large model download consent; nonlocal identity/cloud/notification credentials; public domain; spending; public license; repository publication; final holdout reviewer custody. Defaults stay local, synthetic, fake-control mode while independent work proceeds.

## Update this record after each slice

Record current commit/dirty files, task IDs, changed files, actual commands and results including skips/failures, review findings, blockers, approved deviations, next task and exact next command. Do not store secrets or a private reasoning transcript.
