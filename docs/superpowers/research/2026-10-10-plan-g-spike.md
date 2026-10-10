# Plan G spike: measured idempotency, jobs grant, clock, admission race, errors, ordering, interval and queue bound

Date: 2026-10-10. Branch `plan-f` (HEAD `bcae618`). This was a throwaway spike for T12 (durable admission API and error
mapping); it answers the measurable half of the open questions in
`docs/superpowers/research/2026-10-09-plan-g-inputs.md` §5. Every script lives in `<scratch>` (the session scratchpad's
`spike_g/` directory) and ran from `<repo>` as `PYTHONUTF8=1 uv run python <scratch>/<script>`, so FastAPI, Starlette,
httpx2 and psycopg came from the repository's lock and nothing was added (no `--with`). `pyproject.toml` and `uv.lock`
were not touched. The repository was not modified; this report is the only file written there.

The spike ran only against the per-session test databases the live fixtures use, `ops_test` and `incident_test` under
`PROFILE=test`. `setup_db.py` creates and migrates them with the fixtures' own helpers
(`tests.e2e.conftest.recreate_databases` and `scripts.skeleton.migrate(Profile.TEST)`, exactly what the `migrated`
fixture does), and `cleanup.py` drops them. `migrate` also runs `ensure_roles`, which re-applies every role's password
from its secret file and narrows CONNECT on the two test databases, as every live test session does. Both databases
already existed when the spike started (left by an earlier live session at `0005_sessions_login_logout` +
`tc_0001_test_clock`). The spike ran twice: a first pass, then a final pass with the scripts reformatted so that their
lines and output fit this page. Each pass recreated and dropped both databases. All scripts and outputs below are from
the final pass.

The dev databases `ops` and `incident` received no write. They were only read: by the inventory (database list, `spike%`
relations, `alembic_version`) and by one catalog query in §3 (`has_function_privilege` and `pg_proc` for
`app.current_time()`). `scripts/skeleton.py migrate` and `up` were never run against them, and no skeleton process was
started. The Keycloak and PostgreSQL containers were not restarted.

No secret appears below. The scripts obtain credentials only through `ops_core.settings` (`superuser_postgres()`,
`app_postgres(role)`, both of which call `read_secret`), with `.env` loaded through `scripts.skeleton.load_dotenv` and
`export_environment`. After the final pass `secret_check.py` compared every secret file's value (read through
`read_secret`, printed as booleans only) with every script and output file: `secret files checked: 22 | spike files
checked: 38 | matches: []`.

What was created, and removed at the end:

- **Databases:** `ops_test`, `incident_test` (recreated and migrated, then dropped).
- **Scratch relations in `ops_test`:** `app.spike_idempotency_request` (§1, created and dropped twice),
  `app.spike_messages` and `app.spike_messages_serial` (§6). Each script drops what it created; the inventory before the
  database drop shows no `spike%` relation.
- **Rows in `ops_test`:** conversations, messages, runs and jobs written through the `api` role; they went with the
  database.
- **Test clock:** the offset was set to 2 hours (§3) and 3 days (§7) by `test_harness` and restored to `0` in a
  `finally`.
- **Nothing** in Keycloak, in the dev databases, or among the cluster's roles beyond `ensure_roles`' idempotent password
  and CONNECT statements.

Versions (measured): CPython 3.13.13, FastAPI 0.143.0, Starlette 1.7.0, uvicorn 0.54.0, httpx2 2.13.1, psycopg 3.3.6,
pydantic 2.13.5, PostgreSQL 17.11.

Output lines longer than 120 characters are wrapped at a separator, with the continuation indented by four spaces.
Nothing else in the outputs is edited. `<repo>` stands for `C:\Users\joeys\Desktop\MLOps` and `<scratch>` for the
scratchpad directory.

## Summary

- **§1 Idempotency record in the work's transaction, `api` = SELECT + INSERT.** **Works.** A second INSERT of the same
  scoped key **blocks** on the first transaction's uncommitted row (807 ms here, for as long as T1 holds it) and then
  fails with **23505**. Its transaction is aborted (`25P02` on the next statement), and a fresh transaction reads T1's
  row. A savepoint around the INSERT keeps the outer transaction usable, and so does a target-less `ON CONFLICT DO
  NOTHING` (rowcount 0, no error). In both cases the winner's row is readable in the same transaction. If T1 rolls back,
  T2's INSERT succeeds. A different body hash after commit reads back as a mismatch (the 409 path). `api` gets 42501 on
  UPDATE and DELETE. The sweeper purges by `app.current_time()` only with SELECT beside DELETE (DELETE alone: 42501,
  erratum 25 again). **Placement matters:** with the record written **last** (SA:188), a racing same-key replay never
  reaches it: it blocks in `create_run` on the slot index and gets **OC005 `SLOT_OCCUPIED`**, a 409 instead of the
  recorded 202. With the record written **first**, it gets 23505, whose **DETAIL contains the tenant id, the subject and
  the key**.
- **§2 `jobs` = INSERT for `api`.** Confirmed in `privileges.py` and live (`SELECT` False, `INSERT` True). Accepted:
  plain INSERT of `resume_input` (rowcount 1); target-less `ON CONFLICT DO NOTHING` (rowcount 1, then **0** on the same
  `dedup_key`). Refused with **42501**: `ON CONFLICT (dedup_key)`, `RETURNING id`, and `SELECT count(*)`. A plain
  duplicate gets 23505. RLS refuses a row with no tenant set or under another tenant (42501, "new row violates row-level
  security policy"). **The grant cannot restrict `type`**: `api` inserted `investigate` and **`execute`** jobs, and
  `app.jobs` has no CHECK on `type`. The run came from `app.create_run` called as `api` (message INSERT + function in
  one transaction, the `DbStore.admit` shape).
- **§3 `app.current_time()` from `api`.** `api` holds EXECUTE in the test database and in the dev database (granted by
  revision 0002, `privileges.DEFINER_FUNCTIONS["current_time"]` = all runtime roles). The function is VOLATILE and
  SECURITY DEFINER with `SET app.tenant_id = ''`. A `test_harness` offset of 2 h moves `app.current_time()` by 2 h for
  `api`, while `clock_timestamp()` and `now()` do not move. The caller's `app.tenant_id` is intact after the call. Two
  statements in one transaction get distinct `app.current_time()` values and an equal `now()`. The offset was restored
  to 0.
- **§4 Concurrent admission from one process.** `psycopg-pool` is **not in `uv.lock`** (0 matches) and not importable.
  On the selector loop with two plain `api` connections, 10 of 10 trials gave **exactly one OK and one OC005
  `SLOT_OCCUPIED`** in 6–14 ms; either connection can win. Through the real `create_app` + `DbStore` over
  `httpx2.ASGITransport`, one app (one connection) serialises the two POSTs: 202 then 409, the loser 4–5 ms later. Two
  apps (two connections) race in the database: one 202 and one 409 per trial. **A pool is not needed** for the live
  test; two plain connections or two `DbStore` apps in one process suffice.
- **§5 Error surfaces.** Today: unknown path **404 `{"detail":"Not Found"}`**; wrong method **405 `{"detail":"Method Not
  Allowed"}`** with `Allow`; body, path and query validation give the SafeError 422 `INVALID_INPUT`; an unhandled
  `RuntimeError` gives **500 `text/plain` "Internal Server Error"**. **No body limit**: 70,096 bytes, with or without
  `Content-Length`, is accepted (202 on messages, and 201 on `/conversations`, which reads no body). With
  `StarletteHTTPException`, `RequestValidationError` and `Exception` handlers, every case gets the `{code, message,
  retryable, request_id}` shape. **The `Exception` handler's response is sent, but the exception is still re-raised** to
  the server (and into an httpx2 client with `raise_app_exceptions=True`). Starlette 1.7 has `max_body_size`
  (`Starlette(...)`, `Route`, `Mount`, `Router`), but **`FastAPI()` and `APIRoute` do not accept it**. Its
  `RequestBodyLimitMiddleware`, added by hand, answers an over-limit `Content-Length` with **plain-text 413 after the
  route has run** (a conversation was created). Only a chunked body reaches the handler as a 413 `HTTPException`. A pure
  ASGI middleware of about 35 lines that pre-reads up to the limit gives the safe 422 with no side effect.
- **§6 Message ordering in one transaction.** `now()` is **equal** for both rows. `clock_timestamp()`,
  `app.current_time()` and an identity column all order them strictly. `app.messages` has `created_at DEFAULT now()` and
  **no sequence column** and no `(conversation_id, sequence)` constraint. `api` has **no UPDATE on `conversations`**
  (table or column) and gets 42501 on every row-lock mode, `FOR KEY SHARE` included. `pg_advisory_xact_lock` works for
  `api`. An identity column needs only INSERT; **a `bigserial` column needs USAGE on its sequence** (42501 without it).
- **§7 Interval resolution.** `api/src/ops_api/app.py:447` resolves the interval with **`datetime.now(UTC)`** (the
  Python wall clock) through `store.resolve_interval` (whole seconds). `runs` stores **`start_at`/`end_at`**; there is
  no `interval_start`/`interval_end`. One `create_run` stores exactly what the caller passed. A second call with a later
  `now` (same request, same conversation) is **refused OC005 `SLOT_OCCUPIED`**, and the first run's interval is
  unchanged. Through the app with the test clock at +3 days, the stored `end_at` follows the wall clock (0.72 s before
  `clock_timestamp()`), while the **same run's `run_state_history.at` is 3 days later**. A test-clock-driven R018 test
  is impossible today.
- **§8 Queue bound.** As `api` under a tenant, `count(*) … WHERE state = 'QUEUED'` returns that tenant's rows only (21
  under ALPHA, 1 under BETA, 0 with no tenant). `count(*) FROM app.jobs` gets **42501**. `run_directory` (no RLS) has
  only `run_id, tenant_id`. None of the five functions `api` may execute counts anything. **A global queue bound (BS:550
  "100 total") is not reachable by `api` without a definer function or a new grant**; only
  `pg_stat_user_tables.n_live_tup` (approximate, unfiltered, not by state) leaks a cross-tenant volume.

## 1. Idempotency record in the work's transaction

Shared helper `common.py`, imported by every script:

```python
"""Shared spike helpers. Test profile and the per-session test databases only; secrets come from ops_core.settings
and are never printed."""
import asyncio
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

REPO = Path(r"<repo>")
sys.path.insert(0, str(REPO))

# Exactly what tests/e2e/conftest.py `env` does, before anything reads settings.
os.environ.update({"OPS_PG_DB": "ops_test", "OPS_INCIDENT_PG_DB": "incident_test", "PROFILE": "test"})
from scripts.skeleton import export_environment, load_dotenv  # noqa: E402

export_environment(load_dotenv(REPO / ".env"))

import psycopg  # noqa: E402
from ops_core import persistence, settings  # noqa: E402
from ops_core.settings import Role  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

assert settings.superuser_postgres().dbname == "ops_test", "refusing: not the test database"

ALPHA = "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"  # seeded tenants and persona (tests/e2e)
BETA = "5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201"
ALEX = "2fc05986-c7ec-544c-b628-fdb112bbf18a"


async def su() -> persistence.Conn:
    """The superuser on ops_test (autocommit, dict rows): the conftest `app_conn`."""
    return await persistence.connect(settings.superuser_postgres())


async def as_role(role: Role) -> persistence.Conn:
    """An autocommit connection as a runtime role on ops_test: the conftest `role_conn`."""
    return await persistence.connect(settings.app_postgres(role))


async def try_(label, coro):
    """Run one awaitable; print OK (rowcount for a cursor) or the SQLSTATE and primary message."""
    try:
        r = await coro
        shown = f"rowcount={r.rowcount}" if isinstance(r, psycopg.AsyncCursor) else r
        print(f"{label}: OK {shown}")
        return r
    except psycopg.Error as e:
        print(f"{label}: {type(e).__name__} {e.sqlstate} {e.diag.message_primary!r}")
        return e


def run(main):
    """The selector loop, as serve_app and the live conftest use on win32."""
    if sys.platform == "win32":
        return asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(main())


def ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


async def new_conversation(api: persistence.Conn, tenant: str = ALPHA):
    """As api, the DbStore.create_conversation shape: a plain INSERT under the tenant."""
    conv = uuid4()
    async with api.transaction():
        await persistence.set_tenant(api, tenant)
        await api.execute(
            "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
            (conv, tenant, ALEX))
    return conv


async def admit_in_tx(api, conv, start_at, end_at, tenant: str = ALPHA, intent: str = "investigate"):
    """Inside the caller's transaction, as api: the DbStore.admit shape (message INSERT, then app.create_run)."""
    await persistence.set_tenant(api, tenant)
    msg = uuid4()
    await api.execute(
        "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, context, author)"
        " VALUES (%s, %s, %s, 'investigate', 'x', '{}', %s)", (msg, tenant, conv, ALEX))
    req = {"message_id": str(msg), "requester": ALEX, "asset_id": "A17",
           "start_at": start_at.isoformat(), "end_at": end_at.isoformat()}
    cur = await api.execute("SELECT * FROM app.create_run(%s, %s, %s, %s, NULL)",
                            (tenant, conv, Jsonb(req), intent))
    row = await cur.fetchone()
    return msg, row["run_id"], row["state_version"]
```

