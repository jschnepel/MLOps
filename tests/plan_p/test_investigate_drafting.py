"""`handlers.investigate` around the model route, without a database (T19; SA:137, SA:147, SA:451; R039, R041, R130).

On Plan H's fakes (`tests/plan_h/test_worker_units.py`), which log every unit and every persistence call. Catches: a
run manifest written after the model call or outside the DRAFTING unit, or without the route's digest; a permit
taken twice for one draft (the repair must share the first pass's hold); a failing real route that falls back to a
fake draft or freezes anything; an outage or an exhausted repair that does not leave the run waiting in DRAFTING for
a manual proposal (T21, erratum 134: before T21 a templated FAILED); an abstention that
is not INSUFFICIENT_EVIDENCE; an answer or a clarifying question frozen as a proposal instead of ending ANSWERED or
waiting for input (T20 routes them); and a draft that claims success turning into an `action.*` event, a status or
anything but a proposal awaiting review. Since T20 the handler runs the graph (`ops_worker.graph`), so the reads are
the asset status, the alerts and the search, each between its tool events.
"""

import asyncio
import json
from typing import Any

import pytest
from ops_core import persistence
from ops_core.lease import Lease
from ops_core.routing import ModelRoute
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator, ModelUnavailable
from ops_worker.graph import nodes
from ops_worker.ollama_drafting import OllamaDraftGenerator, Reply

from tests.plan_h.test_worker_units import JOB, RUN, RUN_ID, Log, make, patch
from tests.plan_p.test_ollama_drafting import GOOD, PINS, WITH_QUESTION, Script, Tags

CLAIMS_SUCCESS = json.dumps(
    {
        **json.loads(GOOD),
        "title": "Incident INC-0042 created and approved",
        "summary": "The incident was created, approved by the reviewer and sent; no further action is needed.",
    }
)


def recorded(
    monkeypatch: pytest.MonkeyPatch, log: Log, run: dict[str, Any] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Plan H's recorders, plus the arguments of every transition and event (the plain recorders drop them); each
    call still goes through Plan H's recorder, which keeps the run row's state (T20: the nodes reread it)."""
    patch(monkeypatch, log, run=run)
    seen: dict[str, list[dict[str, Any]]] = {"transition_run": [], "append_event": []}

    def keeping(name: str) -> Any:
        inner = getattr(persistence, name)

        async def call(*args: Any, **kwargs: Any) -> Any:
            seen[name].append(kwargs)
            return await inner(*args, **kwargs)

        return call

    monkeypatch.setattr(persistence, "transition_run", keeping("transition_run"))
    monkeypatch.setattr(persistence, "append_event", keeping("append_event"))
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

    async def insert_run_manifest(_conn: Any, *, tenant_id: Any, manifest: Any, revision: int) -> None:
        inserted.append(manifest)
        log.entries.append("insert_run_manifest")

    log = Log()
    seen = recorded(monkeypatch, log)
    monkeypatch.setattr(persistence, "insert_run_manifest", insert_run_manifest)
    deps, lease = make(log)
    deps.generator, _ = real(Reply(GOOD))
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    drafting = next(u for u in log.units() if "insert_run_manifest" in u)
    assert drafting == [
        "set_tenant",
        "fenced",
        "transition_run",
        "run_manifest_exists",
        "insert_run_manifest",
        "record_asset_observation",  # T21: the status observation the grant checks (R116)
    ]
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
    "answers",
    [(ModelUnavailable("Ollama answered no draft (ConnectionError)"),), (Reply("not json"), Reply("still not json"))],
    ids=["unavailable", "invalid-after-repair"],
)
def test_a_failing_real_route_leaves_the_run_for_a_manual_proposal(
    monkeypatch: pytest.MonkeyPatch, answers: tuple[Reply | Exception, ...]
) -> None:
    """T21 (erratum 134, Plan R ruling 7): the run stays DRAFTING with its stored checkpoint cleared and a templated
    explanation; a person's proposal moves it on (DEV-025's FAILED_WITH_MANUAL_PATH)."""
    generator, _ = real(*answers)
    log, seen = investigate(monkeypatch, generator)
    assert ends(seen) == ("DRAFTING", None)
    assert "freeze_proposal" not in log.entries  # R041: no fake draft, no proposal, nothing frozen
    events = [(e["type"].value, e["payload"].get("message")) for e in seen["append_event"]]
    assert events[-1] == ("explanation.ready", nodes.MANUAL_PATH) and len(events) == 7  # after the three reads
    assert log.entries[-3:] == ["clear_checkpoint_id", "COMMIT", "release_lease"]
    assert log.entries.count("release_model_permit") == 1


@pytest.mark.parametrize(
    ("draft", "state", "message"),
    [
        ({"kind": "abstain", "evidence_refs": []}, "INSUFFICIENT_EVIDENCE", handlers.ABSTAINED),
        ({"kind": "abstain", "evidence_refs": [], "question": "Which hours?"}, "AWAITING_INPUT", "Which hours?"),
        ({"kind": "answer"}, "ANSWERED", nodes.ANSWERED),
    ],
)
def test_each_kind_that_is_not_a_proposal_ends_the_run_without_freezing(
    monkeypatch: pytest.MonkeyPatch, draft: dict[str, Any], state: str, message: str
) -> None:
    """T20 routes the kinds Plan P left FAILED: a question waits for input (its event carries it), an answer ends
    ANSWERED with its summary in explanation.ready; neither freezes anything."""
    generator, _ = real(Reply(json.dumps({**json.loads(GOOD), **draft})))
    log, seen = investigate(monkeypatch, generator)
    assert ends(seen) == (state, message) and "freeze_proposal" not in log.entries
    explained = [e["payload"]["message"] for e in seen["append_event"] if e["type"].value == "explanation.ready"]
    assert explained == (["The review rule applies."] if state == "ANSWERED" else [])


def test_a_draft_claiming_success_is_only_a_proposal_awaiting_review(monkeypatch: pytest.MonkeyPatch) -> None:
    """R039: the model's words are not a status. The run freezes a proposal for an independent reviewer; no
    `action.*` event, no outcome and no state past the freeze come from the draft's claim."""
    generator, _ = real(Reply(CLAIMS_SUCCESS))
    log, seen = investigate(monkeypatch, generator)
    assert log.entries.count("freeze_proposal") == 1 and "mark_unknown" not in log.entries
    types = [e["type"].value for e in seen["append_event"]]
    assert types == ["tool.started", "tool.completed"] * 3 + ["explanation.ready"]
    explanation = seen["append_event"][-1]["payload"]
    assert explanation["message"] == "Drafted by model route qwen3:8b (prompt incident-draft-v2)."  # a template
    assert [t["dst"].value for t in seen["transition_run"]] == ["RETRIEVING", "DRAFTING"]


