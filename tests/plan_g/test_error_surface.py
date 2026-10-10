"""R115's error surface (BUILD_SPEC §7 safe errors, Plan G rulings 19 and 20): every refusal the framework or a
defect produces is the `{code, message, retryable, request_id}` schema, `retryable` is true only for an outage that
may pass, and the id in the body is the id in the `X-Request-Id` header and in the one log line. That holds for a
replayed recorded error too: its stored id is rewritten to the replaying request's (ruling 4; pinned in
tests/plan_g/test_api_admission.py, which has the recorded verdicts).

Catches: FastAPI's `{"detail": ...}` 404/405 (spike §5), a plain-text 500, a psycopg DETAIL (a 23505 names the
tenant, the subject and the key, spike §1) or an exception's text reaching the client or the log, a server defect
marked retryable (a retry storm on a bug, BS:562), a statement too big or too complex for the server (an
`OperationalError` of SQLSTATE class 54) marked retryable like a lost connection, and a lost connection marked final.
"""

import logging
from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_api.limits import REQUEST_ID_HEADER

from tests.plan_d.test_api import FakeStore, StubVerifier, auth
from tests.plan_f.auth_fakes import fake_auth

CANARY = "canary-3e9d tenant=3ea79c95 key=k-secret"


@pytest.fixture
def app_and_store() -> Iterator[tuple[FastAPI, FakeStore]]:
    fake = FakeStore()
    yield create_app(StubVerifier(), store_factory=lambda: fake, auth_factory=fake_auth), fake


def safe_shape(body: dict[str, object]) -> bool:
    return set(body) == {"code", "message", "retryable", "request_id"} and UUID(str(body["request_id"])) is not None


def test_an_unknown_path_is_a_safe_404(app_and_store) -> None:
    app, _ = app_and_store
    with TestClient(app) as c:
        r = c.get("/nope")
    assert r.status_code == 404 and safe_shape(r.json())
    assert (r.json()["code"], r.json()["message"]) == ("NOT_FOUND", "no such route")


def test_a_wrong_method_is_a_safe_405_that_names_the_allowed_one(app_and_store) -> None:
    app, _ = app_and_store
    with TestClient(app) as c:
        r = c.get("/api/v1/conversations", headers=auth("alex"))
    assert r.status_code == 405 and safe_shape(r.json()) and r.json()["code"] == "INVALID_INPUT"
    assert r.headers["allow"] == "POST"


def test_a_malformed_path_parameter_is_a_safe_422(app_and_store) -> None:
    app, _ = app_and_store
    with TestClient(app) as c:
        r = c.get("/api/v1/runs/not-a-uuid", headers=auth("alex"))
    assert r.status_code == 422 and safe_shape(r.json()) and r.json()["message"] == "request is not valid"


def test_an_unhandled_exception_is_a_non_retryable_503_and_one_log_line(app_and_store, caplog) -> None:
    caplog.set_level(logging.ERROR, logger="ops_api")
    app, _ = app_and_store

    async def boom() -> dict[str, str]:
        raise RuntimeError(CANARY)

    app.add_api_route("/boom", boom, methods=["GET"])
    # Starlette re-raises after the catch-all answers (spike §5); the client must still get the safe body.
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    body = r.json()
    assert r.status_code == 503 and safe_shape(body)
    assert (body["code"], body["message"], body["retryable"]) == ("UNAVAILABLE", "service error", False)
    assert CANARY not in r.text and CANARY not in caplog.text
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "ops_api"]
    assert lines == [f"request {body['request_id']} failed: RuntimeError"]


def test_a_unique_violation_is_a_non_retryable_503_without_its_detail(app_and_store, caplog, monkeypatch) -> None:
    caplog.set_level(logging.ERROR, logger="ops_api")
    app, fake = app_and_store

    async def duplicate(tenant_id: UUID, run_id: UUID) -> None:
        raise psycopg.errors.UniqueViolation(f"duplicate key value violates unique constraint: {CANARY}")

    monkeypatch.setattr(fake, "run", duplicate)
    with TestClient(app) as c:
        r = c.get(f"/api/v1/runs/{uuid4()}", headers=auth("alex"))
    assert r.status_code == 503 and r.json()["retryable"] is False and r.json()["message"] == "service error"
    assert CANARY not in r.text and CANARY not in caplog.text and "UniqueViolation" in caplog.text


def test_a_lost_connection_is_a_retryable_503(app_and_store, monkeypatch) -> None:
    app, fake = app_and_store

    async def gone(tenant_id: UUID, run_id: UUID) -> None:
        raise psycopg.OperationalError(CANARY)

    monkeypatch.setattr(fake, "run", gone)
    with TestClient(app) as c:
        r = c.get(f"/api/v1/runs/{uuid4()}", headers=auth("alex"))
    assert r.status_code == 503 and r.json()["retryable"] is True and r.json()["message"] == "database unavailable"
    assert CANARY not in r.text


def test_a_statement_the_server_cannot_run_is_a_non_retryable_503(app_and_store, caplog, monkeypatch) -> None:
    caplog.set_level(logging.ERROR, logger="ops_api")
    app, fake = app_and_store
    answers, texts = [], []
    with TestClient(app) as c:
        # Both are OperationalError subclasses (class 54): the same statement fails the same way on every retry.
        for defect in (psycopg.errors.ProgramLimitExceeded, psycopg.errors.StatementTooComplex):

            async def too_big(tenant_id: UUID, run_id: UUID, defect: type[psycopg.Error] = defect) -> None:
                raise defect(CANARY)

            monkeypatch.setattr(fake, "run", too_big)
            r = c.get(f"/api/v1/runs/{uuid4()}", headers=auth("alex"))
            answers.append((r.status_code, r.json()["retryable"], r.json()["message"]))
            texts.append(r.text)
    assert answers == [(503, False, "service error")] * 2
    assert not any(CANARY in text for text in texts) and CANARY not in caplog.text
    assert "ProgramLimitExceeded" in caplog.text and "StatementTooComplex" in caplog.text


def test_the_request_id_header_is_the_body_request_id(app_and_store) -> None:
    app, _ = app_and_store
    with TestClient(app) as c:
        refused = c.get("/api/v1/me")
        served = c.get("/api/v1/me", headers=auth("alex"))
    assert refused.status_code == 401 and refused.headers[REQUEST_ID_HEADER] == refused.json()["request_id"]
    assert served.status_code == 200 and UUID(served.headers[REQUEST_ID_HEADER]) != UUID(refused.json()["request_id"])
