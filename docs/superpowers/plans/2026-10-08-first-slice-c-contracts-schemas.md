# First Slice C: Core Contracts, Schema Alignment, Reference Traceability

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the domain's truth into `core/` as data and code that every later service imports — canonical JSON v1, the 17-state run transition table with its performers and reasons, the job/route/outcome vocabularies and the request/response contracts — then make the delivered `schemas/`, `schemas/examples/` and `data/handoff-fixtures/` say the same thing (AM-80) with one negative example per row, a checker that proves it, and a traceability record for all 58 reference tests.

**Architecture:** `core/src/ops_core/` gains `canonical.py` (bytes + sha256, NFC, strict parsing), `states.py` (enums, the transition table as frozen rows, one `require_transition` enforcement function, slot and answer-only rules), `jobs.py` (AM-15/20.4 job rules), `routing.py` (AM-16 enums), `outcomes.py` (tombstone, receipt, action outcome, event rules) and `contracts.py` (strict pydantic request/response models and the requester-asserted run fields). The JSON Schemas keep the `if/then` rules the spec wants enforced declaratively, but they are no longer hand-edited: `scripts/build_schemas.py` generates all 25 schema documents under `schemas/`, every example and `index.json` from the `ops_core` vocabularies, and a drift test compares the committed tree with a fresh generation byte for byte. A conformance test feeds every example through the pydantic models so schemas and code cannot drift. `scripts/verify_handoff.py --contracts` learns to check negative examples *for their stated reason*, meta-validate `schemas/tools/` and `evals/`, reject CR bytes and BOMs and read `expected_payload_sha256`; CI runs it. Fixtures get tenant UUIDs, alert UUIDs/revisions and per-section hashes from a deterministic generator. `reference/TRACEABILITY.md` maps the 58 reference tests; the pure ones are ported against `core`.

**Tech Stack:** Python 3.13, pydantic 2.13 (strict, frozen, extra=forbid), `jsonschema` 4.26 (Draft 2020-12) plus `rfc3339-validator` (added to the dev group in Task 6 so the FormatChecker validates `date-time`; without it `"occurred_at": "yesterday"` validates), Hypothesis 6.168, pytest, ruff (120 cols, import sorting; inside `core/src`, `ops_core` is first-party, so its imports form their own block after `pydantic`), mypy strict on `core/src`.

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md` — AM-10 (states, reasons, clock rule), AM-11, AM-13 (attempt states, tombstone, outcome vocabulary, asset guard), AM-14 (event types and source rules), AM-15 (tools, job types), AM-16 (routes), AM-20.3 (performers of each transition), AM-20.4 (jobs, dedup keys), AM-70 (do-not-port list), AM-80 (every row); BUILD_SPEC §6 (canonical JSON v1, hashed payload fields), §7 (endpoint bodies), §8 (base transitions). Tasks T07, T45, T46 in `handoff/tasks.json`. Inventory used to write this plan: the planner's read-only survey of 2026-10-08 (schema shapes, example list, fixture structure, the 58 tests).

**Rulings on spec self-contradictions** (recorded here; the plan is the argument, the spec stays authoritative, and each ruling is noted in `docs/PROJECT_HISTORY.md` and proposed as errata):
1. **Revision source states.** AM-20.3 `create_revision` (SA:455) lists AWAITING_APPROVAL/APPROVED/BLOCKED_REVIEW → QUEUED; the performer table (SA:484) omits AWAITING_APPROVAL; BUILD_SPEC §8 includes it. The table includes **AWAITING_APPROVAL → QUEUED by `create_revision`** (two of three sources agree; a requester may revise before any decision).
2. **`FAILED_NO_COMMIT.reason`.** SA:280 lists `aborted_no_commit`, `cancelled_before_send`, `rejected`; SA:241 and SA:348 also produce `expired`. The enum includes **`expired`**.
3. **Retrieval mode naming.** AM-20.3's `search_procedures_scoped(…, mode)` takes the *value* `mode=vector` (SA:461); the delivered tool-result schema says `lexical | vector_exact`. The externally visible `retrieval_mode` (tool-result data, tool input, run manifest) keeps the delivered **`vector_exact`**, because it says what the search guarantees (exact, not approximate); `vector` stays the SQL function's argument value. The translation point is `search_procedures_scoped`'s caller in mcp-read (T15), recorded as `TODO(T15)` in `routing.py`.
4. **`QUEUED → AWAITING_INPUT`** (BUILD_SPEC §8) is not in `transition_run`'s targets (SA:451), and AM-10 moves context resolution into RETRIEVING. The table has **`QUEUED → RETRIEVING` only**; missing context is detected in RETRIEVING.
5. **Cancel from BLOCKED_REVIEW** is allowed (AM-10 row) even though it holds no slot; "any pre-grant active state → CANCELLED" (SA:485) is read as "any pre-grant non-terminal state".
6. **Timestamp spelling.** BUILD_SPEC §6 asks for "UTC instants with explicit offsets" but names no spelling, and pydantic's JSON mode emits `Z`. Inputs accept any zero-offset spelling (`Z` or `+00:00`); the canonical, hashed output is pydantic's **`Z`**. The schema for the hashed document (`proposal`) requires `Z`; every other timestamp-bearing schema (`manual-proposal`, the `get_recent_alerts` tool input, `model-pins` — which `scripts/probe.py` writes with `+00:00`) accepts `(Z|\+00:00)`; `run-manifest` has no timestamp.
7. **Negative probes before contract code.** AM-80 (SA:754) says T45 commits a negative per row "before writing contract code", while `handoff/tasks.json` makes T45 depend on T07. The plan keeps the task graph: the negatives are committed in Task 6, **before any service consumes a schema**; T07's core contracts precede them because T45's conformance test (Task 7) validates every example against both the schema and the contract. SA:754's intent, "no implementation before its negatives", is kept at the service boundary (T08 onward).
8. **Reasonless FAILED from the worker.** `transition_run` RETRIEVING/DRAFTING → FAILED ("exhausted infrastructure policy", BUILD_SPEC §8) carries **no reason**: a reason, where one is recorded, comes from the enum (SA:152); a FAILED reached through `transition_run` (exhausted infrastructure policy, BUILD_SPEC §8) records none — the event payload carries the message (the `run.failed` event's message says why).
9. **`create_manual_proposal` performs a transition the performer table omits.** AM-20.3 says it is “otherwise identical to `freeze_proposal`” and emits `proposal.ready`, but the “who performs which transition” table (and therefore the brief's count of twelve performers) leaves it out. The table gets `Performer.CREATE_MANUAL_PROPOSAL` with the same two rows as `freeze_proposal` (DRAFTING → AWAITING_APPROVAL; DRAFTING → BLOCKED_REVIEW on the asset-guard reasons): a manual proposal replaces the model's draft for a run that is waiting for one (the manual baseline, AM-50 condition A); how the API brings a run to that state is T10/T12's. 44 rows, 38 pairs, 13 performers. Found by the Task 2 review on 2026-10-08.

## Global Constraints

- `core` is a library: no I/O, no framework imports beyond pydantic, no `datetime.now()` (callers inject time). Every rule below is data or a pure function; mypy `--strict` on `core/src` must stay clean; `tests/plan_a/test_layout.py` forbids cross-member imports.
- Pydantic models: `ConfigDict(frozen=True, extra="forbid", strict=True)`; request bodies are validated with `model_validate_json` (JSON mode), so ISO-8601 strings become datetimes but ints never become strings and bools never become ints (R004, the reference `test_bool_hours_rejected`).
- Canonical JSON v1 (BUILD_SPEC §6): UTF-8, sorted keys, separators `(",", ":")`, `ensure_ascii=False`, `allow_nan=False`; every string and key NFC-normalised, and two keys that collide under NFC rejected; floats rejected (integers only); object keys must be strings; duplicate keys and non-finite numbers rejected on parse; arrays keep the producer's order, so the producer fixes it (`ProposalPayload` requires `evidence_refs` sorted and `source_snapshots` sorted by `evidence_id`); timestamps per ruling 6; `canonicalization_version = 1`. `payload_sha256` = SHA-256 hex of those bytes. The checker's existing serialisation (`scripts/verify_handoff.py` proposal hash) is the same algorithm minus NFC — the example payloads are ASCII, so hashes are unchanged.
- The 17 run states, 10 reasons, 4 attempt states, 4 tool outcomes, 3 destination states, 2 intents, 8 job types, 6 tools and the three route enums are spelled exactly as in SA:118-152, SA:227, SA:274-280, SA:340-346, SA:366-379 and listed in Task 2–3 code below; nothing else is added.
- Schemas keep `$schema` draft 2020-12, `$id` `urn:operations-copilot:schema:<name>:1`, top-level `additionalProperties: false`. Authority fields (`tenant_id`, `actor`, `actor_id`, `role`, `roles`, `approved`, `approved_by`, `destination`) never appear in request bodies; `extra=forbid` plus `additionalProperties: false` reject them (R004).
- Every AM-80 row gets at least one negative example whose `index.json` entry carries `"valid": false`, `"reason": "<why>"` and `"reason_match": "<regex>"`, matched against jsonschema's best-match error rendered as `"<json path>: <message>"`. Every regex starts with `^` and the path (`^\$\.field: …`); an alternation appears only inside the anchored part (`^\$\.field: (wording a|wording b)`). `--contracts` fails if a negative example validates, or fails for a different reason (R104). Examples, schemas and the index are generated by `scripts/build_schemas.py` (Task 6) and never hand-edited.
- No CR byte or BOM in any text file: `tests/plan_b/test_text_hygiene.py` already scans every tracked file (including `tests/` and `core/`); `--contracts` additionally rejects CR and BOM in its governed set (`schemas/`, `data/handoff-fixtures/`, `handoff/prompts/`, `evals/`) so hashes match across platforms. Every `write_text` in a test passes `newline="\n"` (Windows would otherwise write CRLF).
- Scripts resolve paths from the repository root (`ROOT = Path(__file__).resolve().parents[1]`), never the working directory; a script that imports `scripts.*` runs as `uv run python -m scripts.<name>`, and the checker, which runs as `python -I scripts/verify_handoff.py`, puts `ROOT` on `sys.path` itself (the `scripts/probe.py` pattern).
- Tests open repository-relative paths (e.g. `Path("schemas/examples/index.json")`, `Path("reference/tests")`) and therefore run from the repository root, as `scripts/check.py` and CI do; scripts, by contrast, resolve from `ROOT` (above).
- `_tracked_copy` (in `tests/plan_a/test_verify_handoff.py`) copies `git ls-files`, so before any `pytest` run that exercises it, the task's new files are staged with `git add`; the commit follows.
- `reference/` is hash-pinned and byte-compared with the zip by `--reference-tree`; the only repo-owned files allowed under it are `README.md` and (from Task 8) `TRACEABILITY.md`, listed in `TREE_REPO_OWNED`.
- Comments per `docs/CODE_COMMENTS.md` on every file (why-docstrings; reasons beside each rule row that cites its spec line; `TODO(<task>)` for anything deliberately deferred). Test modules say which mistake they catch.
- Files UTF-8 without BOM, LF; `python -m pytest` via `scripts/check.py`; `testpaths` gains `tests/plan_c` in Task 1; commit messages carry no attribution; nothing pushes.
- Expected totals start from `92 passed, 11 skipped` (branch `plan-b` tip); each task states the total its final `check.py` prints. Totals were derived from the per-file counts measured on a scratch copy of the repository; the final `291 passed, 29 skipped` was measured end to end. When Hypothesis has created `.hypothesis/` in the repository root, pytest's summary also shows `1 warning` (Hypothesis's notice that `norecursedirs` replaces the default ignores); it is not a test result.

## Review Focus

1. **A model-asserted authority field slipping through a nested object.** `test_authority_fields_are_rejected_at_every_depth` (Task 4) injects each forbidden key at the top level of each of the eight request models and inside every nested object those models have (`context` in `MessageRequest` and `ClarificationReply`); `test_any_authority_field_with_any_value_is_rejected` does the same for `MessageRequest` with Hypothesis-drawn values. Neither feeds the schema examples; `extra=forbid` on nested models is what is proven.
2. **A transition that is legal in the table but performed by the wrong function** (e.g. the worker moving a run to SUCCEEDED). `test_every_pair_is_decided_by_the_table` probes every (source, target) pair with every performer, and `test_worker_targets_exclude_post_grant_states` (Task 2) pins AM-20.3's "never any post-grant state and never SUCCEEDED".
3. **Canonical bytes that differ across platforms or inputs that look equal.** Hypothesis properties in Task 1 cover key order and NFC vs NFD strings; floats and `-0.0` are rejected, and keys that collide under NFC raise; the checker's CR and BOM rejection (Task 6) covers line endings.
4. **A negative example that fails for the wrong reason** (a typo elsewhere makes it invalid, so the row's rule is never actually exercised). `--contracts` compares jsonschema's best-match error, as `"<path>: <message>"`, against a `reason_match` anchored on that path (Task 6), and a tampered-copy test proves a wrong-reason negative is reported.
5. **A reference test silently dropped.** `test_traceability_covers_all_58` (Task 8) rebuilds the 58 node IDs from the reference test files (AST + parametrize counts) and requires every one in `TRACEABILITY.md` with a disposition and an existing owning task.

---

### Task 1: T07a — Canonical JSON v1 and hashing

**Files:**
- Create: `core/src/ops_core/canonical.py`, `tests/plan_c/__init__.py`, `tests/plan_c/test_canonical.py`
- Modify: `pyproject.toml` (`testpaths` gains `"tests/plan_c"`)

**Interfaces:**
- Produces: `CANONICALIZATION_VERSION: Final = 1`; `canonical_json(value: object) -> bytes`; `sha256_hex(data: bytes) -> str`; `canonical_sha256(value: object) -> str`; `parse_json_strict(text: str) -> object` (rejects duplicate keys, NaN/Infinity, floats); `CanonicalizationError(ValueError)` (also raised by `canonical_json` for floats, non-string keys and keys that collide after NFC). Consumed by Tasks 3, 4, 7, 8 and by T09's `freeze_proposal`.

- [ ] **Step 1: Point pytest at the new test package**

Create `tests/plan_c/__init__.py` (empty). In `pyproject.toml` set `testpaths = ["tests/plan_a", "tests/plan_b", "tests/plan_c"]`.

- [ ] **Step 2: Write the failing tests**

Create `tests/plan_c/test_canonical.py`:
```python
"""Canonical JSON v1 (BUILD_SPEC §6, R005): the same logical payload must always hash to the same bytes.

Catches: a serialiser option drifting (key order, separators, escaping), NFC not applied, two keys that collide under
NFC being silently merged, floats or non-finite numbers sneaking into a hashed payload, and duplicate JSON keys being
silently collapsed by the parser.
"""

import json
import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from ops_core.canonical import (
    CANONICALIZATION_VERSION,
    CanonicalizationError,
    canonical_json,
    canonical_sha256,
    parse_json_strict,
    sha256_hex,
)

# Values that can appear in a hashed payload: no floats (integers only, BUILD_SPEC §6), keys are strings. Keys are
# drawn already NFC-normalised so two generated keys never collide under NFC (a collision is an error, tested below).
nfc_keys = st.text(max_size=12).map(lambda s: unicodedata.normalize("NFC", s))
scalars = st.none() | st.booleans() | st.integers(min_value=-(2**63), max_value=2**63 - 1) | st.text(max_size=40)
payloads = st.recursive(
    scalars,
    lambda inner: st.lists(inner, max_size=5) | st.dictionaries(nfc_keys, inner, max_size=5),
    max_leaves=25,
)


def test_version_is_one():
    assert CANONICALIZATION_VERSION == 1


def test_known_bytes_and_hash():
    assert canonical_json({"b": 1, "a": [True, None, "é"]}) == b'{"a":[true,null,"\xc3\xa9"],"b":1}'
    # The reference's test_canonical_hash_order: key order never changes the hash.
    assert canonical_sha256({"a": 2, "b": 1}) == canonical_sha256({"b": 1, "a": 2})
    assert sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@settings(max_examples=200)
@given(payloads)
def test_round_trip_and_key_order_independence(value):
    first = canonical_json(value)
    assert canonical_json(parse_json_strict(first.decode("utf-8"))) == first
    if isinstance(value, dict):
        reordered = dict(reversed(list(value.items())))
        assert canonical_json(reordered) == first


@given(st.text(min_size=1, max_size=20))
def test_strings_are_nfc_normalised(s):
    nfd = unicodedata.normalize("NFD", s)
    assert canonical_json({"k": nfd}) == canonical_json({"k": unicodedata.normalize("NFC", s)})
    assert json.loads(canonical_json({"k": nfd}))["k"] == unicodedata.normalize("NFC", s)


def test_keys_that_collide_under_nfc_are_rejected():
    # The first key is "e" + combining acute (NFD), the second the precomposed "\u00e9" (NFC): two different Python
    # keys that collide after normalisation. Escapes, not literals, so retyping cannot turn both into NFC.
    with pytest.raises(CanonicalizationError, match="key collision after NFC"):
        canonical_json({"e\u0301": 1, "\u00e9": 2})


@pytest.mark.parametrize(
    "bad", [1.5, float("nan"), float("inf"), {"k": 1.0}, [0.0]], ids=["float", "nan", "inf", "nested", "list"]
)
def test_floats_are_rejected(bad):
    with pytest.raises(CanonicalizationError, match="float"):
        canonical_json(bad)


def test_non_string_keys_are_rejected():
    with pytest.raises(CanonicalizationError, match="key"):
        canonical_json({1: "a"})


@pytest.mark.parametrize(
    "text",
    ['{"a": 1, "a": 2}', "NaN", "[Infinity]", '{"a": 1.5}', '{"a": -0.0}'],
    ids=["duplicate-key", "nan", "infinity", "float", "neg-zero"],
)
def test_strict_parser_rejects(text):
    with pytest.raises(CanonicalizationError):
        parse_json_strict(text)


def test_strict_parser_accepts_ints_and_unicode():
    assert parse_json_strict('{"n": 12345678901234567890, "s": "\\u00e9"}') == {"n": 12345678901234567890, "s": "é"}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_canonical.py -q 2>&1 | tr -d '\r' | tail -3`
Expected: collection fails with `ModuleNotFoundError: No module named 'ops_core.canonical'`; the summary reports `1 error`.

- [ ] **Step 4: Write the module**

Create `core/src/ops_core/canonical.py`:
```python
"""Canonical JSON v1 and the payload hash (BUILD_SPEC §6, R005).

The backend hashes proposal payloads and action bodies; the destination recomputes the hash over the bytes it
receives (AM-13). Both sides must therefore produce the same bytes for the same logical value, on every platform.
The rules: UTF-8, sorted keys, compact separators, no ASCII escaping, NFC-normalised strings and keys, integers only
(floats are rejected rather than rounded), and a parser that refuses duplicate keys and non-finite numbers instead of
silently keeping the last key or producing NaN. Two distinct keys that become the same key under NFC are an error,
not a merge: a silent merge would hash a different payload from the one supplied.

Arrays keep the producer's order; this module never sorts them, because some arrays are ordered by meaning. The
producer is therefore responsible for a stable order ("documented stable array order", BUILD_SPEC §6), and
`ops_core.contracts.ProposalPayload` enforces it for the hashed payload: `evidence_refs` sorted ascending by code
point, `source_snapshots` sorted by `evidence_id`.

Timestamps (plan ruling 6): inputs may spell UTC as `Z` or `+00:00`; the hashed form is the one pydantic's JSON mode
emits (`2026-10-05T12:00:00Z`), so only hashed documents (the proposal) require `Z`; `manual-proposal`, `model-pins`
and the `get_recent_alerts` input accept `Z` or `+00:00`.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Final

CANONICALIZATION_VERSION: Final = 1


class CanonicalizationError(ValueError):
    """The value cannot be part of a hashed payload (float, non-string key, key collision, duplicate, non-finite)."""


def _normalize(value: object, path: str = "$") -> object:
    """Return a copy with NFC strings and keys and only JSON-safe scalars; raise on anything the hash must never see."""
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        raise CanonicalizationError(f"float at {path}: canonical payloads use integers only")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list | tuple):
        return [_normalize(item, f"{path}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"non-string key {key!r} at {path}")
            nfc = unicodedata.normalize("NFC", key)
            if nfc in out:
                raise CanonicalizationError(f"key collision after NFC at {path}: {key!r}")
            out[nfc] = _normalize(item, f"{path}.{key}")
        return out
    raise CanonicalizationError(f"unsupported type {type(value).__name__} at {path}")


def canonical_json(value: object) -> bytes:
    """Serialise `value` to canonical JSON v1 bytes.

    Object keys are sorted; arrays keep the order the caller gives them, so the caller must supply a stable order
    (see the module docstring).

    Raises:
        CanonicalizationError: a float, a non-string key, two keys equal after NFC, or an unsupported type.
    """
    return json.dumps(
        _normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 of `data`."""
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: object) -> str:
    """The `payload_sha256` of a value: SHA-256 over its canonical bytes."""
    return sha256_hex(canonical_json(value))


def _reject_constant(name: str) -> object:
    raise CanonicalizationError(f"non-finite number {name} is not allowed")


def _reject_float(text: str) -> object:
    raise CanonicalizationError(f"float literal {text} is not allowed: canonical payloads use integers only")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, item in pairs:
        if key in out:
            raise CanonicalizationError(f"duplicate key {key!r}")
        out[key] = item
    return out


def parse_json_strict(text: str) -> object:
    """Parse JSON the way the hash requires: duplicate keys, NaN/Infinity and float literals are errors."""
    try:
        return json.loads(
            text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant, parse_float=_reject_float
        )
    except json.JSONDecodeError as exc:
        raise CanonicalizationError(f"invalid JSON: {exc}") from exc
```

- [ ] **Step 5: Run the tests, mypy and the full check**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_canonical.py -q 2>&1 | tr -d '\r' | tail -2`
Expected: `17 passed` (5 plain tests + 2 Hypothesis tests + 5 float ids + 5 parser ids).

