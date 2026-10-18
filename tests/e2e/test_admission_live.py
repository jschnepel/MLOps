"""T12 live (OPS_LIVE=1): durable admission against the per-session test database, through the real API app and
`DbStore` as role `api` in this process (R015, R016, R017, R018, R115, R129; Plan G rulings 6, 11, 15, 24).

Identity is the unit tests' stub verifier (a bearer token is a persona's name) resolved against the seeded
memberships by the real `resolve_identity`; Keycloak is not involved, because nothing here is about tokens (T11 owns
those). Two app instances hold two `api` connections, so a race is a real race in PostgreSQL (spike §4: one process
with one connection serialises it). Writes evidence to reports/admission/ (status codes, counts and the run ids of
the seeded tenant only).

Catches: an acknowledgement before commit or a record without its work (R015), a replay that starts a second run or
a changed body accepted (R016), two runs holding one conversation's slot or a status question that writes a job
(R017), an interval that moves with the clock or a text/form disagreement that starts work (R018), a route no input
reaches live (R129), a refused supersede or a second answer whose message outlives its savepoint beside the
recorded refusal (AM-16), and an error that is not the safe schema (R115).
"""

import asyncio
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from ops_api import store as st
from ops_api.app import ROUTE_MESSAGES, create_app
from ops_core import persistence, settings
from ops_core.settings import AdmissionSettings, Profile, Role
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_conversation
from tests.plan_f.auth_fakes import fake_auth
from tests.plan_g.fakes import StubVerifier

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/admission/t12-admission.txt")
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SAFE_KEYS = {"code", "message", "retryable", "request_id"}
SAMPLE = {
    "kind": "investigate",
    "text": "Investigate the alerts on Asset A17 over the last 24 hours.",
    "context": {"asset_id": "A17", "hours": 24},
}
# A week-long replay window, so R018's replay three days on the test clock is still inside it (the default 24 h
# window is SA:297's; the bound is ruling 7's maximum).
WEEK = AdmissionSettings(idempotency_ttl_seconds=604800)
EXPECTED_LINES = 14  # the evidence lines the six tests append between them
SKELETON_PORTS = (8000, 8070, 8071, 8081, 8082, 8090)
KEYS: list[str] = []  # every Idempotency-Key a test sent, so the `created` fixture can delete its records


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T12 durable admission — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture(scope="module", autouse=True)
def skeleton_is_down() -> None:
    """A live worker or sweeper would race these tests for jobs and slots, so refuse to run beside one."""
    for port in SKELETON_PORTS:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                pytest.fail(f"a skeleton process listens on 127.0.0.1:{port}; stop it (scripts/skeleton.py) first")


@pytest_asyncio.fixture
async def created(app_conn: persistence.Conn) -> AsyncIterator[list[str]]:
    """Every conversation a test makes is purged afterwards with all its rows (revision 0006's downgrade, a later
    module's R006 test, refuses a database that still holds a system message), and every record the test's keys
    left is deleted by key: an error's record names no conversation, so the purge alone would keep it."""
    made: list[str] = []
    yield made
    try:
        for cid in made:
            await purge_conversation(app_conn, UUID(cid))
    finally:
        await app_conn.execute("DELETE FROM app.idempotency_request WHERE key = ANY(%s)", (KEYS,))
        KEYS.clear()


@asynccontextmanager
async def api(admission: AdmissionSettings = WEEK) -> AsyncIterator[httpx2.AsyncClient]:
    """The real app over its own `api` connection, lifespan included (the 0006 relation guard runs)."""

    async def store() -> st.Store:
        return st.DbStore(await persistence.connect(settings.app_postgres(Role.API)))

    app = create_app(
        StubVerifier(), store_factory=store, auth_factory=fake_auth, admission=admission, profile=Profile.TEST
    )
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
            yield client


def h(name: str = "alex", key: str | None = None) -> dict[str, str]:
    """A persona's bearer header and an Idempotency-Key (fresh unless given), remembered for the clean-up."""
    chosen = key or str(uuid4())
    KEYS.append(chosen)
    return {"Authorization": f"Bearer {name}", "Idempotency-Key": chosen}