Script `setup_db.py` (run once before the measurements):

```python
"""Create and migrate the per-session test databases exactly as the live fixture `migrated` does."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402,F401  (sets OPS_PG_DB=ops_test, PROFILE=test and asserts it)

from ops_core.settings import Profile  # noqa: E402
from scripts.skeleton import migrate  # noqa: E402
from tests.e2e.conftest import recreate_databases  # noqa: E402

recreate_databases()
print("migrate(Profile.TEST) ->", migrate(Profile.TEST))
```

Output:

```text
MIGRATE: app at heads, incident at head (profile test)
migrate(Profile.TEST) -> 0
```

Script `m1_idempotency.py`:

```python
"""§1: an idempotency record written in the work's transaction by an api role holding only SELECT + INSERT."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ALEX, ALPHA, Jsonb, Role, as_role, ms, run, su, try_  # noqa: E402

import psycopg  # noqa: E402

DDL = (
    "CREATE TABLE app.spike_idempotency_request (tenant_id uuid, subject uuid, route text, key text,"
    " body_sha256 text, response jsonb, created_at timestamptz DEFAULT clock_timestamp(),"
    " PRIMARY KEY (tenant_id, subject, route, key))",
    "GRANT SELECT, INSERT ON app.spike_idempotency_request TO api",
    "GRANT SELECT, DELETE ON app.spike_idempotency_request TO sweeper",
)
INS = ("INSERT INTO app.spike_idempotency_request (tenant_id, subject, route, key, body_sha256, response)"
       " VALUES (%s, %s, %s, %s, %s, %s)")
SEL = ("SELECT body_sha256, response FROM app.spike_idempotency_request"
       " WHERE tenant_id = %s AND subject = %s AND route = %s AND key = %s")
ROUTE = "POST /api/v1/conversations/{conversation_id}/messages"
PURGE = "DELETE FROM app.spike_idempotency_request WHERE created_at < app.current_time() - interval '24 hours'"


def args(key, sha, resp):
    return (ALPHA, ALEX, ROUTE, key, sha, Jsonb(resp))


async def read(conn, key):
    rows = await (await conn.execute(SEL, (ALPHA, ALEX, ROUTE, key))).fetchall()
    return [(r["body_sha256"][:6], r["response"]) for r in rows]


async def main():
    s = await su()
    for d in DDL:
        await s.execute(d)
    cur = await s.execute(
        "SELECT grantee, string_agg(privilege_type, ',' ORDER BY privilege_type) p"
        " FROM information_schema.role_table_grants WHERE table_name = 'spike_idempotency_request'"
        " AND grantee IN ('api', 'sweeper') GROUP BY 1 ORDER BY 1")
    print("setup as superuser; grants:", [(r["grantee"], r["p"]) for r in await cur.fetchall()])
    a, b = await as_role(Role.API), await as_role(Role.API)

    print("\n-- (a) same key K, two api connections; T1 inserts and holds 1.0 s, T2 inserts at +0.2 s")
    t0 = time.perf_counter()

    async def t1():
        async with a.transaction():
            await a.execute(INS, args("K", "a" * 64, {"status": 202, "run_id": "r1"}))
            print(f"T1 inserted K at {ms(t0)} ms and holds")
            await asyncio.sleep(1.0)
        print(f"T1 committed at {ms(t0)} ms")

    async def t2():
        await asyncio.sleep(0.2)
        async with b.transaction():
            start = time.perf_counter()
            try:
                await b.execute(INS, args("K", "a" * 64, {"status": 202, "run_id": "r2"}))
                print("T2 insert: OK (!)")
            except psycopg.Error as e:
                print(f"T2 insert returned at {ms(t0)} ms after blocking {ms(start)} ms:"
                      f" {type(e).__name__} {e.sqlstate} constraint={e.diag.constraint_name}")
            try:
                await b.execute("SELECT 1")
            except psycopg.Error as e:
                print(f"T2 SELECT 1 in the same transaction: {type(e).__name__} {e.sqlstate}")
            raise psycopg.Rollback()
        print("T2 connection after the block:", b.info.transaction_status.name)
        async with b.transaction():
            print("T2 fresh transaction SELECT ->", await read(b, "K"))

    await asyncio.gather(t1(), t2())

    print("\n-- (a2) same race; T2's INSERT inside a savepoint (nested conn.transaction()); T1 holds 0.5 s")

    async def hold(key, secs):
        async with a.transaction():
            await a.execute(INS, args(key, "b" * 64, {"status": 202, "run_id": "r1"}))
            await asyncio.sleep(secs)

    async def t2_savepoint():
        await asyncio.sleep(0.1)
        async with b.transaction():
            start = time.perf_counter()
            try:
                async with b.transaction():
                    await b.execute(INS, args("K2", "b" * 64, {"status": 202, "run_id": "r2"}))
            except psycopg.errors.UniqueViolation as e:
                print(f"T2 savepoint INSERT: UniqueViolation {e.sqlstate} after {ms(start)} ms")
            print("T2 SELECT in the same outer transaction ->", await read(b, "K2"))

    await asyncio.gather(hold("K2", 0.5), t2_savepoint())

    print("\n-- (a3) same race; T2 uses a target-less INSERT ... ON CONFLICT DO NOTHING")

    async def t2_do_nothing():
        await asyncio.sleep(0.1)
        async with b.transaction():
            start = time.perf_counter()
            cur = await b.execute(INS + " ON CONFLICT DO NOTHING", args("K3", "b" * 64, {"run_id": "r2"}))
            print(f"T2 ON CONFLICT DO NOTHING: rowcount={cur.rowcount} after {ms(start)} ms")
            print("T2 SELECT in the same transaction ->", await read(b, "K3"))

    await asyncio.gather(hold("K3", 0.5), t2_do_nothing())

    print("\n-- (a4) T1 rolls back instead of committing")

    async def t1_rollback():
        async with a.transaction():
            await a.execute(INS, args("K4", "d" * 64, {"status": 202}))
            await asyncio.sleep(0.5)
            raise psycopg.Rollback()

    async def t2_plain():
        await asyncio.sleep(0.1)
        async with b.transaction():
            start = time.perf_counter()
            cur = await b.execute(INS, args("K4", "e" * 64, {"status": 202, "run_id": "t2"}))
            print(f"T2 plain INSERT after T1's rollback: rowcount={cur.rowcount} after {ms(start)} ms")

    await asyncio.gather(t1_rollback(), t2_plain())

    print("\n-- (b) same K, different body hash, after T1's commit (the 409 path)")
    async with b.transaction():
        row = await (await b.execute(SEL, (ALPHA, ALEX, ROUTE, "K"))).fetchone()
    new = "f" * 64
    print("stored hash", row["body_sha256"][:6], "| new hash", new[:6], "| differ:", row["body_sha256"] != new,
          "| stored response:", row["response"])
    await try_("api INSERT of K with the new hash", b.execute(INS, args("K", new, {"status": 202})))

    print("\n-- (c) api cannot UPDATE or DELETE; the sweeper purges by app.current_time()")
    await try_("api UPDATE", b.execute("UPDATE app.spike_idempotency_request SET response = '{}' WHERE key = 'K'"))
    await try_("api DELETE", b.execute("DELETE FROM app.spike_idempotency_request WHERE key = 'K'"))
    await s.execute(
        "INSERT INTO app.spike_idempotency_request (tenant_id, subject, route, key, body_sha256, response, created_at)"
        " VALUES (%s, %s, %s, 'OLD', 'h', '{}', clock_timestamp() - interval '25 hours')", (ALPHA, ALEX, ROUTE))
    rows = await (await s.execute("SELECT key FROM app.spike_idempotency_request ORDER BY key")).fetchall()
    print("rows before (superuser):", [r["key"] for r in rows], "| OLD is 25 h old")
    sw = await as_role(Role.SWEEPER)
    await try_("sweeper (SELECT, DELETE): DELETE ... created_at < app.current_time() - 24 h", sw.execute(PURGE))
    await s.execute("REVOKE SELECT ON app.spike_idempotency_request FROM sweeper")
    await try_("sweeper (DELETE only): the same DELETE", sw.execute(PURGE))
    await try_("sweeper (DELETE only): DELETE ... WHERE false",
               sw.execute("DELETE FROM app.spike_idempotency_request WHERE false"))
    rows = await (await s.execute("SELECT key FROM app.spike_idempotency_request ORDER BY key")).fetchall()
    print("rows after (superuser):", [r["key"] for r in rows])
    for c in (a, b, sw):
        await c.close()
    await s.execute("DROP TABLE app.spike_idempotency_request")
    print("dropped app.spike_idempotency_request")
    await s.close()


run(main)
```

Output (complete):

```text
setup as superuser; grants: [('api', 'INSERT,SELECT'), ('sweeper', 'DELETE,SELECT')]

-- (a) same key K, two api connections; T1 inserts and holds 1.0 s, T2 inserts at +0.2 s
T1 inserted K at 2.9 ms and holds
T1 committed at 1016.7 ms
T2 insert returned at 1017.0 ms after blocking 807.3 ms: UniqueViolation 23505 constraint=spike_idempotency_request_pkey
T2 SELECT 1 in the same transaction: InFailedSqlTransaction 25P02
T2 connection after the block: IDLE
T2 fresh transaction SELECT -> [('aaaaaa', {'run_id': 'r1', 'status': 202})]

-- (a2) same race; T2's INSERT inside a savepoint (nested conn.transaction()); T1 holds 0.5 s
T2 savepoint INSERT: UniqueViolation 23505 after 405.3 ms
T2 SELECT in the same outer transaction -> [('bbbbbb', {'run_id': 'r1', 'status': 202})]

-- (a3) same race; T2 uses a target-less INSERT ... ON CONFLICT DO NOTHING
T2 ON CONFLICT DO NOTHING: rowcount=0 after 390.7 ms
T2 SELECT in the same transaction -> [('bbbbbb', {'run_id': 'r1', 'status': 202})]

-- (a4) T1 rolls back instead of committing
T2 plain INSERT after T1's rollback: rowcount=1 after 403.1 ms

-- (b) same K, different body hash, after T1's commit (the 409 path)
stored hash aaaaaa | new hash ffffff | differ: True | stored response: {'run_id': 'r1', 'status': 202}
api INSERT of K with the new hash: UniqueViolation 23505 'duplicate key value violates unique constraint
    "spike_idempotency_request_pkey"'

-- (c) api cannot UPDATE or DELETE; the sweeper purges by app.current_time()
api UPDATE: InsufficientPrivilege 42501 'permission denied for table spike_idempotency_request'
api DELETE: InsufficientPrivilege 42501 'permission denied for table spike_idempotency_request'
rows before (superuser): ['K', 'K2', 'K3', 'K4', 'OLD'] | OLD is 25 h old
sweeper (SELECT, DELETE): DELETE ... created_at < app.current_time() - 24 h: OK rowcount=1
sweeper (DELETE only): the same DELETE: InsufficientPrivilege 42501 'permission denied for table
    spike_idempotency_request'
sweeper (DELETE only): DELETE ... WHERE false: OK rowcount=0
rows after (superuser): ['K', 'K2', 'K3', 'K4']
dropped app.spike_idempotency_request
```

Script `m1b_admission_race.py`, the same race through the real `create_run`, with the record written last or first:

```python
"""§1 (a5/a6): two same-key admissions racing through the real create_run, idempotency row last vs first."""
import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ALEX, ALPHA, Jsonb, Role, admit_in_tx, as_role, ms, new_conversation, run, su  # noqa: E402

import psycopg  # noqa: E402

DDL = (
    "CREATE TABLE app.spike_idempotency_request (tenant_id uuid, subject uuid, route text, key text,"
    " body_sha256 text, response jsonb, created_at timestamptz DEFAULT clock_timestamp(),"
    " PRIMARY KEY (tenant_id, subject, route, key))",
    "GRANT SELECT, INSERT ON app.spike_idempotency_request TO api",
)
INS = ("INSERT INTO app.spike_idempotency_request (tenant_id, subject, route, key, body_sha256, response)"
       " VALUES (%s, %s, 'POST messages', %s, 'h', %s)")
END = datetime.now(UTC).replace(microsecond=0)
START = END - timedelta(hours=24)


async def attempt(conn, conv, key, order, hold, label, t0):
    start = time.perf_counter()
    try:
        async with conn.transaction():
            if order == "first":
                await conn.execute(INS, (ALPHA, ALEX, key, Jsonb({"by": label})))
            msg, run_id, _ = await admit_in_tx(conn, conv, START, END)
            if order == "last":
                await conn.execute(INS, (ALPHA, ALEX, key, Jsonb({"by": label})))
            await asyncio.sleep(hold)
        print(f"  {label}: committed at {ms(t0)} ms ({ms(start)} ms in the unit)")
    except psycopg.Error as e:
        detail = e.diag.message_detail or ""
        print(f"  {label}: {type(e).__name__} {e.sqlstate} detail={detail[:40]!r} after {ms(start)} ms")
        if e.sqlstate == "23505":
            print(f"  {label}: the 23505 DETAIL names the tenant_id: {ALPHA in detail};"
                  f" the subject: {ALEX in detail}; the key: {key in detail}")
    async with conn.transaction():
        cur = await conn.execute("SELECT response FROM app.spike_idempotency_request WHERE key = %s", (key,))
        print(f"  {label}: fresh read of the key ->", [r["response"]["by"] for r in await cur.fetchall()])


async def main():
    s = await su()
    for d in DDL:
        await s.execute(d)
    a, b = await as_role(Role.API), await as_role(Role.API)
    for order in ("last", "first"):
        conv = await new_conversation(a)
        print(f"\n-- idempotency row written {order.upper()}; same key, same conversation; T1 holds 0.5 s")
        t0 = time.perf_counter()

        async def late():
            await asyncio.sleep(0.1)
            await attempt(b, conv, f"K-{order}", order, 0, "T2", t0)

        await asyncio.gather(attempt(a, conv, f"K-{order}", order, 0.5, "T1", t0), late())
        n_runs = (await (await s.execute(
            "SELECT count(*) n FROM app.runs WHERE conversation_id = %s", (conv,))).fetchone())["n"]
        n_msgs = (await (await s.execute(
            "SELECT count(*) n FROM app.messages WHERE conversation_id = %s", (conv,))).fetchone())["n"]
        print(f"  superuser: runs in the conversation = {n_runs}, messages = {n_msgs}")
    await a.close()
    await b.close()
    await s.execute("DROP TABLE app.spike_idempotency_request")
    print("\ndropped app.spike_idempotency_request")
    await s.close()


run(main)
```

Output (complete):

```text

-- idempotency row written LAST; same key, same conversation; T1 holds 0.5 s
  T1: committed at 516.5 ms (516.5 ms in the unit)
  T2: DatabaseError OC005 detail='SLOT_OCCUPIED' after 408.6 ms
  T1: fresh read of the key -> ['T1']
  T2: fresh read of the key -> ['T1']
  superuser: runs in the conversation = 1, messages = 1

-- idempotency row written FIRST; same key, same conversation; T1 holds 0.5 s
  T1: committed at 521.8 ms (521.8 ms in the unit)
  T2: UniqueViolation 23505 detail='Key (tenant_id, subject, route, key)=(3e' after 409.7 ms
  T2: the 23505 DETAIL names the tenant_id: True; the subject: True; the key: True
  T1: fresh read of the key -> ['T1']
  T2: fresh read of the key -> ['T1']
  superuser: runs in the conversation = 1, messages = 1

dropped app.spike_idempotency_request
```

Findings:

- **(a) Concurrent same key:** the second INSERT **blocks** on the first transaction's uncommitted unique entry, for as
  long as T1 holds it (807 ms of a 1.0 s hold started 0.2 s late). It returns **0.3 ms after T1's commit** with
  `UniqueViolation` 23505 on the primary key. T2's transaction is then aborted: the next statement raises
  `InFailedSqlTransaction` 25P02, and `psycopg.Rollback` leaves the connection `IDLE`. A fresh transaction reads T1's
  row and response. If T1 **rolls back**, T2's INSERT succeeds (rowcount 1) at the moment of the rollback.
- **Two ways to keep the loser's transaction usable**, both measured: a savepoint around the INSERT (a nested
  `conn.transaction()`; 23505 is caught and the outer transaction then SELECTs the winner's row), or a target-less
  `INSERT … ON CONFLICT DO NOTHING` (no error, `rowcount = 0`, then the SELECT in the same transaction finds the
  winner). Both need only SELECT + INSERT.
- **(b) The 409 path:** after commit, a SELECT by the scoped key returns the stored `body_sha256` and `response`;
  comparing hashes is a Python-side decision. A blind INSERT with the new hash is 23505, so the API must read first (or
  catch) to tell "replay" from "conflict".
- **(c) Grants:** `api` UPDATE and DELETE get 42501, so the record is write-once (no "in progress" row can be completed
  later). The sweeper's purge `DELETE … WHERE created_at < app.current_time() - interval '24 hours'` deleted exactly the
  25-hour-old row (rowcount 1) **with SELECT + DELETE**. With DELETE only, the same statement is 42501, and only a
  constant `WHERE false` passes. That is erratum 25 again, now for `idempotency_request` (SA:429 grants a bare `del`).
- **(a5) Record written last, as SA:188 orders ("Idempotency rows are written last, before commit"):** a racing same-key
  request never reaches the record. It blocks inside `app.create_run` on the `runs_one_active_per_conversation` index
  and fails with **OC005 `SLOT_OCCUPIED`**: the client would see a 409 although its key has a recorded 202. A fresh read
  afterwards finds T1's record, so a "re-read the key after `SLOT_OCCUPIED`" step would turn it into the replay.
- **(a6) Record written first:** the racer blocks on the key and gets 23505, and its message and run are never written
  (1 message, 1 run). **The 23505 DETAIL is `Key (tenant_id, subject, route, key)=(…)`, with the tenant id, the subject
  UUID and the client's key in clear.** `persistence.translate` does not map 23505, so today it would reach the
  `psycopg.Error` handler (503, message "database unavailable", DETAIL not in the body). Any log line that prints the
  exception would carry those ids.

## 2. `jobs` INSERT-only for `api`

`core/src/ops_core/privileges.py` (the `GRANTS` row for `jobs`):

```text
    "jobs": {
        "api": _INS,
```

where `_INS = Grant(ins=True)`.

Script `m2_jobs.py`:

```python
"""§2: what an INSERT-only `jobs` grant lets the api role write, inside a tenant-scoped transaction."""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent))
from common import ALPHA, BETA, Role, admit_in_tx, as_role, new_conversation, persistence, run, su  # noqa: E402

import psycopg  # noqa: E402

COLS = "INSERT INTO app.jobs (id, type, run_id, tenant_id, dedup_key) VALUES (%s, %s, %s, %s, %s)"
PRIVS = ("SELECT p, has_table_privilege('api', 'app.jobs', p) AS ok"
         " FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) p")
POLICIES = ("SELECT polname, polcmd, polroles::regrole[]::text[] r, pg_get_expr(polqual, polrelid) = "
            " pg_get_expr(polwithcheck, polrelid) AS same FROM pg_policy WHERE polrelid = 'app.jobs'::regclass")


async def in_tenant(conn, label, sql, params, tenant=ALPHA):
    try:
        async with conn.transaction():
            if tenant:
                await persistence.set_tenant(conn, tenant)
            cur = await conn.execute(sql, params)
        print(f"{label}: accepted, rowcount={cur.rowcount}")
    except psycopg.Error as e:
        print(f"{label}: refused {e.sqlstate} {e.diag.message_primary!r}")


async def main():
    s = await su()
    print("live grants, api on app.jobs:", {r["p"]: r["ok"] for r in await (await s.execute(PRIVS)).fetchall()})
    for r in await (await s.execute(POLICIES)).fetchall():
        print(f"policy {r['polname']} cmd={r['polcmd']} roles={r['r']} using == with check: {r['same']}")
    checks = await (await s.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'app.jobs'::regclass"
                                    " AND contype = 'c'")).fetchall()
    print("CHECK constraints on app.jobs:", [r["conname"] for r in checks])
    api = await as_role(Role.API)
    conv = await new_conversation(api)
    end = datetime.now(UTC).replace(microsecond=0)
    async with api.transaction():
        _, run_id, _ = await admit_in_tx(api, conv, end - timedelta(hours=24), end)
    print("run created by api: message INSERT + app.create_run in one transaction (the DbStore.admit shape)")

    def p(key, typ="resume_input"):
        return (uuid4(), typ, run_id, ALPHA, f"{run_id}:{key}")

    await in_tenant(api, "1  plain INSERT resume_input", COLS, p("e1"))
    await in_tenant(api, "2a ON CONFLICT DO NOTHING (no target), new key", COLS + " ON CONFLICT DO NOTHING", p("e2"))
    await in_tenant(api, "2b ON CONFLICT DO NOTHING (no target), key of 1", COLS + " ON CONFLICT DO NOTHING", p("e1"))
    await in_tenant(api, "2c plain INSERT, key of 1", COLS, p("e1"))
    await in_tenant(api, "3  ON CONFLICT (dedup_key) DO NOTHING", COLS + " ON CONFLICT (dedup_key) DO NOTHING",
                    p("e3"))
    await in_tenant(api, "4  INSERT ... RETURNING id", COLS + " RETURNING id", p("e4"))
    await in_tenant(api, "5  INSERT type 'investigate'", COLS, p("e5", "investigate"))
    await in_tenant(api, "5b INSERT type 'execute'", COLS, p("e5b", "execute"))
    await in_tenant(api, "6  INSERT with no app.tenant_id", COLS, p("e6"), tenant=None)
    await in_tenant(api, "7  INSERT tenant_id ALPHA under app.tenant_id BETA", COLS, p("e7"), tenant=BETA)
    await in_tenant(api, "8  SELECT count(*) FROM app.jobs", "SELECT count(*) FROM app.jobs", ())
    rows = await (await s.execute("SELECT type, split_part(dedup_key, ':', 2) k FROM app.jobs WHERE run_id = %s"
                                  " ORDER BY created_at, k", (run_id,))).fetchall()
    print("jobs of the run (superuser):", [(r["type"], r["k"]) for r in rows])
    await api.close()
    await s.close()


run(main)
```

Output (complete):

```text
live grants, api on app.jobs: {'SELECT': False, 'INSERT': True, 'UPDATE': False, 'DELETE': False}
policy tenant_isolation cmd=* roles=['api', 'worker', 'sweeper', 'app_definer'] using == with check: True
policy sweeper_all cmd=* roles=['sweeper'] using == with check: True
CHECK constraints on app.jobs: ['jobs_tenant_iff_run_check']
run created by api: message INSERT + app.create_run in one transaction (the DbStore.admit shape)
1  plain INSERT resume_input: accepted, rowcount=1
2a ON CONFLICT DO NOTHING (no target), new key: accepted, rowcount=1
2b ON CONFLICT DO NOTHING (no target), key of 1: accepted, rowcount=0
2c plain INSERT, key of 1: refused 23505 'duplicate key value violates unique constraint "jobs_dedup_key_key"'
3  ON CONFLICT (dedup_key) DO NOTHING: refused 42501 'permission denied for table jobs'
4  INSERT ... RETURNING id: refused 42501 'permission denied for table jobs'
5  INSERT type 'investigate': accepted, rowcount=1
5b INSERT type 'execute': accepted, rowcount=1
6  INSERT with no app.tenant_id: refused 42501 'new row violates row-level security policy for table "jobs"'
7  INSERT tenant_id ALPHA under app.tenant_id BETA: refused 42501 'new row violates row-level security policy for
    table "jobs"'
8  SELECT count(*) FROM app.jobs: refused 42501 'permission denied for table jobs'
jobs of the run (superuser): [('investigate', '1'), ('resume_input', 'e1'), ('resume_input', 'e2'), ('investigate',
    'e5'), ('execute', 'e5b')]
```

Findings:

- **Live grant equals the matrix:** `api` on `app.jobs` has INSERT only. Both policies are `cmd=*` with `USING` equal to
  `WITH CHECK`, so an INSERT must carry the tenant set by `set_config('app.tenant_id', …, true)`.
- **Accepted:** a plain INSERT (1) and a target-less `ON CONFLICT DO NOTHING` (2a: rowcount 1; 2b on an existing
  `dedup_key`: rowcount **0**, no error). The rowcount is the only verdict an insert-only role gets, exactly as Plan F
  §5 measured for `logout_jti`.