Run: `uv run python -m mypy core/src 2>&1 | tr -d '\r' | tail -1`
Expected: `Success: no issues found in 3 source files`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tr -d '\r' | tail -3`
Expected: the pytest summary reports `109 passed` and `11 skipped`, then `CHECK: GREEN`.

- [ ] **Step 6: Commit**

```bash
git add core/src/ops_core/canonical.py tests/plan_c pyproject.toml
git commit -m "T07: canonical JSON v1 with NFC, integer-only values and a strict parser"
```

---

### Task 2: T07b — Run states, reasons and the transition table

**Files:**
- Create: `core/src/ops_core/states.py`, `tests/plan_c/test_states.py`

**Interfaces:**
- Produces: `RunState` (17), `Reason` (10), `AttemptState` (4), `Intent` (2), `Performer` (12 definer functions that transition), `TransitionRow(src: RunState | None, dst: RunState, performer: Performer, reasons: frozenset[Reason], note: str)`, `TRANSITIONS: tuple[TransitionRow, ...]` (42 rows, 38 distinct `(src, dst)` pairs), `ACTIVE_STATES`, `TERMINAL_STATES`, `PRE_GRANT_STATES`, `WORKER_TRANSITION_TARGETS`, `IllegalTransition(ValueError)`, `require_transition(src, dst, performer, reason=None) -> TransitionRow`, `revision_allowed(src, conversation_has_other_active_run) -> None` (raises `SlotOccupied`), `freeze_allowed(intent) -> None` (raises `AnswerOnlyRun`; a separate guard because intent is a run field, not a state). The `state_version` rule (bump only on a transition) is SQL and belongs to T09. Consumed by Task 3/4 and by T08 (every transition routed through this table) and T09 (`transition_run` mirrors it in SQL).

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_c/test_states.py`:
```python
"""The run state machine is one table in core (AM-10, AM-20.3 performers, R082, R120, R114, R125).

Catches: a transition added or removed by accident, the wrong function performing a transition (the worker reaching a
post-grant state), a reason enum drifting, a revision taken while another run holds the conversation slot, and a
read-only run producing a proposal.
"""

import itertools

import pytest
from ops_core.states import (
    ACTIVE_STATES,
    PRE_GRANT_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    WORKER_TRANSITION_TARGETS,
    AnswerOnlyRun,
    AttemptState,
    IllegalTransition,
    Intent,
    Performer,
    Reason,
    RunState,
    SlotOccupied,
    freeze_allowed,
    require_transition,
    revision_allowed,
)

S = RunState
P = Performer

# Every allowed (source, target) pair, from AM-10's table over BUILD_SPEC §8 (rulings 1, 4 and 5 in the plan header).
ALLOWED: dict[tuple[RunState | None, RunState], set[Performer]] = {
    (None, S.QUEUED): {P.CREATE_RUN},
    (S.QUEUED, S.RETRIEVING): {P.TRANSITION_RUN},
    (S.QUEUED, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.AWAITING_INPUT, S.QUEUED): {P.TRANSITION_RUN},
    (S.AWAITING_INPUT, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.RETRIEVING, S.DRAFTING): {P.TRANSITION_RUN},
    (S.RETRIEVING, S.AWAITING_INPUT): {P.TRANSITION_RUN},
    (S.RETRIEVING, S.INSUFFICIENT_EVIDENCE): {P.TRANSITION_RUN},
    (S.RETRIEVING, S.FAILED): {P.TRANSITION_RUN},
    (S.RETRIEVING, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.DRAFTING, S.AWAITING_INPUT): {P.TRANSITION_RUN},
    (S.DRAFTING, S.ANSWERED): {P.TRANSITION_RUN},
    (S.DRAFTING, S.INSUFFICIENT_EVIDENCE): {P.TRANSITION_RUN},
    (S.DRAFTING, S.FAILED): {P.TRANSITION_RUN},
    (S.DRAFTING, S.AWAITING_APPROVAL): {P.FREEZE_PROPOSAL},
    (S.DRAFTING, S.BLOCKED_REVIEW): {P.FREEZE_PROPOSAL},
    (S.DRAFTING, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.AWAITING_APPROVAL, S.APPROVED): {P.RECORD_DECISION},
    (S.AWAITING_APPROVAL, S.REJECTED): {P.RECORD_DECISION},
    (S.AWAITING_APPROVAL, S.BLOCKED_REVIEW): {P.RECORD_DECISION, P.EXPIRE_PROPOSAL},
    (S.AWAITING_APPROVAL, S.QUEUED): {P.CREATE_REVISION},
    (S.AWAITING_APPROVAL, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.APPROVED, S.EXECUTING): {P.GRANT_EXECUTION},
    (S.APPROVED, S.BLOCKED_REVIEW): {P.GRANT_EXECUTION, P.EXPIRE_PROPOSAL},
    (S.APPROVED, S.QUEUED): {P.CREATE_REVISION},
    (S.APPROVED, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.BLOCKED_REVIEW, S.QUEUED): {P.CREATE_REVISION},
    (S.BLOCKED_REVIEW, S.CANCELLED): {P.REQUEST_CANCEL},
    (S.EXECUTING, S.OUTCOME_UNKNOWN): {P.MARK_UNKNOWN},
    (S.EXECUTING, S.SUCCEEDED): {P.RECORD_OUTCOME},
    (S.EXECUTING, S.FAILED): {P.RECORD_OUTCOME},
    (S.EXECUTING, S.ESCALATED): {P.ESCALATE_RUN, P.RECORD_OUTCOME},
    (S.OUTCOME_UNKNOWN, S.SUCCEEDED): {P.RECORD_OUTCOME},
    (S.OUTCOME_UNKNOWN, S.FAILED): {P.RECORD_OUTCOME},
    (S.OUTCOME_UNKNOWN, S.ESCALATED): {P.ESCALATE_RUN, P.RECORD_OUTCOME},
    (S.ESCALATED, S.SUCCEEDED): {P.RECORD_OUTCOME},
    (S.ESCALATED, S.FAILED): {P.RECORD_OUTCOME},
    (S.ESCALATED, S.ABANDONED_UNVERIFIED): {P.RESOLVE_ESCALATION},
}


def test_vocabularies_are_exactly_the_spec():
    assert len(RunState) == 17 and len(Reason) == 10 and len(AttemptState) == 4 and len(Intent) == 2
    assert {r.value for r in Reason} == {
        "cancelled_before_send",
        "aborted_no_commit",
        "rejected",
        "asset_action_unresolved",
        "asset_incident_exists",
        "expired",
        "stale_evidence",
        "authority_revoked",
        "conflict",
        "escalation_deadline",
    }
    assert ACTIVE_STATES == frozenset(
        {
            S.QUEUED,
            S.AWAITING_INPUT,
            S.RETRIEVING,
            S.DRAFTING,
            S.AWAITING_APPROVAL,
            S.APPROVED,
            S.EXECUTING,
            S.OUTCOME_UNKNOWN,
        }
    )
    assert TERMINAL_STATES == frozenset(
        {S.REJECTED, S.CANCELLED, S.ANSWERED, S.INSUFFICIENT_EVIDENCE, S.SUCCEEDED, S.FAILED, S.ABANDONED_UNVERIFIED}
    )
    assert set(S) - ACTIVE_STATES - TERMINAL_STATES == {S.BLOCKED_REVIEW, S.ESCALATED}  # live but not slot-holding


def test_table_matches_the_allowed_set_exactly():
    table = {}
    for row in TRANSITIONS:
        table.setdefault((row.src, row.dst), set()).add(row.performer)
    assert table == ALLOWED
    assert len(TRANSITIONS) == 42 and len(table) == 38


def test_every_pair_is_decided_by_the_table():
    """Exhaustive (R082): 18 sources (17 states + creation) x 17 targets x 12 performers.

    A move succeeds iff the table lists that performer for that pair; every other performer, and every performer on a
    pair the table does not list, is refused.
    """
    for src, dst, p in itertools.product([None, *S], S, P):
        if p in ALLOWED.get((src, dst), set()):
            row = next(r for r in TRANSITIONS if (r.src, r.dst, r.performer) == (src, dst, p))
            reason = min(row.reasons) if row.reasons else None  # rows that must say why get a reason
            assert require_transition(src, dst, p, reason).dst is dst
        else:
            with pytest.raises(IllegalTransition):
                require_transition(src, dst, p)


def test_terminal_states_have_no_outgoing_rows():
    assert not [row for row in TRANSITIONS if row.src in TERMINAL_STATES]


def test_wrong_performer_is_rejected():
    with pytest.raises(IllegalTransition, match="performer"):
        require_transition(S.EXECUTING, S.SUCCEEDED, P.TRANSITION_RUN)


def test_worker_targets_exclude_post_grant_states():
    """AM-20.3 transition_run: the worker never reaches a post-grant state and never SUCCEEDED."""
    assert WORKER_TRANSITION_TARGETS == frozenset(
        {S.RETRIEVING, S.DRAFTING, S.AWAITING_INPUT, S.INSUFFICIENT_EVIDENCE, S.FAILED, S.ANSWERED, S.QUEUED}
    )
    for row in TRANSITIONS:
        if row.performer is P.TRANSITION_RUN:
            assert row.dst in WORKER_TRANSITION_TARGETS and row.src in PRE_GRANT_STATES


def test_reasons_are_required_where_the_spec_names_them():
    assert require_transition(S.DRAFTING, S.BLOCKED_REVIEW, P.FREEZE_PROPOSAL, Reason.ASSET_INCIDENT_EXISTS).reasons
    with pytest.raises(IllegalTransition, match="reason"):
        require_transition(S.DRAFTING, S.BLOCKED_REVIEW, P.FREEZE_PROPOSAL)  # a blocked review always says why
    with pytest.raises(IllegalTransition, match="reason"):
        # Expiry is a grant-time or decision-time refusal; at freeze only the asset guard blocks (AM-10 table).
        require_transition(S.DRAFTING, S.BLOCKED_REVIEW, P.FREEZE_PROPOSAL, Reason.EXPIRED)
    assert require_transition(S.AWAITING_APPROVAL, S.BLOCKED_REVIEW, P.RECORD_DECISION, Reason.EXPIRED)
    with pytest.raises(IllegalTransition, match="reason"):
        # record_decision blocks only through lazy expiry.
        require_transition(S.AWAITING_APPROVAL, S.BLOCKED_REVIEW, P.RECORD_DECISION, Reason.STALE_EVIDENCE)
    assert require_transition(S.APPROVED, S.BLOCKED_REVIEW, P.GRANT_EXECUTION, Reason.STALE_EVIDENCE)
    with pytest.raises(IllegalTransition, match="reason"):
        require_transition(S.APPROVED, S.BLOCKED_REVIEW, P.EXPIRE_PROPOSAL, Reason.CONFLICT)  # expiry says 'expired'
    assert require_transition(S.EXECUTING, S.FAILED, P.RECORD_OUTCOME, Reason.CANCELLED_BEFORE_SEND)
    with pytest.raises(IllegalTransition, match="reason"):
        require_transition(S.QUEUED, S.RETRIEVING, P.TRANSITION_RUN, Reason.EXPIRED)  # no reason on plain progress


def test_revision_needs_a_free_slot():
    """R120: a revision from BLOCKED_REVIEW re-takes the slot, so another active run in the conversation is a 409."""
    revision_allowed(S.BLOCKED_REVIEW, conversation_has_other_active_run=False)
    with pytest.raises(SlotOccupied):
        revision_allowed(S.BLOCKED_REVIEW, conversation_has_other_active_run=True)
    revision_allowed(S.APPROVED, conversation_has_other_active_run=False)
    with pytest.raises(IllegalTransition):
        revision_allowed(S.EXECUTING, conversation_has_other_active_run=False)


def test_answer_only_runs_cannot_freeze():
    """R114: the answer-only intent ends ANSWERED; freeze_proposal refuses it."""
    freeze_allowed(Intent.INVESTIGATE)
    with pytest.raises(AnswerOnlyRun):
        freeze_allowed(Intent.ANSWER_ONLY)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_states.py -q 2>&1 | tr -d '\r' | tail -3`
Expected: collection fails with `ModuleNotFoundError: No module named 'ops_core.states'`; `1 error`.

- [ ] **Step 3: Write the module**

Create `core/src/ops_core/states.py`:
```python
"""The run state machine as data (AM-10), with the function that performs each transition (AM-20.3).

One table, one enforcement function (R082). Services never compare state strings themselves: the worker's
`transition_run`, the API's decision/revision/cancel paths and the MCP servers' grant/outcome paths all ask this
module whether a move is legal, who may make it, and whether it must carry a reason. T09 mirrors the same rows in
SQL; the Python table is the one tests enumerate.

Each row's note names the spec section that licenses it (`AM-10 table`, `AM-20.3 performers`, ...) rather than a
line number, so the citation survives edits to the spec file.

TODO(T09): R082 also asks that a disallowed transition be *logged*; `require_transition` raises, and the SQL
`transition_run` mirror records the refusal where the audit trail lives.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class RunState(StrEnum):
    """The 17 run states (BUILD_SPEC §8 plus AM-10's ESCALATED and ABANDONED_UNVERIFIED)."""

    QUEUED = "QUEUED"
    AWAITING_INPUT = "AWAITING_INPUT"
    RETRIEVING = "RETRIEVING"
    DRAFTING = "DRAFTING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    SUCCEEDED = "SUCCEEDED"
    ANSWERED = "ANSWERED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    FAILED = "FAILED"
    BLOCKED_REVIEW = "BLOCKED_REVIEW"
    # AM-10: an unresolved action after a conflict or the escalation deadline; frees the slot, keeps the asset guard.
    ESCALATED = "ESCALATED"
    ABANDONED_UNVERIFIED = "ABANDONED_UNVERIFIED"  # AM-10: operator acknowledgement; never claims success or failure


class Reason(StrEnum):
    """The one reason enum for terminal and blocked states (AM-10 "Reasons")."""

    CANCELLED_BEFORE_SEND = "cancelled_before_send"
    ABORTED_NO_COMMIT = "aborted_no_commit"
    REJECTED = "rejected"
    ASSET_ACTION_UNRESOLVED = "asset_action_unresolved"
    ASSET_INCIDENT_EXISTS = "asset_incident_exists"
    EXPIRED = "expired"
    STALE_EVIDENCE = "stale_evidence"
    AUTHORITY_REVOKED = "authority_revoked"
    CONFLICT = "conflict"
    ESCALATION_DEADLINE = "escalation_deadline"


class AttemptState(StrEnum):
    """Append-only attempt states (AM-13); the latest row by seq is the state."""

    INTENT = "INTENT"
    SENT = "SENT"
    ABORT_REQUESTED = "ABORT_REQUESTED"
    RESOLVED = "RESOLVED"


class Intent(StrEnum):
    """Requester-asserted run intent, set by the admission router (AM-10, AM-16)."""

    INVESTIGATE = "investigate"
    ANSWER_ONLY = "answer_only"


class Performer(StrEnum):
    """The definer function that owns a transition (AM-20.3 "who performs which transition")."""

    CREATE_RUN = "create_run"
    TRANSITION_RUN = "transition_run"
    FREEZE_PROPOSAL = "freeze_proposal"
    RECORD_DECISION = "record_decision"
    EXPIRE_PROPOSAL = "expire_proposal"
    CREATE_REVISION = "create_revision"
    REQUEST_CANCEL = "request_cancel"
    GRANT_EXECUTION = "grant_execution"
    MARK_UNKNOWN = "mark_unknown"
    RECORD_OUTCOME = "record_outcome"
    ESCALATE_RUN = "escalate_run"
    RESOLVE_ESCALATION = "resolve_escalation"


class IllegalTransition(ValueError):
    """The table has no row for this (source, target, performer, reason) combination."""


class SlotOccupied(IllegalTransition):
    """R120: the conversation already holds another active run; the revision gets 409 SLOT_OCCUPIED."""


class AnswerOnlyRun(IllegalTransition):
    """R114: a run with intent answer_only can never produce a proposal."""


@dataclass(frozen=True)
class TransitionRow:
    """One allowed move: source, target, the function that performs it, and the reasons it may carry."""

    src: RunState | None  # None is creation (∅ → QUEUED, AM-10 table)
    dst: RunState
    performer: Performer
    reasons: frozenset[Reason]  # empty: no reason allowed; otherwise the reason is required and must be one of these
    note: str  # the spec section that justifies the row


S = RunState
P = Performer
R = Reason
# The asset guard is the only refusal at freeze (AM-10 table, DRAFTING row; AM-13 asset guard).
_ASSET_GUARD = frozenset({R.ASSET_ACTION_UNRESOLVED, R.ASSET_INCIDENT_EXISTS})
# The final gate can refuse for any of these (AM-10 table, APPROVED row; AM-20.3 grant_execution).
_GRANT_REFUSAL = frozenset(
    {R.ASSET_ACTION_UNRESOLVED, R.ASSET_INCIDENT_EXISTS, R.STALE_EVIDENCE, R.AUTHORITY_REVOKED, R.EXPIRED}
)
_EXPIRED = frozenset({R.EXPIRED})
_FAILED = frozenset({R.CANCELLED_BEFORE_SEND, R.ABORTED_NO_COMMIT, R.REJECTED, R.EXPIRED})  # plan ruling 2
_ESCALATED = frozenset({R.CONFLICT, R.ESCALATION_DEADLINE})
_NONE: frozenset[Reason] = frozenset()


def _rows() -> tuple[TransitionRow, ...]:
    rows: list[TransitionRow] = [
        TransitionRow(None, S.QUEUED, P.CREATE_RUN, _NONE, "AM-10 table: creation only via create_run")
    ]
    # Worker progress: pre-grant states only, never SUCCEEDED (AM-20.3 transition_run; ruling 4 drops QUEUED →
    # AWAITING_INPUT).
    for src, dst in [
        (S.QUEUED, S.RETRIEVING),
        (S.AWAITING_INPUT, S.QUEUED),
        (S.RETRIEVING, S.DRAFTING),
        (S.RETRIEVING, S.AWAITING_INPUT),
        (S.RETRIEVING, S.INSUFFICIENT_EVIDENCE),
        (S.DRAFTING, S.AWAITING_INPUT),
        (S.DRAFTING, S.ANSWERED),
        (S.DRAFTING, S.INSUFFICIENT_EVIDENCE),
    ]:
        rows.append(TransitionRow(src, dst, P.TRANSITION_RUN, _NONE, "AM-20.3 transition_run"))
    # Ruling 8: FAILED on exhausted infrastructure policy carries no reason; no reason value fits it, and the
    # run.failed event's message says why.
    for src in (S.RETRIEVING, S.DRAFTING):
        rows.append(TransitionRow(src, S.FAILED, P.TRANSITION_RUN, _NONE, "BUILD_SPEC §8; AM-20.3 transition_run"))
    rows.append(TransitionRow(S.DRAFTING, S.AWAITING_APPROVAL, P.FREEZE_PROPOSAL, _NONE, "AM-20.3 freeze_proposal"))
    rows.append(TransitionRow(S.DRAFTING, S.BLOCKED_REVIEW, P.FREEZE_PROPOSAL, _ASSET_GUARD, "AM-10 asset guard"))
    rows.append(TransitionRow(S.AWAITING_APPROVAL, S.APPROVED, P.RECORD_DECISION, _NONE, "AM-20.3 record_decision"))
    rows.append(
        TransitionRow(
            S.AWAITING_APPROVAL, S.REJECTED, P.RECORD_DECISION, frozenset({R.REJECTED}), "AM-20.3 record_decision"
        )
    )
    # record_decision's only blocking path is lazy expiry (AM-20.3 record_decision; AM-10 table).
    rows.append(TransitionRow(S.AWAITING_APPROVAL, S.BLOCKED_REVIEW, P.RECORD_DECISION, _EXPIRED, "AM-10 lazy expiry"))
    for src in (S.AWAITING_APPROVAL, S.APPROVED):
        rows.append(TransitionRow(src, S.BLOCKED_REVIEW, P.EXPIRE_PROPOSAL, _EXPIRED, "AM-20.3 expire_proposal"))
    # Revisions (AM-20.3 create_revision; ruling 1 includes AWAITING_APPROVAL); the slot rule is revision_allowed.
    for src in (S.AWAITING_APPROVAL, S.APPROVED, S.BLOCKED_REVIEW):
        rows.append(TransitionRow(src, S.QUEUED, P.CREATE_REVISION, _NONE, "AM-20.3 create_revision"))
    rows.append(TransitionRow(S.APPROVED, S.EXECUTING, P.GRANT_EXECUTION, _NONE, "AM-20.3 grant_execution"))
    rows.append(TransitionRow(S.APPROVED, S.BLOCKED_REVIEW, P.GRANT_EXECUTION, _GRANT_REFUSAL, "AM-10 table"))
    # Cancel from any pre-grant non-terminal state (AM-20.3 performers; ruling 5 includes BLOCKED_REVIEW).
    for src in (
        S.QUEUED,
        S.AWAITING_INPUT,
        S.RETRIEVING,
        S.DRAFTING,
        S.AWAITING_APPROVAL,
        S.APPROVED,
        S.BLOCKED_REVIEW,
    ):
        rows.append(TransitionRow(src, S.CANCELLED, P.REQUEST_CANCEL, _NONE, "AM-20.3 request_cancel"))
    # After the grant (AM-13 attempt protocol; AM-20.3 performers).
    rows.append(TransitionRow(S.EXECUTING, S.OUTCOME_UNKNOWN, P.MARK_UNKNOWN, _NONE, "AM-20.3 mark_unknown"))
    for src in (S.EXECUTING, S.OUTCOME_UNKNOWN, S.ESCALATED):
        rows.append(TransitionRow(src, S.SUCCEEDED, P.RECORD_OUTCOME, _NONE, "AM-20.3 record_outcome: receipt"))
        rows.append(TransitionRow(src, S.FAILED, P.RECORD_OUTCOME, _FAILED, "AM-20.3 record_outcome: tombstone"))
    for src in (S.EXECUTING, S.OUTCOME_UNKNOWN):
        rows.append(TransitionRow(src, S.ESCALATED, P.ESCALATE_RUN, _ESCALATED, "AM-20.3 escalate_run"))
        rows.append(
            TransitionRow(src, S.ESCALATED, P.RECORD_OUTCOME, frozenset({R.CONFLICT}), "AM-20.3 record_outcome")
        )
    rows.append(TransitionRow(S.ESCALATED, S.ABANDONED_UNVERIFIED, P.RESOLVE_ESCALATION, _NONE, "AM-10 operator CLI"))
    return tuple(rows)


TRANSITIONS: Final[tuple[TransitionRow, ...]] = _rows()

# AM-10 "Active states": the states that hold the conversation slot.
ACTIVE_STATES: Final = frozenset(
    {
        S.QUEUED,
        S.AWAITING_INPUT,
        S.RETRIEVING,
        S.DRAFTING,
        S.AWAITING_APPROVAL,
        S.APPROVED,
        S.EXECUTING,
        S.OUTCOME_UNKNOWN,
    }
)
TERMINAL_STATES: Final = frozenset(
    {S.REJECTED, S.CANCELLED, S.ANSWERED, S.INSUFFICIENT_EVIDENCE, S.SUCCEEDED, S.FAILED, S.ABANDONED_UNVERIFIED}
)  # AM-10 table, last row
PRE_GRANT_STATES: Final = frozenset(
    {S.QUEUED, S.AWAITING_INPUT, S.RETRIEVING, S.DRAFTING, S.AWAITING_APPROVAL, S.APPROVED, S.BLOCKED_REVIEW}
)
WORKER_TRANSITION_TARGETS: Final = frozenset(
    {S.RETRIEVING, S.DRAFTING, S.AWAITING_INPUT, S.INSUFFICIENT_EVIDENCE, S.FAILED, S.ANSWERED, S.QUEUED}
)  # AM-20.3 transition_run

_INDEX: Final[dict[tuple[RunState | None, RunState, Performer], TransitionRow]] = {
    (row.src, row.dst, row.performer): row for row in TRANSITIONS
}


def require_transition(
    src: RunState | None, dst: RunState, performer: Performer, reason: Reason | None = None
) -> TransitionRow:
    """Return the table row for this move.

    Raises:
        IllegalTransition: the pair is not in the table, the performer may not make it, or the reason is missing,
            not allowed, or given where none is recorded (the message names which).
    """
    row = _INDEX.get((src, dst, performer))
    if row is None:
        if any(r.src == src and r.dst == dst for r in TRANSITIONS):
            raise IllegalTransition(f"{src} -> {dst}: performer {performer} may not make this transition")
        raise IllegalTransition(f"{src} -> {dst} is not in the transition table")
    if row.reasons and reason not in row.reasons:
        raise IllegalTransition(
            f"{src} -> {dst} by {performer}: reason must be one of {sorted(row.reasons)}, got {reason}"
        )
    if not row.reasons and reason is not None:
        raise IllegalTransition(f"{src} -> {dst} by {performer}: no reason is recorded on this transition")
    return row


def revision_allowed(src: RunState, *, conversation_has_other_active_run: bool) -> None:
    """Refuse a revision that the table forbids or that would give the conversation a second active run.

    R120 (AM-10 BLOCKED_REVIEW row): a revision re-takes the slot, so it is refused while another run in the
    conversation is active.

    Raises:
        IllegalTransition: `src` cannot be revised.
        SlotOccupied: another run in the conversation holds the slot.
    """
    require_transition(src, S.QUEUED, P.CREATE_REVISION)
    if conversation_has_other_active_run:
        raise SlotOccupied(f"revision from {src} refused: the conversation already holds an active run")


def freeze_allowed(intent: Intent) -> None:
    """Refuse a freeze for a read-only run (R114, AM-10 "The ANSWERED path").

    This is a separate guard, not a column of the table, because intent is a run field set at creation
    (`RunRequestFields`, AM-10 "Requester-asserted fields"), not a state: DRAFTING → AWAITING_APPROVAL is a legal
    move for an investigate run and the same move is refused for an answer_only run. T09's `freeze_proposal` calls
    both this guard and the table.

    Raises:
        AnswerOnlyRun: the run's intent is answer_only.
    """
    if intent is Intent.ANSWER_ONLY:
        raise AnswerOnlyRun("freeze_proposal refuses runs with intent answer_only")
```

- [ ] **Step 4: Run the tests, mypy and the full check**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_states.py -q 2>&1 | tr -d '\r' | tail -2`
Expected: `9 passed`.

Run: `uv run python -m mypy core/src 2>&1 | tr -d '\r' | tail -1`
Expected: `Success: no issues found in 4 source files`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tr -d '\r' | tail -3`
Expected: `118 passed`, `11 skipped`, `CHECK: GREEN`.

- [ ] **Step 5: Commit**

```bash
git add core/src/ops_core/states.py tests/plan_c/test_states.py
git commit -m "T07: run states, reasons and the transition table with performers (AM-10, AM-20.3)"
```

---

### Task 3: T07c — Jobs, routes, outcomes and the tombstone

**Files:**
- Create: `core/src/ops_core/jobs.py`, `core/src/ops_core/routing.py`, `core/src/ops_core/outcomes.py`, `tests/plan_c/test_jobs_routes_outcomes.py`

