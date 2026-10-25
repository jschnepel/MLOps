"""`handlers.investigate` around the model route, without a database (T19; SA:137, SA:147, SA:451; R039, R041, R130).

On Plan H's fakes (`tests/plan_h/test_worker_units.py`), which log every unit and every persistence call. Catches: a
run manifest written after the model call or outside the DRAFTING unit, or without the route's digest; a permit
taken twice for one draft (the repair must share the first pass's hold); a failing real route that falls back to a
fake draft or freezes anything; an outage or an exhausted repair that is not a templated FAILED; an abstention that
is not INSUFFICIENT_EVIDENCE; an answer or a clarifying question frozen as a proposal before T20 routes them; and a
draft that claims success turning into an `action.*` event, a status or anything but a proposal awaiting review.
"""

import asyncio
import json
from typing import Any

import pytest
from ops_core import persistence
from ops_core.routing import ModelRoute
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator, ModelUnavailable
from ops_worker.ollama_drafting import OllamaDraftGenerator, Reply

from tests.plan_h.test_worker_units import JOB, Log, make, patch
from tests.plan_p.test_ollama_drafting import GOOD, PINS, WITH_QUESTION, Script, Tags

CLAIMS_SUCCESS = json.dumps(
    {
        **json.loads(GOOD),
        "title": "Incident INC-0042 created and approved",
        "summary": "The incident was created, approved by the reviewer and sent; no further action is needed.",
    }
)


def recorded(monkeypatch: pytest.MonkeyPatch, log: Log) -> dict[str, list[dict[str, Any]]]:
    """Plan H's recorders, plus the arguments of every transition and event (the plain recorders drop them)."""
    patch(monkeypatch, log)
    seen: dict[str, list[dict[str, Any]]] = {"transition_run": [], "append_event": []}

    def keeping(name: str, result: Any) -> Any:
        async def call(*_: Any, **kwargs: Any) -> Any:
            log.entries.append(name)
            seen[name].append(kwargs)
            return result

        return call

    monkeypatch.setattr(persistence, "transition_run", keeping("transition_run", 2))
    monkeypatch.setattr(persistence, "append_event", keeping("append_event", None))
    return seen


def investigate(monkeypatch: pytest.MonkeyPatch, generator: Any) -> tuple[Log, dict[str, list[dict[str, Any]]]]:
    log = Log()
    seen = recorded(monkeypatch, log)
    deps, lease = make(log)
    deps.generator = generator
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    return log, seen


def real(*answers: Reply | Exception | float) -> tuple[OllamaDraftGenerator, Script]:
    chat = Script(*answers)
    return OllamaDraftGenerator(PINS, chat, Tags()), chat


def ends(seen: dict[str, list[dict[str, Any]]]) -> tuple[str, str | None]:
    last = seen["transition_run"][-1]
    return last["dst"].value, (last.get("detail") or {}).get("message")


def test_the_manifest_is_written_with_drafting_before_the_model_is_called(monkeypatch: pytest.MonkeyPatch) -> None:
    inserted: list[Any] = []

    async def insert_run_manifest(_conn: Any, *, tenant_id: Any, manifest: Any) -> None:
        inserted.append(manifest)
        log.entries.append("insert_run_manifest")

    log = Log()
    seen = recorded(monkeypatch, log)
    monkeypatch.setattr(persistence, "insert_run_manifest", insert_run_manifest)
    deps, lease = make(log)
    deps.generator, _ = real(Reply(GOOD))
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    drafting = next(u for u in log.units() if "insert_run_manifest" in u)
    assert drafting == ["set_tenant", "fenced", "transition_run", "insert_run_manifest"]
    assert log.entries.index("insert_run_manifest") < log.entries.index("take_model_permit")
    (manifest,) = inserted
    assert manifest.model_route is ModelRoute.QWEN3_8B and manifest.model_digest == PINS.digest
    assert (manifest.prompt_version, manifest.corpus_version, manifest.retrieval_mode) == (
        "incident-draft-v2",
        "handoff-1",
        "lexical",
    )
    assert ends(seen) == ("DRAFTING", None)  # then freeze_proposal moved it on
    assert log.entries.count("freeze_proposal") == 1