- **Refused 42501:** `ON CONFLICT (dedup_key) DO NOTHING` (3), `RETURNING id` (4), `SELECT count(*)` (8). The first two
  need SELECT, which matches the `persistence.insert_job` comment at `:466-467`. A plain duplicate is 23505 (2c), which
  aborts the admission transaction unless it is caught in a savepoint.
- **The `type` is not constrained:** `api` inserted `investigate` (5) and **`execute`** (5b) jobs for its run. The only
  CHECK on `app.jobs` is `jobs_tenant_iff_run_check`. SA:419's "(`resume_input` only)" holds today only by convention.
  Whether the worker would act on an `api`-inserted `execute` job without a grant was not measured. It belongs to
  T13/T22, and grants are still decided by `grant_execution`.
- **RLS:** no tenant (6) and a mismatched tenant (7) both give 42501 "new row violates row-level security policy".
- **How the run was made:** as `api`, in one transaction: `set_config('app.tenant_id', ALPHA, true)`, an INSERT into
  `app.messages`, and `SELECT * FROM app.create_run(…, 'investigate', NULL)` (the `DbStore.admit` shape). `create_run`
  wrote the `investigate` job with dedup `<run_id>:1`.

## 3. `app.current_time()` from `api`

Script `m3_clock.py`:

```python
"""§3: app.current_time() from the api role; a test_harness offset moves it, clock_timestamp() does not."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ALPHA, Role, as_role, persistence, run, settings, su  # noqa: E402

import psycopg  # noqa: E402

Q = "SELECT app.current_time() - clock_timestamp() AS delta"
PRIV = ("SELECT has_function_privilege('api', 'app.current_time()', 'EXECUTE') AS api_exec, p.provolatile,"
        " p.prosecdef, p.proconfig, to_regclass('app.test_clock') IS NOT NULL AS test_clock"
        " FROM pg_proc p WHERE p.oid = 'app.current_time()'::regprocedure")


async def main():
    s = await su()
    print("[ops_test]", dict(await (await s.execute(PRIV)).fetchone()))
    admin = settings.superuser_postgres()
    dev = settings.Postgres(admin.host, admin.port, admin.user, "ops", admin.password)
    with psycopg.connect(dev.conninfo(), autocommit=True) as c:  # one read-only catalog query on the dev database
        r = c.execute(PRIV).fetchone()
        print("[ops, dev, read-only] api_exec, provolatile, prosecdef, proconfig, test_clock =", r)
    api, harness = await as_role(Role.API), await as_role(Role.TEST_HARNESS)
    print("api, offset 0: app.current_time() - clock_timestamp() =", (await (await api.execute(Q)).fetchone())["delta"])
    try:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '2 hours'")
        print("test_harness: UPDATE app.test_clock SET clock_offset = interval '2 hours'")
        r = await (await api.execute(
            "SELECT app.current_time() AS app_now, clock_timestamp() AS wall, now() AS tx_now")).fetchone()
        print(f"api: app.current_time() {r['app_now'].isoformat(timespec='seconds')}"
              f" | clock_timestamp() {r['wall'].isoformat(timespec='seconds')}"
              f" | now() {r['tx_now'].isoformat(timespec='seconds')}")
        async with api.transaction():
            await persistence.set_tenant(api, ALPHA)
            r = await (await api.execute(Q + ", current_setting('app.tenant_id') = %s AS kept", (ALPHA,))).fetchone()
            print("api in a tenant transaction: delta =", r["delta"], "| app.tenant_id kept after the call:", r["kept"])
            x = await (await api.execute("SELECT app.current_time() t, now() n")).fetchone()
            y = await (await api.execute("SELECT app.current_time() t, now() n")).fetchone()
            print("two statements, one transaction: app.current_time() distinct:", x["t"] != y["t"],
                  "| now() equal:", x["n"] == y["n"])
    finally:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    print("after restoring 0: delta =", (await (await api.execute(Q)).fetchone())["delta"])
    for c in (api, harness, s):
        await c.close()


run(main)
```

Output (complete):

```text
[ops_test] {'api_exec': True, 'provolatile': 'v', 'prosecdef': True, 'proconfig': ['search_path=app, pg_temp',
    'app.tenant_id='], 'test_clock': True}
[ops, dev, read-only] api_exec, provolatile, prosecdef, proconfig, test_clock = (True, 'v', True, ['search_path=app,
    pg_temp', 'app.tenant_id='], False)
api, offset 0: app.current_time() - clock_timestamp() = -1 day, 23:59:59.999997
test_harness: UPDATE app.test_clock SET clock_offset = interval '2 hours'
api: app.current_time() 2026-10-10T09:14:48+00:00 | clock_timestamp() 2026-10-10T07:14:48+00:00 |
    now() 2026-10-10T07:14:48+00:00
api in a tenant transaction: delta = 1:59:59.999999 | app.tenant_id kept after the call: True
two statements, one transaction: app.current_time() distinct: True | now() equal: True
after restoring 0: delta = -1 day, 23:59:59.999999
```

Findings:

- **EXECUTE:** `api` holds it in both profiles. In `ops_test` and in the dev `ops` database,
  `has_function_privilege('api', 'app.current_time()', 'EXECUTE')` is `True`. The grant comes from revision 0002
  (`callers=("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator")`); `tc_0001` adds only `test_harness`. In
  dev, `app.test_clock` does not exist (`False`), and the function returns `clock_timestamp()`.
- **Offset:** with `clock_offset = interval '2 hours'` (written by `test_harness`), `api` reads `app.current_time()` 2 h
  ahead of `clock_timestamp()`. `clock_timestamp()` and `now()` are unchanged. With offset 0 the difference is −1 to −3
  µs (the two calls run in sequence). After restoring, the difference is −1 µs.
- **Inside a tenant unit:** the function's `SET app.tenant_id = ''` is scoped to the call.
  `current_setting('app.tenant_id')` in the same statement still equals the caller's tenant. Calling it inside the
  admission unit is safe.
- **Per statement:** two statements in one transaction give distinct `app.current_time()` values and the same `now()`.

## 4. Concurrent admission from one process

Lock check:

```text
$ grep -c -i -E 'psycopg-pool|psycopg_pool|"pool"' uv.lock
0
$ uv run python -c "import importlib.util as u; print('find_spec(psycopg_pool):', u.find_spec('psycopg_pool'))"
find_spec(psycopg_pool): None
```

The loop: `api/src/ops_api/__main__.py` `serve_app` runs `asyncio.run(server.serve(),
loop_factory=asyncio.SelectorEventLoop)` on win32, and `tests/e2e/conftest.py` installs
`WindowsSelectorEventLoopPolicy`. `common.run` uses the same `loop_factory`.

Script `m4_concurrency.py`:

```python
"""§4: two concurrent create_run calls for one conversation from one process on the selector loop; then the same
through the real API app (DbStore) over httpx2.ASGITransport: one app (one connection) and two apps (two)."""
import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import Role, admit_in_tx, as_role, ms, new_conversation, run, su  # noqa: E402

import httpx2  # noqa: E402
import psycopg  # noqa: E402
from ops_api import store as st  # noqa: E402
from ops_api.app import create_app  # noqa: E402

from tests.plan_d.test_api import StubVerifier  # noqa: E402
from tests.plan_f.auth_fakes import fake_auth  # noqa: E402

END = datetime.now(UTC).replace(microsecond=0)


async def one(conn, conv, label, out, T0):
    start = time.perf_counter()
    try:
        async with conn.transaction():
            _, run_id, _ = await admit_in_tx(conn, conv, END - timedelta(hours=24), END)
        out.append((label, "OK", ms(start), ms(T0)))
    except psycopg.Error as e:
        out.append((label, f"{e.sqlstate} {e.diag.message_detail}", ms(start), ms(T0)))


async def part_a():
    print("-- A: two api connections, asyncio.gather of two admissions (message + create_run), 10 trials")
    print("   loop:", type(asyncio.get_running_loop()).__name__)
    a, b = await as_role(Role.API), await as_role(Role.API)
    for i in range(10):
        conv = await new_conversation(a)
        out = []
        T0 = time.perf_counter()
        await asyncio.gather(one(a, conv, "A", out, T0), one(b, conv, "B", out, T0))
        print(f"   trial {i}: " + " | ".join(f"{lbl}: {res} in {t} ms" for lbl, res, t, _ in out))
    await a.close()
    await b.close()


async def http_app():
    conn = await as_role(Role.API)
    app = create_app(StubVerifier(), store_factory=lambda: st.DbStore(conn), auth_factory=fake_auth)
    return app


async def part_b():
    body = {"kind": "investigate", "text": "Investigate A17.", "context": {"asset_id": "A17", "hours": 24}}
    hdr = {"Authorization": "Bearer alex"}
    for n_apps in (1, 2):
        apps = [await http_app() for _ in range(n_apps)]
        print(f"\n-- B: real create_app over DbStore, {n_apps} app(s) = {n_apps} api connection(s), 2 concurrent POSTs")
        ctxs = [a.router.lifespan_context(a) for a in apps]
        for c in ctxs:
            await c.__aenter__()
        clients = [httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a), base_url="http://localhost:8000")
                   for a in apps]
        try:
            for trial in range(3):
                r = await clients[0].post("/api/v1/conversations", headers=hdr)
                cid = r.json()["conversation_id"]

                async def post(c, label):
                    t = time.perf_counter()
                    resp = await c.post(f"/api/v1/conversations/{cid}/messages", headers=hdr, json=body)
                    return label, resp.status_code, resp.json().get("code", resp.json().get("status")), ms(t)

                res = await asyncio.gather(post(clients[0], "P1"), post(clients[-1], "P2"))
                print(f"   trial {trial} (conversation 201 {r.status_code}): " +
                      " | ".join(f"{lbl}: {code} {c_} in {t} ms" for lbl, code, c_, t in res))
        finally:
            for c in clients:
                await c.aclose()
            for c in ctxs:
                await c.__aexit__(None, None, None)


async def main():
    await part_a()
    await part_b()
    s = await su()
    cur = await s.execute(
        "SELECT conversation_id FROM app.runs WHERE slot_held GROUP BY conversation_id HAVING count(*) > 1")
    print("\nconversations holding more than one slot (superuser):", await cur.fetchall())
    await s.close()


run(main)
```

Output (complete):

```text
-- A: two api connections, asyncio.gather of two admissions (message + create_run), 10 trials
   loop: _WindowsSelectorEventLoop
   trial 0: A: OK in 12.7 ms | B: OC005 SLOT_OCCUPIED in 13.7 ms
   trial 1: B: OK in 8.7 ms | A: OC005 SLOT_OCCUPIED in 9.7 ms
   trial 2: A: OK in 6.2 ms | B: OC005 SLOT_OCCUPIED in 6.9 ms
   trial 3: B: OK in 6.3 ms | A: OC005 SLOT_OCCUPIED in 7.1 ms
   trial 4: A: OK in 7.5 ms | B: OC005 SLOT_OCCUPIED in 8.2 ms
   trial 5: A: OK in 6.7 ms | B: OC005 SLOT_OCCUPIED in 7.5 ms
   trial 6: B: OK in 6.2 ms | A: OC005 SLOT_OCCUPIED in 7.6 ms
   trial 7: A: OK in 6.5 ms | B: OC005 SLOT_OCCUPIED in 7.2 ms
   trial 8: A: OK in 6.4 ms | B: OC005 SLOT_OCCUPIED in 7.2 ms
   trial 9: B: OK in 5.9 ms | A: OC005 SLOT_OCCUPIED in 7.6 ms

-- B: real create_app over DbStore, 1 app(s) = 1 api connection(s), 2 concurrent POSTs
   trial 0 (conversation 201 201): P1: 202 QUEUED in 21.3 ms | P2: 409 SLOT_OCCUPIED in 26.1 ms
   trial 1 (conversation 201 201): P1: 202 QUEUED in 13.7 ms | P2: 409 SLOT_OCCUPIED in 18.1 ms
   trial 2 (conversation 201 201): P1: 202 QUEUED in 14.2 ms | P2: 409 SLOT_OCCUPIED in 18.2 ms

-- B: real create_app over DbStore, 2 app(s) = 2 api connection(s), 2 concurrent POSTs
   trial 0 (conversation 201 201): P1: 202 QUEUED in 17.3 ms | P2: 409 SLOT_OCCUPIED in 15.9 ms
   trial 1 (conversation 201 201): P1: 202 QUEUED in 13.8 ms | P2: 409 SLOT_OCCUPIED in 13.7 ms
   trial 2 (conversation 201 201): P1: 409 SLOT_OCCUPIED in 18.3 ms | P2: 202 QUEUED in 14.8 ms

conversations holding more than one slot (superuser): []
```

Findings:

- **Exactly one wins, every time:** 10 of 10 trials ended with one OK and one `OC005` / `SLOT_OCCUPIED`. The loser's
  latency is the winner's plus about 1 ms: it blocks on the slot index until the winner commits. Either connection can
  win (A won 6, B won 4).
- **Through the real app over one connection** (`DbStore` = one `persistence.Session`), the process-wide lock serialises
  the two POSTs: P1 202, then P2 409 `SLOT_OCCUPIED` 4–5 ms later. PostgreSQL never sees them concurrently. **Over two
  apps (two connections)**, the two requests race in the database, and each trial gave one 202 and one 409 (the winner
  varied).
- **No pool needed:** `psycopg_pool` is absent from the lock and the environment, and adding it would need `uv add` (not
  done). The R017 concurrency test can use two `role_conn(Role.API)` connections (the `test_definers_run_path_live.py`
  precedent) or two `create_app(…, DbStore(conn))` instances in one process over `httpx2.ASGITransport`. The second
  drives the HTTP mapping as well, with no server and no skeleton.

## 5. Error surfaces of the real API app without a server

The app is built the way `tests/plan_d/test_api.py` builds it: `create_app(StubVerifier(), store_factory=lambda:
FakeStore(), auth_factory=fake_auth)`. It runs under `app.router.lifespan_context(app)` and is driven by
`httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app, raise_app_exceptions=…))`. The import name is `httpx2`;
`httpx` is not installed. `ASGITransport.__init__(self, app, raise_app_exceptions=True, root_path='',
client=('127.0.0.1', 123))` is the equivalent of TestClient's `raise_server_exceptions`. The `spike_boom` and
`spike_echo` routes, the three handlers and `SpikeBodyLimit` exist only in this script.

Script `m5_errors.py`:

```python
"""§5: error surfaces of the real API app (FakeStore, fakes) over httpx2.ASGITransport, today and with handlers."""
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402,F401

import httpx2  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from ops_api.app import create_app, safe  # noqa: E402
from ops_core.contracts import ErrorCode  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402
from starlette.middleware.body_limit import RequestBodyLimitMiddleware  # noqa: E402

from tests.plan_d.test_api import FakeStore, StubVerifier  # noqa: E402
from tests.plan_f.auth_fakes import fake_auth  # noqa: E402

LIMIT = 65_536
H = {"Authorization": "Bearer alex"}
GOOD = {"kind": "investigate", "text": "Investigate A17.", "context": {"asset_id": "A17", "hours": 24}}
PADDED = (json.dumps(GOOD) + " " * 70_000).encode()  # valid JSON, 70,0xx bytes


def build(with_handlers: bool, limiter):
    fake = FakeStore()
    app = create_app(StubVerifier(), store_factory=lambda: fake, auth_factory=fake_auth)

    async def spike_boom() -> dict:
        raise RuntimeError("spike canary secret-ish detail")

    async def spike_echo(request: Request) -> dict:
        b = await request.body()
        return {"content-length": request.headers.get("content-length"),
                "transfer-encoding": request.headers.get("transfer-encoding"), "received": len(b)}

    app.add_api_route("/spike_boom", spike_boom, methods=["GET"])
    app.add_api_route("/spike_echo", spike_echo, methods=["POST"])
    if with_handlers:
        @app.exception_handler(StarletteHTTPException)
        async def _http(_: Request, exc: StarletteHTTPException):
            code = {404: ErrorCode.NOT_FOUND, 401: ErrorCode.UNAUTHENTICATED, 403: ErrorCode.FORBIDDEN}.get(
                exc.status_code, ErrorCode.INVALID_INPUT)
            status = 422 if exc.status_code == 413 else exc.status_code
            return safe(status, code, "request refused")

        @app.exception_handler(RequestValidationError)
        async def _val(_: Request, __: RequestValidationError):
            return safe(422, ErrorCode.INVALID_INPUT, "request is not valid")

        @app.exception_handler(Exception)
        async def _any(_: Request, __: Exception):
            return safe(503, ErrorCode.UNAVAILABLE, "service error")

        if limiter == "starlette":
            app.add_middleware(RequestBodyLimitMiddleware, max_body_size=LIMIT)
        else:
            app.add_middleware(SpikeBodyLimit, limit=LIMIT)
    return app, fake


class SpikeBodyLimit:
    """Pure ASGI: refuse a declared Content-Length over the limit before the app runs; otherwise read the whole
    body up to the limit first (chunked included), refuse if it overflows, then replay it to the app."""

    def __init__(self, app, limit: int) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.limit):
            return await safe(422, ErrorCode.INVALID_INPUT, "request body too large")(scope, receive, send)
        parts, total = [], 0
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                break
            total += len(msg.get("body", b""))
            if total > self.limit:
                return await safe(422, ErrorCode.INVALID_INPUT, "request body too large")(scope, receive, send)
            parts.append(msg.get("body", b""))
            if not msg.get("more_body", False):
                break
        body, sent = b"".join(parts), False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def chunks(data: bytes, size: int = 8192):
    for i in range(0, len(data), size):
        yield data[i:i + size]


def show(label, r):
    """Status, media type and a compact body: a SafeError as code/message/retryable (request_id checked as a UUID),
    a success as its keys, anything else verbatim."""
    ct = r.headers.get("content-type", "").split(";")[0]
    extra = f" Allow={r.headers['allow']}" if "allow" in r.headers else ""
    try:
        doc = r.json()
    except ValueError:
        doc = None
    if isinstance(doc, dict) and set(doc) == {"code", "message", "retryable", "request_id"}:
        UUID(doc["request_id"])
        body = f"SafeError {doc['code']} {doc['message']!r} retryable={doc['retryable']}"
    elif isinstance(doc, dict) and "detail" not in doc:
        body = f"keys {sorted(doc)}" if len(str(sorted(doc))) < 60 else f"{len(doc)} keys"
    else:
        body = r.text
    print(f"  {label}: {r.status_code} {ct}{extra} {body}")


async def scenario(with_handlers: bool, raise_app_exceptions: bool, limiter=None):
    app, fake = build(with_handlers, limiter)
    mw = {"starlette": f" + starlette RequestBodyLimitMiddleware({LIMIT})",
          "spike": f" + spike_body_limit ASGI middleware ({LIMIT})"}.get(limiter, "")
    print(f"\n== handlers={'registered' if with_handlers else 'today'}{mw}"
          f" | raise_app_exceptions={raise_app_exceptions}")
    async with app.router.lifespan_context(app):
        t = httpx2.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
        async with httpx2.AsyncClient(transport=t, base_url="http://localhost:8000") as c:
            cid = (await c.post("/api/v1/conversations", headers=H)).json()["conversation_id"]
            url = f"/api/v1/conversations/{cid}/messages"
            show("1  GET /nope", await c.get("/nope"))
            show("2  GET /api/v1/conversations", await c.get("/api/v1/conversations", headers=H))
            show("2b DELETE .../messages", await c.delete(url, headers=H))
            show("3a body kind 'question'", await c.post(url, headers=H, json={**GOOD, "kind": "question"}))
            show("3b path id 'abc'", await c.post("/api/v1/conversations/abc/messages", headers=H, json=GOOD))
            show("3c events?limit=0", await c.get(f"/api/v1/runs/{uuid4()}/events?limit=0", headers=H))
            show("3d text 4,001 chars", await c.post(url, headers=H, json={**GOOD, "text": "x" * 4001}))
            try:
                show("4  RuntimeError in a route", await c.get("/spike_boom"))
            except Exception as e:  # noqa: BLE001
                print(f"  4  RuntimeError in a route: raised into the client: {type(e).__name__}: {e}")
            r = await c.post("/spike_echo", content=PADDED, headers={"content-type": "application/json"})
            print("  5a echo, 70,096 B, Content-Length:", r.status_code, r.json() if r.status_code == 200 else r.text)
            r = await c.post("/spike_echo", content=chunks(PADDED), headers={"content-type": "application/json"})
            if r.status_code == 200:
                print("  5b echo, 70,096 B, chunked:", r.status_code, r.json())
            else:
                show("5b echo, 70,096 B, chunked", r)
            r = await c.post("/spike_echo", content=chunks(b"x" * 1000), headers={"content-type": "text/plain"})
            print("  5c echo, 1,000 B, chunked:", r.status_code, r.json())
            fake.slot_occupied = False
            show("5d messages, 70,096 B valid JSON, Content-Length",
                 await c.post(url, content=PADDED, headers={**H, "content-type": "application/json"}))
            cid2 = (await c.post("/api/v1/conversations", headers=H)).json()["conversation_id"]
            show("5e messages, 70,096 B valid JSON, chunked",
                 await c.post(f"/api/v1/conversations/{cid2}/messages", content=chunks(PADDED),
                              headers={**H, "content-type": "application/json"}))
            before = len(fake.conversations)
            show("5f POST /conversations (reads no body), 70,096 B, Content-Length",
                 await c.post("/api/v1/conversations", content=PADDED, headers=H))
            print(f"     conversations the store created during 5f: {len(fake.conversations) - before}")
            before = len(fake.conversations)
            show("5g POST /conversations (reads no body), 70,096 B, chunked",
                 await c.post("/api/v1/conversations", content=chunks(PADDED), headers=H))
            print(f"     conversations the store created during 5g: {len(fake.conversations) - before}")
            r1, r2 = await c.get("/nope"), await c.get("/nope")
            if r1.headers.get("content-type", "").startswith("application/json") and "request_id" in r1.json():
                print("  request_id differs per response:", r1.json()["request_id"] != r2.json()["request_id"])


async def main():
    await scenario(False, False)
    await scenario(False, True)
    await scenario(True, False, "starlette")
    await scenario(True, True, "starlette")
    await scenario(True, False, "spike")


common.run(main)
```

Output (complete):