**Interfaces:**
- Produces (`jobs.py`): `JobType` (8), `Tool` (6), `Server` (`read`/`write`), `JobRule(type, allowed_tools, run_states, server, created_by, dedup_pattern)` (the job-type dimension of AM-15's allowlist; run and attempt state are applied at call time, `TODO(T15)`), `JOB_RULES: dict[JobType, JobRule]`, `dedup_key(job_type, **ids) -> str`, `server_for(job_type) -> Server | None`, `RECOVER_CADENCE = (300, 3600, 48)` (first-hour interval s, later interval s, cap). (`outcomes.py`): `DestinationState` (COMMITTED/ABORTED/REJECTED), `ToolOutcome` (SUCCEEDED/FAILED_NO_COMMIT/UNKNOWN/CONFLICT), `Receipt`, `Tombstone`, `ActionOutcome` (validators: SUCCEEDED ⇔ receipt; FAILED_NO_COMMIT ⇒ tombstone + reason ∈ {aborted_no_commit, cancelled_before_send, rejected, expired}; UNKNOWN/CONFLICT ⇒ no receipt, no tombstone), `FAILED_NO_COMMIT_REASONS`, `outcome_from_destination(state, *, sent: bool, cancel_requested: bool) -> tuple[ToolOutcome, Reason | None]` (COMMITTED → SUCCEEDED; REJECTED → `rejected`; ABORTED before SENT → `cancelled_before_send` or `expired`; ABORTED after SENT → `aborted_no_commit`), `EventType` (27 values = BS §15's 13 + AM-14's 14), `EventSource`, `DESTINATION_EVIDENCE`, `event_rules_ok(type, source, payload) -> None` raising `EventRuleViolation` (incl. destination evidence only from `source=destination`, `action.failed` with a reason). (`routing.py`): `AdmissionRoute` (6), `GraphRoute` (10), `ModelRoute` (`fake`, `qwen3:8b`), `RunManifest`.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_c/test_jobs_routes_outcomes.py`:
```python
"""Job types, tools, routes and the outcome vocabulary are the spec's tables (AM-13, AM-14, AM-15, AM-16, AM-20.4).

Catches: a tool allowed for the wrong job type (a read handle reaching create_incident), a dedup key format drifting
(two jobs for one proposal), an outcome that claims success without a receipt, a tombstone with the wrong state, and an
event that asserts an outcome from the wrong source (R083's model_summary probe, in code).
"""

import uuid
from datetime import UTC, datetime

import pytest
from ops_core.jobs import JOB_RULES, RECOVER_CADENCE, JobType, Server, Tool, dedup_key, server_for
from ops_core.outcomes import (
    ActionOutcome,
    DestinationState,
    EventRuleViolation,
    EventSource,
    EventType,
    Receipt,
    Tombstone,
    ToolOutcome,
    event_rules_ok,
    outcome_from_destination,
)
from ops_core.routing import AdmissionRoute, GraphRoute, ModelRoute, RunManifest
from ops_core.states import Reason, RunState
from pydantic import ValidationError

ACTION = uuid.UUID("00000000-0000-4000-8000-000000000010")
SHA = "9d5c1fb0f7ef65456f4ccf76396564e6290ecd530e58d2b32024e64079134cf7"
AT = datetime(2026, 10, 8, tzinfo=UTC)
READ_TOOLS = {Tool.GET_ASSET_STATUS, Tool.GET_RECENT_ALERTS, Tool.SEARCH_PROCEDURES}


def test_job_rules_match_am15():
    assert len(JobType) == 8 and len(Tool) == 6
    assert JOB_RULES[JobType.INVESTIGATE].allowed_tools == READ_TOOLS
    assert JOB_RULES[JobType.RESUME_INPUT].allowed_tools == READ_TOOLS
    assert JOB_RULES[JobType.EXECUTE].allowed_tools == {Tool.CREATE_INCIDENT}
    assert JOB_RULES[JobType.RECOVER].allowed_tools == {
        Tool.CREATE_INCIDENT,
        Tool.GET_INCIDENT_RECEIPT,
        Tool.ABORT_INCIDENT,
    }
    for maintenance in (
        JobType.EXPIRE_PROPOSALS,
        JobType.SYNC_MEMBERSHIPS,
        JobType.SWEEP_WAKEUPS,
        JobType.DELIVER_OUTBOX,
    ):
        assert JOB_RULES[maintenance].allowed_tools == set() and JOB_RULES[maintenance].run_states == frozenset()
    assert JOB_RULES[JobType.EXECUTE].run_states == {RunState.APPROVED, RunState.EXECUTING}
    assert JOB_RULES[JobType.RECOVER].run_states == {
        RunState.EXECUTING,
        RunState.OUTCOME_UNKNOWN,
        RunState.ESCALATED,
        RunState.ABANDONED_UNVERIFIED,
    }


def test_handles_bind_to_one_server():
    """R131: investigate/resume_input handles are read handles; execute/recover are write handles."""
    assert server_for(JobType.INVESTIGATE) is Server.READ and server_for(JobType.RESUME_INPUT) is Server.READ
    assert server_for(JobType.EXECUTE) is Server.WRITE and server_for(JobType.RECOVER) is Server.WRITE
    assert server_for(JobType.DELIVER_OUTBOX) is None


def test_dedup_keys_follow_am20_4():
    run = uuid.UUID("00000000-0000-4000-8000-000000000003")
    assert dedup_key(JobType.INVESTIGATE, run_id=run, revision=2) == f"{run}:2"
    assert dedup_key(JobType.RESUME_INPUT, run_id=run, clarification_event_id=ACTION) == f"{run}:{ACTION}"
    assert dedup_key(JobType.EXECUTE, proposal_id=ACTION) == str(ACTION)
    assert dedup_key(JobType.RECOVER, action_id=ACTION, trigger="timeout") == f"{ACTION}:timeout"
    assert (
        dedup_key(JobType.RECOVER, action_id=ACTION, trigger="sweep:2026-10-08T01:05")
        == f"{ACTION}:sweep:2026-10-08T01:05"
    )
    assert dedup_key(JobType.EXPIRE_PROPOSALS, minute_bucket="2026-10-08T01:05") == "expire_proposals:2026-10-08T01:05"
    with pytest.raises(ValueError, match="trigger"):
        dedup_key(JobType.RECOVER, action_id=ACTION, trigger="manual")
    with pytest.raises(ValueError, match="revision"):
        dedup_key(JobType.INVESTIGATE, run_id=run)
    assert RECOVER_CADENCE == (300, 3600, 48)


def test_outcome_vocabulary_and_mapping():
    assert {s.value for s in DestinationState} == {"COMMITTED", "ABORTED", "REJECTED"}
    assert {s.value for s in ToolOutcome} == {"SUCCEEDED", "FAILED_NO_COMMIT", "UNKNOWN", "CONFLICT"}
    failed = ToolOutcome.FAILED_NO_COMMIT
    for sent in (False, True):
        for cancel in (False, True):
            assert outcome_from_destination(DestinationState.COMMITTED, sent=sent, cancel_requested=cancel) == (
                ToolOutcome.SUCCEEDED,
                None,
            )
            assert outcome_from_destination(DestinationState.REJECTED, sent=sent, cancel_requested=cancel) == (
                failed,
                Reason.REJECTED,
            )
            # After SENT a fresh ABORTED tombstone proves only "no commit", whatever triggered the abort (AM-13).
            if sent:
                assert outcome_from_destination(DestinationState.ABORTED, sent=True, cancel_requested=cancel) == (
                    failed,
                    Reason.ABORTED_NO_COMMIT,
                )
    # From INTENT (never sent) the abort was either a cancel or the dispatch deadline (AM-13 recovery table).
    assert outcome_from_destination(DestinationState.ABORTED, sent=False, cancel_requested=True) == (
        failed,
        Reason.CANCELLED_BEFORE_SEND,
    )
    assert outcome_from_destination(DestinationState.ABORTED, sent=False, cancel_requested=False) == (
        failed,
        Reason.EXPIRED,
    )


def test_tombstone_shape():
    t = Tombstone(
        action_id=ACTION,
        state=DestinationState.ABORTED,
        payload_sha256=SHA,
        reason="cancelled_before_send",
        decided_at=AT,
    )
    assert t.state is DestinationState.ABORTED
    with pytest.raises(ValidationError):
        Tombstone(
            action_id=ACTION, state=DestinationState.COMMITTED, payload_sha256=SHA, reason="x", decided_at=AT
        )  # a committed key has a receipt, not a tombstone


def test_action_outcome_agreement():
    receipt = Receipt(receipt_id=ACTION, incident_id="INC-1", committed_at=AT)
    tomb = Tombstone(
        action_id=ACTION, state=DestinationState.REJECTED, payload_sha256=SHA, reason="rejected", decided_at=AT
    )
    ActionOutcome(
        status=ToolOutcome.SUCCEEDED, action_id=ACTION, payload_sha256=SHA, receipt=receipt, tombstone=None, reason=None
    )
    ActionOutcome(
        status=ToolOutcome.FAILED_NO_COMMIT,
        action_id=ACTION,
        payload_sha256=SHA,
        receipt=None,
        tombstone=tomb,
        reason=Reason.REJECTED,
    )
    ActionOutcome(
        status=ToolOutcome.UNKNOWN, action_id=ACTION, payload_sha256=SHA, receipt=None, tombstone=None, reason=None
    )
    for bad in (
        # the reference's outcome-invalid-fake-success: success without a receipt
        {"status": ToolOutcome.SUCCEEDED, "receipt": None, "tombstone": None, "reason": None},
        # outcome-invalid-unknown-receipt: a receipt on UNKNOWN
        {"status": ToolOutcome.UNKNOWN, "receipt": receipt, "tombstone": None, "reason": None},
        # a reason outside the FAILED set
        {"status": ToolOutcome.FAILED_NO_COMMIT, "receipt": None, "tombstone": tomb, "reason": Reason.CONFLICT},
        # FAILED_NO_COMMIT without its tombstone
        {"status": ToolOutcome.FAILED_NO_COMMIT, "receipt": None, "tombstone": None, "reason": Reason.REJECTED},
    ):
        with pytest.raises(ValidationError):
            ActionOutcome(action_id=ACTION, payload_sha256=SHA, **bad)


def test_event_types_and_source_rules():
    assert len(EventType) == 27
    event_rules_ok(EventType.EXPLANATION_READY, EventSource.MODEL_SUMMARY, {"message": "why"})
    with pytest.raises(EventRuleViolation):  # R083 probe: model_summary asserting a status
        event_rules_ok(
            EventType.EXPLANATION_READY, EventSource.MODEL_SUMMARY, {"message": "why", "status": "SUCCEEDED"}
        )
    with pytest.raises(EventRuleViolation):  # the summary payload is closed: message and evidence_refs only
        event_rules_ok(EventType.EXPLANATION_READY, EventSource.MODEL_SUMMARY, {"message": "why", "code": "x"})
    with pytest.raises(EventRuleViolation):  # model_summary may emit nothing else
        event_rules_ok(EventType.ACTION_CONFIRMED, EventSource.MODEL_SUMMARY, {"status": "SUCCEEDED"})
    with pytest.raises(EventRuleViolation):  # action.confirmed needs a receipt and SUCCEEDED
        event_rules_ok(EventType.ACTION_CONFIRMED, EventSource.DESTINATION, {"status": "SUCCEEDED"})
    event_rules_ok(
        EventType.ACTION_CONFIRMED,
        EventSource.DESTINATION,
        {
            "status": "SUCCEEDED",
            "receipt": {"receipt_id": str(ACTION), "incident_id": "INC-1", "committed_at": "2026-10-08T00:00:00Z"},
        },
    )
    with pytest.raises(EventRuleViolation):  # source=destination only on the four destination-evidence types
        event_rules_ok(EventType.ACTION_GRANTED, EventSource.DESTINATION, {"status": "EXECUTING"})
    with pytest.raises(EventRuleViolation):  # late evidence needs an outcome and a receipt or tombstone
        event_rules_ok(EventType.ACTION_LATE_EVIDENCE, EventSource.DESTINATION, {"status": "ABANDONED_UNVERIFIED"})
    with pytest.raises(EventRuleViolation):  # destination evidence never comes from the application
        event_rules_ok(
            EventType.ACTION_CONFIRMED,
            EventSource.APPLICATION,
            {
                "status": "SUCCEEDED",
                "receipt": {"receipt_id": str(ACTION), "incident_id": "INC-1", "committed_at": "x"},
            },
        )
    with pytest.raises(EventRuleViolation):  # action.failed says why (AM-14)
        event_rules_ok(EventType.ACTION_FAILED, EventSource.DESTINATION, {"status": "FAILED"})
    event_rules_ok(EventType.ACTION_FAILED, EventSource.DESTINATION, {"status": "FAILED", "reason": "rejected"})


def test_routes_and_manifest():
    assert {r.value for r in AdmissionRoute} == {
        "investigate",
        "clarification_reply",
        "status_question",
        "readonly_answer",
        "clarify",
        "reject",
    }
    assert {r.value for r in GraphRoute} == {
        "clarify",
        "retrieve",
        "draft",
        "answer_only",
        "abstain",
        "freeze",
        "await_decision",
        "execute",
        "recover",
        "publish",
    }
    assert {r.value for r in ModelRoute} == {"fake", "qwen3:8b"}
    m = RunManifest(
        run_id=ACTION,
        model_route=ModelRoute.FAKE,
        model_digest=None,
        prompt_version="incident-draft-v1",
        corpus_version="fixture-1",
        retrieval_mode="lexical",
    )
    assert m.retrieval_mode == "lexical"
    with pytest.raises(ValidationError):
        RunManifest(
            run_id=ACTION,
            model_route=ModelRoute.QWEN3_8B,
            model_digest=None,
            prompt_version="v1",
            corpus_version="c",
            retrieval_mode="lexical",
        )  # a real model needs its digest
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_jobs_routes_outcomes.py -q 2>&1 | tr -d '\r' | tail -3`
Expected: collection fails with `ModuleNotFoundError: No module named 'ops_core.jobs'`; `1 error`.

- [ ] **Step 3: Write `jobs.py`**

Create `core/src/ops_core/jobs.py`:
```python
"""Job types, their tools, run states, creators and dedup keys (AM-15 table, AM-20.4).

A job is a wake-up; the allowed tools come from the job type (plus run and attempt state at call time), never from the
worker (R131). The dedup key makes "one job per proposal / per clarification / per recovery trigger" a database
uniqueness fact rather than a hope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from ops_core.states import RunState


class Tool(StrEnum):
    """The six MCP tools (AM-15); read tools live on mcp-read, write tools on mcp-write."""

    GET_ASSET_STATUS = "get_asset_status"
    GET_RECENT_ALERTS = "get_recent_alerts"
    SEARCH_PROCEDURES = "search_procedures"
    CREATE_INCIDENT = "create_incident"
    GET_INCIDENT_RECEIPT = "get_incident_receipt"
    ABORT_INCIDENT = "abort_incident"


class Server(StrEnum):
    """Which MCP server accepts a handle for this job type (AM-15: a handle is bound to one server)."""

    READ = "read"
    WRITE = "write"


class JobType(StrEnum):
    """The eight job types (AM-20.4); a job is a wake-up, never an authority."""

    INVESTIGATE = "investigate"
    RESUME_INPUT = "resume_input"
    EXECUTE = "execute"
    RECOVER = "recover"
    EXPIRE_PROPOSALS = "expire_proposals"
    SYNC_MEMBERSHIPS = "sync_memberships"
    SWEEP_WAKEUPS = "sweep_wakeups"
    DELIVER_OUTBOX = "deliver_outbox"


@dataclass(frozen=True)
class JobRule:
    """What a job type may do: its tools, the run states it runs in, its server, creators and dedup key shape.

    TODO(T15): AM-15 derives the allowlist from the job type *plus the run state and the attempt state* (for example
    `create_incident` only while the attempt is absent or INTENT). This rule holds the job-type dimension; T15's
    `resolve_invocation` adds the run-state and attempt-state filters at call time.
    """

    type: JobType
    allowed_tools: frozenset[Tool]
    run_states: frozenset[RunState]  # empty for maintenance jobs, which hold no run lease
    server: Server | None
    created_by: tuple[str, ...]  # AM-20.4 "Inserted by"
    dedup_pattern: str  # documentation of the key shape; `dedup_key` builds it


_READ: Final = frozenset({Tool.GET_ASSET_STATUS, Tool.GET_RECENT_ALERTS, Tool.SEARCH_PROCEDURES})
S = RunState
JOB_RULES: Final[dict[JobType, JobRule]] = {
    JobType.INVESTIGATE: JobRule(
        JobType.INVESTIGATE,
        _READ,
        frozenset({S.QUEUED, S.RETRIEVING, S.DRAFTING}),
        Server.READ,
        ("api", "create_revision"),
        "run_id:revision",
    ),
    JobType.RESUME_INPUT: JobRule(
        JobType.RESUME_INPUT,
        _READ,
        frozenset({S.AWAITING_INPUT, S.QUEUED}),
        Server.READ,
        ("api",),
        "run_id:clarification_event_id",
    ),
    JobType.EXECUTE: JobRule(
        JobType.EXECUTE,
        frozenset({Tool.CREATE_INCIDENT}),
        frozenset({S.APPROVED, S.EXECUTING}),
        Server.WRITE,
        ("record_decision",),
        "proposal_id",
    ),
    JobType.RECOVER: JobRule(
        JobType.RECOVER,
        frozenset({Tool.CREATE_INCIDENT, Tool.GET_INCIDENT_RECEIPT, Tool.ABORT_INCIDENT}),
        frozenset({S.EXECUTING, S.OUTCOME_UNKNOWN, S.ESCALATED, S.ABANDONED_UNVERIFIED}),
        Server.WRITE,
        ("mark_unknown", "worker", "reclaim_leases"),  # never an MCP server (AM-15)
        "action_id:trigger",
    ),
    **{
        t: JobRule(t, frozenset(), frozenset(), None, ("sweeper",), "name:minute_bucket")
        for t in (JobType.EXPIRE_PROPOSALS, JobType.SYNC_MEMBERSHIPS, JobType.SWEEP_WAKEUPS, JobType.DELIVER_OUTBOX)
    },
}

RECOVER_CADENCE: Final = (300, 3600, 48)  # every 5 min for the first hour, then hourly, 48 attempts (AM-20.4)
_TRIGGER: Final = re.compile(r"^(timeout|cancel|deadline|sweep:[0-9T:\-]+)$")  # AM-20.4 recover triggers
_BUCKET: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")  # one-minute bucket, UTC, no seconds


def server_for(job_type: JobType) -> Server | None:
    """The server whose handles this job type receives, or None for maintenance jobs that call no tool."""
    return JOB_RULES[job_type].server


def dedup_key(job_type: JobType, **ids: UUID | int | str) -> str:
    """Build the AM-20.4 dedup key for a job; missing or malformed parts raise ValueError naming the part."""
    match job_type:
        case JobType.INVESTIGATE:
            if "run_id" not in ids or "revision" not in ids:
                raise ValueError("investigate needs run_id and revision")
            return f"{ids['run_id']}:{ids['revision']}"
        case JobType.RESUME_INPUT:
            if "run_id" not in ids or "clarification_event_id" not in ids:
                raise ValueError("resume_input needs run_id and clarification_event_id")
            return f"{ids['run_id']}:{ids['clarification_event_id']}"
        case JobType.EXECUTE:
            if "proposal_id" not in ids:
                raise ValueError("execute needs proposal_id")
            return str(ids["proposal_id"])
        case JobType.RECOVER:
            trigger = str(ids.get("trigger", ""))
            if "action_id" not in ids or not _TRIGGER.match(trigger):
                raise ValueError("recover needs action_id and a trigger in {timeout, cancel, deadline, sweep:<bucket>}")
            return f"{ids['action_id']}:{trigger}"
        case _:
            bucket = str(ids.get("minute_bucket", ""))
            if not _BUCKET.match(bucket):
                raise ValueError("maintenance jobs need minute_bucket as YYYY-MM-DDTHH:MM")
            return f"{job_type.value}:{bucket}"
```

- [ ] **Step 4: Write `routing.py`**

Create `core/src/ops_core/routing.py`:
```python
"""The three routers' enumerable routes (AM-16, ADR-0003) and the per-run manifest (AM-80).

Routing is deterministic-first: model output may hint, never select. The tables that map inputs to these routes
arrive with their owners (T12 admission, T20 graph, T19 model); this module fixes the vocabularies so every table,
schema and event spells them the same way.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AdmissionRoute(StrEnum):
    """Where the admission router sends a message (AM-16; table owned by T12)."""

    INVESTIGATE = "investigate"
    CLARIFICATION_REPLY = "clarification_reply"
    STATUS_QUESTION = "status_question"
    READONLY_ANSWER = "readonly_answer"
    CLARIFY = "clarify"
    REJECT = "reject"


class GraphRoute(StrEnum):
    """The worker graph's next node (AM-16; table owned by T20)."""

    CLARIFY = "clarify"
    RETRIEVE = "retrieve"
    DRAFT = "draft"
    ANSWER_ONLY = "answer_only"
    ABSTAIN = "abstain"
    FREEZE = "freeze"
    AWAIT_DECISION = "await_decision"
    EXECUTE = "execute"
    RECOVER = "recover"
    PUBLISH = "publish"


class ModelRoute(StrEnum):
    """Which drafting model runs (AM-16, AM-31; table owned by T19)."""

    FAKE = "fake"
    QWEN3_8B = "qwen3:8b"


class RunManifest(BaseModel):
    """What produced a run's draft: route, model digest, prompt and corpus versions (AM-80; written by T19)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    run_id: UUID
    model_route: ModelRoute
    model_digest: str | None = Field(pattern=r"^[0-9a-f]{64}$")  # bare hex, as data/model-pins.json
    prompt_version: str = Field(min_length=1, max_length=60)
    corpus_version: str = Field(min_length=1, max_length=100)
    # Plan ruling 3: the externally visible mode keeps the delivered `vector_exact`, which says what the search
    # guarantees (exact, not approximate, vector search); AM-20.3's `mode=vector` is the SQL function's argument value.
    # TODO(T15): mcp-read, the caller of `search_procedures_scoped`, translates `vector_exact` to `mode=vector`.
    retrieval_mode: Literal["lexical", "vector_exact"]

    @model_validator(mode="after")
    def _real_models_carry_a_digest(self) -> RunManifest:
        # The fake route has nothing to pin; every real model route records the digest the worker verified (AM-31).
        if self.model_route is not ModelRoute.FAKE and self.model_digest is None:
            raise ValueError("model_digest is required for a real model route")
        return self
```

- [ ] **Step 5: Write `outcomes.py`**

Create `core/src/ops_core/outcomes.py`:
```python
"""Destination results, tool outcomes, the tombstone, and the event source rules (AM-13, AM-14).

Only destination records say whether an incident exists (BUILD_SPEC §14). This module makes the three vocabularies
(destination, tool, run) and their mapping explicit, and encodes the two schema rules R083 names so code and schema
reject the same things: a model never asserts an outcome, and a confirmed action always carries a receipt.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Final
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from ops_core.states import Reason, RunState


class DestinationState(StrEnum):
    """The destination's permanent key states (AM-13 "Destination")."""

    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    REJECTED = "REJECTED"


class ToolOutcome(StrEnum):
    """What a write tool reports to the worker (AM-13 "Outcome vocabulary")."""

    SUCCEEDED = "SUCCEEDED"
    FAILED_NO_COMMIT = "FAILED_NO_COMMIT"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


FAILED_NO_COMMIT_REASONS: Final = frozenset(
    {Reason.ABORTED_NO_COMMIT, Reason.CANCELLED_BEFORE_SEND, Reason.REJECTED, Reason.EXPIRED}
)  # AM-13 outcome vocabulary plus `expired` (plan ruling 2)


def outcome_from_destination(
    state: DestinationState, *, sent: bool, cancel_requested: bool
) -> tuple[ToolOutcome, Reason | None]:
    """Map a destination result to the tool outcome and the FAILED reason (AM-13 recovery table).

    `sent` is the hinge: an attempt still in INTENT was definitely not sent (`mark_sent` commits SENT before any
    network I/O, AM-13 attempt protocol), so an ABORTED key from INTENT proves the request never left, and the reason
    says why it was aborted: `cancelled_before_send` after a cancel, otherwise `expired` (the dispatch deadline
    passed). After SENT, a fresh ABORTED tombstone only proves nothing committed, so the reason is
    `aborted_no_commit` even when a cancel triggered the abort; claiming "cancelled before send" there would be false.

    Args:
        state: the destination key state from the receipt or tombstone.
        sent: whether the attempt reached SENT before the abort.
        cancel_requested: whether the run's cancel flag was set when the abort was requested.
    """
    if state is DestinationState.COMMITTED:
        return ToolOutcome.SUCCEEDED, None
    if state is DestinationState.REJECTED:
        return ToolOutcome.FAILED_NO_COMMIT, Reason.REJECTED
    if sent:
        return ToolOutcome.FAILED_NO_COMMIT, Reason.ABORTED_NO_COMMIT
    return ToolOutcome.FAILED_NO_COMMIT, Reason.CANCELLED_BEFORE_SEND if cancel_requested else Reason.EXPIRED


_Strict = ConfigDict(frozen=True, extra="forbid", strict=True)


class Receipt(BaseModel):
    """Proof that the destination committed the action (AM-13)."""

    model_config = _Strict
    receipt_id: UUID
    incident_id: str = Field(min_length=1, max_length=100)
    committed_at: AwareDatetime


class Tombstone(BaseModel):
    """What the destination returns for an ABORTED or REJECTED key (AM-13 "Tombstone shape"); never for COMMITTED."""

    model_config = _Strict
    action_id: UUID
    state: DestinationState
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=500)
    decided_at: AwareDatetime

    @model_validator(mode="after")
    def _not_committed(self) -> Tombstone:
        if self.state is DestinationState.COMMITTED:
            raise ValueError("a COMMITTED key has a receipt, not a tombstone")
        return self


class ActionOutcome(BaseModel):
    """A write tool's result data (AM-15 envelope/data agreement): the status and its evidence must agree."""

    model_config = _Strict
    status: ToolOutcome
    action_id: UUID
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    receipt: Receipt | None
    tombstone: Tombstone | None
    reason: Reason | None

    @model_validator(mode="after")
    def _evidence_matches_status(self) -> ActionOutcome:
        match self.status:
            case ToolOutcome.SUCCEEDED:
                if self.receipt is None or self.tombstone is not None or self.reason is not None:
                    raise ValueError("SUCCEEDED carries exactly a receipt")
            case ToolOutcome.FAILED_NO_COMMIT:
                if self.tombstone is None or self.receipt is not None or self.reason not in FAILED_NO_COMMIT_REASONS:
                    raise ValueError("FAILED_NO_COMMIT carries a tombstone and a reason from the FAILED set")
            case _:  # UNKNOWN, CONFLICT: nothing is proven either way
                if self.receipt is not None or self.tombstone is not None or self.reason is not None:
                    raise ValueError(f"{self.status} carries no receipt, tombstone or reason")
        return self


class EventSource(StrEnum):
    """Who asserts an event (AM-14 "Who may assert outcomes")."""

    APPLICATION = "application"
    DESTINATION = "destination"
    MODEL_SUMMARY = "model_summary"


class EventType(StrEnum):
    """The 27 event types: BUILD_SPEC §15's 13 plus AM-14's 14."""

    # BUILD_SPEC §15
    RUN_ACCEPTED = "run.accepted"
    CLARIFICATION_REQUESTED = "clarification.requested"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    PROPOSAL_READY = "proposal.ready"
    APPROVAL_RECORDED = "approval.recorded"
    ACTION_DISPATCHED = "action.dispatched"
    ACTION_UNCERTAIN = "action.uncertain"
    ACTION_CONFIRMED = "action.confirmed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    NOTIFICATION_FAILED = "notification.failed"
    FEEDBACK_RECORDED = "feedback.recorded"
    # AM-14
    CLARIFICATION_RECEIVED = "clarification.received"
    PROPOSAL_REVISED = "proposal.revised"
    REVIEW_BLOCKED = "review.blocked"
    RUN_ANSWERED = "run.answered"
    RUN_INSUFFICIENT_EVIDENCE = "run.insufficient_evidence"
    RUN_REJECTED = "run.rejected"
    ACTION_GRANTED = "action.granted"
    ACTION_REDISPATCHED = "action.redispatched"
    ACTION_FAILED = "action.failed"
    ACTION_CONFLICT = "action.conflict"
    RUN_ESCALATED = "run.escalated"
    RUN_ABANDONED_UNVERIFIED = "run.abandoned_unverified"
    ACTION_LATE_EVIDENCE = "action.late_evidence"
    EXPLANATION_READY = "explanation.ready"


DESTINATION_EVIDENCE: Final = frozenset(
    {EventType.ACTION_CONFIRMED, EventType.ACTION_FAILED, EventType.ACTION_CONFLICT, EventType.ACTION_LATE_EVIDENCE}
)  # AM-80 event row: the only types source=destination may emit, and they come only from record_outcome


class EventRuleViolation(ValueError):
    """The event asserts something its source may not assert (AM-14 'who may assert outcomes')."""


def event_rules_ok(event_type: EventType, source: EventSource, payload: Mapping[str, object]) -> None:
    """Raise EventRuleViolation unless (type, source, payload) obeys AM-14; the schema's if/then rules say the same."""
    prefix = event_type.value.split(".", 1)[0]
    if source is EventSource.MODEL_SUMMARY:
        # The schema's closed summary_payload, mirrored: a non-empty message, optional evidence_refs, nothing else
        # (so no status, AM-14).
        message = payload.get("message")
        if (
            event_type is not EventType.EXPLANATION_READY
            or not set(payload) <= {"message", "evidence_refs"}
            or not isinstance(message, str)
            or not message
        ):
            raise EventRuleViolation("model_summary may emit only explanation.ready with a message and evidence_refs")
        return
    if source is EventSource.DESTINATION and event_type not in DESTINATION_EVIDENCE:
        raise EventRuleViolation(f"source=destination may not emit {event_type}")
    # AM-20.3 record_outcome emits these four, always with source=destination; append_event refuses action.* from
    # application callers, so an application-sourced copy is a forgery.
    if event_type in DESTINATION_EVIDENCE and source is not EventSource.DESTINATION:
        raise EventRuleViolation(f"{event_type} comes only from record_outcome with source=destination")
    if prefix in {"action", "run", "review"} and source not in {EventSource.APPLICATION, EventSource.DESTINATION}:
        raise EventRuleViolation(f"{event_type} needs source application or destination")
    if event_type is EventType.ACTION_CONFIRMED:
        receipt = payload.get("receipt")
        if payload.get("status") != RunState.SUCCEEDED.value or not isinstance(receipt, Mapping):
            raise EventRuleViolation("action.confirmed requires a receipt and status SUCCEEDED")
        try:
            Receipt.model_validate_json(json.dumps(dict(receipt)))
        except ValidationError as exc:
            raise EventRuleViolation("action.confirmed carries a malformed receipt") from exc
    if event_type is EventType.ACTION_FAILED and payload.get("reason") not in {r.value for r in Reason}:
        raise EventRuleViolation("action.failed requires a reason from the reason enum")  # AM-14 "(with reason)"
    if event_type is EventType.ACTION_LATE_EVIDENCE:
        if payload.get("outcome") not in {"SUCCEEDED", "FAILED_NO_COMMIT"}:
            raise EventRuleViolation("action.late_evidence requires outcome SUCCEEDED or FAILED_NO_COMMIT")
        if not isinstance(payload.get("receipt"), Mapping) and not isinstance(payload.get("tombstone"), Mapping):
            raise EventRuleViolation("action.late_evidence requires a receipt or a tombstone")
```

- [ ] **Step 6: Run the tests, mypy and the full check**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_jobs_routes_outcomes.py -q 2>&1 | tr -d '\r' | tail -2`
Expected: `8 passed`.

Run: `uv run python -m mypy core/src 2>&1 | tr -d '\r' | tail -1`
Expected: `Success: no issues found in 7 source files`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tr -d '\r' | tail -3`
Expected: `126 passed`, `11 skipped`, `CHECK: GREEN`.

- [ ] **Step 7: Commit**

```bash
git add core/src/ops_core/jobs.py core/src/ops_core/routing.py core/src/ops_core/outcomes.py tests/plan_c/test_jobs_routes_outcomes.py
git commit -m "T07: job rules and dedup keys, route enums, outcome vocabulary, tombstone and event source rules"
```

---

### Task 4: T07d — Request, response, draft and proposal contracts

**Files:**
- Create: `core/src/ops_core/contracts.py`, `tests/plan_c/test_contracts.py`

**Interfaces:**
- Produces (all `frozen, extra=forbid, strict`): `MessageKind` (`investigate`, `ask`, `status`, `clarification`), `MessageContext(asset_id, hours)`, `MessageRequest(kind, text, context?, supersedes_run_id?)`, `ClarificationReply(question_id, expected_version, context)`, `DecisionRequest(expected_revision, expected_payload_sha256, decision, reason?)`, `RevisionRequest(expected_version, supersedes_run_id?)`, `CancelRequest(expected_version, reason?)`, `CancelResponse(run_id, status, state_version, cancel_requested, grant_exists, attempt_state?, note?)`, `FeedbackRequest(subject_kind, subject_id, category, text?)`, `ManualProposalRequest(asset_id, start_at, end_at, title, summary, evidence_refs, assumptions, limitations)`, `ModelDraft(kind, title, summary, evidence_refs, assumptions, limitations, question?)` with `clarification_requested` property, `RunRequestFields(intent: Intent, supersedes_run_id: UUID | None)` (what `create_run`/`create_revision` store; model output is never a source), `SourceSnapshot`, `ProposalPayload` (the hashed fields incl. optional `supersedes_run_id`; zero-offset aware datetimes, ruling 6; `start_at < end_at`; `evidence_refs` sorted and unique, `source_snapshots` sorted by `evidence_id`), `Proposal(canonicalization_version, payload, payload_sha256, authored_by)` with hash verification, `SafeError(code: ErrorCode, message, retryable, request_id)`, `ErrorCode` enum, `AUTHORITY_FIELDS` (the names every contract must reject). `load(model, text)` helper = `model.model_validate_json`.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_c/test_contracts.py`:
```python
"""Request/response/draft/proposal contracts (BUILD_SPEC §7, AM-10/11/13/80, R004, R005, R125).

Catches: a client or model smuggling an authority field (role, tenant, actor, approval, destination) at the top level
or inside a nested request object, a boolean or string where an integer is required, a draft carrying
supersedes_run_id, run fields taken from anywhere but the request, a proposal whose hash does not match its bytes or
whose arrays are not in canonical order, a non-UTC or inverted interval, and an error code outside the documented set.
"""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from ops_core import contracts as c
from ops_core.canonical import canonical_sha256
from pydantic import ValidationError

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
RUN = UUID("00000000-0000-4000-8000-000000000003")
PROP = UUID("00000000-0000-4000-8000-000000000004")
MESSAGE = {
    "kind": "investigate",
    "text": "Investigate the alerts on Asset A17 over the last 24 hours.",
    "context": {"asset_id": "A17", "hours": 24},
}
DRAFT = {
    "kind": "proposal",
    "title": "Open an incident for A17",
    "summary": "Two warnings inside the window.",
    "evidence_refs": ["ALPHA-INCIDENT:v2:review"],
    "assumptions": [],
    "limitations": ["synthetic data"],
}
PAYLOAD = {
    "tenant_id": str(ALPHA),
    "run_id": str(RUN),
    "proposal_id": str(PROP),
    "revision": 1,
    "action": "create_incident",
    "destination": "synthetic-incidents",
    "asset_id": "A17",
    "start_at": "2026-10-05T12:00:00+00:00",
    "end_at": "2026-10-06T12:00:00+00:00",
    "title": "Open an incident for A17",
    "summary": "Two warnings inside the window.",
    "evidence_refs": ["ALPHA-INCIDENT:v2:review"],
    "source_snapshots": [{"evidence_id": "ALPHA-INCIDENT:v2:review", "content_sha256": "8b" * 32, "version": "2"}],
    "assumptions": [],
    "limitations": ["synthetic data"],
    "workflow_version": "v1",
    "prompt_version": "incident-draft-v1",
    "expires_at": "2026-10-06T12:15:00+00:00",
}
REQUEST_MODELS = [
    (c.MessageRequest, MESSAGE),
    (c.ClarificationReply, {"question_id": str(PROP), "expected_version": 2, "context": {"hours": 24}}),
    (
        c.DecisionRequest,
        {"expected_revision": 1, "expected_payload_sha256": "ab" * 32, "decision": "approve", "reason": "ok"},
    ),
    (c.RevisionRequest, {"expected_version": 3, "supersedes_run_id": str(RUN)}),
    (c.CancelRequest, {"expected_version": 3}),
    (
        c.FeedbackRequest,
        {
            "subject_kind": "proposal",
            "subject_id": str(PROP),
            "category": "wrong_evidence",
            "text": "cites the superseded version",
        },
    ),
    (
        c.ManualProposalRequest,
        {
            "asset_id": "A17",
            "start_at": "2026-10-05T12:00:00+00:00",
            "end_at": "2026-10-06T12:00:00+00:00",
            "title": "t",
            "summary": "s",
            "evidence_refs": ["ALPHA-INCIDENT:v2:review"],
            "assumptions": [],
            "limitations": [],
        },
    ),
    (c.ModelDraft, DRAFT),
]


def test_authority_fields_list_is_the_documented_set():
    assert c.AUTHORITY_FIELDS == frozenset(
        {
            "tenant_id",
            "actor",
            "actor_id",
            "role",
            "roles",
            "approved",
            "approved_by",
            "destination",
            "reviewer",
            "requester",
        }
    )


@pytest.mark.parametrize("model,body", REQUEST_MODELS, ids=[m.__name__ for m, _ in REQUEST_MODELS])
@pytest.mark.parametrize("field", sorted(c.AUTHORITY_FIELDS))
def test_authority_fields_are_rejected_at_every_depth(model, body, field):
    """R004: top level and every nested object; the reference's test_cannot_supply_identity_or_approved_field."""
    assert c.load(model, json.dumps(body))
    with pytest.raises(ValidationError):
        c.load(model, json.dumps({**body, field: "x"}))
    for key, value in body.items():
        if isinstance(value, dict):
            with pytest.raises(ValidationError):
                c.load(model, json.dumps({**body, key: {**value, field: "x"}}))


@given(st.sampled_from(sorted(c.AUTHORITY_FIELDS)), st.one_of(st.text(), st.integers(), st.booleans()))
def test_any_authority_field_with_any_value_is_rejected(field, value):
    """R004 as a property: the field name alone is enough to reject, whatever value the client chose."""
    with pytest.raises(ValidationError):
        c.load(c.MessageRequest, json.dumps({**MESSAGE, field: value}))
    with pytest.raises(ValidationError):
        c.load(c.MessageRequest, json.dumps({**MESSAGE, "context": {**MESSAGE["context"], field: value}}))


def test_run_request_fields():
    """AM-10: intent and supersedes_run_id are run fields from the request; nothing else rides along."""
    fields = c.load(c.RunRequestFields, json.dumps({"intent": "answer_only", "supersedes_run_id": str(RUN)}))
    assert fields.intent is c.Intent.ANSWER_ONLY and fields.supersedes_run_id == RUN
    assert c.load(c.RunRequestFields, json.dumps({"intent": "investigate"})).supersedes_run_id is None
    for bad in ({"intent": "approve"}, {"intent": "investigate", "approved": True}, {"supersedes_run_id": str(RUN)}):
        with pytest.raises(ValidationError):
            c.load(c.RunRequestFields, json.dumps(bad))


@pytest.mark.parametrize("hours", [0, 169, -1, True, 1.5, "24"], ids=["zero", "169", "neg", "bool", "float", "str"])
def test_invalid_hours_rejected(hours):
    """The reference's test_invalid_hours and test_bool_hours_rejected, against the strict contract.

    The reference's `None` case is not here: in the target, `hours` is optional (absent or null), and a request without
    an interval is routed to `clarify` by the admission router (AM-16), which is T12's test, not a 422.
    """
    with pytest.raises(ValidationError):
        c.load(c.MessageRequest, json.dumps({**MESSAGE, "context": {"asset_id": "A17", "hours": hours}}))


@pytest.mark.parametrize("hours", [1, 24, 168])
def test_valid_hours(hours):
    assert (
        c.load(c.MessageRequest, json.dumps({**MESSAGE, "context": {"asset_id": "A17", "hours": hours}})).context.hours
        == hours
    )


@pytest.mark.parametrize("text", ["", " ", "x" * 4001], ids=["empty", "blank", "oversize"])
def test_empty_and_oversize_message(text):
    """The reference's test_empty_and_oversize_message: text is 1..4000 after stripping."""
    with pytest.raises(ValidationError):
        c.load(c.MessageRequest, json.dumps({**MESSAGE, "text": text}))


def test_message_kinds_and_supersedes():
    assert {k.value for k in c.MessageKind} == {"investigate", "ask", "status", "clarification"}
    with pytest.raises(ValidationError):
        c.load(c.MessageRequest, json.dumps({**MESSAGE, "kind": "question"}))  # the 1.0 value is gone (AM-80)
    m = c.load(c.MessageRequest, json.dumps({**MESSAGE, "supersedes_run_id": str(RUN)}))
    assert m.supersedes_run_id == RUN  # requester-asserted, structured (AM-10)


def test_draft_rules():
    d = c.load(c.ModelDraft, json.dumps(DRAFT))
    assert d.clarification_requested is False
    abstain = c.load(
        c.ModelDraft, json.dumps({**DRAFT, "kind": "abstain", "evidence_refs": [], "question": "Which interval?"})
    )
    assert abstain.clarification_requested is True
    assert (
        c.load(c.ModelDraft, json.dumps({**DRAFT, "kind": "abstain", "evidence_refs": []})).clarification_requested
        is False
    )  # abstain without a question = insufficient evidence
    for bad in (
        {**DRAFT, "supersedes_run_id": str(RUN)},  # R125: a draft never names what it supersedes
        {**DRAFT, "approved": True},  # the reference's test_model_cannot_add_authorization_field
        {**DRAFT, "evidence_refs": []},  # a proposal cites at least one piece of evidence
        {**DRAFT, "evidence_refs": ["a", "a"]},  # duplicates
        {**DRAFT, "kind": "abstain", "evidence_refs": [], "question": ""},  # an empty question is no question
        {**DRAFT, "kind": "proposal", "question": "why?"},  # only abstain asks
    ):
        with pytest.raises(ValidationError):
            c.load(c.ModelDraft, json.dumps(bad))


def test_proposal_payload_and_hash():
    payload = c.load(c.ProposalPayload, json.dumps(PAYLOAD))
    sha = canonical_sha256(payload.canonical_dict())
    p = c.Proposal(canonicalization_version=1, payload=payload, payload_sha256=sha, authored_by=[ALPHA])
    assert p.payload_sha256 == sha and p.authored_by == [ALPHA]
    with pytest.raises(ValidationError, match="payload_sha256"):
        c.Proposal(canonicalization_version=1, payload=payload, payload_sha256="0" * 64, authored_by=[ALPHA])
    with_super = c.load(c.ProposalPayload, json.dumps({**PAYLOAD, "supersedes_run_id": str(RUN)}))
    assert (
        canonical_sha256(with_super.canonical_dict()) != sha
    )  # supersedes_run_id is inside the hashed payload (AM-80)
    for bad in (
        {**PAYLOAD, "start_at": "2026-10-06T12:00:00+00:00", "end_at": "2026-10-05T12:00:00+00:00"},  # inverted
        {**PAYLOAD, "start_at": "2026-10-05T14:00:00+02:00"},  # not UTC
        {**PAYLOAD, "start_at": "2026-10-05T12:00:00"},  # naive
        {**PAYLOAD, "authored_by": [str(ALPHA)]},  # authored_by sits outside the hashed payload
        {**PAYLOAD, "action": "delete_incident"},
    ):
        with pytest.raises(ValidationError):
            c.load(c.ProposalPayload, json.dumps(bad))
    stamp = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    assert (
        payload.start_at == stamp and payload.canonical_dict()["start_at"] == "2026-10-05T12:00:00Z"
    )  # pydantic's UTC form


def test_proposal_arrays_must_be_in_canonical_order():
    """Canonical JSON keeps array order, so the payload fixes it: refs by code point, snapshots by evidence_id."""
    snap = PAYLOAD["source_snapshots"][0]
    two = {
        **PAYLOAD,
        "evidence_refs": ["ALPHA-INCIDENT:v2:review", "ALPHA-RUNBOOK:v1:steps"],
        "source_snapshots": [snap, {**snap, "evidence_id": "ALPHA-RUNBOOK:v1:steps", "version": "1"}],
    }
    assert c.load(c.ProposalPayload, json.dumps(two)).evidence_refs[0] == "ALPHA-INCIDENT:v2:review"
    with pytest.raises(ValidationError, match="evidence_refs must be sorted"):
        c.load(c.ProposalPayload, json.dumps({**two, "evidence_refs": two["evidence_refs"][::-1]}))
    with pytest.raises(ValidationError, match="source_snapshots"):
        c.load(c.ProposalPayload, json.dumps({**two, "source_snapshots": two["source_snapshots"][::-1]}))


def test_cancel_response_reports_grant_and_never_undo():
    body = {
        "run_id": str(RUN),
        "status": "EXECUTING",
        "state_version": 4,
        "cancel_requested": True,
        "grant_exists": True,
        "attempt_state": "SENT",
        "note": "cancellation arrived after dispatch",
    }
    r = c.load(c.CancelResponse, json.dumps(body))
    assert r.grant_exists and r.attempt_state == "SENT"
    with pytest.raises(ValidationError):
        c.load(
            c.CancelResponse, json.dumps({**body, "status": "CANCELLED", "grant_exists": False})
        )  # no grant, no attempt


def test_safe_error_codes():
    e = c.load(
        c.SafeError,
        json.dumps(
            {"code": "SLOT_OCCUPIED", "message": "another run is active", "retryable": False, "request_id": str(PROP)}
        ),
    )
    assert e.code is c.ErrorCode.SLOT_OCCUPIED
    with pytest.raises(ValidationError):
        c.load(c.SafeError, json.dumps({"code": "OOPS", "message": "m", "retryable": False, "request_id": str(PROP)}))
    assert {
        "ASSET_ACTION_UNRESOLVED",
        "ASSET_INCIDENT_EXISTS",
        "GRANT_EXISTS",
        "SLOT_OCCUPIED",
        "AUTHORITY_VIOLATION",
        "VERSION_CONFLICT",
        "FORBIDDEN",
        "NOT_FOUND",
        "UNAUTHENTICATED",
        "INVALID_INPUT",
        "RATE_LIMITED",
        "UNAVAILABLE",
        "IDEMPOTENCY_CONFLICT",
    } <= {x.value for x in c.ErrorCode}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_contracts.py -q 2>&1 | tr -d '\r' | tail -3`
Expected: collection fails with `ImportError: cannot import name 'contracts' from 'ops_core'` (the package exists; the module does not); `1 error`.

- [ ] **Step 3: Write the module**

Create `core/src/ops_core/contracts.py`:
```python
"""Request, response, draft and proposal contracts (BUILD_SPEC §7, AM-10, AM-11, AM-13, AM-80).

Every model is strict, frozen and closed (`extra="forbid"`): the server sets actor, tenant, roles, timestamps and
authority fields, and a body that tries to supply them is rejected before any handler runs (R004). Bodies are parsed
with `load()` (JSON mode) so numbers are never coerced from strings or booleans. The JSON Schemas under `schemas/`
say the same things declaratively (they are generated by `scripts/build_schemas.py`);
`tests/plan_c/test_schema_conformance.py` keeps the two in step.

Timestamps (plan ruling 6): every instant must carry a zero UTC offset. Inputs may spell it `Z` or `+00:00`; the
hashed and stored form is pydantic's JSON output, which spells it `Z`, so the proposal schema accepts only `Z` while
request schemas accept either spelling.
"""

from __future__ import annotations

from datetime import UTC
from enum import StrEnum
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from ops_core.canonical import canonical_sha256
from ops_core.states import AttemptState, Intent, RunState

AUTHORITY_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "actor",
        "actor_id",
        "role",
        "roles",
        "approved",
        "approved_by",
        "destination",
        "reviewer",
        "requester",
    }
)  # names a client or model may never supply (BUILD_SPEC §7, R004); `extra="forbid"` rejects them everywhere

