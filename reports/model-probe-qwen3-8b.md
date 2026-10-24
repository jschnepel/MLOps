# Model probe: qwen3:8b (AM-31, T02)

Measurement only; prompts unchanged (sha256 verified against the hashes pinned in probe.py; no holdout seal, erratum 114). Distinct inputs: 60. Date: 2026-10-24T22:42:22.383063+00:00.
Configuration measured (AM-31): model `qwen3:8b`, digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`, Ollama 0.40.4, `ChatOllama(reasoning=False, num_ctx=16384, num_predict=1000, temperature=0)` wrapped in `with_structured_output(schemas/model-draft.schema.json, method="json_schema", include_raw=True)`, plus application-side jsonschema validation of the parsed object. First-pass, repair and repeat calls use the wrapper; JSON-valid means the wrapper parsed an object (`parsing_error` is None) and the raw text has no thinking. The mid-generation cancel and the following `ok` call use the same ChatOllama unwrapped. 60s cap per call. Interpreter: 3.13.13. Model unloaded before the first call.

| Metric | Value | Wilson 95% CI |
|---|---|---|
| JSON-valid (first pass) | 59/60 | [0.911, 0.997] |
| Schema-valid (first pass) | 5/60 | [0.036, 0.181] |
| Schema-valid after one repair | 5/60 | [0.036, 0.181] |
| Thinking present in first-pass outputs (text tag or metadata) | 0/60 inputs | any > 0 fails the no-thinking setting |
| Thinking present in repair outputs (text tag or metadata) | 0/54 repair calls | any > 0 fails the no-thinking setting |
| Cold-start latency (after unload) | not measured (cold call failed: TimeoutError: ) | |
| Warm latency p50 / p95 | 2.77 s / 4.14 s | |
| Peak VRAM (max of 806 whole-GPU samples at 0.5 s during calls, NVIDIA GeForce RTX 3080) | 8851 MB | |
| Thinking present in repeat and post-cancel outputs (text tag or metadata) | 0/16 calls | any > 0 fails the no-thinking setting |
| Identical outputs on 3 repeats (5 inputs) | 1/5 | |
| Full `ok` call after mid-generation cancel, incl. /api/ps | 0.15 s | |

Whole-GPU memory.used immediately after cancel (nvidia-smi): 8848 MB.
`/api/ps` immediately after cancel: `{"models": [{"name": "qwen3:8b", "model": "qwen3:8b", "size": 7411114966, "digest": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41", "details": {"parent_model": "", "format": "gguf", "family": "qwen3", "families": ["qwen3"], "parameter_size": "8.2B", "quantization_level": "Q4_K_M"`

Errors: [('PR-001', 'TimeoutError: ')]
Repeat errors: []
Cancel/post-cancel error: None

Owner decision (R081): proceed — PROVISIONAL, recorded by the agent on 2026-10-24 under the owner's instruction to run
the build autonomously; the owner confirms or reverses it.
model_permit release rule (AM-12, chosen from the cancel row above): release on cancel — PROVISIONAL, same basis (the
`ok` call after the cancel completed in 0.15 s).

## Diagnosis added after the run (agent, 2026-10-24; not part of the measured figures)

A follow-up run of 8 inputs (PR-002 to PR-009) through the same configuration, tallying jsonschema errors, found one
error per failing draft: the draft is `proposal` or `answer` and also carries `question`, which the schema's `allOf`
`else: not required [question]` forbids. Ollama's `format` constraint does not enforce `if`/`then`/`else`, and the
repair call returned the same field. The probe's user payload is `{request, evidence}` with no evidence IDs, not the
starter prompt's assembled payload (`allowed_evidence_ids`, `requested_output_schema`), so `evidence_refs` named
bundle keys (`status`, `alerts`, `documents`). The cold call exceeded the 60 s cap (PR-001's timeout). These are
inputs to T19's design, which measures validity again with the real payload.
