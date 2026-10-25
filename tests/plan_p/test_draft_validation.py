"""The runtime prompts and the structural validation of a model's reply (T19; BS:447-452; R036, R039, R040).

Catches: a runtime prompt edited without a new version (each file's SHA-256 is pinned) or a starter in
`handoff/prompts/` edited at all (the probe pins them); a reply accepted with thinking in its text or its metadata, or
with the thinking stripped; an authority key, a question on a proposal, a citation the run did not offer, a proposal
on an `answer_only` run, a whitespace-only title or a repeated key accepted; repair feedback that echoes the reply
(the T02 probe's feedback embedded the whole draft) or runs past ten lines; and the validator drifting from T23's
schema grader (`grading.check_schema`), whose two-judge rule it re-implements to get error paths.
"""

import hashlib
import json
from pathlib import Path

import pytest
from ops_core import grading, prompts
from ops_core.contracts import ModelDraft
from ops_core.draft_validation import MAX_FEEDBACK, DraftInvalid, validate

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = frozenset({"ALPHA-INCIDENT:v2:review", "ALPHA-VENDOR-PORTAL:v1:portal-note"})
MARK = "ZEBRA-7731"  # a token only the reply contains: feedback must never show it


def reply(**fields: object) -> str:
    """A proposal reply with the given fields replaced (a field set to `...` is left out)."""
    doc: dict[str, object] = {
        "kind": "proposal",
        "title": f"Review warnings on A17 {MARK}",
        "summary": f"Two warnings within 24 hours meet the review rule. {MARK}",
        "evidence_refs": ["ALPHA-INCIDENT:v2:review"],
        "assumptions": ["The alerts are synthetic."],
        "limitations": ["No root cause is known."],
    }
    doc.update(fields)
    return json.dumps({k: v for k, v in doc.items() if v is not ...})


def refused(text: str, *, reasoning: object = None, answer_only: bool = False) -> DraftInvalid:
    with pytest.raises(DraftInvalid) as caught:
        validate(text, reasoning=reasoning, allowed_ids=ALLOWED, answer_only=answer_only)
    assert len(caught.value.feedback) <= MAX_FEEDBACK
    assert not any(MARK in line for line in caught.value.feedback), caught.value.feedback  # never the instance
    return caught.value


def test_each_runtime_prompt_is_pinned_and_the_starters_are_untouched() -> None:
    assert prompts.DRAFT_VERSION == "incident-draft-v2" and prompts.REPAIR_VERSION == "schema-repair-v2"
    assert prompts.sha256("incident-draft-v2") == "6540c7158931489dc1b4c67b5fab9480dc06fc08d8633ed14c3666ea619d7b82"
    assert prompts.sha256("schema-repair-v2") == "c0257f2a0bdbbba45a9779ab5a021fbe1d1b71a8c9a2ecf52c06b72fdb8085c1"
    starters = {  # SA:607-608 and scripts/probe.py's EXPECTED: the probe measured exactly these
        "incident-draft-v1.md": "e3c26da349dcb0a9bfafb6c786a06f15fece389c21fa63b1b64fef7659b6a942",
        "schema-repair-v1.md": "8b6658eb0f08136699b78e7ab1d76972f88f4399db720e92e5be5335b0c7c343",
    }
    for name, digest in starters.items():
        assert hashlib.sha256((ROOT / "handoff" / "prompts" / name).read_bytes()).hexdigest() == digest, name
    # Each v2 system message starts with its starter's own system message, word for word. Line numbers are 1-based:
    # the draft starter's system message is the paragraphs on lines 7, 9 and 11; the repair starter's is line 5.
    draft = (ROOT / "handoff" / "prompts" / "incident-draft-v1.md").read_text(encoding="utf-8").split("\n")
    repair = (ROOT / "handoff" / "prompts" / "schema-repair-v1.md").read_text(encoding="utf-8").split("\n")
    assert prompts.text("incident-draft-v2").startswith("\n\n".join(draft[i - 1] for i in (7, 9, 11)))
    assert prompts.text("schema-repair-v2").startswith(repair[5 - 1])


def test_a_valid_draft_of_each_kind_is_accepted_unchanged() -> None:
    proposal = validate(reply(), reasoning=None, allowed_ids=ALLOWED, answer_only=False)
    assert isinstance(proposal, ModelDraft) and proposal.kind == "proposal"
    assert proposal.model_dump(exclude_none=True) == json.loads(reply())  # not one field changed, added or dropped
    answer = validate(reply(kind="answer"), reasoning=None, allowed_ids=ALLOWED, answer_only=True)
    assert answer.kind == "answer"
    abstain = validate(reply(kind="abstain", evidence_refs=[]), reasoning="", allowed_ids=ALLOWED, answer_only=False)
    assert abstain.kind == "abstain" and not abstain.clarification_requested
    asking = validate(
        reply(kind="abstain", evidence_refs=[], question="Which interval?"),
        reasoning=None,
        allowed_ids=ALLOWED,
        answer_only=True,
    )
    assert asking.clarification_requested