```text

== handlers=today | raise_app_exceptions=False
  1  GET /nope: 404 application/json {"detail":"Not Found"}
  2  GET /api/v1/conversations: 405 application/json Allow=POST {"detail":"Method Not Allowed"}
  2b DELETE .../messages: 405 application/json Allow=POST {"detail":"Method Not Allowed"}
  3a body kind 'question': 422 application/json SafeError INVALID_INPUT 'request body is not valid' retryable=False
  3b path id 'abc': 422 application/json SafeError INVALID_INPUT 'request is not valid' retryable=False
  3c events?limit=0: 422 application/json SafeError INVALID_INPUT 'request is not valid' retryable=False
  3d text 4,001 chars: 422 application/json SafeError INVALID_INPUT 'request body is not valid' retryable=False
  4  RuntimeError in a route: 500 text/plain Internal Server Error
  5a echo, 70,096 B, Content-Length: 200 {'content-length': '70096', 'transfer-encoding': None, 'received': 70096}
  5b echo, 70,096 B, chunked: 200 {'content-length': None, 'transfer-encoding': 'chunked', 'received': 70096}
  5c echo, 1,000 B, chunked: 200 {'content-length': None, 'transfer-encoding': 'chunked', 'received': 1000}
  5d messages, 70,096 B valid JSON, Content-Length: 202 application/json 7 keys
  5e messages, 70,096 B valid JSON, chunked: 202 application/json 7 keys
  5f POST /conversations (reads no body), 70,096 B, Content-Length: 201 application/json keys ['conversation_id']
     conversations the store created during 5f: 1
  5g POST /conversations (reads no body), 70,096 B, chunked: 201 application/json keys ['conversation_id']
     conversations the store created during 5g: 1

== handlers=today | raise_app_exceptions=True
  1  GET /nope: 404 application/json {"detail":"Not Found"}
  2  GET /api/v1/conversations: 405 application/json Allow=POST {"detail":"Method Not Allowed"}
  2b DELETE .../messages: 405 application/json Allow=POST {"detail":"Method Not Allowed"}
  3a body kind 'question': 422 application/json SafeError INVALID_INPUT 'request body is not valid' retryable=False
  3b path id 'abc': 422 application/json SafeError INVALID_INPUT 'request is not valid' retryable=False
  3c events?limit=0: 422 application/json SafeError INVALID_INPUT 'request is not valid' retryable=False
  3d text 4,001 chars: 422 application/json SafeError INVALID_INPUT 'request body is not valid' retryable=False
  4  RuntimeError in a route: raised into the client: RuntimeError: spike canary secret-ish detail
  5a echo, 70,096 B, Content-Length: 200 {'content-length': '70096', 'transfer-encoding': None, 'received': 70096}
  5b echo, 70,096 B, chunked: 200 {'content-length': None, 'transfer-encoding': 'chunked', 'received': 70096}
  5c echo, 1,000 B, chunked: 200 {'content-length': None, 'transfer-encoding': 'chunked', 'received': 1000}
  5d messages, 70,096 B valid JSON, Content-Length: 202 application/json 7 keys
  5e messages, 70,096 B valid JSON, chunked: 202 application/json 7 keys
  5f POST /conversations (reads no body), 70,096 B, Content-Length: 201 application/json keys ['conversation_id']
     conversations the store created during 5f: 1
  5g POST /conversations (reads no body), 70,096 B, chunked: 201 application/json keys ['conversation_id']
     conversations the store created during 5g: 1

== handlers=registered + starlette RequestBodyLimitMiddleware(65536) | raise_app_exceptions=False
  1  GET /nope: 404 application/json SafeError NOT_FOUND 'request refused' retryable=False
  2  GET /api/v1/conversations: 405 application/json SafeError INVALID_INPUT 'request refused' retryable=False
  2b DELETE .../messages: 405 application/json SafeError INVALID_INPUT 'request refused' retryable=False
  3a body kind 'question': 422 application/json SafeError INVALID_INPUT 'request body is not valid' retryable=False
  3b path id 'abc': 422 application/json SafeError INVALID_INPUT 'request is not valid' retryable=False
  3c events?limit=0: 422 application/json SafeError INVALID_INPUT 'request is not valid' retryable=False
  3d text 4,001 chars: 422 application/json SafeError INVALID_INPUT 'request body is not valid' retryable=False
  4  RuntimeError in a route: 503 application/json SafeError UNAVAILABLE 'service error' retryable=True
  5a echo, 70,096 B, Content-Length: 413 Content Too Large
  5b echo, 70,096 B, chunked: 422 application/json SafeError INVALID_INPUT 'request refused' retryable=False
  5c echo, 1,000 B, chunked: 200 {'content-length': None, 'transfer-encoding': 'chunked', 'received': 1000}
  5d messages, 70,096 B valid JSON, Content-Length: 413 text/plain Content Too Large
  5e messages, 70,096 B valid JSON,
    chunked: 422 application/json SafeError INVALID_INPUT 'request refused' retryable=False
  5f POST /conversations (reads no body), 70,096 B, Content-Length: 413 text/plain Content Too Large
     conversations the store created during 5f: 1
  5g POST /conversations (reads no body), 70,096 B, chunked: 201 application/json keys ['conversation_id']
     conversations the store created during 5g: 1
  request_id differs per response: True

== handlers=registered + starlette RequestBodyLimitMiddleware(65536) | raise_app_exceptions=True
  1  GET /nope: 404 application/json SafeError NOT_FOUND 'request refused' retryable=False
  2  GET /api/v1/conversations: 405 application/json SafeError INVALID_INPUT 'request refused' retryable=False
  2b DELETE .../messages: 405 application/json SafeError INVALID_INPUT 'request refused' retryable=False
  3a body kind 'question': 422 application/json SafeError INVALID_INPUT 'request body is not valid' retryable=False
  3b path id 'abc': 422 application/json SafeError INVALID_INPUT 'request is not valid' retryable=False
  3c events?limit=0: 422 application/json SafeError INVALID_INPUT 'request is not valid' retryable=False
  3d text 4,001 chars: 422 application/json SafeError INVALID_INPUT 'request body is not valid' retryable=False
  4  RuntimeError in a route: raised into the client: RuntimeError: spike canary secret-ish detail
  5a echo, 70,096 B, Content-Length: 413 Content Too Large
  5b echo, 70,096 B, chunked: 422 application/json SafeError INVALID_INPUT 'request refused' retryable=False
  5c echo, 1,000 B, chunked: 200 {'content-length': None, 'transfer-encoding': 'chunked', 'received': 1000}
  5d messages, 70,096 B valid JSON, Content-Length: 413 text/plain Content Too Large
  5e messages, 70,096 B valid JSON,
    chunked: 422 application/json SafeError INVALID_INPUT 'request refused' retryable=False
  5f POST /conversations (reads no body), 70,096 B, Content-Length: 413 text/plain Content Too Large
     conversations the store created during 5f: 1
  5g POST /conversations (reads no body), 70,096 B, chunked: 201 application/json keys ['conversation_id']
     conversations the store created during 5g: 1
  request_id differs per response: True

== handlers=registered + spike_body_limit ASGI middleware (65536) | raise_app_exceptions=False
  1  GET /nope: 404 application/json SafeError NOT_FOUND 'request refused' retryable=False
  2  GET /api/v1/conversations: 405 application/json SafeError INVALID_INPUT 'request refused' retryable=False
  2b DELETE .../messages: 405 application/json SafeError INVALID_INPUT 'request refused' retryable=False
  3a body kind 'question': 422 application/json SafeError INVALID_INPUT 'request body is not valid' retryable=False
  3b path id 'abc': 422 application/json SafeError INVALID_INPUT 'request is not valid' retryable=False
  3c events?limit=0: 422 application/json SafeError INVALID_INPUT 'request is not valid' retryable=False
  3d text 4,001 chars: 422 application/json SafeError INVALID_INPUT 'request body is not valid' retryable=False
  4  RuntimeError in a route: 503 application/json SafeError UNAVAILABLE 'service error' retryable=True
  5a echo, 70,096 B, Content-Length: 422 {"code":"INVALID_INPUT","message":"request body too
    large","retryable":false,"request_id":"c4c56b43-0720-4756-aa53-43eda51d8f8c"}
  5b echo, 70,096 B, chunked: 422 application/json SafeError INVALID_INPUT 'request body too large' retryable=False
  5c echo, 1,000 B, chunked: 200 {'content-length': None, 'transfer-encoding': 'chunked', 'received': 1000}
  5d messages, 70,096 B valid JSON,
    Content-Length: 422 application/json SafeError INVALID_INPUT 'request body too large' retryable=False
  5e messages, 70,096 B valid JSON,
    chunked: 422 application/json SafeError INVALID_INPUT 'request body too large' retryable=False
  5f POST /conversations (reads no body), 70,096 B,
    Content-Length: 422 application/json SafeError INVALID_INPUT 'request body too large' retryable=False
     conversations the store created during 5f: 0
  5g POST /conversations (reads no body), 70,096 B,
    chunked: 422 application/json SafeError INVALID_INPUT 'request body too large' retryable=False
     conversations the store created during 5g: 0
  request_id differs per response: True
```

FastAPI's view of `max_body_size`:

```text
$ uv run python -c "…inspect.signature(...).parameters…"
FastAPI.__init__ has max_body_size: False
APIRoute.__init__ has max_body_size: False
Starlette.__init__ has max_body_size: True
FastAPI.build_middleware_stack mentions max_body_size: False
```

Starlette 1.7.0 source, read (`starlette/middleware/body_limit.py`, `starlette/requests.py`,
`starlette/applications.py`):

- `Request.body()` joins every chunk of `Request.stream()` into one `bytes`. With no limit, the whole body is held in
  memory, however it arrives.
- `Starlette.__init__(…, max_body_size=None)` adds `RequestBodyLimitMiddleware` right inside `ServerErrorMiddleware`.
  `Route`, `Mount` and `Router` take `max_body_size` too. FastAPI overrides `build_middleware_stack` without it, and
  `FastAPI()`/`APIRoute` have no such parameter (measured above). From FastAPI it is reachable only as
  `app.add_middleware(RequestBodyLimitMiddleware, max_body_size=…)`.
- `RequestBodyLimitMiddleware.receive_with_limit` raises `_RequestBodyTooLarge` (an `HTTPException(413)`) when the
  declared `Content-Length` or the running total exceeds the limit. That happens **only when the app calls `receive`**.
  `send_with_limit` replaces any response start with a plain-text `413 Content Too Large` when the declared
  `Content-Length` exceeds the limit. So the route runs first, and the handler's own response is discarded.

Findings:

- **Today:** unknown path → `404 {"detail":"Not Found"}`. Wrong method → `405 {"detail":"Method Not Allowed"}` with
  `Allow: POST`. Both are FastAPI defaults, not the SafeError. Body, path-parameter and query validation already give
  SafeError 422 `INVALID_INPUT`: "request body is not valid" from `body()`, "request is not valid" from the
  `RequestValidationError` handler. An unhandled `RuntimeError` → **500 `text/plain` "Internal Server Error"**, the code
  not in the enum and the shape not the SafeError. With `raise_app_exceptions=True` the exception, canary text included,
  propagates into the client.
- **No size bound today:** 70,096 bytes of valid JSON (padded with whitespace) was accepted by `POST …/messages` with
  `Content-Length` (202) and chunked (202). `POST /api/v1/conversations`, which reads no body, accepted it too (201, one
  conversation created each time). The echo route received all 70,096 bytes either way.
- **With the three handlers registered,** every error case has the `{code, message, retryable, request_id}` shape. 404 →
  `NOT_FOUND`. 405 → a code must be chosen: `ErrorCode` has no method code, the spike used `INVALID_INPUT`, and the
  `Allow` header is lost unless it is copied. The `RuntimeError` → 503 `UNAVAILABLE`, `retryable: true`. `request_id` is
  a new UUID per response. **The `Exception` handler does not stop propagation:** with `raise_app_exceptions=True` the
  client still receives the `RuntimeError`, because `ServerErrorMiddleware` sends the handler's response and then
  re-raises. Under uvicorn that is the "Exception in ASGI application" log record, which Plan F §6 showed must go
  through the redaction filter.