_Strict = ConfigDict(frozen=True, extra="forbid", strict=True)
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Summary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2500)]
AssetId = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_-]{0,31}$")]
EvidenceRef = Annotated[str, StringConstraints(min_length=1, max_length=160)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


def load[M: BaseModel](model: type[M], text: str) -> M:
    """Parse a JSON body into a contract in strict JSON mode (strings never become numbers, bools never ints)."""
    return model.model_validate_json(text)


def _unique(items: list[str]) -> list[str]:
    if len(set(items)) != len(items):
        raise ValueError("duplicate entries")
    return items


def _sorted(items: list[str], what: str) -> None:
    # Canonical JSON keeps array order (BUILD_SPEC §6 "documented stable array order"), so the producer must fix it.
    if items != sorted(items):
        raise ValueError(f"{what} must be sorted ascending by code point so the payload hash is stable")


def _utc(value: AwareDatetime) -> AwareDatetime:
    # BUILD_SPEC §6 "UTC instants with explicit offsets": a zero offset is required (`Z` or `+00:00` both parse to
    # it), so one instant has one canonical spelling once pydantic serialises it as `Z` (ruling 6).
    if value.utcoffset() != UTC.utcoffset(None):
        raise ValueError("timestamps must carry a zero UTC offset (Z or +00:00)")
    return value


class MessageKind(StrEnum):
    """What a message asks for; the admission router (AM-16) reads it."""

    INVESTIGATE = "investigate"
    ASK = "ask"
    STATUS = "status"
    CLARIFICATION = "clarification"


class MessageContext(BaseModel):
    """Structured context a requester may attach: the asset and the look-back window in hours."""

    model_config = _Strict
    asset_id: AssetId | None = None
    hours: int | None = Field(default=None, ge=1, le=168)  # strict: True, 1.5 and "24" are rejected


class MessageRequest(BaseModel):
    """`POST /conversations/{id}/messages` (BUILD_SPEC §7 sample; AM-16 admission routes read `kind`)."""

    model_config = _Strict
    kind: MessageKind
    text: Text
    context: MessageContext | None = None
    supersedes_run_id: UUID | None = None  # requester-asserted (AM-10 "Requester-asserted fields")


class RunRequestFields(BaseModel):
    """The requester-asserted run fields `create_run`/`create_revision` store on `runs` (AM-10, AM-20.3).

    They come only from the authenticated request's structured fields (admission or revision); model output is never
    a source for either, which is why `ModelDraft` has neither field. `intent` drives `freeze_allowed`;
    `supersedes_run_id` is injected into the hashed payload by `freeze_proposal`.
    """

    model_config = _Strict
    intent: Intent
    supersedes_run_id: UUID | None = None


class ClarificationReply(BaseModel):
    """The requester's answer to a clarification question (AM-10 clarification signal)."""

    model_config = _Strict
    question_id: UUID
    expected_version: int = Field(ge=1)
    context: MessageContext

    @model_validator(mode="after")
    def _answers_something(self) -> ClarificationReply:
        if self.context.asset_id is None and self.context.hours is None:
            raise ValueError("a clarification reply must supply asset_id or hours")
        return self


class DecisionRequest(BaseModel):
    """`POST /proposals/{id}/decisions`; the reviewer is the session, never a field (BUILD_SPEC §13)."""

    model_config = _Strict
    expected_revision: int = Field(ge=1)
    expected_payload_sha256: Sha256  # AM-11 / AM-80 row 14 (renamed from payload_sha256)
    decision: Literal["approve", "reject"]
    reason: Annotated[str, StringConstraints(max_length=500)] | None = None


class RevisionRequest(BaseModel):
    """`POST /runs/{id}/revisions`: re-queue a run, optionally naming the run it supersedes (AM-20.3)."""

    model_config = _Strict
    expected_version: int = Field(ge=1)
    supersedes_run_id: UUID | None = None


class CancelRequest(BaseModel):
    """`POST /runs/{id}/cancel` body (schemas/cancellation.schema.json)."""

    model_config = _Strict
    expected_version: int = Field(ge=1)
    reason: Annotated[str, StringConstraints(max_length=500)] | None = None


class CancelResponse(BaseModel):
    """`POST /runs/{id}/cancel` reports whether a grant or dispatch already happened; it never claims undo (AM-13)."""

    model_config = _Strict
    run_id: UUID
    status: RunState
    state_version: int = Field(ge=1)
    cancel_requested: bool
    grant_exists: bool
    attempt_state: AttemptState | None
    note: Short | None

    @model_validator(mode="after")
    def _attempt_only_with_grant(self) -> CancelResponse:
        if not self.grant_exists and self.attempt_state is not None:
            raise ValueError("an attempt state exists only after a grant")
        return self


class FeedbackRequest(BaseModel):
    """`POST /runs/{id}/feedback`: classified, stored, never a runtime policy (R113)."""

    model_config = _Strict
    subject_kind: Literal["run", "proposal", "event"]
    subject_id: UUID
    category: Literal["wrong_evidence", "missing_evidence", "wrong_conclusion", "unclear", "other"]
    text: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ManualProposalRequest(BaseModel):
    """`POST /manual-proposals`: a human-authored draft that enters the same approval path (AM-20.3)."""

    model_config = _Strict
    asset_id: AssetId
    start_at: AwareDatetime
    end_at: AwareDatetime
    title: Title
    summary: Summary
    evidence_refs: Annotated[list[EvidenceRef], Field(min_length=1, max_length=8)]
    assumptions: Annotated[list[Short], Field(max_length=8)]
    limitations: Annotated[list[Short], Field(max_length=8)]

    @field_validator("start_at", "end_at")
    @classmethod
    def _utc_only(cls, value: AwareDatetime) -> AwareDatetime:
        return _utc(value)

    @field_validator("evidence_refs")
    @classmethod
    def _unique_refs(cls, items: list[str]) -> list[str]:
        return _unique(items)

    @model_validator(mode="after")
    def _interval(self) -> ManualProposalRequest:
        if not self.start_at < self.end_at:
            raise ValueError("start_at must be before end_at")
        return self


class ModelDraft(BaseModel):
    """The validated model output (schemas/model-draft.schema.json). Carries no authority and no supersession."""

    model_config = _Strict
    kind: Literal["proposal", "answer", "abstain"]
    title: Title
    summary: Summary
    evidence_refs: Annotated[list[EvidenceRef], Field(max_length=8)]
    assumptions: Annotated[list[Short], Field(max_length=8)]
    limitations: Annotated[list[Short], Field(max_length=8)]
    question: Short | None = None  # AM-10: abstain + question = clarification; abstain alone = insufficient evidence

    @field_validator("evidence_refs")
    @classmethod
    def _unique_refs(cls, items: list[str]) -> list[str]:
        return _unique(items)

    @model_validator(mode="after")
    def _kind_rules(self) -> ModelDraft:
        if self.kind in {"proposal", "answer"} and not self.evidence_refs:
            raise ValueError(f"a {self.kind} cites at least one piece of evidence")
        if self.question is not None and self.kind != "abstain":
            raise ValueError("only an abstain carries a question")
        return self

    @property
    def clarification_requested(self) -> bool:
        return self.kind == "abstain" and self.question is not None


class SourceSnapshot(BaseModel):
    """The version and hash of one cited evidence item at freeze time."""

    model_config = _Strict
    evidence_id: EvidenceRef
    content_sha256: Sha256
    version: Annotated[str, StringConstraints(min_length=1, max_length=40)]


class ProposalPayload(BaseModel):
    """The hashed payload (BUILD_SPEC §6 list; AM-80 row 19). `authored_by` is NOT here: it is a sibling of payload."""

    model_config = _Strict
    tenant_id: UUID
    run_id: UUID
    proposal_id: UUID
    revision: int = Field(ge=1)
    action: Literal["create_incident"]
    destination: Literal["synthetic-incidents"]
    asset_id: AssetId
    start_at: AwareDatetime
    end_at: AwareDatetime
    title: Title
    summary: Summary
    evidence_refs: Annotated[list[EvidenceRef], Field(min_length=1, max_length=8)]
    source_snapshots: Annotated[list[SourceSnapshot], Field(min_length=1, max_length=8)]
    assumptions: Annotated[list[Short], Field(max_length=8)]
    limitations: Annotated[list[Short], Field(max_length=8)]
    workflow_version: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    prompt_version: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    expires_at: AwareDatetime
    supersedes_run_id: UUID | None = None  # injected by freeze_proposal from runs (AM-20.3); inside the hash (R125)

    @field_validator("start_at", "end_at", "expires_at")
    @classmethod
    def _utc_only(cls, value: AwareDatetime) -> AwareDatetime:
        return _utc(value)

    @field_validator("evidence_refs")
    @classmethod
    def _unique_sorted_refs(cls, items: list[str]) -> list[str]:
        _sorted(items, "evidence_refs")
        return _unique(items)

    @field_validator("source_snapshots")
    @classmethod
    def _snapshots_sorted(cls, items: list[SourceSnapshot]) -> list[SourceSnapshot]:
        _sorted([s.evidence_id for s in items], "source_snapshots (by evidence_id)")
        return items

    @model_validator(mode="after")
    def _interval(self) -> ProposalPayload:
        if not self.start_at < self.end_at:
            raise ValueError("start_at must be before end_at")
        return self

    def canonical_dict(self) -> dict[str, Any]:
        """Return the JSON-ready mapping that is hashed.

        UUIDs become strings and UTC timestamps pydantic's `…Z` form (ruling 6), whatever spelling the input used;
        None fields are omitted so an absent supersedes_run_id and a missing one hash alike. Arrays are already in
        their validated sorted order.
        """
        return self.model_dump(mode="json", exclude_none=True)


class Proposal(BaseModel):
    """An immutable revision: canonical bytes' hash plus the content authors, kept outside the hash (AM-80)."""

    model_config = _Strict
    canonicalization_version: Literal[1]
    payload: ProposalPayload
    payload_sha256: Sha256
    authored_by: list[UUID] = Field(min_length=1, max_length=8)  # requester plus revision authors (AM-20.3)

    @model_validator(mode="after")
    def _hash_matches(self) -> Proposal:
        expected = canonical_sha256(self.payload.canonical_dict())
        if self.payload_sha256 != expected:
            raise ValueError(f"payload_sha256 {self.payload_sha256} does not match the canonical bytes ({expected})")
        return self


class ErrorCode(StrEnum):
    """The documented error codes (BUILD_SPEC §7 plus the AM-80 error row)."""

    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INVALID_INPUT = "INVALID_INPUT"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    ASSET_ACTION_UNRESOLVED = "ASSET_ACTION_UNRESOLVED"
    ASSET_INCIDENT_EXISTS = "ASSET_INCIDENT_EXISTS"
    GRANT_EXISTS = "GRANT_EXISTS"
    SLOT_OCCUPIED = "SLOT_OCCUPIED"
    AUTHORITY_VIOLATION = "AUTHORITY_VIOLATION"


class SafeError(BaseModel):
    """BUILD_SPEC §7 safe error: no stack traces, queries, tokens or unauthorized IDs."""

    model_config = _Strict
    code: ErrorCode
    message: Short
    retryable: bool
    request_id: UUID
```

- [ ] **Step 4: Run the tests, mypy and the full check**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_contracts.py -q 2>&1 | tr -d '\r' | tail -2`
Expected: `101 passed` (1 + 8 models × 10 authority fields + 1 Hypothesis property + 1 run-fields test + 6 + 3 + 3 + 1 + 1 + 1 + 1 + 1 + 1).

Run: `uv run python -m mypy core/src 2>&1 | tr -d '\r' | tail -1`
Expected: `Success: no issues found in 8 source files`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tr -d '\r' | tail -3`
Expected: `227 passed`, `11 skipped`, `CHECK: GREEN`.

- [ ] **Step 5: Commit**

```bash
git add core/src/ops_core/contracts.py tests/plan_c/test_contracts.py
git commit -m "T07: strict request, response, draft and proposal contracts; authority fields rejected at every depth"
```

---

### Task 5: T45b — Fixture metadata: tenant UUIDs, alert UUIDs and revisions, per-section hashes

**Files:**
- Create: `scripts/gen_fixture_meta.py`, `data/handoff-fixtures/meta.json`, `tests/plan_c/test_fixture_meta.py`
- Modify: `data/handoff-fixtures/README.md` (document `meta.json`), `scripts/verify_handoff.py` (puts `ROOT` on `sys.path`; base checks validate `meta.json` against the markdown)

**Interfaces:**
- Consumes: `data/handoff-fixtures/catalog.json` (unchanged — its whole-file hashes stay valid because no markdown changes), `observations.json` (unchanged), `data/seed-ids.json`, the seed namespace from `scripts/gen_seed_ids.py` (`NS = uuid5(NAMESPACE_URL, "https://github.com/jschnepel/MLOps/seed")`).
- Produces: `data/handoff-fixtures/meta.json` = `{"fixture_version": "handoff-1", "meta_version": 1, "tenants": {"alpha": <uuid>, "beta": <uuid>}, "alerts": [{"id": "A17-alert-001", "alert_id": <uuid5(NS, "alert/A17-alert-001")>, "revision": 1}, …], "sections": [{"document_id", "version", "section", "sha256"}]}`; `scripts/gen_fixture_meta.py` with `ROOT`, `FIXTURES`, `SEED_IDS` (all resolved from the script's location) and functions `section_hashes(path) -> list[tuple[str, str]]`, `generate(root=FIXTURES) -> dict`, `write_meta(root=FIXTURES) -> Path`; run as `uv run python -m scripts.gen_fixture_meta`. Per-section hash rule (documented in the README): the section body is every line after the `## <name>` heading up to the next `## ` heading or end of file, joined with `\n`, stripped of leading/trailing newlines, UTF-8 encoded, SHA-256. Task 6's generator reads the two in-window alert UUIDs from `meta.json`.

- [ ] **Step 1: Write the failing tests**

Create `tests/plan_c/test_fixture_meta.py`:
```python
"""Fixture metadata (AM-80 fixtures row): tenant UUIDs, alert UUIDs/revisions and per-section hashes are generated
deterministically from the seed namespace and the markdown, and the committed file never drifts from the generator.

Catches: a hand-edited meta.json, an alert UUID that is not the uuid5 of its id, a section hash that no longer matches
the markdown, and a tenant map that disagrees with data/seed-ids.json.
"""

import hashlib
import json
import uuid
from pathlib import Path

from scripts import gen_fixture_meta as g
from scripts.gen_seed_ids import NS

ROOT = g.FIXTURES
SEEDS = json.loads(g.SEED_IDS.read_text(encoding="utf-8"))


def test_generator_is_deterministic_and_committed_file_matches():
    assert g.generate(ROOT) == g.generate(ROOT)
    assert json.loads((ROOT / "meta.json").read_text(encoding="utf-8")) == g.generate(ROOT)
    raw = (ROOT / "meta.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"}\n")


def test_tenants_match_seed_ids():
    meta = g.generate(ROOT)
    assert meta["tenants"] == SEEDS["tenants"]


def test_alert_uuids_are_uuid5_of_their_ids_with_revision_one():
    meta = g.generate(ROOT)
    ids = {a["id"] for a in json.loads((ROOT / "observations.json").read_text(encoding="utf-8"))["alerts"]}
    assert {a["id"] for a in meta["alerts"]} == ids == {"A17-alert-001", "A17-alert-002", "A17-old-001"}
    for a in meta["alerts"]:
        assert a["alert_id"] == str(uuid.uuid5(NS, f"alert/{a['id']}")) and a["revision"] == 1


def test_section_hashes_follow_the_documented_rule(tmp_path: Path):
    p = tmp_path / "scratch.md"
    p.write_text("# Title\n\n## review\n\nline one\nline two\n\n## evidence\nx\n", encoding="utf-8", newline="\n")
    hashes = dict(g.section_hashes(p))
    assert hashes == {
        "review": hashlib.sha256(b"line one\nline two").hexdigest(),
        "evidence": hashlib.sha256(b"x").hexdigest(),
    }


def test_every_catalog_section_has_a_hash():
    catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    meta = g.generate(ROOT)
    have = {(s["document_id"], s["version"], s["section"]) for s in meta["sections"]}
    want = {(d["document_id"], d["version"], sec) for d in catalog["documents"] for sec in d["sections"]}
    assert want <= have
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_fixture_meta.py -q 2>&1 | tr -d '\r' | tail -3`
Expected: collection fails with `ImportError: cannot import name 'gen_fixture_meta'`; `1 error`.

- [ ] **Step 3: Write the generator and run it**

Create `scripts/gen_fixture_meta.py`:
```python
"""Generate data/handoff-fixtures/meta.json (AM-80 fixtures row): tenant UUIDs, alert UUIDs + revisions, section hashes.

The delivered fixtures identify tenants by slug and alerts by a readable id; the target contracts need UUIDs
(tool-result alerts carry `alert_id` uuid + `revision`, evidence rows carry per-section hashes). Everything here is
derived — from data/seed-ids.json, from the seed namespace, and from the markdown bytes — so the file can always be
regenerated and a test guards it against hand edits. The markdown and catalog.json are not touched: catalog hashes
stay valid. Paths are resolved from the repository root, never the working directory, because the checker imports
`generate` from a tampered copy of the repository whose root is not the current directory.

Usage: uv run python -m scripts.gen_fixture_meta
(`-m` from the repository root, because the module imports `scripts.gen_seed_ids`; running it by path would put
`scripts/` rather than the root on sys.path.)
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

from scripts.gen_seed_ids import NS

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data/handoff-fixtures"
SEED_IDS = ROOT / "data/seed-ids.json"
_HEADING = re.compile(r"^## (?P<name>\S.*?)\s*$")


def section_hashes(path: Path) -> list[tuple[str, str]]:
    """(section, sha256) for each `## ` heading: body = lines until the next `## ` heading, stripped of blank edges."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[tuple[str, str]] = []
    name: str | None = None
    body: list[str] = []

    def flush() -> None:
        if name is not None:
            out.append((name, hashlib.sha256("\n".join(body).strip("\n").encode("utf-8")).hexdigest()))

    for line in lines:
        m = _HEADING.match(line)
        if m:
            flush()
            name, body = m.group("name"), []
        elif name is not None:
            body.append(line)
    flush()
    return out


def generate(root: Path = FIXTURES) -> dict[str, object]:
    """Build the meta.json document for the fixture directory `root` (tenants always come from SEED_IDS)."""
    seeds = json.loads(SEED_IDS.read_text(encoding="utf-8"))
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    observations = json.loads((root / "observations.json").read_text(encoding="utf-8"))
    sections = [
        {"document_id": d["document_id"], "version": d["version"], "section": name, "sha256": digest}
        for d in catalog["documents"]
        for name, digest in section_hashes(root / d["path"])
    ]
    alerts = [
        # uuid5 under the seed namespace keeps alert UUIDs stable across regenerations and machines.
        {"id": a["id"], "alert_id": str(uuid.uuid5(NS, f"alert/{a['id']}")), "revision": 1}
        for a in observations["alerts"]
    ]
    return {
        "fixture_version": catalog["fixture_version"],
        "meta_version": 1,
        "tenants": dict(seeds["tenants"]),
        "alerts": alerts,
        "sections": sections,
    }


def write_meta(root: Path = FIXTURES) -> Path:
    """Write `root/meta.json` with LF line endings and no BOM; return its path."""
    path = root / "meta.json"
    path.write_text(json.dumps(generate(root), indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    print(write_meta().relative_to(ROOT).as_posix())
```

Run: `PYTHONUTF8=1 uv run python -m scripts.gen_fixture_meta && python -I -c "import json; m=json.load(open('data/handoff-fixtures/meta.json',encoding='utf-8')); print(len(m['alerts']), len(m['sections'])); [print(a['id'], a['alert_id']) for a in m['alerts']]"`
Expected (measured):
```text
data/handoff-fixtures/meta.json
3 10
A17-alert-001 cfa4e790-6f70-5e49-b73f-e9e8d613f52e
A17-alert-002 8fd07823-d6b4-5ffc-a691-3bba680494e1
A17-old-001 4f165b6c-3bda-5839-a401-6be0086b9dfc
```
Task 6's generator reads the two in-window alert UUIDs from `meta.json`; nothing is copied by hand.

- [ ] **Step 4: Teach the checker's base checks about `meta.json`**

In `scripts/verify_handoff.py`, directly below `ROOT = Path(__file__).resolve().parents[1]`, add:
```python
# `python -I` (how CI and the tests run this checker) drops both the script directory and the working directory from
# sys.path, so put the repository root on it explicitly; without this `scripts.*` cannot be imported (the
# scripts/probe.py pattern). The imported module is stdlib-only, so the default checks stay stdlib-only.
sys.path.insert(0, str(ROOT))
from scripts.gen_fixture_meta import generate as generate_fixture_meta

```
(the blank line after the import is the one `ruff check` requires before the next comment block). Then, right after the catalog hash loop (the `for doc in catalog["documents"]:` block), add:
```python
    # meta.json (T45) is derived from the markdown and the seed namespace; a stale copy would let an example cite a
    # section hash that no longer matches the fixture bytes.
    check(
        load("data/handoff-fixtures/meta.json") == generate_fixture_meta(ROOT / "data/handoff-fixtures"),
        "Fixture meta.json is stale: run uv run python -m scripts.gen_fixture_meta",
    )
```
and append `; fixture meta.json current` to the second PASS line's f-string — the line that today reads `f"PASS: {len(catalog['documents'])} source hashes; {len(scenarios)} development scenario cards; {py_count} Python syntax checks; 6 SVG XML files"` — so it ends `… Python syntax checks; 6 SVG XML files; fixture meta.json current"`. In the module docstring, replace the exact sentence `Default checks need only Python's standard library.` (it opens the docstring's second paragraph, on the line after the blank line; the summary line `Validate this handoff package, not the target production application.` stays) with: "Default checks need only Python's standard library (they import the stdlib-only scripts.gen_fixture_meta from this repository)." The rest of that line (` --contracts requires the`) stays as it is.

Append to `data/handoff-fixtures/README.md`:
```markdown

## meta.json (generated, 2026-10-08)

`scripts/gen_fixture_meta.py` derives `meta.json` from this directory and `data/seed-ids.json`; never edit it by hand (`tests/plan_c/test_fixture_meta.py` and `verify_handoff.py` fail on drift). Regenerate with `uv run python -m scripts.gen_fixture_meta`.

- `tenants`: slug → tenant UUID, identical to `data/seed-ids.json`.
- `alerts`: each `observations.json` alert id → `alert_id` = `uuid5(NS, "alert/<id>")` under the repository seed namespace, and `revision` 1 (the delivered observations have no revisions; later fixture versions bump it).
- `sections`: for every `## <name>` heading in every catalog document, the SHA-256 of the section body — the lines after the heading up to the next `## ` heading or end of file, joined with `\n`, with leading and trailing newlines stripped, UTF-8 encoded. The whole-file hashes in `catalog.json` are unchanged.

The schema examples still cite the whole-file hash of `ALPHA-INCIDENT` (`8bc76314…`) as the `content_sha256` of `ALPHA-INCIDENT:v2:review`. Evidence rows switch to these per-section hashes when T17's governed ingestion consumes them — TODO(T17).
```

- [ ] **Step 5: Stage the new files, then run the tests and the checker**

The tracked-copy helper copies `git ls-files`, so new files must be staged first; the commit follows.
```bash
git add scripts/gen_fixture_meta.py data/handoff-fixtures/meta.json data/handoff-fixtures/README.md scripts/verify_handoff.py tests/plan_c/test_fixture_meta.py
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_fixture_meta.py -q 2>&1 | tr -d '\r' | tail -2`
Expected: `5 passed`.

Run: `PYTHONUTF8=1 uv run python -I scripts/verify_handoff.py --reference-code --manifest | tail -6`
Expected: the second PASS line ends with `6 SVG XML files; fixture meta.json current`; then `PASS: synthetic proposal/decision/outcome example hashes agree`, `PASS: 19 inherited source/test/integration files match original snapshot (remapped)`, `PASS: 26 delivered reference/ files byte-identical to handoff-1.0.zip; …`, `PASS: 161 delivered 1.0 snapshot checksums verified against handoff-1.0.zip`, the `LIMIT:` line; exit 0. (The checker inserts `ROOT` into `sys.path` itself, so `python -I` works with or without `uv run`.)

Run: `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tr -d '\r' | tail -3`
Expected: `232 passed`, `11 skipped`, `CHECK: GREEN`.

- [ ] **Step 6: Commit**

```bash
git status --short   # only the five paths above
git commit -m "T45: fixture meta.json with tenant UUIDs, alert UUIDs and per-section hashes, derived and drift-guarded"
```

---

### Task 6: T45a — Generated schemas, examples, negative probes, index 1.3.3, checker `--contracts`, CI

**Files:**
- Create: `scripts/build_schemas.py` (the generator, committed), `tests/plan_c/test_schemas_generated.py` (the drift test). Generated by the script: 14 new schema files — 8 top-level (`feedback`, `manual-proposal`, `revision`, `cancel-response`, `model-pins`, `route`, `run-manifest`, `job`) and 6 tool inputs (`schemas/tools/{get_asset_status,get_recent_alerts,search_procedures,create_incident,get_incident_receipt,abort_incident}.input.schema.json`); 10 new positive examples; 27 new negative examples (the 25 AM-80 probes, plus `event-invalid-occurred-at.json`, which proves the `date-time` check, and `event-invalid-confirmed-application-source.json`, which proves the destination-only source rule).
- Modify (regenerated by the script): the 11 delivered schemas (8 change content: `message`, `decision`, `error`, `model-draft`, `action-outcome`, `proposal`, `event`, `tool-result`; `cancellation`, `clarification`, `evidence` come out byte-identical), the 29 delivered examples (12 change content: `decision-valid`, `decision-invalid-actor`, `proposal-valid` (gains `authored_by`), `outcome-success-valid`, `outcome-unknown-valid`, `outcome-invalid-fake-success` (gains `"tombstone": null, "reason": null`), `outcome-invalid-unknown-receipt`, `tool-create_incident-valid`, `tool-get_incident_receipt-valid`, `tool-get_recent_alerts-valid`, `event-valid`, `event-invalid-model-success` (re-generated with the new payload shape, still the model_summary probe); the other 17 come out byte-identical), and `schemas/examples/index.json`. Also: `schemas/README.md`, `scripts/verify_handoff.py`, `.github/workflows/ci.yml`, `pyproject.toml` and `uv.lock` (`rfc3339-validator`), `tests/plan_a/test_verify_handoff.py`.

**Interfaces:**
- Consumes: the Task 2–4 vocabularies (every enum in a schema is read from `ops_core`: `RunState`, `Reason`, `AttemptState`, `ToolOutcome`, `DestinationState`, `EventType`, `DESTINATION_EVIDENCE`, `FAILED_NO_COMMIT_REASONS`, `Tool`, `JOB_RULES`, `ErrorCode`, `MessageKind`, the route enums); `ops_core.canonical.canonical_sha256` (the example proposal's hash is computed, never typed); Task 5's `meta.json` (the two in-window alert UUIDs) and `observations.json`. The examples are synthetic: `proposal-valid.json`'s `authored_by` is the placeholder `00000000-0000-4000-8000-00000000000a` (distinct from the example's conversation id `…0002`), not a seed persona; T21's fixtures use the seed ids from `data/seed-ids.json`.
- Produces: `scripts/build_schemas.py` with `ROOT`, `schemas() -> dict[str, Doc]`, `examples(root) -> list[tuple[Doc, Doc]]`, `build(root) -> dict[str, Doc]`, `render(doc) -> bytes`, `write(out, root) -> dict[str, int]`, `main()`; the 1.3.6 contract set that `--contracts` proves and Task 7's conformance test ties to the pydantic models.

- [ ] **Step 1: Write the failing checker tests and the drift test**

Append to `tests/plan_a/test_verify_handoff.py` (it already has `_tracked_copy(tmp_path)`, `_run_tree` and `CHECKER`), and add `import os` after `import json` in its imports. The block below begins with two blank lines and they are part of it: the file ends right after its last `assert`, and ruff format requires two blank lines before a top-level `def`, so appending without them turns `check.py` RED.
```python


def _run_contracts(copy: Path) -> subprocess.CompletedProcess[str]:
    """Run `--contracts` on a copy; the checker prints PASS lines to stdout and its FAIL line to stderr."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-I", "scripts/verify_handoff.py", "--contracts"],
        cwd=copy,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_contracts_pass_on_the_committed_tree(tmp_path: Path):
    r = _run_contracts(_tracked_copy(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "negative examples failed for their stated reason" in r.stdout


def test_contracts_fail_when_a_negative_example_validates(tmp_path: Path):
    copy = _tracked_copy(tmp_path)
    p = copy / "schemas/examples/message-invalid-kind-question.json"
    # newline="\n": on Windows the default would write CRLF, and the CR check would then fire first.
    p.write_text(p.read_text(encoding="utf-8").replace('"question"', '"ask"'), encoding="utf-8", newline="\n")
    r = _run_contracts(copy)
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "message-invalid-kind-question.json" in out and "validated" in out


def test_contracts_fail_when_a_negative_fails_for_the_wrong_reason(tmp_path: Path):
    copy = _tracked_copy(tmp_path)
    p = copy / "schemas/examples/message-invalid-kind-question.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["kind"] = "ask"
    doc["tenant_id"] = "x"  # now invalid for an unrelated reason
    p.write_text(json.dumps(doc), encoding="utf-8", newline="\n")
    r = _run_contracts(copy)
    assert r.returncode == 1 and "stated reason" in r.stdout + r.stderr


def test_contracts_reject_a_carriage_return_in_a_governed_file(tmp_path: Path):
    copy = _tracked_copy(tmp_path)
    p = copy / "schemas/examples/message-valid.json"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n", 1))
    r = _run_contracts(copy)
    assert r.returncode == 1 and "carriage return" in r.stdout + r.stderr


def test_contracts_require_index_version(tmp_path: Path):
    copy = _tracked_copy(tmp_path)
    p = copy / "schemas/examples/index.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["version"] = "1.0"
    p.write_text(json.dumps(doc), encoding="utf-8", newline="\n")
    r = _run_contracts(copy)
    assert r.returncode == 1 and "index.json version" in r.stdout + r.stderr
```

Create `tests/plan_c/test_schemas_generated.py`:
```python
"""The committed contract set under schemas/ is exactly what scripts/build_schemas.py generates (T45, AM-80).

Catches: a hand edit of a schema, an example or index.json (the generator is the one source of truth, so the edit
would be lost or, worse, silently disagree with the code's enums), a JSON file under schemas/ that the generator does
not own, and a generator change that was never rerun.
"""

from pathlib import Path

from scripts import build_schemas


def _json_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in (root / "schemas").rglob("*.json")}


def test_every_json_file_under_schemas_is_generated(tmp_path: Path):
    build_schemas.write(tmp_path)
    assert _json_files(build_schemas.ROOT) == _json_files(tmp_path)


def test_committed_files_match_the_generator_byte_for_byte(tmp_path: Path):
    build_schemas.write(tmp_path)
    stale = [
        rel
        for rel in sorted(_json_files(tmp_path))
        if (build_schemas.ROOT / rel).read_bytes() != (tmp_path / rel).read_bytes()
    ]
    assert not stale, f"regenerate with `uv run python -m scripts.build_schemas`: {stale}"
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_a/test_verify_handoff.py -q -k contracts 2>&1 | tr -d '\r' | tail -3`
Expected: `5 failed` (the committed tree has no `version`, no reasons, no `message-invalid-kind-question.json` and no CR or version check).

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_schemas_generated.py -q 2>&1 | tr -d '\r' | tail -3`
Expected: collection fails with `ImportError: cannot import name 'build_schemas' from 'scripts'`; `1 error`.

- [ ] **Step 2: Make the FormatChecker check `date-time`**

Run: `uv add --group dev "rfc3339-validator>=0.1.4,<1"`
Expected (measured): the output ends with `+ rfc3339-validator==0.1.4` and `+ six==1.17.0`; `pyproject.toml`'s dev group gains `"rfc3339-validator>=0.1.4,<1",` and `uv.lock` is updated. Without this package jsonschema's FormatChecker silently skips `date-time`, so `"occurred_at": "yesterday"` validates; with it, `event-invalid-occurred-at.json` (Step 3) fails for exactly that reason.

- [ ] **Step 3: Create the generator**

The schema rules that earlier drafts of this plan described in prose now live in the generator, each beside its reason and spec section. Points a reader should not miss: the write-tool data rules are guarded by `status ∈ [ok, outcome]` (both non-error envelopes carry a well-formed action outcome); `event` rule (3) makes the four destination-evidence types `source=destination` only and rule (7) requires `reason` on `action.failed`, both mirrored by `event_rules_ok` (Task 3); only hashed documents (the proposal) require `Z`: `proposal` timestamps require `Z`; `manual-proposal`, `model-pins` and the `get_recent_alerts` input accept `Z` or `+00:00` (ruling 6); the `job` schema's per-type rows are generated from `JOB_RULES`; every `reason_match` is anchored on the JSON path of jsonschema's best-match error, and alternations appear only for wording that differs between jsonschema versions or for two errors at the same path.

Create `scripts/build_schemas.py`:
```python
"""Generate the contract set under schemas/: 25 JSON Schema documents, every example, and examples/index.json.

Why a generator: the schemas, the examples and the index describe one contract from three angles, and AM-80 changes
all three at once. Hand-editing some ninety JSON files lets them drift apart silently (the dry run of this plan found
examples the prose forgot to update). Here every rule is written once, with its reason beside it, and every enum comes
from `ops_core`, so a schema can never spell a state, reason, tool, job type, route or event type differently from the
code that enforces it. `tests/plan_c/test_schemas_generated.py` regenerates the tree into a temporary directory and
compares every file byte for byte with the committed one, so a hand edit of a generated file fails the build: change
this script and rerun it instead.

Scope: the 19 top-level schemas, the 6 tool-input schemas, all examples and the index. The checker's 26th schema,
`evals/holdout-case.schema.json`, belongs to T03 and is not generated here; `schemas/README.md` stays hand-written.

Paths resolve from the repository root (`ROOT`), never the working directory. Files are written as UTF-8 without a
BOM, with LF line endings, two-space indentation and a trailing newline.

Usage: uv run python -m scripts.build_schemas
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from ops_core.canonical import canonical_sha256
from ops_core.contracts import ErrorCode, MessageKind
from ops_core.jobs import JOB_RULES, Tool
from ops_core.outcomes import DESTINATION_EVIDENCE, FAILED_NO_COMMIT_REASONS, DestinationState, EventType, ToolOutcome
from ops_core.routing import AdmissionRoute, GraphRoute, ModelRoute
from ops_core.states import AttemptState, Reason, RunState

ROOT = Path(__file__).resolve().parents[1]
Doc = dict[str, Any]

COMMENT = (
    "Target contract. Declarative validation does not implement authentication, authorization, semantic support, "
    "atomicity, or runtime integrations."
)
NOTE = "Synthetic target contract example; not a live result."

# --- Vocabularies, all read from ops_core so schema and code cannot disagree on a spelling. ---
STATES = [s.value for s in RunState]
REASONS = [r.value for r in Reason]
FAILED_REASONS = [r.value for r in Reason if r in FAILED_NO_COMMIT_REASONS]  # plan ruling 2 adds `expired`
TOOL_OUTCOMES = [o.value for o in ToolOutcome]
EVENT_TYPES = [e.value for e in EventType]
DESTINATION_TYPES = [e.value for e in EventType if e in DESTINATION_EVIDENCE]
TOOLS = [t.value for t in Tool]
READ_TOOLS = [Tool.GET_ASSET_STATUS.value, Tool.GET_RECENT_ALERTS.value, Tool.SEARCH_PROCEDURES.value]
RECEIPT_TOOLS = [Tool.CREATE_INCIDENT.value, Tool.GET_INCIDENT_RECEIPT.value]  # data = the action-outcome shape
WRITE_TOOLS = [*RECEIPT_TOOLS, Tool.ABORT_INCIDENT.value]

# --- Building blocks. ---
UUID: Doc = {"type": "string", "format": "uuid"}
DATE_TIME: Doc = {"type": "string", "format": "date-time"}  # checked by FormatChecker via rfc3339-validator
# Ruling 6: only a hashed document (the proposal) spells UTC the way pydantic's JSON mode emits it (`Z`), so one
# instant has one spelling inside a hash; manual-proposal, model-pins and the get_recent_alerts input accept `Z` or
# `+00:00`, and the contract normalises before hashing.
UTC_HASHED: Doc = {**DATE_TIME, "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?Z$"}
UTC_REQUEST: Doc = {**DATE_TIME, "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|\\+00:00)$"}
SHA256: Doc = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
DIGEST: Doc = {"type": "string", "pattern": "^[0-9a-f]{64}$"}  # bare hex, as ops_core.model_pins (AM-31)
ASSET_ID: Doc = {"type": "string", "pattern": "^[A-Z][A-Z0-9_-]{0,31}$"}
NULL: Doc = {"type": "null"}


def text(min_length: int, max_length: int) -> Doc:
    """A string with length bounds."""
    return {"type": "string", "minLength": min_length, "maxLength": max_length}


def integer(minimum: int, maximum: int | None = None) -> Doc:
    """An integer with an inclusive lower (and optional upper) bound."""
    return {"type": "integer", "minimum": minimum} | ({} if maximum is None else {"maximum": maximum})


def array(items: Doc, min_items: int, max_items: int, *, unique: bool = False) -> Doc:
    """A bounded array; `unique` adds uniqueItems."""
    doc: Doc = {"type": "array", "items": items, "minItems": min_items, "maxItems": max_items}
    return doc | ({"uniqueItems": True} if unique else {})


def nullable(schema: Doc) -> Doc:
    """The schema or JSON null."""
    return {"anyOf": [schema, NULL]}


def closed(properties: Doc, required: list[str], **extra: Any) -> Doc:
    """A closed object: `additionalProperties: false` is how authority fields are rejected at every depth (R004)."""
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": required} | extra


def head(name: str, title: str | None = None) -> Doc:
    """The header every contract carries (kept from the delivered 1.0 schemas)."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:operations-copilot:schema:{name}:1",
        "title": title or f"Operations Copilot target {name} v1",
        "$comment": COMMENT,
    }


def contract(name: str, body: Doc, title: str | None = None) -> Doc:
    """A top-level schema: header plus a closed object body."""
    return head(name, title) | body


def when(condition: Doc, then: Doc, otherwise: Doc | None = None) -> Doc:
    """An if/then(/else) rule.

    Every property an `if` tests is top-level `required`, so a missing property cannot satisfy a condition vacuously.
    """
    return {"if": condition, "then": then} | ({} if otherwise is None else {"else": otherwise})


def props(**properties: Doc) -> Doc:
    """`{"properties": {...}}`, the shape of every if/then condition and consequence below."""
    return {"properties": properties}


EVIDENCE_REF = text(1, 160)
SHORT = text(1, 500)
RECEIPT = closed(
    {"receipt_id": UUID, "incident_id": text(1, 100), "committed_at": DATE_TIME},
    ["receipt_id", "incident_id", "committed_at"],
)
# AM-13 "Tombstone shape": returned for ABORTED and REJECTED keys only; a COMMITTED key has a receipt instead.
TOMBSTONE = closed(
    {
        "action_id": UUID,
        "state": {"type": "string", "enum": [DestinationState.ABORTED.value, DestinationState.REJECTED.value]},
        "payload_sha256": SHA256,
        "reason": SHORT,
        "decided_at": DATE_TIME,
    },
    ["action_id", "state", "payload_sha256", "reason", "decided_at"],
)
EVIDENCE_ROW = closed(
    {
        "evidence_id": EVIDENCE_REF,
        "document_id": text(1, 100),
        "version": text(1, 40),
        "section": text(1, 120),
        "content_sha256": SHA256,
        "excerpt": text(1, 8000),
        "effective_from": DATE_TIME,
        "retrieved_at": DATE_TIME,
    },
    ["evidence_id", "document_id", "version", "section", "content_sha256", "excerpt", "effective_from", "retrieved_at"],
)


def action_outcome() -> Doc:
    """The write-tool result (AM-13, AM-15): the status and its evidence must agree, mirrored by ActionOutcome."""
    return closed(
        {
            "status": {"enum": TOOL_OUTCOMES},
            "action_id": UUID,
            "payload_sha256": SHA256,
            "receipt": nullable(RECEIPT),
            "tombstone": nullable(TOMBSTONE),
            "reason": nullable({"type": "string", "enum": FAILED_REASONS}),
        },
        ["status", "action_id", "payload_sha256", "receipt", "tombstone", "reason"],
        allOf=[
            # Only a receipt proves a commit (BUILD_SPEC §14): SUCCEEDED carries exactly a receipt.
            when(
                props(status={"const": ToolOutcome.SUCCEEDED.value}),
                props(receipt=RECEIPT, tombstone=NULL, reason=NULL),
            ),
            # A tombstone proves no commit; the reason comes from the FAILED set (AM-13 outcome vocabulary).
            when(
                props(status={"const": ToolOutcome.FAILED_NO_COMMIT.value}),
                props(tombstone=TOMBSTONE, receipt=NULL, reason={"type": "string", "enum": FAILED_REASONS}),
            ),
            # UNKNOWN and CONFLICT prove nothing either way, so they carry no evidence and no reason.
            when(
                props(status={"enum": [ToolOutcome.UNKNOWN.value, ToolOutcome.CONFLICT.value]}),
                props(receipt=NULL, tombstone=NULL, reason=NULL),
            ),
        ],
    )


def abort_outcome() -> Doc:
    """`abort_incident` data: the destination answers an abort with a receipt (already committed) or a tombstone."""
    return closed(
        {
            "action_id": UUID,
            "outcome": {"enum": [ToolOutcome.SUCCEEDED.value, ToolOutcome.FAILED_NO_COMMIT.value]},
            "receipt": nullable(RECEIPT),
            "tombstone": nullable(TOMBSTONE),
        },
        ["action_id", "outcome", "receipt", "tombstone"],
        allOf=[
            when(
                props(outcome={"const": ToolOutcome.SUCCEEDED.value}),
                props(receipt=RECEIPT, tombstone=NULL),
                props(tombstone=TOMBSTONE, receipt=NULL),
            )
        ],
    )


def message() -> Doc:
    """`POST /conversations/{id}/messages` (AM-80 message row)."""
    context = closed({"asset_id": ASSET_ID, "hours": integer(1, 168)}, [])
    return contract(
        "message",
        closed(
            {
                "kind": {"enum": [k.value for k in MessageKind]},  # 1.0's `question` is gone
                "text": text(1, 4000),
                "context": context,
                "supersedes_run_id": UUID,  # requester-asserted and structured (AM-10); optional
            },
            ["kind", "text"],
        ),
    )


def clarification() -> Doc:
    """The clarification reply; it must answer something (minProperties 1)."""
    context = closed({"asset_id": ASSET_ID, "hours": integer(1, 168)}, [], minProperties=1)
    return contract(
        "clarification",
        closed(
            {"question_id": UUID, "expected_version": integer(1), "context": context},
            ["question_id", "expected_version", "context"],
        ),
    )


def decision() -> Doc:
    """`POST /proposals/{id}/decisions`; `expected_payload_sha256` replaces 1.0's `payload_sha256` (AM-11, AM-80)."""
    return contract(
        "decision",
        closed(
            {
                "expected_revision": integer(1),
                "expected_payload_sha256": SHA256,
                "decision": {"enum": ["approve", "reject"]},
                "reason": text(0, 500),
            },
            ["expected_revision", "expected_payload_sha256", "decision"],
        ),
    )


def cancellation() -> Doc:
    """`POST /runs/{id}/cancel` request body (unchanged from 1.0)."""
    return contract(
        "cancellation", closed({"expected_version": integer(1), "reason": text(0, 500)}, ["expected_version"])
    )


def error() -> Doc:
    """BUILD_SPEC §7 safe error; the code list is ops_core's ErrorCode (AM-80 error row)."""
    return contract(
        "error",
        closed(
            {
                "code": {"type": "string", "enum": [c.value for c in ErrorCode]},
                "message": SHORT,
                "retryable": {"type": "boolean"},
                "request_id": UUID,
            },
            ["code", "message", "retryable", "request_id"],
        ),
    )


def evidence() -> Doc:
    """A retrieval row (unchanged from 1.0; per-section hashes are consumed from T17)."""
    return contract("evidence", EVIDENCE_ROW)


def model_draft() -> Doc:
    """The validated model output (AM-10 clarification signal, AM-80 model-draft row)."""
    return contract(
        "model-draft",
        closed(
            {
                "kind": {"enum": ["proposal", "answer", "abstain"]},
                "title": text(1, 120),
                "summary": text(1, 2500),
                "evidence_refs": array(EVIDENCE_REF, 0, 8, unique=True),
                "assumptions": array(SHORT, 0, 8),
                "limitations": array(SHORT, 0, 8),
                "question": SHORT,  # abstain + question = clarification; abstain alone = insufficient evidence
            },
            ["kind", "title", "summary", "evidence_refs", "assumptions", "limitations"],
            allOf=[
                when(props(kind={"enum": ["proposal", "answer"]}), props(evidence_refs={"minItems": 1})),
                # Only an abstain asks a question. The draft never carries supersedes_run_id: the closed object
                # already rejects it (AM-13 asset guard, R125).
                {"if": props(kind={"const": "abstain"}), "else": {"not": {"required": ["question"]}}},
            ],
        ),
    )


def proposal() -> Doc:
    """An immutable proposal revision (BUILD_SPEC §6, AM-80 proposal row)."""
    snapshot = closed(
        {"evidence_id": EVIDENCE_REF, "content_sha256": SHA256, "version": text(1, 40)},
        ["evidence_id", "content_sha256", "version"],
    )
    payload = closed(
        {
            "tenant_id": UUID,
            "run_id": UUID,
            "proposal_id": UUID,
            "revision": integer(1),
            "action": {"const": "create_incident"},
            "destination": {"const": "synthetic-incidents"},
            "asset_id": ASSET_ID,
            "start_at": UTC_HASHED,
            "end_at": UTC_HASHED,
            "title": text(1, 120),
            "summary": text(1, 2500),
            # Sorted order (code rule, ProposalPayload) cannot be said in JSON Schema; uniqueness can.
            "evidence_refs": array(EVIDENCE_REF, 1, 8, unique=True),
            "source_snapshots": array(snapshot, 1, 8),
            "assumptions": array(SHORT, 0, 8),
            "limitations": array(SHORT, 0, 8),
            "workflow_version": text(1, 60),
            "prompt_version": text(1, 60),
            "expires_at": UTC_HASHED,
            # Inside the hashed payload, injected by freeze_proposal from runs (AM-13 asset guard, R125); optional.
            "supersedes_run_id": UUID,
        },
        [
            "tenant_id",
            "run_id",
            "proposal_id",
            "revision",
            "action",
            "destination",
            "asset_id",
            "start_at",
            "end_at",
            "title",
            "summary",
            "evidence_refs",
            "source_snapshots",
            "assumptions",
            "limitations",
            "workflow_version",
            "prompt_version",
            "expires_at",
        ],
    )
    return contract(
        "proposal",
        closed(
            {
                "canonicalization_version": {"const": 1},
                "payload": payload,
                "payload_sha256": SHA256,
                # Outside the hash, a sibling of payload: the requester plus revision authors (AM-80 proposal row).
                "authored_by": array(UUID, 1, 8, unique=True),
            },
            ["canonicalization_version", "payload", "payload_sha256", "authored_by"],
        ),
    )


def event() -> Doc:
    """The run event (AM-14): types, payload fields and the rules on who may assert an outcome."""
    payload = closed(
        {
            "message": text(0, 2500),
            "status": {"enum": STATES},
            "evidence_refs": array(EVIDENCE_REF, 0, 8, unique=True),
            "proposal_id": UUID,
            "action_id": UUID,
            "code": text(1, 80),
            "reason": {"type": "string", "enum": REASONS},
            "outcome": {"type": "string", "enum": [ToolOutcome.SUCCEEDED.value, ToolOutcome.FAILED_NO_COMMIT.value]},
            "receipt": RECEIPT,  # replaces 1.0's flat receipt_id/incident_id
            "tombstone": TOMBSTONE,
        },
        [],
    )
    summary_payload = closed(
        {"message": text(1, 2500), "evidence_refs": array(EVIDENCE_REF, 0, 8, unique=True)}, ["message"]
    )
    return contract(
        "event",
        closed(
            {
                "event_id": UUID,
                "tenant_id": UUID,
                "conversation_id": UUID,
                "run_id": UUID,
                "sequence": integer(1),
                "type": {"enum": EVENT_TYPES},
                "occurred_at": DATE_TIME,
                "source": {"enum": ["application", "destination", "model_summary"]},
                "payload": payload,
            },
            [
                "event_id",
                "tenant_id",
                "conversation_id",
                "run_id",
                "sequence",
                "type",
                "occurred_at",
                "source",
                "payload",
            ],
            allOf=[
                # (1) model_summary may emit only explanation.ready, with no status (AM-14, R083).
                when(
                    props(source={"const": "model_summary"}),
                    props(type={"const": EventType.EXPLANATION_READY.value}, payload=summary_payload),
                ),
                # (2) source=destination only on the four destination-evidence types ...
                when(props(source={"const": "destination"}), props(type={"enum": DESTINATION_TYPES})),
                # (3) ... and those four only with source=destination: record_outcome emits them (AM-20.3), and
                # append_event refuses action.* from application callers.
                when(props(type={"enum": DESTINATION_TYPES}), props(source={"const": "destination"})),
                # (4) action.*, run.* and review.* come from the application or the destination (AM-14).
                when(
                    props(type={"pattern": "^(action|run|review)\\."}),
                    props(source={"enum": ["application", "destination"]}),
                ),
                # (5) action.confirmed requires a receipt and SUCCEEDED (AM-14).
                when(
                    props(type={"const": EventType.ACTION_CONFIRMED.value}),
                    props(payload={"required": ["status", "receipt"], **props(status={"const": "SUCCEEDED"})}),
                ),
                # (6) action.late_evidence requires the destination outcome plus a receipt or tombstone (AM-10).
                when(
                    props(type={"const": EventType.ACTION_LATE_EVIDENCE.value}),
                    props(
                        payload={
                            "required": ["outcome"],
                            "anyOf": [{"required": ["receipt"]}, {"required": ["tombstone"]}],
                        }
                    ),
                ),
                # (7) action.failed says why (AM-14 "action.failed (with reason)").
                when(
                    props(type={"const": EventType.ACTION_FAILED.value}),
                    props(payload={"required": ["reason"]}),
                ),
            ],
        ),
    )


def tool_result() -> Doc:
    """The MCP tool-result envelope (AM-15, AM-80 tool-result row)."""
    error_object = closed(
        {"code": text(1, 80), "message": SHORT, "retryable": {"type": "boolean"}}, ["code", "message", "retryable"]
    )
    alert = closed(
        {
            "alert_id": UUID,
            "asset_id": ASSET_ID,
            "occurred_at": DATE_TIME,
            "code": text(1, 80),
            "message": SHORT,
            "revision": integer(1),
        },
        ["alert_id", "asset_id", "occurred_at", "code", "message", "revision"],
    )
    read_data = {
        Tool.GET_ASSET_STATUS.value: closed(
            {
                "asset_id": ASSET_ID,
                "state": {"enum": ["normal", "warning", "unavailable"]},
                "revision": integer(1),
                "observed_at": DATE_TIME,
                "data_source": {"const": "synthetic"},
            },
            ["asset_id", "state", "revision", "observed_at", "data_source"],
        ),
        Tool.GET_RECENT_ALERTS.value: closed(
            {
                "asset_id": ASSET_ID,
                "start_at": DATE_TIME,
                "end_at": DATE_TIME,
                "alerts": array(alert, 0, 100),
                "next_cursor": nullable(text(1, 200)),  # AM-80: pagination is explicit; null on the last page
            },
            ["asset_id", "start_at", "end_at", "alerts", "next_cursor"],
        ),
        Tool.SEARCH_PROCEDURES.value: closed(
            {
                "results": array(EVIDENCE_ROW, 0, 8),
                "retrieval_mode": {"enum": ["lexical", "vector_exact"]},  # plan ruling 3
                "corpus_version": text(1, 100),
            },
            ["results", "retrieval_mode", "corpus_version"],
        ),
    }
    rules: list[Doc] = [
        # An error envelope carries an error and no data; every other envelope carries no error.
        when(props(status={"const": "error"}), props(data=NULL, error=error_object), props(error=NULL)),
        # Read tools answer `ok` (or `error`); their data shapes are checked only on `ok`.
        *(
            when(props(tool_name={"const": name}, status={"const": "ok"}), props(data=shape))
            for name, shape in read_data.items()
        ),
        # Write-tool data shapes apply to both non-error envelopes, `ok` and `outcome` (status ∈ [ok, outcome]):
        # `outcome` is not an error, and its data must still be a well-formed action outcome.
        *(
            when(props(tool_name={"const": name}, status={"enum": ["ok", "outcome"]}), props(data=action_outcome()))
            for name in RECEIPT_TOOLS
        ),
        when(
            props(tool_name={"const": Tool.ABORT_INCIDENT.value}, status={"enum": ["ok", "outcome"]}),
            props(data=abort_outcome()),
        ),
        # (a) A read tool never reports an action outcome.
        when(props(tool_name={"enum": READ_TOOLS}), props(status={"enum": ["ok", "error"]})),
        # (b) `outcome` belongs to write tools and always names the action (AM-80: action_id required on outcomes).
        when(
            props(status={"const": "outcome"}),
            props(tool_name={"enum": WRITE_TOOLS}, data={"type": "object", "required": ["action_id"]}),
        ),
        # (c) Envelope/data agreement (R083): `outcome` never wraps a success ...
        when(
            {**props(status={"const": "outcome"}, tool_name={"enum": RECEIPT_TOOLS}), "required": ["tool_name"]},
            props(data=props(status={"enum": ["UNKNOWN", "CONFLICT", "FAILED_NO_COMMIT"]})),
        ),
        # (d) ... and `ok` wraps nothing but a success: `ok` + UNKNOWN is the R083 probe.
        when(
            {**props(status={"const": "ok"}, tool_name={"enum": RECEIPT_TOOLS}), "required": ["tool_name"]},
            props(data=props(status={"const": "SUCCEEDED"})),
        ),
        # (e) The same agreement for abort_incident: `ok` iff the destination already held a receipt.
        when(
            {
                **props(status={"const": "ok"}, tool_name={"const": Tool.ABORT_INCIDENT.value}),
                "required": ["tool_name"],
            },
            props(data=props(outcome={"const": "SUCCEEDED"})),
        ),
        when(
            {
                **props(status={"const": "outcome"}, tool_name={"const": Tool.ABORT_INCIDENT.value}),
                "required": ["tool_name"],
            },
            props(data=props(outcome={"const": "FAILED_NO_COMMIT"})),
        ),
    ]
    return contract(
        "tool-result",
        closed(
            {
                "tool_name": {"enum": TOOLS},
                "request_id": UUID,
                "status": {"enum": ["ok", "error", "outcome"]},  # 1.0's `unknown` is gone (AM-80)
                "observed_at": DATE_TIME,
                "truncated": {"type": "boolean"},
                "data": {"type": ["object", "null"]},
                "error": nullable(error_object),
            },
            ["tool_name", "request_id", "status", "observed_at", "truncated", "data", "error"],
            allOf=rules,
        ),
    )


def feedback() -> Doc:
    """`POST /runs/{id}/feedback`: classified, stored, never a runtime policy (AM-14, R113)."""
    return contract(
        "feedback",
        closed(
            {
                "subject_kind": {"enum": ["run", "proposal", "event"]},
                "subject_id": UUID,
                "category": {"enum": ["wrong_evidence", "missing_evidence", "wrong_conclusion", "unclear", "other"]},
                "text": text(0, 2000),
            },
            ["subject_kind", "subject_id", "category"],
        ),
    )


def manual_proposal() -> Doc:
    """`POST /manual-proposals`: a request body, so either zero-offset spelling is accepted (ruling 6)."""
    return contract(
        "manual-proposal",
        closed(
            {
                "asset_id": ASSET_ID,
                "start_at": UTC_REQUEST,
                "end_at": UTC_REQUEST,
                "title": text(1, 120),
                "summary": text(1, 2500),
                "evidence_refs": array(EVIDENCE_REF, 1, 8, unique=True),
                "assumptions": array(SHORT, 0, 8),
                "limitations": array(SHORT, 0, 8),
            },
            ["asset_id", "start_at", "end_at", "title", "summary", "evidence_refs", "assumptions", "limitations"],
        ),
    )


def revision() -> Doc:
    """`POST /runs/{id}/revisions` with the requester-asserted supersedes_run_id (AM-10)."""
    return contract(
        "revision", closed({"expected_version": integer(1), "supersedes_run_id": UUID}, ["expected_version"])
    )


def cancel_response() -> Doc:
    """The cancel response reports whether a grant or dispatch already happened; it never claims undo (AM-13)."""
    return contract(
        "cancel-response",
        closed(
            {
                "run_id": UUID,
                "status": {"enum": STATES},
                "state_version": integer(1),
                "cancel_requested": {"type": "boolean"},
                "grant_exists": {"type": "boolean"},
                "attempt_state": nullable({"enum": [a.value for a in AttemptState]}),
                "note": nullable(SHORT),
            },
            ["run_id", "status", "state_version", "cancel_requested", "grant_exists", "attempt_state", "note"],
            allOf=[when(props(grant_exists={"const": False}), props(attempt_state=NULL))],  # no grant, no attempt
        ),
    )


def model_pins() -> Doc:
    """data/model-pins.json (AM-31). Written by scripts/probe.py with `datetime.now(UTC).isoformat()`, i.e. `+00:00`.

    The file is not hashed, so ruling 6's `Z`-only spelling (reserved for hashed documents) does not apply: either
    zero-offset spelling is accepted here. `ops_core.model_pins` accepts any aware timestamp; the schema additionally
    pins a zero offset.
    """
    return contract(
        "model-pins",
        closed(
            {"model": text(1, 200), "digest": DIGEST, "ollama_version": text(1, 80), "probed_at": UTC_REQUEST},
            ["model", "digest", "ollama_version", "probed_at"],
        ),
    )


def route() -> Doc:
    """The three routers' enumerable routes (AM-16); a document names at least one."""
    return contract(
        "route",
        closed(
            {
                "admission": {"enum": [r.value for r in AdmissionRoute]},
                "graph": {"enum": [r.value for r in GraphRoute]},
                "model": {"enum": [r.value for r in ModelRoute]},
            },
            [],
            minProperties=1,
        ),
    )


def run_manifest() -> Doc:
    """What produced a run's draft (AM-80 run-manifest row); mirrored by ops_core.routing.RunManifest."""
    return contract(
        "run-manifest",
        closed(
            {
                "run_id": UUID,
                "model_route": {"enum": [r.value for r in ModelRoute]},
                "model_digest": nullable(DIGEST),
                "prompt_version": text(1, 60),
                "corpus_version": text(1, 100),
                "retrieval_mode": {"enum": ["lexical", "vector_exact"]},
            },
            ["run_id", "model_route", "model_digest", "prompt_version", "corpus_version", "retrieval_mode"],
            # The fake route has nothing to pin; every real model records the digest the worker verified (AM-31).
            allOf=[
                when(
                    props(model_route={"not": {"const": ModelRoute.FAKE.value}}), props(model_digest={"type": "string"})
                )
            ],
        ),
    )


def exactly(values: list[str]) -> Doc:
    """An array (already uniqueItems) holding exactly these values, in any order."""
    if not values:
        return {"maxItems": 0}
    return {"items": {"enum": values}, "minItems": len(values), "maxItems": len(values)}


def job() -> Doc:
    """The AM-15 job-type table as a document: each type's row is generated from ops_core.jobs.JOB_RULES."""
    per_type = [
        when(
            props(type={"const": job_type.value}),
            props(
                allowed_tools=exactly([t.value for t in Tool if t in rule.allowed_tools]),
                run_states=exactly([s.value for s in RunState if s in rule.run_states]),
            ),
        )
        for job_type, rule in JOB_RULES.items()
    ]
    return contract(
        "job",
        closed(
            {
                "type": {"enum": [t.value for t in JOB_RULES]},
                "allowed_tools": {"type": "array", "uniqueItems": True, "items": {"enum": TOOLS}},
                "run_states": {"type": "array", "uniqueItems": True, "items": {"enum": STATES}},
                "created_by": {"type": "array", "items": text(1, 80)},
                "dedup_key": text(1, 200),
            },
            ["type", "allowed_tools", "run_states", "created_by", "dedup_key"],
            allOf=per_type,
        ),
    )


def tool_inputs() -> dict[str, Doc]:
    """Input schemas for the six tools (AM-80 tools row).

    Closed objects: a tool argument never carries tenant_id, actor, role, approval or destination (AM-15); the server
    derives all of them from the invocation handle.
    """

    def tool_input(name: str, properties: Doc, required: list[str]) -> Doc:
        return contract(f"tools/{name}-input", closed(properties, required), f"Operations Copilot tool input {name} v1")

    inputs = {
        Tool.GET_ASSET_STATUS.value: tool_input(Tool.GET_ASSET_STATUS.value, {"asset_id": ASSET_ID}, ["asset_id"]),
        Tool.GET_RECENT_ALERTS.value: tool_input(
            Tool.GET_RECENT_ALERTS.value,
            {
                "asset_id": ASSET_ID,
                "start_at": UTC_REQUEST,  # a request: either zero-offset spelling (ruling 6)
                "end_at": UTC_REQUEST,
                "limit": integer(1, 100),
                "cursor": text(1, 200),
            },
            ["asset_id", "start_at", "end_at", "limit"],
        ),
        Tool.SEARCH_PROCEDURES.value: tool_input(
            Tool.SEARCH_PROCEDURES.value,
            {
                "query": SHORT,
                "asset_type": text(1, 40),
                "limit": integer(1, 8),
                "mode": {"enum": ["lexical", "vector_exact"]},  # ruling 3; mcp-read maps vector_exact (TODO(T15))
            },
            ["query", "limit", "mode"],
        ),
    }
    for name in WRITE_TOOLS:
        inputs[name] = tool_input(name, {"proposal_id": UUID}, ["proposal_id"])
    return inputs


def schemas() -> dict[str, Doc]:
    """Every schema document, keyed by its repository-relative path."""
    top = {
        "message": message(),
        "clarification": clarification(),
        "decision": decision(),
        "cancellation": cancellation(),
        "error": error(),
        "evidence": evidence(),
        "model-draft": model_draft(),
        "proposal": proposal(),
        "action-outcome": contract("action-outcome", action_outcome()),
        "event": event(),
        "tool-result": tool_result(),
        "feedback": feedback(),
        "manual-proposal": manual_proposal(),
        "revision": revision(),
        "cancel-response": cancel_response(),
        "model-pins": model_pins(),
        "route": route(),
        "run-manifest": run_manifest(),
        "job": job(),
    }
    out = {f"schemas/{name}.schema.json": doc for name, doc in top.items()}
    out |= {f"schemas/tools/{name}.input.schema.json": doc for name, doc in tool_inputs().items()}
    return out


# --- Examples. Synthetic IDs and fixed times, as delivered in 1.0; T21's fixtures use the seed ids, not these. ---
TENANT = "00000000-0000-4000-8000-000000000001"
CONVERSATION = "00000000-0000-4000-8000-000000000002"
RUN = "00000000-0000-4000-8000-000000000003"
PROPOSAL = "00000000-0000-4000-8000-000000000004"
QUESTION = "00000000-0000-4000-8000-000000000005"
EVENT = "00000000-0000-4000-8000-000000000006"
ACTION = "00000000-0000-4000-8000-000000000007"
RECEIPT_ID = "00000000-0000-4000-8000-000000000008"
REQUEST = "00000000-0000-4000-8000-000000000009"
AUTHOR = "00000000-0000-4000-8000-00000000000a"  # proposal-valid's authored_by: a placeholder, not a seed persona
CLOCK = "2026-10-06T12:00:00Z"  # the fixture clock (data/handoff-fixtures/observations.json)
EVIDENCE_ID = "ALPHA-INCIDENT:v2:review"
# The whole-file hash of the ALPHA-INCIDENT fixture, as delivered. TODO(T17): evidence rows switch to the per-section
# hash from data/handoff-fixtures/meta.json when T17 consumes it.
EVIDENCE_SHA = "8bc7631462663afea7fb457da5159c99f9ef3d3cffe21056d487c45c55931c4a"
EXCERPT = (
    "Repeated simulated warnings may be summarized in a reviewable incident draft. A different authorized reviewer "
    "must inspect the exact content before submission. The warning count alone does not establish root cause."
)
DRAFT_TITLE = "Review repeated synthetic warnings on A17"
DRAFT_SUMMARY = (
    "The supplied synthetic records contain two warnings within the requested interval. An independent reviewer "
    "should inspect the incident draft. Root cause is not established."
)
LIMITATIONS = ["Synthetic data only.", "Root cause is not established."]
COMMITTED_AT = "2026-10-06T12:04:00Z"


def payload() -> Doc:
    """The hashed payload of proposal-valid.json; its hash is computed here, never typed in."""
    return {
        "tenant_id": TENANT,
        "run_id": RUN,
        "proposal_id": PROPOSAL,
        "revision": 1,
        "action": "create_incident",
        "destination": "synthetic-incidents",
        "asset_id": "A17",
        "start_at": "2026-10-05T12:00:00Z",
        "end_at": CLOCK,
        "title": DRAFT_TITLE,
        "summary": DRAFT_SUMMARY,
        "evidence_refs": [EVIDENCE_ID],
        "source_snapshots": [{"evidence_id": EVIDENCE_ID, "content_sha256": EVIDENCE_SHA, "version": "2"}],
        "assumptions": [],
        "limitations": LIMITATIONS,
        "workflow_version": "investigation-v1",
        "prompt_version": "incident-draft-v1",
        "expires_at": "2026-10-06T12:15:00Z",
    }


PAYLOAD_SHA = canonical_sha256(payload())  # 9d5c1fb0…4cf7, unchanged from 1.0 (the payload is ASCII)


def envelope(tool: str, status: str, data: Doc | None, error: Doc | None = None) -> Doc:
    """A tool-result envelope with the fixed request id and fixture clock."""
    return {
        "tool_name": tool,
        "request_id": REQUEST,
        "status": status,
        "observed_at": CLOCK,
        "truncated": False,
        "data": data,
        "error": error,
    }


def outcome(status: str, *, receipt: Doc | None = None, tombstone: Doc | None = None, reason: str | None = None) -> Doc:
    """An action outcome for the example action."""
    return {
        "status": status,
        "action_id": ACTION,
        "payload_sha256": PAYLOAD_SHA,
        "receipt": receipt,
        "tombstone": tombstone,
        "reason": reason,
    }


def event_doc(source: str, payload: Doc, event_type: str = EventType.ACTION_CONFIRMED.value) -> Doc:
    """An event envelope for the example run."""
    return {
        "event_id": EVENT,
        "tenant_id": TENANT,
        "conversation_id": CONVERSATION,
        "run_id": RUN,
        "sequence": 8,
        "type": event_type,
        "occurred_at": "2026-10-06T12:04:01Z",
        "source": source,
        "payload": payload,
    }


def examples(root: Path = ROOT) -> list[tuple[Doc, Doc]]:
    """(index entry, document) for every example, in index order: the delivered 29, then 10 new valid, 27 invalid.

    Reads only data/handoff-fixtures/{meta,observations}.json (the two in-window alerts, AM-80 row "draft/alerts
    consistency") under `root`.
    """
    meta = json.loads((root / "data/handoff-fixtures/meta.json").read_text(encoding="utf-8"))
    observations = json.loads((root / "data/handoff-fixtures/observations.json").read_text(encoding="utf-8"))
    alert_ids = {a["id"]: a["alert_id"] for a in meta["alerts"]}
    receipt = {"receipt_id": RECEIPT_ID, "incident_id": "INC-SYNTHETIC-0001", "committed_at": COMMITTED_AT}
    tombstone = {
        "action_id": ACTION,
        "state": DestinationState.ABORTED.value,
        "payload_sha256": PAYLOAD_SHA,
        "reason": "cancelled before send",
        "decided_at": COMMITTED_AT,
    }
    message_valid = {
        "kind": "investigate",
        "text": "Investigate the alerts on A17 over the last 24 hours.",
        "context": {"asset_id": "A17", "hours": 24},
    }
    draft = {
        "kind": "proposal",
        "title": DRAFT_TITLE,
        "summary": DRAFT_SUMMARY,
        "evidence_refs": [EVIDENCE_ID],
        "assumptions": [],
        "limitations": LIMITATIONS,
    }
    decision_valid = {
        "expected_revision": 1,
        "expected_payload_sha256": PAYLOAD_SHA,
        "decision": "approve",
        "reason": "Reviewed the exact synthetic proposal.",
    }
    proposal_valid = {
        "canonicalization_version": 1,
        "payload": payload(),
        "payload_sha256": PAYLOAD_SHA,
        "authored_by": [AUTHOR],  # synthetic, like the payload's tenant/run/proposal ids
    }
    receipt_unknown = envelope(Tool.GET_INCIDENT_RECEIPT.value, "outcome", outcome("UNKNOWN"))
    event_valid = event_doc("destination", {"status": "SUCCEEDED", "action_id": ACTION, "receipt": receipt})
    in_window = [a for a in observations["alerts"] if a["id"] in ("A17-alert-001", "A17-alert-002")]
    alerts = [
        {
            "alert_id": alert_ids[a["id"]],
            "asset_id": a["asset_id"],
            "occurred_at": a["occurred_at"],
            "code": a["code"],
            "message": a["message"],
            "revision": 1,
        }
        for a in in_window
    ]
    feedback_valid = {
        "subject_kind": "proposal",
        "subject_id": PROPOSAL,
        "category": "wrong_evidence",
        "text": "Cites the superseded version.",
    }
    manual_valid = {
        "asset_id": "A17",
        "start_at": "2026-10-05T12:00:00Z",
        "end_at": CLOCK,
        "title": DRAFT_TITLE,
        "summary": "Two synthetic warnings in the interval.",
        "evidence_refs": [EVIDENCE_ID],
        "assumptions": [],
        "limitations": ["Synthetic data only."],
    }
    cancel_valid = {
        "run_id": RUN,
        "status": "EXECUTING",
        "state_version": 4,
        "cancel_requested": True,
        "grant_exists": True,
        "attempt_state": "SENT",
        "note": "cancellation arrived after dispatch",
    }
    pins_valid = {
        "model": "qwen3:8b",
        "digest": "ab" * 32,
        "ollama_version": "0.12.3",
        "probed_at": "2026-10-08T00:00:00Z",
    }
    manifest_valid = {
        "run_id": RUN,
        "model_route": "fake",
        "model_digest": None,
        "prompt_version": "incident-draft-v1",
        "corpus_version": "fixture-1",
        "retrieval_mode": "lexical",
    }
    failed = outcome("FAILED_NO_COMMIT", tombstone=tombstone, reason="cancelled_before_send")
    asset_status = envelope(
        Tool.GET_ASSET_STATUS.value,
        "ok",
        {"asset_id": "A17", "state": "warning", "revision": 1, "observed_at": CLOCK, "data_source": "synthetic"},
    )
    error_valid = {
        "code": "VERSION_CONFLICT",
        "message": "The proposal has changed. Reload the current revision.",
        "retryable": False,
        "request_id": REQUEST,
    }

    items: list[tuple[Doc, Doc]] = []

    def valid(name: str, schema: str, doc: Doc, note: str = NOTE) -> None:
        entry = {"path": f"schemas/examples/{name}.json", "schema": f"schemas/{schema}.schema.json", "valid": True}
        items.append((entry | {"note": note}, doc))

    def invalid(name: str, schema: str, doc: Doc, reason: str, reason_match: str) -> None:
        # reason_match is anchored on the JSON path of jsonschema's best_match error ("<path>: <message>"), so a
        # negative that fails somewhere else cannot pass for the stated reason (R104); alternations only cover
        # wording that differs between jsonschema versions or two errors at the same path.
        entry = {"path": f"schemas/examples/{name}.json", "schema": f"schemas/{schema}.schema.json", "valid": False}
        items.append((entry | {"note": NOTE, "reason": reason, "reason_match": reason_match}, doc))

    # The delivered 1.0 examples, in their delivered order, updated to the 1.3.6 contract.
    valid("message-valid", "message", message_valid)
    valid(
        "message-clarification-needed",
        "message",
        {"kind": "investigate", "text": "Investigate A17.", "context": {"asset_id": "A17"}},
    )
    invalid(
        "message-invalid-authority",
        "message",
        {"kind": "investigate", "text": "Do it.", "tenant_id": TENANT},
        "A client may not supply tenant_id (R004).",
        "^\\$: Additional properties are not allowed \\('tenant_id'",
    )
    invalid(
        "message-invalid-bool-hours",
        "message",
        {"kind": "investigate", "text": "Check A17.", "context": {"asset_id": "A17", "hours": True}},
        "hours must be an integer, never a boolean.",
        "^\\$\\.context\\.hours: True is not of type 'integer'$",
    )
    valid(
        "clarification-valid",
        "clarification",
        {"question_id": QUESTION, "expected_version": 2, "context": {"asset_id": "A17", "hours": 24}},
    )
    valid("draft-valid", "model-draft", draft)
    valid(
        "draft-abstain-valid",
        "model-draft",
        {
            "kind": "abstain",
            "title": "No suitable approved evidence",
            "summary": "No permitted approved procedure was returned for this investigation.",
            "evidence_refs": [],
            "assumptions": [],
            "limitations": ["Cannot prepare an evidence-backed incident."],
        },
    )
    invalid(
        "draft-invalid-approval",
        "model-draft",
        {**draft, "approved": True},
        "A model may not assert approval.",
        "^\\$: Additional properties are not allowed \\('approved'",
    )
    invalid(
        "draft-invalid-no-evidence",
        "model-draft",
        {**draft, "evidence_refs": []},
        "A proposal cites at least one piece of evidence.",
        "^\\$\\.evidence_refs: \\[\\] (is too short|should be non-empty)$",
    )
    invalid(
        "draft-invalid-duplicate-evidence",
        "model-draft",
        {**draft, "evidence_refs": [EVIDENCE_ID, EVIDENCE_ID]},
        "Evidence references are unique.",
        "^\\$\\.evidence_refs: .* has non-unique elements$",
    )
    valid(
        "evidence-valid",
        "evidence",
        {
            "evidence_id": EVIDENCE_ID,
            "document_id": "ALPHA-INCIDENT",
            "version": "2",
            "section": "review",
            "content_sha256": EVIDENCE_SHA,
            "excerpt": EXCERPT,
            "effective_from": "2026-10-01T00:00:00Z",
            "retrieved_at": CLOCK,
        },
    )
    valid("proposal-valid", "proposal", proposal_valid)
    valid("decision-valid", "decision", decision_valid)
    invalid(
        "decision-invalid-actor",
        "decision",
        {"expected_revision": 1, "expected_payload_sha256": PAYLOAD_SHA, "decision": "approve", "actor_id": "sam"},
        "The reviewer is the session, never a body field.",
        "^\\$: Additional properties are not allowed \\('actor_id'",
    )
    valid("cancellation-valid", "cancellation", {"expected_version": 4, "reason": "Stop pending work."})
    valid("outcome-success-valid", "action-outcome", outcome("SUCCEEDED", receipt=receipt))
    valid("outcome-unknown-valid", "action-outcome", outcome("UNKNOWN"))
    invalid(
        "outcome-invalid-fake-success",
        "action-outcome",
        outcome("SUCCEEDED"),
        "SUCCEEDED without a receipt is a fake success.",
        "^\\$\\.receipt: None is not of type 'object'$",
    )
    invalid(
        "outcome-invalid-unknown-receipt",
        "action-outcome",
        outcome("UNKNOWN", receipt=receipt),
        "A receipt on UNKNOWN would claim a commit nobody verified.",
        "^\\$\\.receipt: .* is not of type 'null'$",
    )
    valid("tool-get_asset_status-valid", "tool-result", asset_status)
    valid(
        "tool-get_recent_alerts-valid",
        "tool-result",
        envelope(
            Tool.GET_RECENT_ALERTS.value,
            "ok",
            {
                "asset_id": "A17",
                "start_at": "2026-10-05T12:00:00Z",
                "end_at": CLOCK,
                "alerts": alerts,
                "next_cursor": None,
            },
        ),
    )
    valid(
        "tool-search_procedures-valid",
        "tool-result",
        envelope(
            Tool.SEARCH_PROCEDURES.value,
            "ok",
            {
                "results": [
                    {
                        "evidence_id": EVIDENCE_ID,
                        "document_id": "ALPHA-INCIDENT",
                        "version": "2",
                        "section": "review",
                        "content_sha256": EVIDENCE_SHA,
                        "excerpt": EXCERPT,
                        "effective_from": "2026-10-01T00:00:00Z",
                        "retrieved_at": CLOCK,
                    }
                ],
                "retrieval_mode": "lexical",
                "corpus_version": "fixture-1",
            },
        ),
    )
    valid(
        "tool-create_incident-valid",
        "tool-result",
        envelope(Tool.CREATE_INCIDENT.value, "ok", outcome("SUCCEEDED", receipt=receipt)),
    )
    valid("tool-get_incident_receipt-valid", "tool-result", receipt_unknown)
    valid(
        "tool-error-valid",
        "tool-result",
        envelope(
            Tool.GET_ASSET_STATUS.value,
            "error",
            None,
            {"code": "FORBIDDEN", "message": "This operation is not available.", "retryable": False},
        ),
    )
    valid("event-valid", "event", event_valid)
    invalid(
        "event-invalid-model-success",
        "event",
        event_doc("model_summary", event_valid["payload"]),
        "model_summary may emit only explanation.ready, never an outcome (R083).",
        "^\\$\\.type: 'explanation\\.ready' was expected$",
    )
    valid("error-valid", "error", error_valid)
    valid(
        "draft-answer-valid",
        "model-draft",
        {
            "kind": "answer",
            "title": "Summary of synthetic A17 observations",
            "summary": DRAFT_SUMMARY,
            "evidence_refs": [EVIDENCE_ID],
            "assumptions": [],
            "limitations": LIMITATIONS,
        },
        "Synthetic read-only answer shape, not a write or actual model result.",
    )

    # New positive examples (one per new schema, plus abort_incident and one tool input).
    valid("feedback-valid", "feedback", feedback_valid)
    valid("manual-proposal-valid", "manual-proposal", manual_valid)
    valid("revision-valid", "revision", {"expected_version": 3, "supersedes_run_id": RUN})
    valid("cancel-response-valid", "cancel-response", cancel_valid)
    valid("model-pins-valid", "model-pins", pins_valid)
    valid("route-valid", "route", {"admission": "investigate", "graph": "retrieve", "model": "fake"})
    valid("run-manifest-valid", "run-manifest", manifest_valid)
    valid(
        "job-valid",
        "job",
        {
            "type": "recover",
            "allowed_tools": WRITE_TOOLS,
            "run_states": ["EXECUTING", "OUTCOME_UNKNOWN", "ESCALATED", "ABANDONED_UNVERIFIED"],
            "created_by": ["mark_unknown", "worker", "reclaim_leases"],
            "dedup_key": f"{ACTION}:timeout",
        },
    )
    valid(
        "tool-abort_incident-valid",
        "tool-result",
        envelope(
            Tool.ABORT_INCIDENT.value,
            "outcome",
            {"action_id": ACTION, "outcome": "FAILED_NO_COMMIT", "receipt": None, "tombstone": tombstone},
        ),
    )
    valid("tools-create_incident-input-valid", "tools/create_incident.input", {"proposal_id": PROPOSAL})

    # Negative probes: one per AM-80 row, each derived from a valid example with exactly one change.
    no_receipt = copy.deepcopy(event_valid)
    del no_receipt["payload"]["receipt"]
    invalid(
        "event-invalid-confirmed-no-receipt",
        "event",
        no_receipt,
        "action.confirmed requires a receipt (R083).",
        "^\\$\\.payload: 'receipt' is a required property$",
    )
    invalid(
        "event-invalid-destination-granted",
        "event",
        event_doc("destination", {"status": "EXECUTING", "action_id": ACTION}, EventType.ACTION_GRANTED.value),
        "source=destination only on the four destination-evidence types.",
        "^\\$\\.type: 'action\\.granted' is not one of",
    )
    invalid(
        "event-invalid-late-evidence-no-outcome",
        "event",
        event_doc("destination", {"action_id": ACTION, "tombstone": tombstone}, EventType.ACTION_LATE_EVIDENCE.value),
        "action.late_evidence requires the destination outcome.",
        "^\\$\\.payload: 'outcome' is a required property$",
    )
    invalid(
        "event-invalid-confirmed-application-source",
        "event",
        {**event_valid, "source": "application"},
        "action.confirmed comes only from record_outcome with source=destination.",
        "^\\$\\.source: 'destination' was expected$",
    )
    invalid(
        "event-invalid-occurred-at",
        "event",
        {**event_valid, "occurred_at": "yesterday"},
        "occurred_at must be an RFC 3339 date-time (FormatChecker with rfc3339-validator).",
        "^\\$\\.occurred_at: 'yesterday' is not a 'date-time'$",
    )
    invalid(
        "tool-invalid-ok-unknown",
        "tool-result",
        {**receipt_unknown, "status": "ok"},
        "Envelope ok must wrap a success, never UNKNOWN (R083).",
        "^\\$\\.data\\.status: ('SUCCEEDED' was expected|'UNKNOWN' is not one of \\['SUCCEEDED'\\])$",
    )
    no_action = copy.deepcopy(receipt_unknown)
    del no_action["data"]["action_id"]
    invalid(
        "tool-invalid-outcome-no-action-id",
        "tool-result",
        no_action,
        "An outcome always names its action (R083).",
        "^\\$\\.data: 'action_id' is a required property$",
    )
    invalid(
        "tool-invalid-status-unknown",
        "tool-result",
        {**envelope(Tool.CREATE_INCIDENT.value, "ok", outcome("SUCCEEDED", receipt=receipt)), "status": "unknown"},
        "The 1.0 envelope status unknown is gone (probed on a create_incident success).",
        "^\\$\\.status: 'unknown' is not one of",
    )
    invalid(
        "tool-invalid-read-tool-outcome",
        "tool-result",
        {**asset_status, "status": "outcome"},
        "A read tool cannot return an outcome envelope: rule (b) restricts `outcome` to the write tools.",
        "^\\$\\.tool_name: 'get_asset_status' is not one of",
    )
    invalid(
        "draft-invalid-empty-question",
        "model-draft",
        {**draft, "kind": "abstain", "evidence_refs": [], "question": ""},
        "An empty question is no question.",
        "^\\$\\.question: '' (is too short|should be non-empty)$",
    )
    invalid(
        "draft-invalid-question-on-proposal",
        "model-draft",
        {**draft, "question": "Which interval?"},
        "Only an abstain carries a question.",
        "^\\$: .* should not be valid under \\{'required': \\['question'\\]\\}$",
    )
    invalid(
        "feedback-invalid-authority",
        "feedback",
        {**feedback_valid, "actor_id": TENANT},
        "A client may not supply actor_id (R004).",
        "^\\$: Additional properties are not allowed \\('actor_id'",
    )
    invalid(
        "manual-proposal-invalid-authored-by",
        "manual-proposal",
        {**manual_valid, "authored_by": [TENANT]},
        "authored_by is derived by the server, never supplied.",
        "^\\$: Additional properties are not allowed \\('authored_by'",
    )
    invalid(
        "revision-invalid-supersedes",
        "revision",
        {"expected_version": 3, "supersedes_run_id": "run-7"},
        "supersedes_run_id is a run UUID.",
        "^\\$\\.supersedes_run_id: 'run-7' is not a 'uuid'$",
    )
    invalid(
        "cancel-response-invalid-attempt-without-grant",
        "cancel-response",
        {**cancel_valid, "grant_exists": False},
        "An attempt state exists only after a grant.",
        "^\\$\\.attempt_state: 'SENT' is not of type 'null'$",
    )
    invalid(
        "error-invalid-unknown-code",
        "error",
        {**error_valid, "code": "OOPS"},
        "Error codes come from the documented set.",
        "^\\$\\.code: 'OOPS' is not one of",
    )
    invalid(
        "tools-create_incident-input-invalid-tenant",
        "tools/create_incident.input",
        {"proposal_id": PROPOSAL, "tenant_id": TENANT},
        "Tool arguments never carry tenant_id (AM-15).",
        "^\\$: Additional properties are not allowed \\('tenant_id'",
    )
    invalid(
        "outcome-invalid-failed-reason",
        "action-outcome",
        {**failed, "reason": "conflict"},
        "conflict is not a FAILED_NO_COMMIT reason.",
        "^\\$\\.reason: 'conflict' is not one of",
    )
    invalid(
        "outcome-invalid-committed-tombstone",
        "action-outcome",
        {**failed, "tombstone": {**tombstone, "state": "COMMITTED"}},
        "A COMMITTED key has a receipt, not a tombstone.",
        "^\\$\\.tombstone\\.state: 'COMMITTED' is not one of",
    )
    invalid(
        "model-pins-invalid-prefixed-digest",
        "model-pins",
        {**pins_valid, "digest": "sha256:" + "ab" * 32},
        "The digest is bare hex (AM-31).",
        "^\\$\\.digest: '.*' does not match",
    )
    invalid(
        "message-invalid-kind-question",
        "message",
        {**message_valid, "kind": "question"},
        "The 1.0 kind question is gone.",
        "^\\$\\.kind: 'question' is not one of",
    )
    invalid(
        "run-manifest-invalid-model-route",
        "run-manifest",
        {**manifest_valid, "model_route": "gpt"},
        "Unknown model route.",
        "^\\$\\.model_route: 'gpt' is not one of",
    )
    invalid(
        "job-invalid-execute-read-tool",
        "job",
        {
            "type": "execute",
            "allowed_tools": [Tool.GET_RECENT_ALERTS.value],
            "run_states": ["APPROVED", "EXECUTING"],
            "created_by": ["record_decision"],
            "dedup_key": PROPOSAL,
        },
        "An execute job may call only create_incident.",
        "^\\$\\.allowed_tools\\[0\\]: 'get_recent_alerts' is not one of",
    )
    old_hash = {("payload_sha256" if k == "expected_payload_sha256" else k): v for k, v in decision_valid.items()}
    invalid(
        "decision-invalid-old-hash-field",
        "decision",
        old_hash,
        "The 1.0 field name payload_sha256 is gone (AM-11).",
        "^\\$: (Additional properties are not allowed \\('payload_sha256'"
        "|'expected_payload_sha256' is a required property)",
    )
    in_payload = copy.deepcopy(proposal_valid)
    in_payload["payload"]["authored_by"] = proposal_valid["authored_by"]
    invalid(
        "proposal-invalid-authored-by-in-payload",
        "proposal",
        in_payload,
        "authored_by sits outside the hashed payload.",
        "^\\$\\.payload: Additional properties are not allowed \\('authored_by'",
    )
    non_utc = copy.deepcopy(proposal_valid)
    non_utc["payload"]["start_at"] = "2026-10-05T14:00:00+02:00"
    invalid(
        "proposal-invalid-non-utc",
        "proposal",
        non_utc,
        "A stored proposal spells UTC as Z (ruling 6).",
        "^\\$\\.payload\\.start_at: '2026-10-05T14:00:00\\+02:00' does not match",
    )
    invalid(
        "tool-get_incident_receipt-invalid-unknown",
        "tool-result",
        {**receipt_unknown, "status": "unknown"},
        "The 1.0 receipt example's envelope unknown is gone.",
        "^\\$\\.status: 'unknown' is not one of",
    )
    return items


def build(root: Path = ROOT) -> dict[str, Doc]:
    """Every generated file, keyed by repository-relative path, in a fixed order."""
    files = schemas()
    entries = []
    for entry, doc in examples(root):
        files[entry["path"]] = doc
        entries.append(entry)
    files["schemas/examples/index.json"] = {"specification": "OPS-BUILD-1.3.6", "version": "1.3.3", "examples": entries}
    return files


def render(doc: Doc) -> bytes:
    """The committed byte form: two-space indent, non-ASCII kept, LF, trailing newline, no BOM."""
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write(out: Path, root: Path = ROOT) -> dict[str, int]:
    """Write every generated file under `out` (the repository root, or a temporary directory for the drift test).

    Returns:
        Counts of what was written: schemas, tool-input schemas, valid and invalid examples.
    """
    files = build(root)
    for rel, doc in files.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render(doc))  # bytes, so no platform newline translation can add a CR
    index = files["schemas/examples/index.json"]["examples"]
    return {
        "schemas": sum(1 for rel in files if rel.endswith(".schema.json") and "/tools/" not in rel),
        "tool_inputs": sum(1 for rel in files if "/tools/" in rel),
        "valid": sum(1 for e in index if e["valid"]),
        "invalid": sum(1 for e in index if not e["valid"]),
    }


def main() -> None:
    """Regenerate schemas/ in the repository and print the counts."""
    n = write(ROOT)
    print(
        f"schemas/: {n['schemas'] + n['tool_inputs']} schema documents ({n['schemas']} contracts, {n['tool_inputs']} "
        f"tool inputs); {n['valid'] + n['invalid']} examples ({n['valid']} valid, {n['invalid']} invalid); "
        "index.json version 1.3.3"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the generator**

Run: `PYTHONUTF8=1 uv run python -m scripts.build_schemas`
Expected (measured): `schemas/: 25 schema documents (19 contracts, 6 tool inputs); 66 examples (30 valid, 36 invalid); index.json version 1.3.3`.

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_schemas_generated.py -q 2>&1 | tr -d '\r' | tail -2`
Expected: `2 passed`.

Append to `schemas/README.md`:
```markdown

Every `*.schema.json` here, every file in `examples/` and `examples/index.json` is generated by `scripts/build_schemas.py` from the `ops_core` vocabularies (1.3.6, T45). Do not edit them by hand: change the generator, run `uv run python -m scripts.build_schemas`, and commit both; `tests/plan_c/test_schemas_generated.py` fails on any difference. Each negative example's index entry states the reason it must fail and the `reason_match` regex its first validation error must match.
```

- [ ] **Step 5: Upgrade `--contracts` in the checker**

In `scripts/verify_handoff.py`, replace the base-check hash linking loop (`for name in ["decision-valid", "outcome-success-valid", "outcome-unknown-valid"]:` and its body) with:
```python
    # AM-11 renamed the decision's field to expected_payload_sha256; the outcomes keep payload_sha256.
    check(
        load("schemas/examples/decision-valid.json")["expected_payload_sha256"] == proposal["payload_sha256"],
        "Example hash not linked: decision-valid",
    )
    for name in ["outcome-success-valid", "outcome-unknown-valid"]:
        check(
            load(f"schemas/examples/{name}.json")["payload_sha256"] == proposal["payload_sha256"],
            f"Example hash not linked: {name}",
        )
```
Replace the `if args.contracts:` block body after the `ImportError` guard (from `schema_paths = …` through the final `print(…)`) with:
```python
        from jsonschema.exceptions import best_match

        # Meta-validate every schema: the top-level contracts, the per-tool input schemas and the evals schemas
        # (quality-gates arrives with T23 and may be absent; holdout-case is T03's).
        schema_paths = sorted((ROOT / "schemas").rglob("*.schema.json")) + sorted(
            (ROOT / "evals").glob("*.schema.json")
        )
        for path in schema_paths:
            Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))

        # Governed text must be LF-only and BOM-free so hashes and examples match across platforms (AM-80 checker
        # changes; tests/plan_b/test_text_hygiene.py applies the same rule to every tracked file).
        governed = [
            p
            for d in ("schemas", "data/handoff-fixtures", "handoff/prompts", "evals")
            for p in (ROOT / d).rglob("*")
            if p.is_file() and p.suffix in {".json", ".md", ".jsonl", ".txt", ".sha256"}
        ]
        for path in governed:
            raw = path.read_bytes()
            check(b"\r" not in raw, f"carriage return in governed file: {path.relative_to(ROOT)}")
            check(not raw.startswith(b"\xef\xbb\xbf"), f"byte-order mark in governed file: {path.relative_to(ROOT)}")

        index = load("schemas/examples/index.json")
        check(index.get("version") == "1.3.3", f"index.json version must be 1.3.3, got {index.get('version')!r}")
        positive = negative = 0
        for item in index["examples"]:
            # FormatChecker validates `date-time` only because rfc3339-validator is installed (dev group, T45).
            validator = Draft202012Validator(load(item["schema"]), format_checker=FormatChecker())
            errors = list(validator.iter_errors(load(item["path"])))
            if item["valid"]:
                check(not errors, f"Valid example {item['path']} failed: {[e.message for e in errors]}")
                positive += 1
                continue
            # A negative example must fail, and fail for the reason the index states (R104): a typo elsewhere must not
            # masquerade as proof that the row's rule is enforced.
            check(
                "reason" in item and "reason_match" in item,
                f"Negative example {item['path']} lacks reason/reason_match",
            )
            check(bool(errors), f"Negative example {item['path']} validated; it must fail: {item['reason']}")
            top = best_match(errors)
            where = "$" + "".join(f".{p}" if isinstance(p, str) else f"[{p}]" for p in top.absolute_path)
            text = f"{where}: {top.message}"
            check(
                re.search(item["reason_match"], text) is not None,
                f"Negative example {item['path']} failed, but not for its stated reason. "
                f"Expected /{item['reason_match']}/, got: {text}",
            )
            negative += 1

        # AM-80 row "draft/alerts consistency": the draft example's prose must agree with the alerts it summarises.
        alerts = load("schemas/examples/tool-get_recent_alerts-valid.json")["data"]["alerts"]
        check(
            len(alerts) == 2 and "two" in load("schemas/examples/draft-valid.json")["summary"].lower(),
            "draft-valid.json and tool-get_recent_alerts-valid.json disagree on the alert count",
        )
        print(
            f"PASS: {len(schema_paths)} JSON Schema documents; {positive} accepted examples; "
            f"{negative} negative examples failed for their stated reason; governed files LF-only"
        )
```
`re` is already imported. In the module docstring, the sentence about `--contracts` becomes: "--contracts requires the jsonschema package, plus rfc3339-validator so that its FormatChecker checks `date-time`; `uv run` provides both from the dev group."

Edit `.github/workflows/ci.yml`: replace the comment and step
```yaml
      # The handoff checker is stdlib-only, so it runs on the runner's own python3; -I ignores environment
      # variables and the working directory so nothing outside the checked-out files can change what it imports.
      - run: python3 -I scripts/verify_handoff.py --reference-code --manifest
```
with
```yaml
      # --contracts needs jsonschema and rfc3339-validator (dev group), so the checker runs under `uv run`; -I still
      # ignores environment variables and the working directory, and the checker puts the repository root on
      # sys.path itself, so nothing outside the checked-out files can change what it imports.
      - run: uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts
```
`tests/plan_a/test_ci_workflow.py`'s substring assertion (`verify_handoff.py --reference-code --manifest`) still holds.

- [ ] **Step 6: Stage the new files, then run the checker, the checker tests and the full check**

The tracked-copy helper copies `git ls-files`, so new files must be staged first; the commit follows.
```bash
git add schemas scripts/build_schemas.py scripts/verify_handoff.py tests/plan_a/test_verify_handoff.py tests/plan_c/test_schemas_generated.py .github/workflows/ci.yml pyproject.toml uv.lock
```

Run: `PYTHONUTF8=1 uv run python -I scripts/verify_handoff.py --contracts 2>&1 | tr -d '\r' | tail -2`
Expected (measured): `PASS: 26 JSON Schema documents; 30 accepted examples; 36 negative examples failed for their stated reason; governed files LF-only`, then the `LIMIT:` line; exit 0. (26 = 19 top-level + 6 tool inputs + T03's `evals/holdout-case.schema.json`; 30 = 20 delivered + 10 new positives; 36 = 9 delivered + 27 new negatives.)

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_a/test_verify_handoff.py -q -k contracts 2>&1 | tr -d '\r' | tail -2`
Expected: `5 passed`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tr -d '\r' | tail -3`
Expected: `239 passed`, `11 skipped`, `CHECK: GREEN`.

- [ ] **Step 7: Commit**

CI now runs the checker through `uv run` (so jsonschema and rfc3339-validator come from the dev group) instead of the runner's bare `python3`; this is deliberate: `--contracts` cannot run without those packages, and the default checks' stdlib-only promise is still exercised locally by `python -I scripts/verify_handoff.py --reference-code --manifest` (Task 5).

```bash
git status --short   # only the paths staged in Step 6
git commit -m "T45: generated 1.3.6 schemas with AM-80 rules, eight new schemas and six tool inputs, negative probes checked for their stated reason, CI runs --contracts"
```

---

### Task 7: T45c — Contract ↔ schema conformance

**Files:**
- Create: `tests/plan_c/test_schema_conformance.py`

**Interfaces:**
- Consumes: Task 4/3 models and Task 6's index. Produces: the proof that code and schema accept and reject the same examples (R083 in code, R104 in schema).

- [ ] **Step 1: Write the test (it is the deliverable; it must pass against Task 6's tree)**

Create `tests/plan_c/test_schema_conformance.py`:
```python
"""Every example in schemas/examples/index.json gets the same verdict from the pydantic contract as from its schema.

Catches: a schema rule with no code counterpart (a model would accept what the API rejects) or the reverse, and an
example edited on one side only. Schemas without a pydantic model (tool-result envelopes, tool inputs, job, route)
are listed in NO_MODEL with the reason; they are covered by --contracts alone. Event envelopes have no pydantic model
yet (T14 writes events); their code-side checks are `event_rules_ok` plus a strict parse of `occurred_at`.
"""

import json
from pathlib import Path

import pytest
from ops_core import contracts as c
from ops_core.model_pins import ModelPins
from ops_core.outcomes import ActionOutcome, EventRuleViolation, EventSource, EventType, event_rules_ok
from ops_core.routing import RunManifest
from pydantic import AwareDatetime, BaseModel, TypeAdapter, ValidationError

INDEX = json.loads(Path("schemas/examples/index.json").read_text(encoding="utf-8"))
MODELS: dict[str, type[BaseModel]] = {
    "schemas/message.schema.json": c.MessageRequest,
    "schemas/clarification.schema.json": c.ClarificationReply,
    "schemas/decision.schema.json": c.DecisionRequest,
    "schemas/cancellation.schema.json": c.CancelRequest,
    "schemas/model-draft.schema.json": c.ModelDraft,
    "schemas/proposal.schema.json": c.Proposal,
    "schemas/action-outcome.schema.json": ActionOutcome,
    "schemas/error.schema.json": c.SafeError,
    "schemas/feedback.schema.json": c.FeedbackRequest,
    "schemas/manual-proposal.schema.json": c.ManualProposalRequest,
    "schemas/revision.schema.json": c.RevisionRequest,
    "schemas/cancel-response.schema.json": c.CancelResponse,
    "schemas/model-pins.schema.json": ModelPins,
    "schemas/run-manifest.schema.json": RunManifest,
}
NO_MODEL = {
    "schemas/tool-result.schema.json": "envelopes are built by the MCP servers (T15/T47); the data shapes are ActionOutcome",
    "schemas/evidence.schema.json": "retrieval rows are produced by mcp-read (T17)",
    "schemas/route.schema.json": "enums only; tested in test_jobs_routes_outcomes",
    "schemas/job.schema.json": "table document; tested in test_jobs_routes_outcomes",
}
EVENT = "schemas/event.schema.json"
TIMESTAMP = TypeAdapter(AwareDatetime)


def _event_checks(doc: dict) -> None:
    TIMESTAMP.validate_json(json.dumps(doc["occurred_at"]))  # ValidationError is a ValueError
    event_rules_ok(EventType(doc["type"]), EventSource(doc["source"]), doc["payload"])


@pytest.mark.parametrize("item", INDEX["examples"], ids=[e["path"].rsplit("/", 1)[-1] for e in INDEX["examples"]])
def test_code_and_schema_agree(item):
    text = Path(item["path"]).read_text(encoding="utf-8")
    schema = item["schema"]
    if schema.startswith("schemas/tools/") or schema in NO_MODEL:
        pytest.skip(NO_MODEL.get(schema, "tool input schema: enforced by the MCP server's argument validation (T15)"))
    if schema == EVENT:
        doc = json.loads(text)
        if item["valid"]:
            _event_checks(doc)
        else:
            with pytest.raises((EventRuleViolation, ValueError)):
                _event_checks(doc)
        return
    model = MODELS[schema]
    if item["valid"]:
        model.model_validate_json(text)
    else:
        with pytest.raises(ValidationError):
            model.model_validate_json(text)


def test_every_schema_is_either_modelled_or_listed():
    schemas = {e["schema"] for e in INDEX["examples"]}
    for s in schemas:
        assert s in MODELS or s in NO_MODEL or s == EVENT or s.startswith("schemas/tools/"), s
```

- [ ] **Step 2: Run it; fix mismatches on whichever side is wrong**

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_schema_conformance.py -q 2>&1 | tr -d '\r' | tail -3`
Expected (measured): `49 passed, 18 skipped` (66 index entries + the listing test = 67; the 18 skips are the entries whose schema has no pydantic model: 12 tool-result envelopes, 2 tool inputs, 2 job, 1 route and 1 evidence example). A failure means the model and the schema disagree on an example: decide which side the spec supports (the plan's Global Constraints), fix that side in `ops_core` or in `scripts/build_schemas.py` (then regenerate), and record the decision in the report.

Run: `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tr -d '\r' | tail -3`
Expected: `288 passed`, `29 skipped`, `CHECK: GREEN`.

- [ ] **Step 3: Commit**

```bash
git add tests/plan_c/test_schema_conformance.py
git commit -m "T45: conformance test ties every schema example to its pydantic contract"
```

---

### Task 8: T46 — Reference traceability and the pure-core port

**Files:**
- Create: `reference/TRACEABILITY.md` (repo-owned; the only file besides `README.md` allowed under `reference/`), `tests/plan_c/test_traceability.py`
- Modify: `scripts/verify_handoff.py` (`TREE_REPO_OWNED = {"README.md", "TRACEABILITY.md"}`), `tests/plan_a/test_verify_handoff.py` (the added-file tree test keeps using `evil.py`; a new test proves an untouched copy with `TRACEABILITY.md` passes)

**Interfaces:**
- Consumes: the 58 reference tests (`reference/tests/test_api.py`: 11; `reference/tests/test_control.py`: 39 test functions = 47 cases — 37 plain, `test_invalid_hours` ×7 and `test_valid_hours` ×3) and the ports already written in Tasks 1 and 4 (`test_known_bytes_and_hash` covers `test_canonical_hash_order`; `test_invalid_hours_rejected`/`test_valid_hours` cover the ten `validate_hours` cases; `test_authority_fields_are_rejected_at_every_depth`, `test_empty_and_oversize_message` and `test_draft_rules` replace #42, #46, #53, #54).

- [ ] **Step 1: Write the failing traceability test**

Create `tests/plan_c/test_traceability.py`:
```python
"""R123: every reference test is traced to a port, a replacement with an owning task, or a justified drop.

Catches: a reference test silently forgotten when the inventory changes, a row pointing at a task that does not exist,
a 'port' row whose target test does not exist in tests/plan_c, and a drop without an AM-70 reason.
"""

import ast
import json
import re
from pathlib import Path

REF = Path("reference/tests")
DOC = Path("reference/TRACEABILITY.md")
# One table row: a backticked node id and four more cells. Cells may be empty (`| |`), so the cell patterns allow any
# run of non-pipe characters and the values are stripped after matching.
ROW = re.compile(
    r"^\|\s*`(?P<node>[^`]+)`\s*\|\s*(?P<disposition>port|replace-by|drop)\s*\|"
    r"(?P<target>[^|]*)\|(?P<task>[^|]*)\|(?P<reason>[^|]*)\|$"
)


def reference_node_ids() -> set[str]:
    """Rebuild pytest's node ids from the source: function names plus parametrize expansions (ids as pytest renders them)."""
    nodes: set[str] = set()
    for file in sorted(REF.glob("test_*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]:
            params = [
                d for d in fn.decorator_list if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "parametrize"
            ]
            if not params:
                nodes.add(f"{file.name}::{fn.name}")
                continue
            for value in ast.literal_eval(params[0].args[1]):
                nodes.add(f"{file.name}::{fn.name}[{value}]")
    return nodes


def test_reference_inventory_has_58_cases():
    assert len(reference_node_ids()) == 58


def test_traceability_covers_all_58():
    matches = [ROW.match(line) for line in DOC.read_text(encoding="utf-8").splitlines()]
    rows = [{key: value.strip() for key, value in m.groupdict().items()} for m in matches if m]
    assert {r["node"] for r in rows} == reference_node_ids()
    tasks = {t["id"] for t in json.loads(Path("handoff/tasks.json").read_text(encoding="utf-8"))["tasks"]}
    local = {
        f"{f.name}::{n.name}"
        for f in Path("tests/plan_c").glob("test_*.py")
        for n in ast.parse(f.read_text(encoding="utf-8")).body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
    }
    for r in rows:
        if r["disposition"] == "port":
            assert r["target"] in local, r
        elif r["disposition"] == "replace-by":
            assert r["task"] in tasks, r
            assert r["target"], r
        else:
            assert "AM-70" in r["reason"] or "reference-only" in r["reason"], r
    counts = {d: sum(1 for r in rows if r["disposition"] == d) for d in ("port", "replace-by", "drop")}
    assert counts == {"port": 10, "replace-by": 46, "drop": 2}
```

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_traceability.py -q 2>&1 | tr -d '\r' | tail -3`
Expected: `1 failed, 1 passed` (the inventory count passes; `TRACEABILITY.md` is missing).

- [ ] **Step 2: Write `reference/TRACEABILITY.md`**

Header and 58 rows in the exact table shape the test parses (`| node | disposition | target | task | reason |`); dispositions and owners from the inventory (Part E.2). The block below is the complete file:
```markdown
# Reference test traceability (T46, R123)

The delivered reference (`reference/`, hash-pinned) has 58 tests. Each is **ported** (rewritten against `core`, the target test named), **replaced** by a target test owned by a later task, or **dropped** with the AM-70 reason. Dispositions were decided on 2026-10-08 from `SPEC_AMENDMENTS.md` AM-70 and the task graph; `tests/plan_c/test_traceability.py` checks this table against the reference sources.

| Reference test | Disposition | Target test | Owning task | Reason |
|---|---|---|---|---|
| `test_control.py::test_invalid_hours[None]` | replace-by | tests/acceptance R018 missing interval routes to clarify | T12 | the target makes hours optional; a missing interval is a clarification, not a 422 (AM-16) |
| `test_control.py::test_invalid_hours[0]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | same |
| `test_control.py::test_invalid_hours[169]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | same |
| `test_control.py::test_invalid_hours[-1]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | same |
| `test_control.py::test_invalid_hours[True]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | strict mode rejects bool |
| `test_control.py::test_invalid_hours[1.5]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | same |
| `test_control.py::test_invalid_hours[24]` | port | test_contracts.py::test_invalid_hours_rejected | T07 | the string '24' |
| `test_control.py::test_valid_hours[1]` | port | test_contracts.py::test_valid_hours | T07 | |
| `test_control.py::test_valid_hours[24]` | port | test_contracts.py::test_valid_hours | T07 | |
| `test_control.py::test_valid_hours[168]` | port | test_contracts.py::test_valid_hours | T07 | |
| `test_control.py::test_canonical_hash_order` | port | test_canonical.py::test_known_bytes_and_hash | T07 | canonical JSON v1 |
| `test_control.py::test_clarification_then_proposal` | replace-by | tests/acceptance R018 clarification round trip | T12 | admission clarification_reply route; resume in T20 |
| `test_control.py::test_stale_clarification` | replace-by | tests/acceptance R017 expected_version 409 | T12 | |
| `test_control.py::test_success` | replace-by | tests/acceptance R105 walking skeleton e2e | T08 | record_outcome in T22 |
| `test_control.py::test_no_write_without_approval` | replace-by | tests/acceptance R045 grant gate | T21 | |
| `test_control.py::test_operator_cannot_approve` | replace-by | tests/acceptance R043 reviewer membership | T21 | |
| `test_control.py::test_reader_cannot_create` | replace-by | tests/acceptance R015 admission authorization | T12 | |
| `test_control.py::test_cross_team_asset_hidden` | replace-by | tests/acceptance R028 asset-sim tenant filter | T16 | admission 404 in T12 |
| `test_control.py::test_cross_team_run_denied` | replace-by | tests/acceptance R007 RLS and R115 404 mapping | T09 | |
| `test_control.py::test_cross_team_events_denied` | replace-by | tests/acceptance R053 authorized event history | T14 | |
| `test_control.py::test_self_approval_denied` | replace-by | tests/acceptance R093 independence covers every author | T21 | |
| `test_control.py::test_proposal_hash_mismatch` | replace-by | tests/acceptance R044 expected_payload_sha256 | T21 | |
| `test_control.py::test_stale_version` | replace-by | tests/acceptance R044 stale revision 409 | T21 | |
| `test_control.py::test_expired_proposal` | replace-by | tests/acceptance R092 lazy expiry to BLOCKED_REVIEW | T21 | |
| `test_control.py::test_expired_approval` | replace-by | tests/acceptance R092 expiry at grant | T21 | |
| `test_control.py::test_approver_revoked_before_execution` | replace-by | tests/acceptance R086 revocation before grant | T21 | enabled check in T11 |
| `test_control.py::test_requester_revoked_before_execution` | replace-by | tests/acceptance R086 requester revoked | T21 | |
| `test_control.py::test_changed_evidence` | replace-by | tests/acceptance R116 asset freshness at grant | T21 | |
| `test_control.py::test_mutated_proposal` | replace-by | tests/acceptance R044 hash verified at grant | T21 | immutable proposals in T09 |
| `test_control.py::test_duplicate_decision_and_execute` | replace-by | tests/acceptance R090 concurrent decide and execute | T21 | AM-70 names this test as weak; replaced by concurrent tests |
| `test_control.py::test_concurrent_destination_dedup` | replace-by | tests/acceptance R047 action_key ON CONFLICT | T10 | |
| `test_control.py::test_destination_idempotency_key_content_conflict` | replace-by | tests/acceptance R049 CONFLICT on changed hash | T10 | |
| `test_control.py::test_lost_response_restart_and_reconcile` | replace-by | tests/acceptance R048 lost response recovery | T22 | fault hook in T10 |
| `test_control.py::test_unknown_cannot_blind_retry` | replace-by | tests/acceptance R050 no blind retry after SENT | T22 | |
| `test_control.py::test_executing_without_receipt_stays_unknown` | drop | | | AM-70 stuck EXECUTING after a crash (service.py:175-178, :213-216); the surviving invariant (NOT_FOUND is never no-commit) is R050/R096 in T22 |
| `test_control.py::test_cancel_before_write` | replace-by | tests/acceptance R046 cancel wins before grant | T21 | |
| `test_control.py::test_cancel_does_not_undo_commit` | replace-by | tests/acceptance R046 cancel-response reports the grant | T22 | |
| `test_control.py::test_rejection` | replace-by | tests/acceptance R043 rejection path | T21 | |
| `test_control.py::test_duplicate_request_key` | replace-by | tests/acceptance R016 idempotency replay | T12 | |
| `test_control.py::test_request_key_scoped_by_identity` | replace-by | tests/acceptance R016 key scoped by identity | T12 | |
| `test_control.py::test_unknown_citation_rejected` | replace-by | tests/acceptance R041 citation membership | T19 | |
| `test_control.py::test_model_cannot_add_authorization_field` | replace-by | test_contracts.py::test_draft_rules | T07 | R004, already green |
| `test_control.py::test_missing_documents_abstains` | replace-by | tests/acceptance R114 evidence-sufficient rule | T20 | |
| `test_control.py::test_cancellation_during_generation_discards_output` | replace-by | tests/acceptance R098 cancel mid-draft | T20 | lease cancel in T13 |
| `test_control.py::test_event_cursor` | replace-by | tests/acceptance R089 gap-free sequence | T14 | |
| `test_control.py::test_empty_and_oversize_message` | replace-by | test_contracts.py::test_empty_and_oversize_message | T07 | already green; 422 mapping in T12 |
| `test_control.py::test_reader_cannot_reconcile` | replace-by | tests/acceptance R131 recover handles only on mcp-write | T47 | |
| `test_api.py::test_health` | replace-by | tests/acceptance health endpoints (BUILD_SPEC §7) | T12 | |
| `test_api.py::test_auth_required` | replace-by | tests/acceptance R011 401 without identity | T11 | |
| `test_api.py::test_bad_token` | replace-by | tests/acceptance R011 unknown bearer | T11 | |
| `test_api.py::test_me` | replace-by | tests/acceptance GET /api/v1/me | T11 | |
| `test_api.py::test_create_and_read` | replace-by | tests/acceptance R015 and R115 202/404 | T12 | |
| `test_api.py::test_cannot_supply_identity_or_approved_field` | replace-by | test_contracts.py::test_authority_fields_are_rejected_at_every_depth | T07 | already green; 422 mapping in T12 |
| `test_api.py::test_bool_hours_rejected` | replace-by | test_contracts.py::test_invalid_hours_rejected | T07 | already green; 422 mapping in T12 |
| `test_api.py::test_cross_origin_mutation_rejected` | replace-by | tests/acceptance R012 origin check | T11 | |
| `test_api.py::test_host_restriction` | replace-by | tests/acceptance trusted host (BUILD_SPEC §9) | T11 | |
| `test_api.py::test_complete_api_workflow` | replace-by | tests/acceptance R105 walking skeleton e2e | T08 | |
| `test_api.py::test_ui_served_with_security_headers` | drop | | | reference-only demo UI (web/); the target UI is T26 and its CSP is BUILD_SPEC §9 |
```
Counts (measured with the test's `ROW` regex): 58 rows — 10 port, 46 replace-by, 2 drop (the `[None]` hours case is a replacement, see its row). Keep the rows in the shape above: a backticked node in the first cell, five cells, a trailing `|`; empty cells are written `| |`, which the regex accepts.

- [ ] **Step 3: Allow the file under `reference/`, stage, and run everything**

In `scripts/verify_handoff.py`, replace the `TREE_REPO_OWNED` line and its comment with:
```python
# The files under reference/ this repository wrote, so they have no counterpart in the delivered zip: README.md and,
# from T46, TRACEABILITY.md (R123). Each must exist; check_reference_tree reports a missing one.
TREE_REPO_OWNED = {"README.md", "TRACEABILITY.md"}
```
and in the module docstring (its third paragraph, about `--reference-tree`) replace these two lines, which wrap after "skipped),":
```text
reference/ except the repository-owned reference/README.md (caches and build output skipped),
and every reference-code-hashes.remap.json target must lie under reference/.
```
with:
```text
reference/ except the repository-owned reference/README.md and reference/TRACEABILITY.md (caches
and build output skipped), and every reference-code-hashes.remap.json target must lie under reference/.
```
Append to `tests/plan_a/test_verify_handoff.py`:
```python


def test_reference_tree_accepts_traceability(tmp_path: Path):
    """T46: the repo-owned reference/TRACEABILITY.md is allowed (and required) like README.md."""
    root = _tracked_copy(tmp_path)
    assert (root / "reference/TRACEABILITY.md").is_file()
    out = _run_tree(root)
    assert out.returncode == 0, out.stdout + out.stderr
```

The tracked-copy helper copies `git ls-files`, so new files must be staged first; the commit follows. (`TREE_REPO_OWNED` makes `TRACEABILITY.md` required, so an unstaged copy fails `--reference-tree` with `missing: reference/TRACEABILITY.md`.)
```bash
git add reference/TRACEABILITY.md scripts/verify_handoff.py tests/plan_a/test_verify_handoff.py tests/plan_c/test_traceability.py
```

Run: `PYTHONUTF8=1 uv run python -I scripts/verify_handoff.py --reference-code --manifest | tail -3`
Expected: `PASS: 26 delivered reference/ files byte-identical to handoff-1.0.zip; no extra or missing files; 19 remap targets under reference/`, `PASS: 161 delivered 1.0 snapshot checksums verified against handoff-1.0.zip`, the `LIMIT:` line; exit 0 (TRACEABILITY.md is repo-owned and not counted, like README.md).

Run: `PYTHONUTF8=1 uv run python -m pytest tests/plan_c/test_traceability.py tests/plan_a/test_verify_handoff.py -q 2>&1 | tr -d '\r' | tail -2`
Expected (measured): `18 passed` (2 traceability + 16 checker tests).

Run: `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tr -d '\r' | tail -3`
Expected (measured): `291 passed`, `29 skipped`, `CHECK: GREEN`.

- [ ] **Step 4: Commit**

```bash
git add reference/TRACEABILITY.md scripts/verify_handoff.py tests/plan_a/test_verify_handoff.py tests/plan_c/test_traceability.py
git commit -m "T46: trace all 58 reference tests to ports, replacements with owning tasks, or AM-70 drops"
```

---

### Task 9: Slice-end handoff

**Files:**
- Modify: `handoff/tasks.json` (T07, T45, T46 → `DONE` with review notes naming the commits and the nine rulings), `handoff/BUILD_BACKLOG.md` (mirror), `STATUS.md` (Plan C section: totals, what is evidenced: R004, R005, R082 (without the "logged" half, `TODO(T09)`), R083, R104, R120-partial, R123; still no target capability), `SESSION_STATE.md` ("Plan C executed" section; the nine rulings as proposed spec errata, worded as below; next: Plan D = T08 walking skeleton written from the real contracts and dry-run first; in "Exact next step", the checker line `python -I scripts/verify_handoff.py --reference-code --manifest` becomes `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`, the command CI runs), `handoff/acceptance-matrix.json` (evidence for R004, R005, R082, R083, R104 and R123, as below; R120 stays `NOT_RUN`, because its 409 `SLOT_OCCUPIED` is T21's), `docs/PROJECT_HISTORY.md` (append a **§18** paragraph — §18 “The contract plan was wrong about its own spec in four places” already tells the review story and §19 is the closing section; add what the contract work itself found — the nine rulings (four spec contradictions: rulings 1, 2, 4 and 7; four readings the spec leaves open: rulings 3, 5, 6 and 8), the FormatChecker not checking `date-time` until `rfc3339-validator` was added, the R083 probe `event-invalid-confirmed-no-receipt` that validated against the 1.0 schema, the index with no reasons, and the move from hand-edited schemas to a generator with a drift test).

`handoff/acceptance-matrix.json` today uses only `evidence_status: NOT_RUN` and `implementation_status: NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` (all 131 rows). Two new values are introduced, the way `tasks.json` introduced `DONE_PENDING_OWNER`: for R004, R005, R082, R083, R104 and R123 set `evidence_status` to `RECORDED_LOCALLY` and `implementation_status` to `IMPLEMENTED_LOCALLY_VERIFIED`, and set `evidence_paths` to:
- R004: `tests/plan_c/test_contracts.py`
- R005: `tests/plan_c/test_canonical.py`, `tests/plan_c/test_contracts.py`
- R082: `tests/plan_c/test_states.py` (the "logged" half stays `TODO(T09)`; STATUS.md says so)
- R083: `tests/plan_c/test_jobs_routes_outcomes.py`, `tests/plan_c/test_schema_conformance.py`, `tests/plan_a/test_verify_handoff.py`
- R104: `tests/plan_c/test_schemas_generated.py`, `tests/plan_c/test_schema_conformance.py`, `tests/plan_c/test_fixture_meta.py`, `tests/plan_a/test_verify_handoff.py`
- R123: `tests/plan_c/test_traceability.py`

Append to the matrix's top-level `note`: " Status vocabulary: evidence_status NOT_RUN or RECORDED_LOCALLY (the tests in evidence_paths pass in scripts/check.py and CI; the suggested_test acceptance file does not exist yet); implementation_status NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED or IMPLEMENTED_LOCALLY_VERIFIED (the core library or contract exists and those tests verify it; no running target capability)." Keep the file's existing formatting (indentation, key order, trailing newline, LF).

The errata, verbatim, for `SESSION_STATE.md` and the T07/T45 review notes (the owner decides; the spec text stays authoritative until then):
1. AM-20.3 "Who performs which transition": the `create_revision` row should read "AWAITING_APPROVAL / APPROVED / BLOCKED_REVIEW → QUEUED", matching the function table and BUILD_SPEC §8.
2. AM-13 "Outcome vocabulary": `FAILED_NO_COMMIT` carries `reason ∈ {aborted_no_commit, cancelled_before_send, rejected, expired}`; `expired` is produced by the recovery table (INTENT after the deadline) and by `create_incident` past the deadline.
3. AM-20.3 `search_procedures_scoped`: `mode=vector` is the SQL argument value; the externally visible `retrieval_mode` is `vector_exact`, and mcp-read translates between them.
4. BUILD_SPEC §8 `QUEUED → AWAITING_INPUT` is superseded: missing context is detected in RETRIEVING (AM-10), and `transition_run` allows only `QUEUED → RETRIEVING`.
5. AM-20.3 "any pre-grant active state → CANCELLED" should read "any pre-grant non-terminal state, including BLOCKED_REVIEW", as the AM-10 BLOCKED_REVIEW row already allows.
6. BUILD_SPEC §6 "UTC instants with explicit offsets": only hashed documents (the proposal) spell UTC as `Z`; `manual-proposal`, `model-pins` and the `get_recent_alerts` input accept `Z` or `+00:00`, as do request bodies, and the contract normalises to `Z` before hashing.
7. AM-80 "Negative probes": "before writing contract code" should read "before any service consumes a schema"; T45 depends on T07 in `handoff/tasks.json`, and the conformance test needs both.
8. AM-10 "Reasons": a FAILED run reached by `transition_run` on exhausted infrastructure policy carries no reason; the `run.failed` event's message says why.
9. AM-20.3 "Who performs which transition": add `create_manual_proposal` with the `freeze_proposal` rows (DRAFTING → AWAITING_APPROVAL; DRAFTING → BLOCKED_REVIEW on `asset_action_unresolved` / `asset_incident_exists`); the function table already says it is otherwise identical to `freeze_proposal`.

- [ ] **Step 1: Make the edits, run the full check, commit**

Run: `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tr -d '\r' | tail -3`
Expected: `291 passed`, `29 skipped`, `CHECK: GREEN` (the same totals as Task 8).

```bash
git add handoff/tasks.json handoff/acceptance-matrix.json handoff/BUILD_BACKLOG.md STATUS.md SESSION_STATE.md docs/PROJECT_HISTORY.md
git commit -m "docs: handoff state after Plan C (T07, T45, T46 done; spec errata proposed)"
```

---

## Coverage notes

- **R004, R005, R082** (T07): Tasks 1, 2, 4. R082's "disallowed transitions … logged" is `TODO(T09)` in `states.py`. **R120**: the slot rule in Task 2 (`revision_allowed`) — the 409 itself is T21. **R114/R125** rows: `freeze_allowed`, `RunRequestFields` and the draft/payload rules in Tasks 2 and 4 — the live refusals are T09/T22.
- **R083, R104** (T45): Tasks 5–7; CI runs `--contracts` from Task 6 on.
- **R123** (T46): Task 8.
- **Not in this plan:** `evals/quality-gates.schema.json` and the AM-80 `evals` row's meta-validation of it (T23; `--contracts` already globs `evals/*.schema.json`, so it is checked the day it lands); `schemas/run-manifest` consumers (T19); the SQL mirror of the transition table and the `state_version` rule (T09); the attempt-state dimension of the tool allowlist (`TODO(T15)` on `JobRule`); OpenAPI generation from the contracts (T12).
- **`date-time` validity:** closed by the `rfc3339-validator` dev dependency (Task 6): jsonschema's FormatChecker now checks every `date-time` field, and `event-invalid-occurred-at.json` proves it. The UTC patterns are a separate rule (ruling 6): they pin the *spelling* in `proposal` (`Z`, the hashed document) and in `manual-proposal`, `model-pins` and the `get_recent_alerts` input (`Z` or `+00:00`); the pydantic contracts additionally require a zero offset.

## After Plan C

Plan D (T08, the walking skeleton across api, worker, mcp-read, mcp-write and incident-sim with real Keycloak tokens and the fake model) is written from the real `ops_core` contracts, `compose.yaml` and realm, with the SESSION_STATE debt list as its constraint, and is dry-run on scratch copies before execution.
