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
from ops_core.states import RunState
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
    (c.RunRequestFields, {"intent": "investigate", "supersedes_run_id": str(RUN)}),
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


def test_authority_fields_are_rejected_inside_source_snapshots():
    snap = PAYLOAD["source_snapshots"][0]
    assert c.load(c.ProposalPayload, json.dumps(PAYLOAD))
    for field in sorted(c.AUTHORITY_FIELDS):
        body = {**PAYLOAD, "source_snapshots": [{**snap, field: "x"}]}
        with pytest.raises(ValidationError):
            c.load(c.ProposalPayload, json.dumps(body))


JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(), inner, max_size=3),
    max_leaves=5,
)
FIELD_SPELLINGS = st.sampled_from(sorted(c.AUTHORITY_FIELDS)).flatmap(
    lambda n: st.sampled_from([n, n.upper(), n.capitalize()])
)


@given(st.sampled_from(REQUEST_MODELS), FIELD_SPELLINGS, JSON_VALUES)
def test_any_authority_field_with_any_value_is_rejected(model_and_body, field, value):
    """R004 as a property: the field name alone is enough to reject, whatever its case or the value chosen."""
    model, body = model_and_body
    with pytest.raises(ValidationError):  # unknown keys are rejected regardless of case
        c.load(model, json.dumps({**body, field: value}))


def test_duplicate_json_keys_are_rejected():
    """BUILD_SPEC §6: pydantic would keep the last value, so a gateway and a handler could disagree."""
    with pytest.raises(c.DuplicateKey, match="expected_version"):
        c.load(c.RevisionRequest, '{"expected_version": 1, "expected_version": 2}')
    with pytest.raises(c.DuplicateKey, match="hours"):
        c.load(c.MessageRequest, '{"kind": "ask", "text": "t", "context": {"hours": 1, "hours": 2}}')
    with pytest.raises(c.DuplicateKey, match="asset_id"):  # inside the hashed payload too
        c.load(c.ProposalPayload, json.dumps(PAYLOAD)[:-1] + ', "asset_id": "B22"}')
    with pytest.raises(ValidationError):  # malformed JSON stays pydantic's error
        c.load(c.RevisionRequest, "{")
    with pytest.raises(ValidationError):  # absurd nesting: never a bare RecursionError from the duplicate-key scan
        c.load(c.RevisionRequest, "[" * 100000)


def test_server_code_may_build_contracts_from_aware_datetimes():
    """T09's freeze path builds payloads from database timestamps, so an aware datetime object is accepted in python
    mode; a naive one and a non-UTC one still fail the explicit-offset rule."""
    body = {
        **PAYLOAD,
        "start_at": datetime(2026, 10, 5, 12, tzinfo=UTC),
        "end_at": datetime(2026, 10, 6, 12, tzinfo=UTC),
        "expires_at": datetime(2026, 10, 6, 12, 15, tzinfo=UTC),
    }
    body = {**body, "tenant_id": ALPHA, "run_id": RUN, "proposal_id": PROP}
    assert c.ProposalPayload.model_validate(body).start_at == datetime(2026, 10, 5, 12, tzinfo=UTC)
    with pytest.raises(ValidationError):
        # A naive datetime is the point of this case, so the DTZ001 lint rule does not apply here.
        c.ProposalPayload.model_validate({**body, "start_at": datetime(2026, 10, 5, 12)})  # noqa: DTZ001


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


def test_proposal_nfc_normalisation():
    """R005: strings are normalised before ordering, uniqueness and hashing, so NFC-equivalent payloads agree."""
    nfd_e = "e\u0301"
    snaps = [{"evidence_id": r, "content_sha256": "8b" * 32, "version": "1"} for r in ("\u00e9", "\u00e9x")]
    unsorted = {**PAYLOAD, "evidence_refs": [nfd_e + "x", "\u00e9"], "source_snapshots": snaps[::-1]}
    with pytest.raises(ValidationError, match="evidence_refs must be sorted"):
        c.load(c.ProposalPayload, json.dumps(unsorted))  # raw NFD sorts before NFC "é", normalised it sorts after
    dup = {**PAYLOAD, "evidence_refs": ["caf\u00e9", "cafe\u0301"]}
    with pytest.raises(ValidationError, match="duplicate"):
        c.load(c.ProposalPayload, json.dumps(dup))
    nfc = {**PAYLOAD, "title": "caf\u00e9", "evidence_refs": ["\u00e9"], "source_snapshots": snaps[:1]}
    nfd_snaps = [{**snaps[0], "evidence_id": nfd_e}]
    nfd = {**nfc, "title": "cafe\u0301", "evidence_refs": [nfd_e], "source_snapshots": nfd_snaps}
    a, b = (c.load(c.ProposalPayload, json.dumps(x)) for x in (nfc, nfd))
    assert a.title == "caf\u00e9" and canonical_sha256(a.canonical_dict()) == canonical_sha256(b.canonical_dict())