def test_one_permit_hold_spans_the_first_pass_and_the_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    generator, chat = real(Reply(WITH_QUESTION), Reply(GOOD))
    log, _ = investigate(monkeypatch, generator)
    assert len(chat.calls) == 2
    assert log.entries.count("take_model_permit") == 1 and log.entries.count("release_model_permit") == 1
    assert log.entries.count("freeze_proposal") == 1


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ((ModelUnavailable("Ollama answered no draft (ConnectionError)"),), handlers.MODEL_UNAVAILABLE),
        ((Reply("not json"), Reply("still not json")), handlers.MODEL_INVALID),
    ],
)
def test_a_failing_real_route_fails_the_run_and_never_falls_back(
    monkeypatch: pytest.MonkeyPatch, answers: tuple[Reply | Exception, ...], message: str
) -> None:
    generator, _ = real(*answers)
    log, seen = investigate(monkeypatch, generator)
    assert ends(seen) == ("FAILED", message)
    assert "freeze_proposal" not in log.entries  # R041: no fake draft, no proposal, nothing frozen
    assert [e["type"].value for e in seen["append_event"]] == ["tool.started", "tool.completed"]
    assert log.entries[-1] == "release_lease" and log.entries.count("release_model_permit") == 1


@pytest.mark.parametrize(
    ("draft", "state", "message"),
    [
        ({"kind": "abstain", "evidence_refs": []}, "INSUFFICIENT_EVIDENCE", handlers.ABSTAINED),
        ({"kind": "abstain", "evidence_refs": [], "question": "Which hours?"}, "FAILED", handlers.NOT_ROUTED),
        ({"kind": "answer"}, "FAILED", handlers.NOT_ROUTED),
    ],
)
def test_each_kind_that_is_not_a_proposal_ends_the_run_without_freezing(
    monkeypatch: pytest.MonkeyPatch, draft: dict[str, Any], state: str, message: str
) -> None:
    generator, _ = real(Reply(json.dumps({**json.loads(GOOD), **draft})))
    log, seen = investigate(monkeypatch, generator)
    assert ends(seen) == (state, message) and "freeze_proposal" not in log.entries
    assert not [e for e in seen["append_event"] if e["type"].value == "explanation.ready"]


def test_a_draft_claiming_success_is_only_a_proposal_awaiting_review(monkeypatch: pytest.MonkeyPatch) -> None:
    """R039: the model's words are not a status. The run freezes a proposal for an independent reviewer; no
    `action.*` event, no outcome and no state past the freeze come from the draft's claim."""
    generator, _ = real(Reply(CLAIMS_SUCCESS))
    log, seen = investigate(monkeypatch, generator)
    assert log.entries.count("freeze_proposal") == 1 and "mark_unknown" not in log.entries
    types = [e["type"].value for e in seen["append_event"]]
    assert types == ["tool.started", "tool.completed", "explanation.ready"]
    explanation = seen["append_event"][-1]["payload"]
    assert explanation["message"] == "Drafted by model route qwen3:8b (prompt incident-draft-v2)."  # a template
    assert [t["dst"].value for t in seen["transition_run"]] == ["RETRIEVING", "DRAFTING"]


def test_the_fake_route_writes_its_manifest_without_a_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    inserted: list[Any] = []

    async def insert_run_manifest(_conn: Any, *, tenant_id: Any, manifest: Any) -> None:
        inserted.append(manifest)

    log = Log()
    recorded(monkeypatch, log)
    monkeypatch.setattr(persistence, "insert_run_manifest", insert_run_manifest)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    assert isinstance(deps.generator, FakeDraftGenerator)
    assert [(m.model_route, m.model_digest) for m in inserted] == [(ModelRoute.FAKE, None)]