async def conversation(c: httpx2.AsyncClient, created: list[str]) -> str:
    r = await c.post("/api/v1/conversations", headers=h())
    status, cid = r.status_code, r.json().get("conversation_id")
    assert status == 201, status
    created.append(str(cid))
    return str(cid)


async def count(app_conn: persistence.Conn, sql: str, *params: Any) -> int:
    cur = await app_conn.execute(sql, params)
    return int((await cur.fetchone())["n"])


def messages(cid: str) -> str:
    return f"/api/v1/conversations/{cid}/messages"


async def test_r015_a_crash_before_commit_leaves_nothing_and_the_retry_commits(
    app_conn: persistence.Conn, created: list[str], lines: list[str]
) -> None:
    async with api() as c:
        cid = await conversation(c, created)
        armed = await c.post("/internal/faults/drop_before_commit", headers=h(), json={"count": 1})
        armed_status = armed.status_code
        assert armed_status == 200, armed_status
        # The run's id dies with the rollback, so its job is counted table-wide against this count; only an admission
        # inserts an `investigate` job (a sweeper's maintenance rows have their own type).
        investigate_jobs = "SELECT count(*) AS n FROM app.jobs WHERE type = 'investigate'"
        jobs_before = await count(app_conn, investigate_jobs)
        crashed = await c.post(messages(cid), headers=h(key="r015-key-0001"), json=SAMPLE)
        crash_status, crash_body = crashed.status_code, crashed.json()
        assert set(crash_body) == SAFE_KEYS and crash_body["retryable"] is True, crash_body
        assert crash_status == 503, crash_status  # a lost connection (ruling 24)
        left = [
            await count(app_conn, "SELECT count(*) AS n FROM app.messages WHERE conversation_id = %s", UUID(cid)),
            await count(app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", UUID(cid)),
            await count(app_conn, investigate_jobs) - jobs_before,
            await count(app_conn, "SELECT count(*) AS n FROM app.idempotency_request WHERE key = %s", "r015-key-0001"),
        ]
        assert left == [0, 0, 0, 0], left  # no ack, and nothing behind it (BS:681)
        retried = await c.post(messages(cid), headers=h(key="r015-key-0001"), json=SAMPLE)
        retry_status, run_id = retried.status_code, retried.json().get("run_id")
        assert retry_status == 202, retry_status
    cur = await app_conn.execute("SELECT type, dedup_key FROM app.jobs WHERE run_id = %s", (UUID(run_id),))
    jobs = [(r["type"], r["dedup_key"]) for r in await cur.fetchall()]
    assert jobs == [("investigate", f"{run_id}:1")]  # after commit the job exists
    lines.append(
        f"R015 crash before commit: 503 retryable=True, left messages/runs/jobs/records={left}; "
        f"retry 202 jobs={len(jobs)}"
    )


async def test_r016_a_replay_resolves_once_and_a_changed_body_conflicts(
    app_conn: persistence.Conn, created: list[str], lines: list[str]
) -> None:
    async with api() as c:
        cid, other = await conversation(c, created), await conversation(c, created)
        first = await c.post(messages(cid), headers=h(key="r016-key-0001"), json=SAMPLE)
        again = await c.post(messages(cid), headers=h(key="r016-key-0001"), json=SAMPLE)
        codes, same = (first.status_code, again.status_code), again.content == first.content
        assert codes == (202, 202) and same, codes
        first_run = first.json()["run_id"]
        changed = await c.post(
            messages(cid), headers=h(key="r016-key-0001"), json={**SAMPLE, "context": {"asset_id": "A17", "hours": 12}}
        )
        elsewhere = await c.post(messages(other), headers=h(key="r016-key-0001"), json=SAMPLE)
        conflicts = [(r.status_code, r.json()["code"]) for r in (changed, elsewhere)]
        assert conflicts == [(409, "IDEMPOTENCY_CONFLICT")] * 2, conflicts
        runs = await count(app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", UUID(cid))
        assert runs == 1
        # Ruling 6's re-read path: an expired record the sweeper has not purged yet blocks its key.
        await app_conn.execute(
            "INSERT INTO app.idempotency_request (tenant_id, subject, route, key, fingerprint_sha256, status_code,"
            " response, expires_at) VALUES (%s, %s, %s, 'r016-key-0002', %s, 202, %s,"
            " app.current_time() - interval '1 minute')",
            (ALPHA, ALEX, ROUTE_MESSAGES, "0" * 64, Jsonb({"old": True})),
        )
        try:
            blocked = await c.post(messages(other), headers=h(key="r016-key-0002"), json=SAMPLE)
            blocked_code, blocked_message = blocked.status_code, blocked.json()["message"]
            assert (blocked_code, blocked_message) == (409, "Idempotency-Key is not reusable yet; use a new key")
            other_runs = await count(
                app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", UUID(other)
            )
            assert other_runs == 0  # the unit's work was rolled back with the failed record insert
        finally:
            await app_conn.execute("DELETE FROM app.idempotency_request WHERE key = 'r016-key-0002'")
        # AM-16 in PostgreSQL: create_run refuses a supersede across conversations (OC002) after the message is
        # written, and only start_run's savepoint takes that message back before the 404 is recorded.
        across = {**SAMPLE, "supersedes_run_id": first_run}
        superseding = await c.post(messages(other), headers=h(key="r016-key-0003"), json=across)
        supersede = (superseding.status_code, superseding.json()["message"])
        assert supersede == (404, "no such superseded run"), supersede
        kept = [
            await count(app_conn, "SELECT count(*) AS n FROM app.messages WHERE conversation_id = %s", UUID(other)),
            await count(app_conn, "SELECT count(*) AS n FROM app.idempotency_request WHERE key = %s", "r016-key-0003"),
        ]
        assert kept == [0, 1], kept
    lines.append(f"R016 replay: 202 twice, same bytes={same}, runs=1; changed body and other conversation: {conflicts}")
    lines.append(f"R016 expired unpurged key: {blocked_code} not reusable, runs started=0")
    lines.append(f"R016 supersede across conversations: {supersede}, messages/records={kept}")


async def test_r017_one_active_run_per_conversation(
    app_conn: persistence.Conn, created: list[str], lines: list[str]
) -> None:
    async with api() as one, api() as two:  # two apps, two `api` connections: the race reaches PostgreSQL
        cid = await conversation(one, created)
        keys = ("r017-key-0001", "r017-key-0002")
        raced = await asyncio.gather(
            one.post(messages(cid), headers=h(key=keys[0]), json=SAMPLE),
            two.post(messages(cid), headers=h(key=keys[1]), json=SAMPLE),
        )
        statuses = sorted(r.status_code for r in raced)
        codes = [r.json().get("code") for r in raced if r.status_code == 409]
        assert statuses == [202, 409] and codes == ["SLOT_OCCUPIED"], statuses
        loser = next(key for key, r in zip(keys, raced, strict=True) if r.status_code == 409)
        held = await count(
            app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s AND slot_held", UUID(cid)
        )
        written = await count(app_conn, "SELECT count(*) AS n FROM app.messages WHERE conversation_id = %s", UUID(cid))
        refusals = await count(
            app_conn, "SELECT count(*) AS n FROM app.idempotency_request WHERE key = %s AND status_code = 409", loser
        )
        # AM-16: the loser wrote nothing but its record, whether the slot read or create_run's savepoint refused it.
        assert (held, written, refusals) == (1, 1, 1), (held, written, refusals)
        twin = await conversation(one, created)
        same_key = await asyncio.gather(
            one.post(messages(twin), headers=h(key="r017-key-0003"), json=SAMPLE),
            two.post(messages(twin), headers=h(key="r017-key-0003"), json=SAMPLE),
        )
        twins, twin_bytes = [r.status_code for r in same_key], same_key[0].content == same_key[1].content
        assert twins == [202, 202] and twin_bytes, twins  # the advisory lock, then a replay
        twin_runs = await count(app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", UUID(twin))
        assert twin_runs == 1
        before = [
            await count(
                app_conn,
                "SELECT count(*) AS n FROM app.jobs j JOIN app.runs r ON r.run_id = j.run_id"
                " WHERE r.conversation_id = %s",
                UUID(cid),
            ),
            await count(app_conn, "SELECT count(*) AS n FROM app.events e WHERE e.conversation_id = %s", UUID(cid)),
        ]
        status = await one.post(messages(cid), headers=h(), json={"kind": "status", "text": "Where is my run?"})
        after = [
            await count(
                app_conn,
                "SELECT count(*) AS n FROM app.jobs j JOIN app.runs r ON r.run_id = j.run_id"
                " WHERE r.conversation_id = %s",
                UUID(cid),
            ),
            await count(app_conn, "SELECT count(*) AS n FROM app.events e WHERE e.conversation_id = %s", UUID(cid)),
        ]
        status_code, answer = status.status_code, status.json()["answer"]
        assert status_code == 200 and after == before and answer.startswith("Run ")
        busy = await one.post(messages(cid), headers=h(), json=SAMPLE)
        busy_code = (busy.status_code, busy.json()["code"])
        assert busy_code == (409, "SLOT_OCCUPIED")
    lines.append(
        f"R017 race, two connections, two keys: {statuses}; slot holders, messages, loser's 409 records: "
        f"{[held, written, refusals]}; one key: {twins} with one run"
    )
    lines.append(
        f"R017 status question while busy: 200, jobs/events unchanged {before}; sequential admission {busy_code}"
    )


async def test_r018_the_interval_is_resolved_once_and_ambiguity_clarifies(
    app_conn: persistence.Conn, role_conn: RoleConn, created: list[str], lines: list[str]
) -> None:
    harness = await role_conn(Role.TEST_HARNESS)
    try:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '2 hours'")
        async with api() as c:
            cid = await conversation(c, created)
            first = await c.post(messages(cid), headers=h(key="r018-key-0001"), json=SAMPLE)
            first_code, first_body = first.status_code, first.json()
            assert first_code == 202, first_code
            run_id = UUID(first_body["run_id"])
            cur = await app_conn.execute(
                "SELECT start_at, end_at, end_at - clock_timestamp() AS ahead FROM app.runs WHERE run_id = %s",
                (run_id,),
            )
            stored = await cur.fetchone()
            ahead = stored["ahead"]
            # The window ends on the database clock, two hours ahead of the wall clock (ruling 11; spike §7).
            assert timedelta(hours=1, minutes=59) < ahead < timedelta(hours=2, minutes=1), ahead
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '3 days 2 hours'")
            replay = await c.post(messages(cid), headers=h(key="r018-key-0001"), json=SAMPLE)
            replay_code, replay_same = replay.status_code, replay.content == first.content
            assert replay_code == 202 and replay_same, replay_code
            cur = await app_conn.execute("SELECT start_at, end_at FROM app.runs WHERE run_id = %s", (run_id,))
            again = await cur.fetchone()
            interval_same = (again["start_at"], again["end_at"]) == (stored["start_at"], stored["end_at"])
            assert interval_same
            fresh = await c.post(messages(cid), headers=h(), json=SAMPLE)
            fresh_code = (fresh.status_code, fresh.json()["code"])
            assert fresh_code == (409, "SLOT_OCCUPIED")  # a new request, and the run still holds the slot
            ask = await conversation(c, created)
            conflict = {
                "kind": "investigate",
                "text": "Investigate B22 over the last 24 hours.",
                "context": {"asset_id": "A17", "hours": 24},
            }
            clarified = await c.post(messages(ask), headers=h(), json=conflict)
            clarify = (clarified.status_code, clarified.json()["cause"])
            assert clarify == (200, "asset_conflict"), clarify
        cur = await app_conn.execute(
            "SELECT kind, author IS NULL AS system FROM app.messages WHERE conversation_id = %s ORDER BY seq",
            (UUID(ask),),
        )
        stored_kinds = [(r["kind"], r["system"]) for r in await cur.fetchall()]
        assert stored_kinds == [("investigate", False), ("clarification_question", True)]
        runs_after = await count(app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", UUID(ask))
        assert runs_after == 0  # a stored clarification and never a job (R018)
    finally:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    lines.append(
        f"R018 window ends {ahead} past the wall clock (test clock +2 h); replay at +3 d: {replay_code}, "
        f"identical={replay_same}, interval unchanged={interval_same}"
    )
    lines.append(
        f"R018 new key while active: {fresh_code}; text B22 vs form A17: {clarify}, messages={stored_kinds}, runs=0"
    )


async def test_r129_every_admission_route_live(
    app_conn: persistence.Conn, role_conn: RoleConn, created: list[str], lines: list[str]
) -> None:
    worker = await role_conn(Role.WORKER)
    seen: dict[str, Any] = {}
    async with api() as c:
        inv_key = "r129-key-0000"
        investigate = await c.post(messages(cid := await conversation(c, created)), headers=h(key=inv_key), json=SAMPLE)
        seen["investigate"] = investigate.status_code
        assert seen["investigate"] == 202, seen
        inv_body = investigate.json()
        msgs_sql = "SELECT count(*) AS n FROM app.messages WHERE conversation_id = %s"
        msgs_before = await count(app_conn, msgs_sql, UUID(cid))
        status = await c.post(messages(cid), headers=h(), json={"kind": "status", "text": "Status?"})
        seen["status_question"] = status.status_code
        msgs_delta = await count(app_conn, msgs_sql, UUID(cid)) - msgs_before
        cur = await app_conn.execute(
            "SELECT kind, author IS NULL AS system FROM app.messages WHERE conversation_id = %s"
            " ORDER BY seq DESC LIMIT 1",
            (UUID(cid),),
        )
        last = await cur.fetchone()
        answer_row = (last["kind"], last["system"])
        assert msgs_delta == 2 and answer_row == ("status_answer", True), (msgs_delta, answer_row)
        ask = await c.post(
            messages(await conversation(c, created)),
            headers=h(),
            json={"kind": "ask", "text": "What did A17 log in the last day?"},
        )
        seen["readonly_answer"] = ask.status_code
        assert seen["readonly_answer"] == 202, seen
        ask_run = ask.json()["run_id"]
        clarify = await c.post(
            messages(await conversation(c, created)),
            headers=h(),
            json={"kind": "investigate", "text": "Investigate A17."},
        )
        seen["clarify"] = clarify.status_code
        reject = await c.post(
            messages(await conversation(c, created)), headers=h(), json={"kind": "clarification", "text": "A17"}
        )
        seen["reject"] = reject.status_code
        # Nothing in the worker asks for clarification yet (T20), so the run is staged where the worker would put it,
        # through the worker role's own function (as tests/e2e/test_definers_run_path_live.py does).
        run_id = UUID(inv_body["run_id"])
        async with worker.transaction():
            await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run_id,))
            await worker.execute(
                "SELECT app.transition_run(%s, 'RETRIEVING', 'AWAITING_INPUT', NULL, 2, '{}')", (run_id,)
            )
        cur = await app_conn.execute(
            "SELECT event_id FROM app.events WHERE run_id = %s AND type = 'clarification.requested'"
            " ORDER BY sequence DESC LIMIT 1",
            (run_id,),
        )
        question = (await cur.fetchone())["event_id"]
        # R016: the recorded 202 still says QUEUED; the run is AWAITING_INPUT now, and the replay is that record.
        cur = await app_conn.execute("SELECT state FROM app.runs WHERE run_id = %s", (run_id,))
        state_then = (await cur.fetchone())["state"]
        moved = await c.post(messages(cid), headers=h(key=inv_key), json=SAMPLE)
        moved_code, moved_same = moved.status_code, moved.content == investigate.content
        assert (moved_code, moved_same, state_then) == (202, True, "AWAITING_INPUT"), (moved_code, state_then)
        body = {"question_id": str(question), "expected_version": 3, "context": {"hours": 12}}
        url = f"/api/v1/runs/{run_id}/clarifications"
        # The realm's other requester is BETA's: RLS hides alex's run from riley's unit, so it is absent (404,
        # recorded). A second requester of ALPHA (the 403) exists only in the unit tests' fake (CASEY).
        foreign = await c.post(url, headers=h("riley"), json=body)
        foreign_status = foreign.status_code
        assert foreign_status == 404, foreign_status
        reply = await c.post(url, headers=h(), json=body)
        seen["clarification_reply"] = reply.status_code
        later = await c.post(messages(cid), headers=h(key=inv_key), json=SAMPLE)
        later_same = later.content == investigate.content
        assert later_same  # and again once the answer has moved the run on
        # AM-16 in PostgreSQL: a second answer under a new key writes its message, meets the job's dedup key
        # (rowcount 0), and only record_reply's savepoint takes that message back before the 409 is recorded.
        again = await c.post(url, headers=h(), json=body)
        answered = (again.status_code, again.json()["message"])
        assert answered == (409, "the clarification was already answered"), answered
        replies = await count(
            app_conn,
            "SELECT count(*) AS n FROM app.messages WHERE conversation_id = %s AND kind = 'clarification_reply'",
            UUID(cid),
        )
        assert replies == 1, replies
        # DoD 4: an unroutable kind is a 422 before the router, and nothing is written (AM-16, SA:373).
        unroutable = await c.post(
            messages(silent := await conversation(c, created)),
            headers=h(key="r129-key-0001"),
            json={"kind": "delete", "text": "Investigate A17 over the last 24 hours."},
        )
        refused = (unroutable.status_code, unroutable.json()["code"])
    assert seen == {
        "investigate": 202,
        "status_question": 200,
        "readonly_answer": 202,
        "clarify": 200,
        "reject": 422,
        "clarification_reply": 202,
    }, seen
    cur = await app_conn.execute("SELECT intent FROM app.runs WHERE run_id = %s", (UUID(ask_run),))
    intent = (await cur.fetchone())["intent"]
    assert intent == "answer_only"
    cur = await app_conn.execute(
        "SELECT dedup_key FROM app.jobs WHERE run_id = %s AND type = 'resume_input'", (run_id,)
    )
    resume_jobs = [r["dedup_key"] for r in await cur.fetchall()]
    assert resume_jobs == [f"{run_id}:{question}"]
    cur = await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run_id,))
    events = [r["type"] for r in await cur.fetchall()]
    assert events[-1] == "clarification.received", events
    written = [
        await count(app_conn, "SELECT count(*) AS n FROM app.messages WHERE conversation_id = %s", UUID(silent)),
        await count(app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", UUID(silent)),
        await count(app_conn, "SELECT count(*) AS n FROM app.idempotency_request WHERE key = %s", "r129-key-0001"),
    ]
    assert refused == (422, "INVALID_INPUT") and written == [0, 0, 0], (refused, written)
    lines.append(
        f"R129 routes: {seen}; run intent={intent}, resume_input jobs={len(resume_jobs)}, last event={events[-1]}"
    )
    lines.append(f"R129 status question: messages +{msgs_delta} (question, then system answer {answer_row})")
    lines.append(
        f"R016 replay after state moved: identical={moved_same} state_then={state_then}; "
        f"after the answer: identical={later_same}"
    )
    lines.append(
        f"R129 second answer under a new key: {answered}, clarification_reply messages={replies}; "
        f"the other tenant's requester: {foreign_status}"
    )
    lines.append(f"R129 unroutable kind 'delete': {refused}, messages/runs/records written={written}")


async def test_r115_live_errors_use_the_safe_schema(created: list[str], lines: list[str]) -> None:
    codes: list[int] = []
    checked = 0
    async with api(AdmissionSettings(max_body_bytes=1024)) as c:
        cid = await conversation(c, created)
        refusals = [
            await c.get("/api/v1/me", headers={"Authorization": "Bearer nobody"}),  # 401
            await c.post(messages(cid), headers=h("sam"), json=SAMPLE),  # 403: a reviewer cannot ask
            await c.post(messages(str(uuid4())), headers=h(), json=SAMPLE),  # 404
            await c.post(messages(cid), headers={"Authorization": "Bearer alex"}, json=SAMPLE),  # 422: no key
            await c.post(messages(cid), headers=h(), content=b" " * 1025),  # 422: body over the limit
            await c.get("/nope"),  # 404 from the router itself
        ]
        for r in refusals:
            status, doc, header = r.status_code, r.json(), r.headers.get("X-Request-Id")
            same = doc["request_id"] == header  # bound first: a header is never an assert operand
            assert set(doc) == SAFE_KEYS and same, status
            codes.append(status)
            checked += 1
    assert codes == [401, 403, 404, 422, 422, 404], codes
    lines.append(
        f"R115 live sample: {codes}, {checked} bodies checked, each with exactly {sorted(SAFE_KEYS)} "
        "and its X-Request-Id"
    )