@pytest.mark.parametrize(
    ("text", "reasoning"),
    [
        (f"<think>plan {MARK}</think>" + reply(), None),
        (reply(), f"I should propose {MARK}"),
        (reply() + "</think>", None),
    ],
)
def test_thinking_in_the_text_or_the_metadata_refuses_the_reply_whole(text: str, reasoning: object) -> None:
    assert refused(text, reasoning=reasoning).rules == ("thinking",)


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[1, 2]", '"a string"', reply()[:-1], '{"kind": "proposal", "kind": "answer"}', "NaN"],
)
def test_anything_but_one_strict_json_object_is_not_json(text: str) -> None:
    assert refused(text).rules == ("not_json",)


def test_authority_keys_are_named_and_refused_before_the_schema() -> None:
    invalid = refused(reply(approved=True, destination="https://example.invalid", tool="create_incident"))
    assert invalid.rules == ("authority_key",)
    assert invalid.feedback == (
        "/approved: field not allowed; the application sets it",
        "/destination: field not allowed; the application sets it",
        "/tool: field not allowed; the application sets it",
    )


def test_schema_failures_give_a_path_and_a_rule_per_line() -> None:
    assert refused(reply(question="Anything else?")).feedback == (
        "/question: allowed only with kind abstain; leave it out",
    )
    assert refused(reply(question=None)).feedback == (  # the probe's commonest failure: `question: null`
        "/question: allowed only with kind abstain; leave it out",
        '/question: type "string"',
    )
    assert refused(reply(kind="report")).feedback == ('/kind: enum ["proposal", "answer", "abstain"]',)
    invalid = refused(reply(title="x" * 121, evidence_refs=[], extra=MARK, assumptions=...))
    assert invalid.rules == ("schema",)
    assert set(invalid.feedback) == {
        "/: only these fields are allowed: kind, title, summary, evidence_refs, assumptions, limitations, question",
        "/: required field missing: assumptions",
        "/evidence_refs: minItems 1",
        "/title: maxLength 120",
    }


def test_feedback_stops_at_ten_lines() -> None:
    invalid = refused(reply(limitations=["x" * 501] * 8, assumptions=["y" * 501] * 8))
    assert len(invalid.feedback) == MAX_FEEDBACK and invalid.rules == ("schema",)


def test_what_only_the_contract_sees_is_refused_as_contract() -> None:
    invalid = refused(reply(title="   "))  # the schema counts the spaces; ModelDraft strips them and refuses
    assert invalid.rules == ("contract",) and invalid.feedback == ("/title: string_too_short",)


def test_a_citation_the_run_did_not_offer_is_refused_by_position() -> None:
    invalid = refused(reply(evidence_refs=["ALPHA-INCIDENT:v2:review", "status", f"{MARK}:v1:x"]))
    assert invalid.rules == ("not_offered",)
    assert invalid.feedback == (
        "/evidence_refs/1: not one of allowed_evidence_ids",
        "/evidence_refs/2: not one of allowed_evidence_ids",
    )


def test_a_proposal_is_refused_on_an_answer_only_run() -> None:
    assert refused(reply(), answer_only=True).rules == ("proposal_on_answer_only",)


DEV_CASE = grading.load_cases(ROOT / "evals" / "dev" / "cases.jsonl")[0]  # check_schema reads no case field


@pytest.mark.parametrize(
    "text",
    [
        reply(),
        reply(kind="answer"),
        reply(kind="abstain", evidence_refs=[]),
        reply(question=None),
        reply(kind="report"),
        reply(title="x" * 121),
        reply(title="x" * 119 + "  "),  # the schema counts the spaces; ModelDraft strips them (Plan O)
        reply(title="   "),
    ],
)
def test_the_validator_and_the_schema_grader_agree(text: str) -> None:
    """Departure 6: on these drafts `validate` refuses (as `schema` or `contract`) exactly when `check_schema` fails."""
    graded = grading.check_schema(grading.Output(draft=json.loads(text), offered_refs=ALLOWED, case=DEV_CASE))
    try:
        validate(text, reasoning=None, allowed_ids=ALLOWED, answer_only=False)
        structural = True
    except DraftInvalid as invalid:
        assert set(invalid.rules) <= {"schema", "contract"}  # no other stage may stand in for the two judges
        structural = False
    assert graded is not None and graded.passed == structural