- **Starlette's `RequestBodyLimitMiddleware` (added by hand)** is not a safe answer:
  - An over-limit `Content-Length` gets **plain-text 413**, not the SafeError, even with the `HTTPException` handler.
    The route runs anyway: 5f created a conversation and still answered 413.
  - A chunked over-limit body reaches the handler as an `HTTPException(413)` only when the route reads the body (5b/5e →
    the handler's 422). A route that reads no body is never stopped (5g: 201).
- **A pure ASGI middleware that checks `Content-Length` before calling the app and otherwise pre-reads up to the limit
  and replays the body** (`SpikeBodyLimit`, about 35 lines in the script) gave SafeError 422 "request body too large"
  for every over-limit case. It created no conversation and still passed a 1,000-byte chunked body through. It holds at
  most 64 KiB per request before the route runs. BS:301 puts "shape/content limits" under 422; HTTP's 413 is not in the
  spec's list.

## 6. Message ordering inside one transaction

Script `m6_ordering.py`:

```python
"""§6: ordering two messages inserted in one transaction; what app.messages has; api's rights on conversations."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ALPHA, Role, as_role, persistence, run, su, try_  # noqa: E402

DDL = (
    "CREATE TABLE app.spike_messages (label text,"
    " at_now timestamptz DEFAULT now(), at_clock timestamptz DEFAULT clock_timestamp(),"
    " at_app timestamptz DEFAULT app.current_time(), id bigint GENERATED ALWAYS AS IDENTITY)",
    "GRANT SELECT, INSERT ON app.spike_messages TO api",
    "CREATE TABLE app.spike_messages_serial (label text, ser bigserial)",
    "GRANT SELECT, INSERT ON app.spike_messages_serial TO api",
)
LOCKS = ("FOR UPDATE", "FOR NO KEY UPDATE", "FOR SHARE", "FOR KEY SHARE")


async def two(conn, who):
    async with conn.transaction():
        await conn.execute("INSERT INTO app.spike_messages (label) VALUES (%s)", (f"{who}-question",))
        await conn.execute("INSERT INTO app.spike_messages (label) VALUES (%s)", (f"{who}-answer",))
    return "committed"


async def main():
    s = await su()
    for d in DDL:
        await s.execute(d)
    api = await as_role(Role.API)
    await try_("superuser: two INSERTs in one transaction", two(s, "su"))
    await try_("api: two INSERTs in one transaction", two(api, "api"))
    rows = await (await s.execute("SELECT * FROM app.spike_messages ORDER BY id")).fetchall()
    for r in rows:
        print(f"  {r['label']:<13} now()={r['at_now'].time()} clock_timestamp()={r['at_clock'].time()}"
              f" app.current_time()={r['at_app'].time()} id={r['id']}")
    for a, b in ((rows[0], rows[1]), (rows[2], rows[3])):
        print(f"  pair {a['label'][:3]}: now() equal={a['at_now'] == b['at_now']}"
              f" | clock_timestamp() increasing={a['at_clock'] < b['at_clock']}"
              f" | app.current_time() increasing={a['at_app'] < b['at_app']} | id increasing={a['id'] < b['id']}")
    await try_("api: INSERT into a bigserial table (INSERT only)",
               api.execute("INSERT INTO app.spike_messages_serial (label) VALUES ('x')"))
    await try_("api: INSERT into the identity table (INSERT only)",
               api.execute("INSERT INTO app.spike_messages (label) VALUES ('x')"))

    print("\n-- app.messages today")
    cols = await (await s.execute(
        "SELECT column_name c, data_type t, is_nullable n, column_default d FROM information_schema.columns"
        " WHERE table_schema = 'app' AND table_name = 'messages' ORDER BY ordinal_position")).fetchall()
    for r in cols:
        print(f"  {r['c']:<16} {r['t']:<25} nullable={r['n']:<3} default={r['d']}")
    cons = await (await s.execute("SELECT conname, contype FROM pg_constraint"
                                  " WHERE conrelid = 'app.messages'::regclass ORDER BY 1")).fetchall()
    print("  constraints:", [(r["conname"], r["contype"]) for r in cons])

    print("\n-- api on app.conversations")
    privs = await (await s.execute(
        "SELECT p, has_table_privilege('api', 'app.conversations', p) ok"
        " FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) p")).fetchall()
    print("  table privileges:", {r["p"]: r["ok"] for r in privs})
    n = await (await s.execute(
        "SELECT count(*) n FROM information_schema.column_privileges WHERE grantee = 'api'"
        " AND table_schema = 'app' AND table_name = 'conversations' AND privilege_type = 'UPDATE'")).fetchone()
    print("  column UPDATE grants:", n["n"])
    conv = (await (await s.execute("SELECT conversation_id c FROM app.conversations LIMIT 1")).fetchone())["c"]

    async def lock(sql):
        async with api.transaction():
            await persistence.set_tenant(api, ALPHA)
            return await (await api.execute(sql, (conv,))).fetchall()

    for mode in LOCKS:
        sql = f"SELECT 1 FROM app.conversations WHERE conversation_id = %s {mode}"
        await try_(f"  api: SELECT ... {mode}", lock(sql))
    await try_("  api: pg_advisory_xact_lock(hashtextextended(conversation_id, 0))",
               lock("SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0)) AS locked"))
    await api.close()
    await s.execute("DROP TABLE app.spike_messages, app.spike_messages_serial")
    print("\ndropped app.spike_messages, app.spike_messages_serial")
    await s.close()


run(main)
```

Output (complete):

```text
superuser: two INSERTs in one transaction: OK committed
api: two INSERTs in one transaction: OK committed
  su-question   now()=07:14:53.075182 clock_timestamp()=07:14:53.076227 app.current_time()=07:14:53.077301 id=1
  su-answer     now()=07:14:53.075182 clock_timestamp()=07:14:53.078352 app.current_time()=07:14:53.078442 id=2
  api-question  now()=07:14:53.081375 clock_timestamp()=07:14:53.082582 app.current_time()=07:14:53.083575 id=3
  api-answer    now()=07:14:53.081375 clock_timestamp()=07:14:53.084413 app.current_time()=07:14:53.084457 id=4
  pair su-: now() equal=True | clock_timestamp() increasing=True | app.current_time() increasing=True |
    id increasing=True
  pair api: now() equal=True | clock_timestamp() increasing=True | app.current_time() increasing=True |
    id increasing=True
api: INSERT into a bigserial table (INSERT only): InsufficientPrivilege 42501 'permission denied for sequence
    spike_messages_serial_ser_seq'
api: INSERT into the identity table (INSERT only): OK rowcount=1

-- app.messages today
  message_id       uuid                      nullable=NO  default=None
  tenant_id        uuid                      nullable=NO  default=None
  conversation_id  uuid                      nullable=NO  default=None
  kind             text                      nullable=NO  default=None
  text             text                      nullable=NO  default=None
  context          jsonb                     nullable=YES default=None
  author           uuid                      nullable=NO  default=None
  created_at       timestamp with time zone  nullable=NO  default=now()
  constraints: [('messages_pkey', 'p'), ('messages_tenant_id_conversation_id_fkey', 'f'),
    ('messages_tenant_message_key', 'u')]

-- api on app.conversations
  table privileges: {'SELECT': True, 'INSERT': True, 'UPDATE': False, 'DELETE': False}
  column UPDATE grants: 0
  api: SELECT ... FOR UPDATE: InsufficientPrivilege 42501 'permission denied for table conversations'
  api: SELECT ... FOR NO KEY UPDATE: InsufficientPrivilege 42501 'permission denied for table conversations'
  api: SELECT ... FOR SHARE: InsufficientPrivilege 42501 'permission denied for table conversations'
  api: SELECT ... FOR KEY SHARE: InsufficientPrivilege 42501 'permission denied for table conversations'
  api: pg_advisory_xact_lock(hashtextextended(conversation_id, 0)): OK [{'locked': ''}]

dropped app.spike_messages, app.spike_messages_serial
```

Findings:

- **`now()` cannot order two rows of one transaction:** both rows carry the same `now()` (the transaction start), for
  the superuser and for `api`. `clock_timestamp()`, `app.current_time()` and a `bigint GENERATED ALWAYS AS IDENTITY`
  column are all strictly increasing in insertion order. Timestamps order these two inserts but are not unique in
  general. The identity column is unique and monotonic per table, though not gap-free and not per conversation.
- **Identity versus serial for an INSERT-only role:** `api` with INSERT only could insert into the identity table
  (rowcount 1). The `bigserial` table refused with **42501 "permission denied for sequence …"**: a serial default needs
  `USAGE` on its sequence, and an identity column does not.
- **`app.messages` today:** `message_id, tenant_id, conversation_id, kind, text, context, author, created_at (DEFAULT
  now())`. Constraints: PK, the composite FK to `conversations`, and `UNIQUE (tenant_id, message_id)`. **No `sequence`
  column, no `(conversation_id, sequence)` constraint (BS:230), and no CHECK on `kind`.** A status question and its
  answer inserted in one admission transaction get the same `created_at` today.
- **`api` cannot keep a per-conversation counter:** no UPDATE on `conversations` (table or column grants, 0 rows). Every
  row-lock mode (`FOR UPDATE`, `FOR NO KEY UPDATE`, `FOR SHARE`, `FOR KEY SHARE`) is 42501, since all of them need
  UPDATE (or DELETE/TRUNCATE) on the table. **`pg_advisory_xact_lock(hashtextextended(conversation_id::text, 0))` works
  for `api`** (no grant needed), so it is the only serialiser on a conversation available to `api` today.

## 7. Interval resolution

`api/src/ops_api/app.py:447` (read):

```text
        start_at, end_at = st.resolve_interval(message.context.hours, datetime.now(UTC))
```

`api/src/ops_api/store.py:97-100` truncates `now` to whole seconds and returns `(end - hours, end)`.

Script `m7_interval.py`:

```python
"""§7: where the admission interval comes from and whether a second call with a later clock moves it."""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ALPHA, Role, admit_in_tx, as_role, new_conversation, persistence, run, su  # noqa: E402

import httpx2  # noqa: E402
import psycopg  # noqa: E402
from ops_api import store as st  # noqa: E402
from ops_api.app import create_app  # noqa: E402

from tests.plan_d.test_api import StubVerifier  # noqa: E402
from tests.plan_f.auth_fakes import fake_auth  # noqa: E402

READ = "SELECT start_at, end_at, created_at FROM app.runs WHERE run_id = %s"


async def read_run(api, run_id):
    async with api.transaction():
        await persistence.set_tenant(api, ALPHA)
        return await (await api.execute(READ, (run_id,))).fetchone()


async def main():
    s = await su()
    cur = await s.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='app'"
                          " AND table_name='runs' AND column_name ~ '(interval|start|end)' ORDER BY 1")
    print("runs columns matching interval|start|end:", [r["column_name"] for r in await cur.fetchall()])
    api = await as_role(Role.API)
    conv = await new_conversation(api)
    now1 = datetime.now(UTC)
    s1, e1 = st.resolve_interval(24, now1)
    async with api.transaction():
        _, run_id, _ = await admit_in_tx(api, conv, s1, e1)
    row = await read_run(api, run_id)
    print(f"\n-- A. call 1: now={now1.isoformat(timespec='microseconds')}")
    print(f"   passed [{s1.isoformat()}, {e1.isoformat()})")
    print(f"   stored [{row['start_at'].isoformat()}, {row['end_at'].isoformat()}) | equal to passed:",
          (row["start_at"], row["end_at"]) == (s1, e1))
    now2 = now1 + timedelta(hours=2)
    s2, e2 = st.resolve_interval(24, now2)
    try:
        async with api.transaction():
            await admit_in_tx(api, conv, s2, e2)
        print("   call 2: OK (!)")
    except psycopg.Error as e:
        print(f"   call 2, same request, now + 2 h -> [{s2.isoformat()}, {e2.isoformat()}):")
        print(f"   {e.sqlstate} {e.diag.message_detail}")
    row2 = await read_run(api, run_id)
    print("   run 1 after call 2: unchanged:", (row2["start_at"], row2["end_at"]) == (s1, e1))
    cur = await s.execute("SELECT count(*) n FROM app.runs WHERE conversation_id = %s", (conv,))
    print("   runs in the conversation:", (await cur.fetchone())["n"])

    print("\n-- B. through create_app + DbStore with the test clock moved +3 days (test_harness)")
    harness = await as_role(Role.TEST_HARNESS)
    app_conn = await as_role(Role.API)
    app = create_app(StubVerifier(), store_factory=lambda: st.DbStore(app_conn), auth_factory=fake_auth)
    body = {"kind": "investigate", "text": "Investigate A17.", "context": {"asset_id": "A17", "hours": 24}}
    h = {"Authorization": "Bearer alex"}
    try:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '3 days'")
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
                cid = (await c.post("/api/v1/conversations", headers=h)).json()["conversation_id"]
                r1 = await c.post(f"/api/v1/conversations/{cid}/messages", headers=h, json=body)
                r2 = await c.post(f"/api/v1/conversations/{cid}/messages", headers=h, json=body)
                print("   POST 1:", r1.status_code, r1.json().get("status"), "| POST 2 (same body, no key):",
                      r2.status_code, r2.json().get("code"))
                run_id = r1.json()["run_id"]
        q = ("SELECT end_at, clock_timestamp() AS wall, app.current_time() AS app_now,"
             " clock_timestamp() - end_at AS wall_minus_end, app.current_time() - end_at AS app_minus_end"
             " FROM app.runs WHERE run_id = %s")
        r = await (await s.execute(q, (run_id,))).fetchone()
        print(f"   stored end_at={r['end_at'].isoformat()} | clock_timestamp() - end_at={r['wall_minus_end']}")
        print(f"   app.current_time() - end_at={r['app_minus_end']}")
        cur = await s.execute("SELECT at FROM app.run_state_history WHERE run_id = %s", (run_id,))
        hist = (await cur.fetchone())["at"]
        print(f"   same run: run_state_history.at (app.current_time() inside create_run) - end_at ="
              f" {hist - r['end_at']}")
    finally:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
        print("   test clock offset restored to 0")
    for c in (api, harness, s):
        await c.close()


run(main)
```

Output (complete):

```text
runs columns matching interval|start|end: ['end_at', 'start_at']

-- A. call 1: now=2026-10-10T07:14:54.548261+00:00
   passed [2026-10-09T07:14:54+00:00, 2026-10-10T07:14:54+00:00)
   stored [2026-10-09T07:14:54+00:00, 2026-10-10T07:14:54+00:00) | equal to passed: True
   call 2, same request, now + 2 h -> [2026-10-09T09:14:54+00:00, 2026-10-10T09:14:54+00:00):
   OC005 SLOT_OCCUPIED
   run 1 after call 2: unchanged: True
   runs in the conversation: 1

-- B. through create_app + DbStore with the test clock moved +3 days (test_harness)
   POST 1: 202 QUEUED | POST 2 (same body, no key): 409 SLOT_OCCUPIED
   stored end_at=2026-10-10T07:14:54+00:00 | clock_timestamp() - end_at=0:00:00.722558
   app.current_time() - end_at=3 days, 0:00:00.722591
   same run: run_state_history.at (app.current_time() inside create_run) - end_at = 3 days, 0:00:00.702001
   test clock offset restored to 0
```

Findings:

- **Column names:** `runs` stores the interval as `start_at` and `end_at` (`timestamptz NOT NULL`, `CHECK (start_at <
  end_at)`). No `interval_start`/`interval_end` exists.
- **Stored as passed:** `create_run` stored exactly the caller's `[start_at, end_at)` (whole seconds, UTC).
- **"Two calls, same request, different `now`":** the second call (now + 2 h, so a window 2 h later) never reaches the
  interval. It is refused **OC005 `SLOT_OCCUPIED`**, because the first run holds the conversation slot, and the first
  run's interval is unchanged. Without an idempotency record, a client retry today gets 409, not the original result.
  Part B shows the same over HTTP: POST 1 202, POST 2 (same body) 409 `SLOT_OCCUPIED`.
- **Clock mismatch under the test clock:** with the offset at +3 days, the API resolved the interval from the wall clock
  (`end_at` 0.72 s before `clock_timestamp()`), while `create_run` stamped the same run's history row with
  `app.current_time()` (3 days after `end_at`). From the function source (read, not measured), the job's `available_at`
  (`0003:312`) and the event's `occurred_at` (`0003:183`) use `app.current_time()` as well, while `runs.created_at` is
  `DEFAULT now()`. An R018 test that advances the test clock cannot see the interval move, or not move, until the API
  reads `app.current_time()` inside its unit (§3 shows `api` may).

## 8. Queue bound

Script `m8_queue.py`:

```python
"""§8: can the api role see a queue length, per tenant or globally?"""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ALPHA, BETA, Role, admit_in_tx, as_role, new_conversation, persistence, run, su, try_  # noqa: E402

Q_RUNS = "SELECT count(*) AS n FROM app.runs WHERE state = 'QUEUED'"


async def count_as(api, tenant, sql):
    async with api.transaction():
        if tenant:
            await persistence.set_tenant(api, tenant)
        return (await (await api.execute(sql)).fetchone())


async def main():
    s = await su()
    api = await as_role(Role.API)
    end = datetime.now(UTC).replace(microsecond=0)
    conv_b = await new_conversation(api, BETA)
    async with api.transaction():
        await admit_in_tx(api, conv_b, end - timedelta(hours=1), end, tenant=BETA)
    print("seeded one more QUEUED run in BETA through api create_run (tenant BETA)")
    cur = await s.execute(
        "SELECT tenant_id::text t, count(*) n FROM app.runs WHERE state = 'QUEUED' GROUP BY 1 ORDER BY 1")
    names = {ALPHA: "ALPHA", BETA: "BETA"}
    print("superuser, QUEUED runs per tenant:", {names.get(r["t"], r["t"]): r["n"] for r in await cur.fetchall()})
    cur = await s.execute("SELECT count(*) n FROM app.jobs WHERE done_at IS NULL AND claimed_at IS NULL")
    print("superuser, unclaimed jobs (all tenants):", (await cur.fetchone())["n"])
    print("api under ALPHA:", dict(await count_as(api, ALPHA, Q_RUNS)))
    print("api under BETA:", dict(await count_as(api, BETA, Q_RUNS)))
    print("api with no app.tenant_id:", dict(await count_as(api, None, Q_RUNS)))
    await try_("api under ALPHA: SELECT count(*) FROM app.jobs",
               count_as(api, ALPHA, "SELECT count(*) FROM app.jobs"))
    cur = await s.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='app'"
                          " AND table_name='run_directory' ORDER BY ordinal_position")
    print("run_directory columns (api SELECT, no RLS):", [r["column_name"] for r in await cur.fetchall()])
    print("api: SELECT count(*) FROM app.run_directory (all tenants, no state):",
          dict(await count_as(api, None, "SELECT count(*) AS n FROM app.run_directory")))
    cur = await s.execute(
        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
        " AND has_function_privilege('api', p.oid, 'EXECUTE') ORDER BY 1")
    print("app functions api may EXECUTE:", [r["proname"] for r in await cur.fetchall()])
    print("api: pg_stat_user_tables n_live_tup (statistics, no RLS):",
          [tuple(r.values()) for r in await (await api.execute(
              "SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE schemaname = 'app'"
              " AND relname IN ('runs', 'jobs') ORDER BY 1")).fetchall()])
    await api.close()
    await s.close()


run(main)
```

Output (complete):

```text
seeded one more QUEUED run in BETA through api create_run (tenant BETA)
superuser, QUEUED runs per tenant: {'ALPHA': 21, 'BETA': 1}
superuser, unclaimed jobs (all tenants): 26
api under ALPHA: {'n': 21}
api under BETA: {'n': 1}
api with no app.tenant_id: {'n': 0}
api under ALPHA: SELECT count(*) FROM app.jobs: InsufficientPrivilege 42501 'permission denied for table jobs'
run_directory columns (api SELECT, no RLS): ['run_id', 'tenant_id']
api: SELECT count(*) FROM app.run_directory (all tenants, no state): {'n': 22}
app functions api may EXECUTE: ['append_event', 'create_run', 'current_time', 'record_decision', 'resolve_identity']
api: pg_stat_user_tables n_live_tup (statistics, no RLS): [('jobs', 25), ('runs', 21)]
```

Findings:

- **RLS scopes the count:** as `api`, `SELECT count(*) FROM app.runs WHERE state = 'QUEUED'` returns 21 under ALPHA and
  1 under BETA (the superuser sees ALPHA 21 + BETA 1), and **0 with no `app.tenant_id`**. That is a per-tenant quota
  count, not a global one.
- **`jobs` is unreadable:** `SELECT count(*) FROM app.jobs` gets 42501, so "queued work" in BS:550's sense (jobs) cannot
  be counted by `api` at all.
- **No other path:** `run_directory` (SELECT, no RLS) has only `run_id, tenant_id`, so it can count runs across tenants
  but not by state. The functions `api` may execute are `append_event, create_run, current_time, record_decision,
  resolve_identity`, and none of them counts. **A global queue bound needs a SECURITY DEFINER function or a new grant**,
  either of which is a matrix change.
- **Side channel:** `pg_stat_user_tables.n_live_tup` is readable by `api` and shows approximate cross-tenant row counts
  (jobs 25, runs 21 here). The numbers are stale statistics, not filtered by state, and not a queue bound. They do
  reveal total volume across tenants.

## 9. Other things learned

- **`api` can enqueue any job type for a run in its tenant** (§2: `execute` accepted). The column grant cannot express
  "`resume_input` only", and no CHECK or trigger does. A definer function for the `resume_input` insert would close it;
  so would a trigger, or a CHECK on `type` combined with a policy.
- **The idempotency 23505 DETAIL leaks ids** (§1 a6): tenant, subject and key in clear. If the API catches it, the
  message must be replaced, and the exception must not be logged with its DETAIL.
- **Admission is fast:** a full admission (message + `create_run`) took 5.9–13.7 ms on one connection, and the HTTP
  round trip through the real app over `ASGITransport` took 13.7–26.1 ms (§4).
- **The two test databases outlive a live session:** they existed before this spike (left at `0005` + `tc_0001` by an
  earlier live run) because the `migrated` fixture recreates them at session start but nothing drops them at the end.
- **`app.current_time()` minus `clock_timestamp()` at offset 0 is −1 to −3 µs** (§3), not exactly zero. A test that
  asserts equality must allow a tolerance, as `test_clock_live.py` does with `< 1 s`.

## Cross-cutting gotchas (most consequential first)

1. **Where the idempotency row goes decides what a racing replay sees.** Written last (SA:188), a concurrent same-key
   retry gets 409 `SLOT_OCCUPIED` from `create_run` instead of the recorded 202. Written first, it gets 23505 with ids
   in the DETAIL. Either way the loser must re-read the key in a fresh transaction (or after a savepoint) before
   answering. A target-less `ON CONFLICT DO NOTHING` written first gives a clean "I lost" signal (rowcount 0) without
   aborting the transaction. One API process never sees this race (§4: the session lock serialises), but two processes
   or a live test do.
2. **The interval and the run's other timestamps use different clocks** (§7). The interval comes from
   `datetime.now(UTC)`, the history, job and event from `app.current_time()`, and they differ by the full offset under
   the test clock. R018 is untestable with the test clock until the API reads `app.current_time()` in its unit.
3. **No body limit exists, and the one Starlette ships is unsafe as is** (§5): plain-text 413 after the route has
   already run, and no effect on routes that never read the body. A pure ASGI pre-read middleware measured clean.
4. **FastAPI's 404/405 and an unhandled exception's 500 are not the SafeError** (§5), and an `Exception` handler still
   lets the exception propagate (the traceback reaches the server log).
5. **`api` cannot count global queued work** (§8) or lock a conversation row (§6). It can take `pg_advisory_xact_lock`,
   count its own tenant's runs, and insert jobs blind.
6. **Insert-only roles get one verdict: the rowcount of a target-less `ON CONFLICT DO NOTHING`.** `ON CONFLICT
   (target)`, `RETURNING`, and a sweeper's `DELETE … WHERE` all need SELECT (§1, §2). The column grant does not restrict
   a job's `type`.
7. **Two rows in one transaction share `now()`** (§6). Ordering messages needs an identity column (INSERT-only friendly;
   `serial` is not) or `clock_timestamp()`/`app.current_time()` defaults.

## Cleanup proof

Script `inventory.py` (run before `setup_db.py`, after the last measurement, and after `cleanup.py`):

```python
"""Inventory: databases, spike_* relations in every app database that exists, alembic heads. Read-only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import settings  # noqa: E402

import psycopg  # noqa: E402

admin = settings.superuser_postgres()
SPIKE = "SELECT relname FROM pg_class WHERE relname LIKE 'spike%' ORDER BY 1"


def conn(db: str) -> psycopg.Connection:
    pg = settings.Postgres(admin.host, admin.port, admin.user, db, admin.password)
    return psycopg.connect(pg.conninfo(), autocommit=True)


with conn("postgres") as c:
    dbs = [r[0] for r in c.execute("SELECT datname FROM pg_database ORDER BY 1").fetchall()]
    print("SELECT datname FROM pg_database ->", dbs)
for db in ("ops", "incident", "ops_test", "incident_test"):
    if db not in dbs:
        continue
    with conn(db) as c:
        rel = [r[0] for r in c.execute(SPIKE).fetchall()]
        heads = [r[0] for r in c.execute("SELECT version_num FROM public.alembic_version ORDER BY 1").fetchall()]
        print(f"[{db}] relname LIKE 'spike%' -> {rel} | alembic_version {heads}")
```

Script `cleanup.py`:

```python
"""Drop the per-session test databases this spike recreated (ops_test, incident_test) and nothing else."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import settings  # noqa: E402

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

from tests.e2e.conftest import TEST_DATABASES  # noqa: E402

admin = settings.superuser_postgres()
maintenance = settings.Postgres(admin.host, admin.port, admin.user, "postgres", admin.password)
with psycopg.connect(maintenance.conninfo(), autocommit=True) as conn:
    for name in TEST_DATABASES.values():
        assert name.endswith("_test")
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        print("dropped database", name)
```

Script `secret_check.py`:

```python
"""Every secret value (read only through ops_core.settings.read_secret) against every spike file; booleans only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import settings  # noqa: E402

names = sorted(p.name for p in settings.secrets_dir().iterdir() if p.is_file())
files = sorted(p for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in {".py", ".txt"})
hits = [(n, f.name) for n in names for f in files if settings.read_secret(n) in f.read_text(encoding="utf-8")]
print(f"secret files checked: {len(names)} | spike files checked: {len(files)} | matches: {hits}")
```

Before the final pass (the first pass's cleanup had already dropped the test databases; before the first pass they
existed at `0005` + `tc_0001`):

```text
SELECT datname FROM pg_database -> ['incident', 'ops', 'postgres', 'template0', 'template1']
[ops] relname LIKE 'spike%' -> [] | alembic_version ['0005_sessions_login_logout']
[incident] relname LIKE 'spike%' -> [] | alembic_version ['0002_destination_hardening']
```

After the last measurement, before the drop (each script had already dropped its own `spike_*` tables):

```text
SELECT datname FROM pg_database -> ['incident', 'incident_test', 'ops', 'ops_test', 'postgres', 'template0',
    'template1']
[ops] relname LIKE 'spike%' -> [] | alembic_version ['0005_sessions_login_logout']
[incident] relname LIKE 'spike%' -> [] | alembic_version ['0002_destination_hardening']
[ops_test] relname LIKE 'spike%' -> [] | alembic_version ['0005_sessions_login_logout', 'tc_0001_test_clock']
[incident_test] relname LIKE 'spike%' -> [] | alembic_version ['0002_destination_hardening']
```

`cleanup.py`:

```text
dropped database ops_test
dropped database incident_test
```

After (`SELECT datname FROM pg_database` and `SELECT relname FROM pg_class WHERE relname LIKE 'spike%'` in every
remaining application database):

```text
SELECT datname FROM pg_database -> ['incident', 'ops', 'postgres', 'template0', 'template1']
[ops] relname LIKE 'spike%' -> [] | alembic_version ['0005_sessions_login_logout']
[incident] relname LIKE 'spike%' -> [] | alembic_version ['0002_destination_hardening']
```

`secret_check.py`:

```text
secret files checked: 22 | spike files checked: 38 | matches: []
```

`git status --short` in `<repo>` after the run printed only `?? docs/superpowers/research/2026-10-09-plan-g-inputs.md`
(the fact sheet, which this spike did not create) and this report. The branch is still `plan-f` at `bcae618`, and
nothing was committed.