def test_snapshots_must_match_evidence_refs():
    snap = PAYLOAD["source_snapshots"][0]
    for snapshots in (
        [snap, {**snap, "evidence_id": "ZZZ"}],  # stray snapshot
        [snap, snap],  # duplicate snapshot
        [{**snap, "evidence_id": "OTHER"}],  # wrong id
    ):
        with pytest.raises(ValidationError):
            c.load(c.ProposalPayload, json.dumps({**PAYLOAD, "source_snapshots": snapshots}))


@pytest.mark.parametrize("stamp", ["1759665600", "0", "2026-10-05T12:00:00-00:00", "2026-10-05", 1759665600])
def test_timestamps_must_be_explicit_iso_instants(stamp):
    manual = dict(REQUEST_MODELS)[c.ManualProposalRequest]
    for key in ("start_at", "expires_at"):
        with pytest.raises(ValidationError):
            c.load(c.ProposalPayload, json.dumps({**PAYLOAD, key: stamp}))
    with pytest.raises(ValidationError):
        c.load(c.ManualProposalRequest, json.dumps({**manual, "start_at": stamp}))


def test_zero_offset_spellings_still_accepted():
    for stamp in ("2026-10-05T12:00:00.000Z", "2026-10-05T12:00:00+00:00", "2026-10-05T12:00:00Z"):
        p = c.load(c.ProposalPayload, json.dumps({**PAYLOAD, "start_at": stamp}))
        assert p.canonical_dict()["start_at"] == "2026-10-05T12:00:00Z"


def test_proposal_envelope_rules():
    payload = c.load(c.ProposalPayload, json.dumps(PAYLOAD))
    sha = canonical_sha256(payload.canonical_dict())
    good = {"canonicalization_version": 1, "payload": payload, "payload_sha256": sha, "authored_by": [ALPHA]}
    assert c.Proposal(**good)
    for bad in (
        {"canonicalization_version": True},  # strict int: `true` is not version 1
        {"canonicalization_version": 2},
        {"authored_by": [ALPHA, ALPHA]},
    ):
        with pytest.raises(ValidationError):
            c.Proposal(**(good | bad))
    explicit_null = c.load(c.ProposalPayload, json.dumps({**PAYLOAD, "supersedes_run_id": None}))
    assert canonical_sha256(explicit_null.canonical_dict()) == sha  # an explicit null and an absent key hash alike


@pytest.mark.parametrize("model", [c.DecisionRequest, c.CancelRequest])
def test_empty_reason_is_rejected(model):
    body = dict(REQUEST_MODELS)[model]
    assert c.load(model, json.dumps({**body, "reason": "ok"}))
    for reason in ("", "  "):
        with pytest.raises(ValidationError):
            c.load(model, json.dumps({**body, "reason": reason}))


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
    cancelled = {**body, "status": "CANCELLED", "grant_exists": False, "attempt_state": None, "note": None}
    assert c.load(c.CancelResponse, json.dumps(cancelled)).status is RunState.CANCELLED
    # A run can fail in RETRIEVING/DRAFTING before any grant (ruling 8); the truthful answer must be expressible.
    failed_early = {**cancelled, "status": "FAILED"}
    assert not c.load(c.CancelResponse, json.dumps(failed_early)).grant_exists
    for bad in (
        {**body, "cancel_requested": False},  # it is a cancel response
        {**body, "status": "CANCELLED"},  # CANCELLED after a grant would be an undo claim
        {**cancelled, "status": "EXECUTING"},  # a post-grant state needs a grant
        {**cancelled, "status": "SUCCEEDED"},
    ):
        with pytest.raises(ValidationError):
            c.load(c.CancelResponse, json.dumps(bad))
    # The grant commits together with APPROVED → EXECUTING, so a pre-grant status with a grant contradicts itself.
    with pytest.raises(ValidationError, match="pre-grant, so no grant can exist"):
        c.load(c.CancelResponse, json.dumps({**body, "status": "QUEUED"}))


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
