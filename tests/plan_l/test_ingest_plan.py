"""Ingestion's plan and its command without a database (R032's rules; BS:411-413; Plan L rulings 5-7).

Catches: a repeated run that writes a row (an ingestion record included), a changed hash or immutable attribute under
the same version accepted instead of refused, a lifecycle change written as anything but one more state row with the
next `seq`, a revoked version brought back, a stored version silently dropped because the catalog no longer lists it,
a refusal message that quotes document text, versions written out of order (a successor before its predecessor), and
a `skeleton.py ingest` that writes after a refusal or exits 0 on one.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from ops_core import corpus, ingest

from scripts import skeleton

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
GOVERNED = corpus.load(skeleton.CORPUS)
ALPHA_DOCS = [d for d in GOVERNED.documents if d.tenant == "alpha"]


def stored(docs: list[corpus.Document], **over: Any) -> dict[tuple[str, str], ingest.Stored]:
    """What the store would hold after ingesting `docs`, with `over` applied to every entry."""
    return {
        (d.document_id, d.version): replace(
            ingest.Stored(d.content_sha256, ingest.attributes(d), ingest.lifecycle(d), 1), **over
        )
        for d in docs
    }


def current() -> tuple[int, str, str]:
    return (1, GOVERNED.corpus_version, GOVERNED.lock_sha256)


def test_a_fresh_store_gets_every_version_in_order_and_one_record() -> None:
    step = ingest.plan(GOVERNED, "alpha", ALPHA, {}, None)
    assert step.problems == () and step.record and step.next_seq == 1 and step.restated == ()
    keys = [(d.document_id, int(d.version)) for d in step.new]
    assert keys == sorted(keys) and len(keys) == len(ALPHA_DOCS)  # a predecessor is always written first


def test_a_repeated_run_writes_nothing_at_all() -> None:
    step = ingest.plan(GOVERNED, "alpha", ALPHA, stored(ALPHA_DOCS), current())
    assert (step.new, step.restated, step.record, step.unchanged) == ((), (), False, len(ALPHA_DOCS))


def test_a_new_corpus_version_is_recorded_even_when_no_document_changed() -> None:
    step = ingest.plan(GOVERNED, "alpha", ALPHA, stored(ALPHA_DOCS), (4, "corpus-0", "f" * 64))
    assert step.record and step.next_seq == 5 and (step.new, step.restated) == ((), ())


def test_a_lifecycle_change_appends_the_next_state_row() -> None:
    held = stored(ALPHA_DOCS)
    key = ("ALPHA-ALERT-REVIEW", "1")
    held[key] = replace(held[key], lifecycle=("draft", held[key].lifecycle[1], None), seq=3)
    step = ingest.plan(GOVERNED, "alpha", ALPHA, held, current())
    assert [(d.document_id, seq) for d, seq in step.restated] == [("ALPHA-ALERT-REVIEW", 4)] and step.record


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"content_sha256": "0" * 64}, "the content changed under the same version"),
        (
            {"attributes": ("other.md", (), None, "normal", None, None)},
            "an immutable attribute changed under the same version",
        ),
    ],
)
def test_a_changed_version_is_refused(change: dict[str, Any], reason: str) -> None:
    held = stored(ALPHA_DOCS)
    key = ("ALPHA-ALERT-REVIEW", "1")
    held[key] = replace(held[key], **change)
    step = ingest.plan(GOVERNED, "alpha", ALPHA, held, current())
    assert step.problems == (f"alpha ALPHA-ALERT-REVIEW v1: {reason}",)
    assert (step.new, step.restated, step.record) == ((), (), False)


def test_a_revoked_version_never_changes_and_a_dropped_one_is_refused() -> None:
    held = stored(ALPHA_DOCS)
    revoked = ("ALPHA-ALARM-BYPASS", "1")
    held[revoked] = replace(held[revoked], lifecycle=("revoked", held[revoked].lifecycle[1], None))
    approved = [replace(d, status="approved") if (d.document_id, d.version) == revoked else d for d in ALPHA_DOCS]
    step = ingest.plan(replace(GOVERNED, documents=tuple(approved)), "alpha", ALPHA, held, current())
    assert step.problems == ("alpha ALPHA-ALARM-BYPASS v1: a revoked version cannot change again",)
    dropped = [d for d in GOVERNED.documents if d.document_id != "ALPHA-NOISE-SURVEY"]
    step = ingest.plan(replace(GOVERNED, documents=tuple(dropped)), "alpha", ALPHA, stored(ALPHA_DOCS), current())
    assert step.problems == ("alpha ALPHA-NOISE-SURVEY v1: stored but missing from the catalog (revoke it instead)",)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"status": "draft"}, "a version that has left draft cannot return to it"),
        ({"effective_from": datetime(2027, 1, 1, tzinfo=UTC)}, "keeps its effective_from"),
    ],
)
def test_a_successor_cannot_be_pulled_back_or_postponed(change: dict[str, Any], reason: str) -> None:
    """Round 2, I1: either change would un-retire ALPHA-PUMP-SEAL v1 (the search retires a version by the latest
    state of every later one), so both are refused; the allowed changes stay allowed."""
    key = ("ALPHA-PUMP-SEAL", "2")
    changed = [replace(d, **change) if (d.document_id, d.version) == key else d for d in ALPHA_DOCS]
    step = ingest.plan(replace(GOVERNED, documents=tuple(changed)), "alpha", ALPHA, stored(ALPHA_DOCS), current())
    assert len(step.problems) == 1 and reason in step.problems[0] and "ALPHA-PUMP-SEAL v2" in step.problems[0]
    for allowed in (
        {"status": "superseded"},
        {"status": "revoked"},
        {"effective_to": datetime(2027, 1, 1, tzinfo=UTC)},
    ):
        changed = [replace(d, **allowed) if (d.document_id, d.version) == key else d for d in ALPHA_DOCS]
        step = ingest.plan(replace(GOVERNED, documents=tuple(changed)), "alpha", ALPHA, stored(ALPHA_DOCS), current())
        assert step.problems == () and [d.version for d, _ in step.restated] == ["2"], allowed


def test_no_refusal_quotes_document_text() -> None:
    held = {key: replace(value, content_sha256="0" * 64) for key, value in stored(ALPHA_DOCS).items()}
    step = ingest.plan(GOVERNED, "alpha", ALPHA, held, current())
    bodies = [s.body for d in ALPHA_DOCS for s in d.sections]
    assert len(step.problems) == len(ALPHA_DOCS)
    assert not any(body[:40] in problem for problem in step.problems for body in bodies)


def test_the_command_reports_refusals_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(skeleton, "load_dotenv", lambda path: {})
    monkeypatch.setattr(skeleton, "export_environment", lambda dotenv: None)
    monkeypatch.setattr(skeleton.settings, "app_postgres", lambda role: role)
    calls: list[Any] = []

    async def refusing(pg: Any, governed: corpus.Corpus) -> list[ingest.Report]:
        calls.append(pg)
        raise ingest.IngestRefused(["alpha X v1: the content changed under the same version"])

    monkeypatch.setattr(skeleton, "_ingest", refusing)
    assert skeleton.ingest() == 1 and calls == [skeleton.Role.WORKER]  # it connects as the worker, nobody else
    assert capsys.readouterr().out.splitlines() == [
        "INGEST: refused, nothing written",
        "  alpha X v1: the content changed under the same version",
    ]

    async def moved(pg: Any, governed: corpus.Corpus) -> list[ingest.Report]:
        raise ingest.IngestRefused(["beta X v1: the content changed under the same version"], written=("alpha",))

    monkeypatch.setattr(skeleton, "_ingest", moved)
    assert skeleton.ingest() == 1  # a phase-2 refusal never claims that nothing was written (round 1, M1)
    assert capsys.readouterr().out.splitlines()[0] == "INGEST: refused after writing alpha"

    async def ingesting(pg: Any, governed: corpus.Corpus) -> list[ingest.Report]:
        return [ingest.Report("alpha", "corpus-1", 9, 0, 0, True), ingest.Report("beta", "corpus-1", 0, 0, 7, False)]

    monkeypatch.setattr(skeleton, "_ingest", ingesting)
    assert skeleton.ingest() == 0
    assert capsys.readouterr().out.splitlines() == [
        "INGEST: alpha corpus-1: 9 new, 0 restated, 0 unchanged",
        "INGEST: beta corpus-1: 0 new, 0 restated, 7 unchanged (nothing to write)",
    ]
    assert skeleton.main(["skeleton.py", "ingest"]) == 0  # the sub-command is registered