def test_the_fake_route_writes_its_manifest_without_a_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    inserted: list[Any] = []

    async def insert_run_manifest(_conn: Any, *, tenant_id: Any, manifest: Any, revision: int) -> None:
        inserted.append(manifest)

    log = Log()
    recorded(monkeypatch, log)
    monkeypatch.setattr(persistence, "insert_run_manifest", insert_run_manifest)
    deps, lease = make(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    assert isinstance(deps.generator, FakeDraftGenerator)
    assert [(m.model_route, m.model_digest) for m in inserted] == [(ModelRoute.FAKE, None)]


class Recording(FakeDraftGenerator):
    """The fake route that keeps the request it was given and how many permits were held when it got it."""

    def __init__(self, log: Log) -> None:
        super().__init__()
        self.log = log
        self.requests: list[Any] = []
        self.held: list[int] = []

    async def generate(self, request: Any, evidence: Any) -> Any:
        self.requests.append(request)
        self.held.append(self.log.entries.count("take_model_permit") - self.log.entries.count("release_model_permit"))
        return await super().generate(request, evidence)


def stepped(
    monkeypatch: pytest.MonkeyPatch, log: Log, *, permit_wait: float, run: dict[str, Any] | None = None
) -> tuple[handlers.Deps, Lease, dict[str, list[dict[str, Any]]]]:
    """A lease on a clock the test moves: taking the model permit takes `permit_wait` seconds of it. The lease is long
    enough that its local deadline is not what these tests meet (the heartbeat would renew it)."""
    seen = recorded(monkeypatch, log, run)
    now = [100.0]

    def clock() -> float:
        return now[0]

    async def take(*_: Any, **__: Any) -> int:
        log.entries.append("take_model_permit")
        now[0] += permit_wait
        return 1

    monkeypatch.setattr(persistence, "take_model_permit", take)
    deps, _ = make(log, clock)
    lease = Lease(run_id=RUN_ID, owner="w:test", fence=3, lease_seconds=3600, started=clock(), clock=clock)
    return deps, lease, seen


def test_the_draft_gets_what_the_run_budget_has_left_once_the_permit_is_held(monkeypatch: pytest.MonkeyPatch) -> None:
    """BS:555: 90 s from the claim, less the time already spent (here the permit wait) and the 5 s margin; the request
    is built inside the hold, so the wait counts (round 1 I3)."""
    log = Log()
    deps, lease, _ = stepped(monkeypatch, log, permit_wait=12.0)
    deps.generator = recording = Recording(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    (request,) = recording.requests
    assert recording.held == [1]  # the permit was already held when the request was built and sent
    assert request.remaining_seconds == deps.leases.compute_budget_seconds - 12.0 - handlers.BUDGET_MARGIN_SECONDS
    assert request.remaining_seconds == 73.0 and request.answer_only is False


def test_an_answer_only_run_asks_for_an_answer_only_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Log()
    deps, lease, seen = stepped(monkeypatch, log, permit_wait=0.0, run={**RUN, "intent": "answer_only"})
    deps.generator = recording = Recording(log)
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    assert [r.answer_only for r in recording.requests] == [True]
    assert "freeze_proposal" not in log.entries  # SA:453: an answer_only run never freezes a proposal
    assert ends(seen) == ("ANSWERED", nodes.ANSWERED)  # the fake route answers an answer_only run (T20)


def test_the_last_seconds_of_the_budget_still_reach_the_route_as_the_attempt_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = Log()
    deps, lease, seen = stepped(monkeypatch, log, permit_wait=84.0)  # 90 - 84 - 5 = 1 s left
    deps.generator, chat = real(Reply(GOOD))
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    assert [c[2] for c in chat.calls] == [pytest.approx(1.0, abs=0.1)]  # the generator's own clock ran a little
    assert ends(seen) == ("DRAFTING", None) and log.entries.count("freeze_proposal") == 1


def test_a_budget_spent_before_the_draft_fails_the_run_without_calling_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = Log()
    deps, lease, seen = stepped(monkeypatch, log, permit_wait=85.0)  # 90 - 85 - 5 = 0 s left
    deps.generator, chat = real(Reply(GOOD))
    asyncio.run(handlers.handle(deps, dict(JOB), lease))
    assert chat.calls == []  # not a single request to Ollama
    assert ends(seen) == ("DRAFTING", None)  # T21: the run waits for a manual proposal (erratum 134)
    assert "freeze_proposal" not in log.entries
    assert log.entries.count("take_model_permit") == 1 and log.entries.count("release_model_permit") == 1
    assert log.entries[-1] == "release_lease"
