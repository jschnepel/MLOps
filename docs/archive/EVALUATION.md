# Evaluation protocol

## Distinct evidence categories

1. **Deterministic controls:** the supplied 58 tests cover state and permission behavior plus local HTTP boundaries. They use a fake model.
2. **SDK/network contracts:** separately install and test MCP/LangGraph; add real authenticated transport and PostgreSQL.
3. **Real-model quality:** select a local model and hardware; run isolated repeated scenarios with actual output.
4. **Operational experiments:** measure browser behavior, deployment, load, faults, restore and upgrades.

Never substitute one category's pass count for another. Agent-evaluation guidance emphasizes environment outcomes, isolation, repeated trials and calibrated graders. [S13 in SOURCES.md]

## Baselines

A: permitted search plus manual incident form. B: basic RAG chatbot plus the same manual form. C: controlled MCP workflow. All receive the same underlying allowed evidence and task. Count the user's remaining work for each. Manual timing is meaningful only after actual people or a documented repeatable task protocol perform the comparison; do not fabricate human-effort results from model timing.

## Dataset design

Proposed target: 120 definitions, split 80 development/40 held out before tuning, three trials per model-based scenario. Stratify normal cases, missing/conflicting data, correction/clarification, permission denial, injection, external failure, cancellation and replay. Use independently authored variants to reduce template memorization. The ten supplied seeds in `evals/development-seeds.jsonl` are development examples only; expand and review them. Some control scenarios require test-harness fault injection rather than only a natural-language prompt.

Keep held-out content outside the tuning loop. Once inspected for debugging, treat that set as used and create a new release holdout; document this instead of continuing to claim untouched evidence. There is no completed hidden dataset or real-model benchmark in the archive.

## Trial record

Record trial/scenario IDs, split, seed, model name/digest, generation settings, code/workflow/prompt/tool/corpus versions, hardware, input, permitted evidence, tool events, actual final destination state, timing, token/resource measurements, deterministic checks, semantic grades and human corrections. Redact credentials and private content. Run each trial in clean isolated data namespaces so one incident cannot contaminate the next.

## Metrics

| Metric | Definition |
|---|---|
| Task success | All scenario-specific evidence, authorization and final-state requirements met. |
| Citation support | Supported cited claims divided by evaluated cited claims; human-calibrate automated judgments. |
| Evidence retrieval | Relevant permitted items retrieved relative to scenario's labeled evidence set. |
| Appropriate abstention | Correctly withheld unsupported conclusions/actions in designated cases. |
| Write integrity | Counts of unauthorized, duplicate, wrong-asset or wrong-content committed incidents. |
| Reviewer effort | Actually measured corrections/interactions/time using a declared protocol. |
| Performance | End-to-end and per-stage p50/p95, including vs excluding human waits clearly separated. |
| Resource usage | Measured tokens, local compute/memory or actual provider usage; no invented cost estimate. |

Hard blocker: any observed forbidden write, wrong-team disclosure or duplicate destination effect in the release suite. Quality thresholds should be calibrated on development evidence and frozen before the held-out run. Include denominators, all trial failures, baseline uncertainty and small-sample limitations. An LLM judge is a supplementary instrument, not the source of truth for committed side effects.

## Release report structure

Purpose -> versions/hardware -> datasets and splits -> baseline methodology -> aggregate and per-category results -> failures -> grader calibration -> limitations -> release decision. Include an unsuccessful prompt change and its regression when available; do not select only favorable runs.
