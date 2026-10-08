# Plan E spike: measured PostgreSQL and tooling behaviour for roles, grants, RLS, definer functions and the destination

Date: 2026-10-08. Branch `plan-d`. This was a throwaway spike. Every script lives in `<scratch>` (the session scratchpad `spike-e/` directory) and ran against the live dev stack (PostgreSQL at 127.0.0.1:15432) as `uv run python <scratch>/<script>` from `<repo>`, so `psycopg`, `alembic` and `sqlalchemy` came from the repository's lock. Nothing in the repository was edited (`git status --short` was empty after cleanup); this report is the only file written there. Only scratch objects named `spike_*` were created: schemas `spike_app`, `spike_alembic` (database `ops`) and `spike_incident` (database `incident`), and roles `spike_definer`, `spike_api`, `spike_migrator`, `spike_sweeper`, `spike_member`. The schema `app` was never touched. No secret appears below: scripts read `postgres_password` / `postgres_incident_password` from `OPS_SECRETS_DIR`, and the scratch LOGIN roles get a per-run `secrets.token_urlsafe(24)` password that is never printed. The one change outside a `spike_*` object was a revoke-and-restore of `CONNECT` on database `incident` (measurement 3), whose ACL was compared before and after and is identical.

Versions: PostgreSQL `server_version` 17.11 (Debian 17.11-1.pgdg12+2); psycopg 3.3.6; alembic 1.20.0; sqlalchemy 2.1.4 (all three from `<repo>/uv.lock`); CPython 3.13.13.

## Summary

| # | Measurement | Result |
|---|---|---|
| 1 | SECURITY DEFINER `transition_run` (AM-20.3 shape), tenant GUC semantics, custom SQLSTATE, `SET app.tenant_id = ''` attribute | **works**. Inside the function `session_user` is the caller and `current_user` is the owner. `spike_api` has no table grants, yet calling the function changes the rows; a direct UPDATE fails with 42501. Custom SQLSTATE `OCxxx` reaches psycopg as a plain `DatabaseError` with `.sqlstate` set. The SET attribute blanks the GUC inside the function and restores the caller's value on exit |
| 2 | RLS (ENABLE + FORCE), owner, superuser, definer functions, BYPASSRLS, OR-ed policies | **works**, with one serious gotcha: `current_setting('app.tenant_id', true)::uuid` **raises 22P02** once the GUC is `''`, which is the normal state after any committed `set_config(..., true)`. `NULLIF(..., '')::uuid` is required |
| 3 | Column grants, append-only grants, `InsufficientPrivilege` payload, CONNECT | **works**. A column UPDATE grant also needs SELECT on every column it reads (WHERE, RHS). `ON CONFLICT (target)` and `RETURNING` need SELECT. The 42501 payload carries no row data. CONNECT was measured on `incident` (revoked, then restored identically) |
| 4 | Alembic branch label + `depends_on`, `heads` / `current`, one-string PL/pgSQL | **works**. `upgrade(cfg, "head")`, which is what `scripts/skeleton.py` calls, **fails once a second head exists**. Use `heads`, `<rev>` or `testclock@head`. The skeleton's `split(";\n")` breaks any PL/pgSQL body |
| 5 | Advisory xact locks, `current_time()` with an optional `test_clock` | **works**. `hashtext()` is int4 and goes to the bigint signature. The `(int,int)` and bigint keyspaces never collide. **Unqualified `current_time` is the SQL keyword** (it returns `timetz`), so the function must always be schema-qualified |
| 6 | Destination races on `incident` (sync, two sessions, and asyncio.gather), freeze trigger | **works**. The second writer blocks on the uncommitted key and then sees the committed winner; the invariant held 20/20 under `asyncio.gather`. BEFORE INSERT triggers fire even when ON CONFLICT then skips the insert |

All scripts import one helper, `common.py`:

```python
"""Shared spike helpers: superuser conninfo from the secrets dir; never prints secrets."""
import secrets
from pathlib import Path

import psycopg

REPO = Path(r"<repo>")


def _secrets_dir() -> Path:
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPS_SECRETS_DIR="):
            return Path(line.split("=", 1)[1].strip())
    raise RuntimeError("OPS_SECRETS_DIR missing")


def su_kwargs(dbname: str = "ops") -> dict:
    pw = (_secrets_dir() / "postgres_password").read_text(encoding="utf-8").strip()
    return dict(host="127.0.0.1", port=15432, dbname=dbname, user="ops", password=pw)


def su(dbname: str = "ops", autocommit: bool = True) -> psycopg.Connection:
    return psycopg.connect(**su_kwargs(dbname), autocommit=autocommit)


# Scratch LOGIN password: generated per run, never a real secret, never printed.
SPIKE_PW = secrets.token_urlsafe(24)


def as_role(role: str, dbname: str = "ops", autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(host="127.0.0.1", port=15432, dbname=dbname, user=role, password=SPIKE_PW,
                           autocommit=autocommit)


def try_(label, fn):
    try:
        r = fn()
        print(f"{label}: OK -> {r}")
        return r
    except psycopg.Error as e:
        print(f"{label}: {type(e).__name__} sqlstate={e.sqlstate} primary={e.diag.message_primary!r}")
        return e
```

## 1. Definer function pattern (AM-20.3)

Script `m1_definer.py` (measurements 2 and 3 import its `SETUP` and `FUNC`):

```python
"""M1: SECURITY DEFINER transition function (AM-20.3 pattern), tenant GUC semantics, custom SQLSTATE mapping."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import uuid

import psycopg
from common import SPIKE_PW, as_role, su, try_

T1, T2 = uuid.UUID(int=1), uuid.UUID(int=2)
R1, R2 = uuid.UUID(int=101), uuid.UUID(int=102)

SETUP = f"""
DROP SCHEMA IF EXISTS spike_app CASCADE;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='spike_definer') THEN DROP OWNED BY spike_definer; DROP ROLE spike_definer; END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='spike_api') THEN DROP OWNED BY spike_api; DROP ROLE spike_api; END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='spike_migrator') THEN DROP OWNED BY spike_migrator; DROP ROLE spike_migrator; END IF;
END $$;
CREATE ROLE spike_definer NOLOGIN;
CREATE ROLE spike_api LOGIN PASSWORD '{SPIKE_PW}';
CREATE ROLE spike_migrator LOGIN PASSWORD '{SPIKE_PW}';
CREATE SCHEMA spike_app AUTHORIZATION spike_migrator;
SET ROLE spike_migrator;
CREATE TABLE spike_app.runs (run_id uuid PRIMARY KEY, tenant_id uuid NOT NULL, state text NOT NULL,
                             state_version int NOT NULL DEFAULT 1);
CREATE TABLE spike_app.run_state_history (run_id uuid NOT NULL REFERENCES spike_app.runs, seq int NOT NULL,
    from_state text, to_state text NOT NULL, performer text NOT NULL, PRIMARY KEY (run_id, seq));
INSERT INTO spike_app.runs VALUES ('{R1}', '{T1}', 'QUEUED', 1), ('{R2}', '{T2}', 'QUEUED', 1);
GRANT USAGE ON SCHEMA spike_app TO spike_definer, spike_api;
GRANT SELECT, UPDATE (state, state_version) ON spike_app.runs TO spike_definer;
GRANT SELECT, INSERT ON spike_app.run_state_history TO spike_definer;
RESET ROLE;
"""

FUNC = """
CREATE FUNCTION spike_app.transition_run(p_run_id uuid, p_from text, p_to text, p_expected int) RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = spike_app, pg_temp AS $fn$
DECLARE
  v_tenant text := current_setting('app.tenant_id', true);
  v_row runs%ROWTYPE;
  v_seq int;
BEGIN
  RAISE NOTICE 'inside: session_user=% current_user=% app.tenant_id=%', session_user, current_user, coalesce(v_tenant, '<NULL>');
  IF session_user <> 'spike_api' THEN
    RAISE EXCEPTION 'caller % not allowed', session_user USING ERRCODE = 'OC001';
  END IF;
  SELECT * INTO v_row FROM runs WHERE run_id = p_run_id FOR UPDATE;
  IF NOT FOUND OR v_tenant IS NULL OR v_tenant = '' OR v_row.tenant_id::text <> v_tenant THEN
    RAISE EXCEPTION 'run not found' USING ERRCODE = 'OC002';   -- same error for absent and foreign: no oracle
  END IF;
  IF v_row.state <> p_from OR v_row.state_version <> p_expected THEN
    RAISE EXCEPTION 'stale transition' USING ERRCODE = 'OC003', DETAIL = format('have %s/v%s', v_row.state, v_row.state_version);
  END IF;
  UPDATE runs SET state = p_to, state_version = state_version + 1 WHERE run_id = p_run_id;
  SELECT coalesce(max(seq), 0) + 1 INTO v_seq FROM run_state_history WHERE run_id = p_run_id;
  INSERT INTO run_state_history VALUES (p_run_id, v_seq, p_from, p_to, session_user);
  RETURN v_row.state_version + 1;
END $fn$;
ALTER FUNCTION spike_app.transition_run(uuid, text, text, int) OWNER TO spike_definer;
REVOKE ALL ON FUNCTION spike_app.transition_run(uuid, text, text, int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION spike_app.transition_run(uuid, text, text, int) TO spike_api;

-- probe for the SET-attribute trick: returns what the function sees for app.tenant_id
CREATE FUNCTION spike_app.probe_attr() RETURNS text LANGUAGE sql SECURITY DEFINER
  SET search_path = spike_app, pg_temp SET app.tenant_id = ''
  AS $$ SELECT coalesce(current_setting('app.tenant_id', true), '<NULL>') || ' | cu=' || current_user $$;
ALTER FUNCTION spike_app.probe_attr() OWNER TO spike_definer;
REVOKE ALL ON FUNCTION spike_app.probe_attr() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION spike_app.probe_attr() TO spike_api;

CREATE FUNCTION spike_app.probe_leak() RETURNS void LANGUAGE sql SECURITY DEFINER
  SET search_path = spike_app, pg_temp SET app.tenant_id = ''
  AS $$ SELECT set_config('app.tenant_id', '00000000-0000-0000-0000-00000000dead', true) $$;
ALTER FUNCTION spike_app.probe_leak() OWNER TO spike_definer;
REVOKE ALL ON FUNCTION spike_app.probe_leak() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION spike_app.probe_leak() TO spike_api;

CREATE FUNCTION spike_app.probe_noattr_leak() RETURNS void LANGUAGE sql SECURITY DEFINER
  SET search_path = spike_app, pg_temp
  AS $$ SELECT set_config('app.tenant_id', '00000000-0000-0000-0000-00000000beef', true) $$;
ALTER FUNCTION spike_app.probe_noattr_leak() OWNER TO spike_definer;
REVOKE ALL ON FUNCTION spike_app.probe_noattr_leak() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION spike_app.probe_noattr_leak() TO spike_api;
"""


def notices(conn):
    conn.add_notice_handler(lambda d: print("   NOTICE:", d.message_primary))


def main():
    with su() as s:
        s.execute(SETUP)
        s.execute(FUNC)
        print("pg_proc transition_run:", s.execute(
            "SELECT proowner::regrole, proacl, prosecdef, proconfig FROM pg_proc WHERE proname='transition_run'").fetchone())
        print("pg_proc probe_attr proconfig:", s.execute(
            "SELECT proconfig FROM pg_proc WHERE proname='probe_attr'").fetchone())

    print("\n-- A. GUC semantics")
    a, b = as_role("spike_api"), as_role("spike_api")
    print("fresh session, never set:", a.execute("SELECT current_setting('app.tenant_id', true)").fetchone())
    a.execute("SELECT set_config('app.tenant_id', %s, true)", (str(T1),))
    print("same txn after set_config(...,true):", a.execute("SELECT current_setting('app.tenant_id', true)").fetchone())
    print("other session meanwhile:", b.execute("SELECT current_setting('app.tenant_id', true)").fetchone())
    b.rollback()
    a.commit()
    print("after COMMIT (same session):", repr(a.execute("SELECT current_setting('app.tenant_id', true)").fetchone()[0]))
    a.rollback()
    a.execute("SELECT set_config('app.tenant_id', %s, true)", (str(T1),)); a.rollback()
    print("after ROLLBACK:", repr(a.execute("SELECT current_setting('app.tenant_id', true)").fetchone()[0]))
    a.rollback()
    try_("current_setting('app.tenant_id') WITHOUT missing_ok in a never-set session", lambda: b.execute(
        "SELECT current_setting('app.tenant_id')").fetchone())
    b.rollback()

    print("\n-- B. spike_api calls transition_run (no table grants)")
    notices(a)
    a.execute("SELECT set_config('app.tenant_id', %s, true)", (str(T1),))
    try_("transition R1 QUEUED->RETRIEVING v1", lambda: a.execute(
        "SELECT spike_app.transition_run(%s,'QUEUED','RETRIEVING',1)", (R1,)).fetchone())
    a.commit()
    a.execute("SELECT set_config('app.tenant_id', %s, true)", (str(T1),))
    r = try_("replay same transition (stale)", lambda: a.execute(
        "SELECT spike_app.transition_run(%s,'QUEUED','RETRIEVING',1)", (R1,)).fetchone())
    if isinstance(r, psycopg.Error):
        print("   mro:", [c.__name__ for c in type(r).__mro__[:4]], "| detail:", r.diag.message_detail,
              "| context:", (r.diag.context or "").splitlines()[:1])
        try:
            print("   psycopg.errors.lookup('OC003'):", psycopg.errors.lookup("OC003"))
        except KeyError as e:
            print("   psycopg.errors.lookup('OC003'): KeyError", e)
    a.rollback()
    a.execute("SELECT set_config('app.tenant_id', %s, true)", (str(T1),))
    try_("foreign-tenant run R2 with T1 set", lambda: a.execute(
        "SELECT spike_app.transition_run(%s,'QUEUED','RETRIEVING',1)", (R2,)).fetchone())
    a.rollback()
    try_("no tenant set in this txn (GUC is '' after earlier commit)", lambda: a.execute(
        "SELECT spike_app.transition_run(%s,'RETRIEVING','DRAFTING',2)", (R1,)).fetchone())
    a.rollback()
    try_("direct UPDATE spike_app.runs as spike_api", lambda: a.execute(
        "UPDATE spike_app.runs SET state='X' WHERE run_id=%s", (R1,)).rowcount)
    a.rollback()
    try_("direct SELECT spike_app.runs as spike_api", lambda: a.execute("SELECT * FROM spike_app.runs").fetchall())
    a.rollback()

    print("\n-- C. superuser ops calls it")
    with su(autocommit=False) as s:
        notices(s)
        s.execute("SELECT set_config('app.tenant_id', %s, true)", (str(T1),))
        try_("ops -> transition_run", lambda: s.execute(
            "SELECT spike_app.transition_run(%s,'RETRIEVING','DRAFTING',2)", (R1,)).fetchone())
        s.rollback()
        print("rows:", s.execute("SELECT run_id, state, state_version FROM spike_app.runs ORDER BY run_id").fetchall())
        print("history:", s.execute(
            "SELECT run_id, seq, from_state, to_state, performer FROM spike_app.run_state_history").fetchall())
        s.rollback()

    print("\n-- D. SET app.tenant_id = '' function attribute")
    a.execute("SELECT set_config('app.tenant_id', %s, true)", (str(T1),))
    print("inside probe_attr():", repr(a.execute("SELECT spike_app.probe_attr()").fetchone()[0]))
    print("caller after call (same txn):", a.execute("SELECT current_setting('app.tenant_id', true)").fetchone()[0])
    a.execute("SELECT spike_app.probe_leak()")
    print("after probe_leak() (fn has SET attr, does set_config(..,true) inside):",
          a.execute("SELECT current_setting('app.tenant_id', true)").fetchone()[0])
    a.execute("SELECT spike_app.probe_noattr_leak()")
    print("after probe_noattr_leak() (no SET attr, set_config(..,true) inside):",
          a.execute("SELECT current_setting('app.tenant_id', true)").fetchone()[0])
    a.rollback()
    a.close(); b.close()


if __name__ == "__main__":
    main()
```

Output (complete):

```text
pg_proc transition_run: ('spike_definer', ['spike_definer=X/spike_definer', 'spike_api=X/spike_definer'], True, ['search_path=spike_app, pg_temp'])
pg_proc probe_attr proconfig: (['search_path=spike_app, pg_temp', 'app.tenant_id='],)

-- A. GUC semantics
fresh session, never set: (None,)
same txn after set_config(...,true): ('00000000-0000-0000-0000-000000000001',)
other session meanwhile: (None,)
after COMMIT (same session): ''
after ROLLBACK: ''
current_setting('app.tenant_id') WITHOUT missing_ok in a never-set session: UndefinedObject sqlstate=42704 primary='unrecognized configuration parameter "app.tenant_id"'

-- B. spike_api calls transition_run (no table grants)
   NOTICE: inside: session_user=spike_api current_user=spike_definer app.tenant_id=00000000-0000-0000-0000-000000000001
transition R1 QUEUED->RETRIEVING v1: OK -> (2,)
   NOTICE: inside: session_user=spike_api current_user=spike_definer app.tenant_id=00000000-0000-0000-0000-000000000001
replay same transition (stale): DatabaseError sqlstate=OC003 primary='stale transition'
   mro: ['DatabaseError', 'Error', 'Exception', 'BaseException'] | detail: have RETRIEVING/v2 | context: ['PL/pgSQL function transition_run(uuid,text,text,integer) line 16 at RAISE']
   psycopg.errors.lookup('OC003'): KeyError 'OC003'
   NOTICE: inside: session_user=spike_api current_user=spike_definer app.tenant_id=00000000-0000-0000-0000-000000000001
foreign-tenant run R2 with T1 set: DatabaseError sqlstate=OC002 primary='run not found'
   NOTICE: inside: session_user=spike_api current_user=spike_definer app.tenant_id=
no tenant set in this txn (GUC is '' after earlier commit): DatabaseError sqlstate=OC002 primary='run not found'
direct UPDATE spike_app.runs as spike_api: InsufficientPrivilege sqlstate=42501 primary='permission denied for table runs'
direct SELECT spike_app.runs as spike_api: InsufficientPrivilege sqlstate=42501 primary='permission denied for table runs'

-- C. superuser ops calls it
   NOTICE: inside: session_user=ops current_user=spike_definer app.tenant_id=00000000-0000-0000-0000-000000000001
ops -> transition_run: DatabaseError sqlstate=OC001 primary='caller ops not allowed'
rows: [(UUID('00000000-0000-0000-0000-000000000065'), 'RETRIEVING', 2), (UUID('00000000-0000-0000-0000-000000000066'), 'QUEUED', 1)]
history: [(UUID('00000000-0000-0000-0000-000000000065'), 1, 'QUEUED', 'RETRIEVING', 'spike_api')]

-- D. SET app.tenant_id = '' function attribute
inside probe_attr(): ' | cu=spike_definer'
caller after call (same txn): 00000000-0000-0000-0000-000000000001
after probe_leak() (fn has SET attr, does set_config(..,true) inside): 00000000-0000-0000-0000-000000000001
after probe_noattr_leak() (no SET attr, set_config(..,true) inside): 00000000-0000-0000-0000-00000000beef
```

Findings:

- **`session_user` vs `current_user`.** When `spike_api` calls the function, `session_user=spike_api` and `current_user=spike_definer`. When `ops` calls it, `session_user=ops` and the guard raises `OC001`. `SET ROLE spike_api` by a member role does **not** change `session_user` (measurement 3: `caller spike_member not allowed`). A non-superuser cannot `SET SESSION AUTHORIZATION` (42501). A **superuser can** (`SET SESSION AUTHORIZATION spike_api` passes the guard; measurement 3). So the `session_user` guard stops every non-superuser login and not a superuser, which is expected.
- **The function works without table grants.** `spike_api` has `USAGE` on the schema and `EXECUTE` on the function only. The transition succeeds, and the history row is written with `performer = session_user = spike_api`. A direct `UPDATE`/`SELECT` on `spike_app.runs` gives `InsufficientPrivilege 42501 'permission denied for table runs'`.
- **ACL shape.** After `REVOKE ALL ... FROM PUBLIC; GRANT EXECUTE ... TO spike_api`, `proacl = {spike_definer=X/spike_definer, spike_api=X/spike_definer}`, and `proconfig` holds the `search_path`.
- **GUC lifecycle.** In a session that never set it, `current_setting('app.tenant_id', true)` is `NULL`. After any `set_config(..., true)`, whether committed **or rolled back**, the placeholder stays defined and reads back as `''`, not NULL. Without `missing_ok`, a never-set session raises `42704 unrecognized configuration parameter`. A value set in another session is never visible (`None`). `set_config(..., true)` is reset at COMMIT and at ROLLBACK.
- **Custom SQLSTATE.** `RAISE ... USING ERRCODE = 'OC003', DETAIL = ...` reaches psycopg as `psycopg.DatabaseError` (the base class: `psycopg.errors.lookup('OC003')` raises `KeyError`). `exc.sqlstate == 'OC003'`, `exc.diag.message_primary == 'stale transition'`, `exc.diag.message_detail` carries the DETAIL, and `exc.diag.context` names the function and line. Map errors on `exc.sqlstate`, not on the exception class. Measurement 3 shows how psycopg maps a custom code by its **class** prefix: `P0xxx`/`42xxx` -> `ProgrammingError`, `22xxx` -> `DataError`, `23xxx` -> `IntegrityError`, `40xxx`/`57xxx` -> `OperationalError`, `XXxxx` -> `InternalError`, an unknown class (`OC`) -> `DatabaseError`. A custom class (for example `OC`) therefore never collides with built-in handling such as retry-on-`40001`.
- **The `SET app.tenant_id = ''` function attribute does what SA says.** Inside the function the GUC is `''`. After the call, the caller's transaction-local value (`...0001`) is back. Even a `set_config(..., true)` *inside* such a function is undone on exit (`probe_leak`). Without the attribute it leaks to the caller (`probe_noattr_leak` left `...beef` set). This is a second reason to declare the attribute on every definer function. **But** the attribute and the plain `::uuid` RLS policy together raise 22P02 (measurement 2), so the policy must use `NULLIF`.
- **Concurrency.** The guard `SELECT ... FOR UPDATE` then `state_version` compare-and-set rejected the replayed transition with `OC003` and `have RETRIEVING/v2`. The absent-run and foreign-tenant cases both return the same `OC002 'run not found'`, so the error gives no oracle.

Failure modes / gotchas:
1. `ALTER FUNCTION ... OWNER TO spike_definer` run by the **superuser** ignores the "new owner needs CREATE on the schema" rule. Run by a non-superuser migrator, it needs (a) membership in `spike_definer` with the SET option (PG16+ error text: `must be able to SET ROLE "spike_definer"`) **and** (b) `CREATE` on the schema for `spike_definer` (`permission denied for schema spike_app` otherwise). Both are shown in measurement 3. If T09's migrator is not a superuser, its revision has to grant both, and the definer role then holds CREATE on `app`. Consider revoking CREATE after the ownership change. Ownership survives the revoke; this was not measured.
2. (From the docs, not measured.) A PL/pgSQL `%ROWTYPE` variable and `RETURNING` values all resolve through the function's `search_path`. Without `pg_temp` last, a caller could shadow names through temp objects. This is the reason for `SET search_path = <schema>, pg_temp`.

## 2. RLS

Script `m2_rls.py`:

```python
"""M2: RLS on spike_app.runs — unset/empty GUC, owner + FORCE, superuser, definer functions, BYPASSRLS, OR-ed policies."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import psycopg
from common import SPIKE_PW, as_role, su, try_
from m1_definer import R1, R2, SETUP, T1, T2

RLS = f"""
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='spike_sweeper') THEN DROP OWNED BY spike_sweeper; DROP ROLE spike_sweeper; END IF;
END $$;
CREATE ROLE spike_sweeper LOGIN PASSWORD '{SPIKE_PW}';
SET ROLE spike_migrator;
INSERT INTO spike_app.runs VALUES ('00000000-0000-0000-0000-000000000067', '{T2}', 'DRAFTING', 3);
ALTER TABLE spike_app.runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE spike_app.runs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON spike_app.runs USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON spike_app.runs TO spike_api;
GRANT USAGE ON SCHEMA spike_app TO spike_sweeper;
GRANT SELECT ON spike_app.runs TO spike_sweeper;
RESET ROLE;
-- definer readers: one owned by spike_definer (not table owner), one owned by the table owner
CREATE FUNCTION spike_app.count_runs_definer() RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path = spike_app, pg_temp AS $$ SELECT count(*) FROM runs $$;
ALTER FUNCTION spike_app.count_runs_definer() OWNER TO spike_definer;
CREATE FUNCTION spike_app.count_runs_blank() RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path = spike_app, pg_temp SET app.tenant_id = '' AS $$ SELECT count(*) FROM runs $$;
ALTER FUNCTION spike_app.count_runs_blank() OWNER TO spike_definer;
CREATE FUNCTION spike_app.count_runs_owner() RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path = spike_app, pg_temp AS $$ SELECT count(*) FROM runs $$;
ALTER FUNCTION spike_app.count_runs_owner() OWNER TO spike_migrator;
REVOKE ALL ON FUNCTION spike_app.count_runs_definer(), spike_app.count_runs_blank(), spike_app.count_runs_owner() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION spike_app.count_runs_definer(), spike_app.count_runs_blank(), spike_app.count_runs_owner() TO spike_api;
"""

Q = "SELECT tenant_id::text, count(*) FROM spike_app.runs GROUP BY 1 ORDER BY 1"


def setcfg(c, v):
    c.execute("SELECT set_config('app.tenant_id', %s, true)", (v,))


def main():
    with su() as s:
        s.execute(SETUP)
        s.execute(RLS)
        print("relrowsecurity/relforcerowsecurity:", s.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid='spike_app.runs'::regclass").fetchone())

    api = as_role("spike_api")
    print("\n-- spike_api")
    try_("never-set GUC (NULL) -> rows", lambda: api.execute(Q).fetchall()); api.rollback()
    setcfg(api, str(T1)); api.commit()          # leaves the placeholder at '' for later txns
    try_("GUC '' (after a committed local set) -> rows", lambda: api.execute(Q).fetchall()); api.rollback()
    setcfg(api, str(T1)); try_("T1 set -> rows", lambda: api.execute(Q).fetchall()); api.rollback()
    setcfg(api, "not-a-uuid"); try_("garbage GUC -> rows", lambda: api.execute(Q).fetchall()); api.rollback()
    setcfg(api, str(T1))
    try_("UPDATE foreign run R2 under T1 (rowcount)", lambda: api.execute(
        "UPDATE spike_app.runs SET state='X' WHERE run_id=%s", (R2,)).rowcount)
    api.rollback(); setcfg(api, str(T1))
    try_("INSERT row for T2 while T1 set (USING doubles as WITH CHECK)", lambda: api.execute(
        "INSERT INTO spike_app.runs VALUES (gen_random_uuid(), %s, 'QUEUED', 1)", (T2,)).rowcount)
    api.rollback()
    setcfg(api, str(T1))
    try_("count_runs_blank() [SET app.tenant_id=''] under the plain ::uuid policy", lambda: api.execute(
        "SELECT spike_app.count_runs_blank()").fetchone())
    api.rollback()

    print("\n-- policy rewritten with NULLIF(...,'')")
    with su() as s:
        s.execute("SET ROLE spike_migrator; ALTER POLICY tenant_isolation ON spike_app.runs "
                  "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid); RESET ROLE")
    try_("GUC '' -> rows", lambda: api.execute(Q).fetchall()); api.rollback()
    setcfg(api, str(T2)); try_("T2 set -> rows", lambda: api.execute(Q).fetchall()); api.rollback()

    print("\n-- table owner spike_migrator with FORCE")
    mig = as_role("spike_migrator")
    try_("owner, GUC unset -> rows", lambda: mig.execute(Q).fetchall()); mig.rollback()
    setcfg(mig, str(T1)); try_("owner, T1 -> rows", lambda: mig.execute(Q).fetchall()); mig.rollback()
    with su() as s:
        s.execute("ALTER TABLE spike_app.runs NO FORCE ROW LEVEL SECURITY")
    try_("owner, NO FORCE, unset -> rows", lambda: mig.execute(Q).fetchall()); mig.rollback()
    with su() as s:
        s.execute("ALTER TABLE spike_app.runs FORCE ROW LEVEL SECURITY")

    print("\n-- superuser ops")
    with su() as s:
        try_("ops, unset -> rows", lambda: s.execute(Q).fetchall())

    print("\n-- definer functions called by spike_api")
    setcfg(api, str(T1))
    for v in (str(T1), str(T2)):
        setcfg(api, v)
        try_(f"count_runs_definer() with caller GUC {v[-1]}", lambda: api.execute(
            "SELECT spike_app.count_runs_definer()").fetchone())
        try_("count_runs_blank() (SET app.tenant_id='')", lambda: api.execute(
            "SELECT spike_app.count_runs_blank()").fetchone())
        try_("count_runs_owner() (owned by table owner, FORCE on)", lambda: api.execute(
            "SELECT spike_app.count_runs_owner()").fetchone())
        api.rollback()
    with su() as s:
        s.execute("ALTER TABLE spike_app.runs NO FORCE ROW LEVEL SECURITY")
    setcfg(api, str(T1))
    try_("count_runs_owner() with NO FORCE (owner bypasses)", lambda: api.execute(
        "SELECT spike_app.count_runs_owner()").fetchone())
    api.rollback()
    with su() as s:
        s.execute("ALTER TABLE spike_app.runs FORCE ROW LEVEL SECURITY")

    print("\n-- BYPASSRLS on spike_migrator")
    try_("spike_migrator ALTER ROLE self BYPASSRLS", lambda: mig.execute("ALTER ROLE spike_migrator BYPASSRLS"))
    mig.rollback()
    with su() as s:
        s.execute("ALTER ROLE spike_migrator BYPASSRLS")
    mig.close(); mig = as_role("spike_migrator")
    try_("migrator BYPASSRLS + FORCE, unset -> rows", lambda: mig.execute(Q).fetchall()); mig.rollback()
    setcfg(api, str(T1))
    try_("count_runs_owner() (owner now BYPASSRLS) via spike_api", lambda: api.execute(
        "SELECT spike_app.count_runs_owner()").fetchone())
    api.rollback()
    with su() as s:
        s.execute("ALTER ROLE spike_migrator NOBYPASSRLS")

    print("\n-- sweeper_all permissive policy OR-ed with tenant_isolation")
    with su() as s:
        s.execute("SET ROLE spike_migrator; CREATE POLICY sweeper_all ON spike_app.runs FOR SELECT TO spike_sweeper "
                  "USING (true); RESET ROLE")
    sw = as_role("spike_sweeper")
    try_("sweeper, unset -> rows", lambda: sw.execute(Q).fetchall()); sw.rollback()
    setcfg(sw, str(T1)); try_("sweeper, T1 -> rows", lambda: sw.execute(Q).fetchall()); sw.rollback()
    setcfg(api, str(T1)); try_("spike_api still T1 only", lambda: api.execute(Q).fetchall()); api.rollback()
    with su() as s:
        s.execute("SET ROLE spike_migrator; CREATE POLICY t_restrict ON spike_app.runs AS RESTRICTIVE FOR SELECT "
                  "TO spike_sweeper USING (state <> 'DRAFTING'); RESET ROLE")
    try_("sweeper + RESTRICTIVE (state<>'DRAFTING') -> rows", lambda: sw.execute(Q).fetchall()); sw.rollback()
    with su() as s:
        print("pg_policies:", s.execute("SELECT policyname, permissive, roles, cmd, qual FROM pg_policies "
                                        "WHERE schemaname='spike_app' ORDER BY 1").fetchall())
    for c in (api, mig, sw):
        c.close()


if __name__ == "__main__":
    main()
```

Output (complete):

```text
relrowsecurity/relforcerowsecurity: (True, True)

-- spike_api
never-set GUC (NULL) -> rows: OK -> []
GUC '' (after a committed local set) -> rows: InvalidTextRepresentation sqlstate=22P02 primary='invalid input syntax for type uuid: ""'
T1 set -> rows: OK -> [('00000000-0000-0000-0000-000000000001', 1)]
garbage GUC -> rows: InvalidTextRepresentation sqlstate=22P02 primary='invalid input syntax for type uuid: "not-a-uuid"'
UPDATE foreign run R2 under T1 (rowcount): OK -> 0
INSERT row for T2 while T1 set (USING doubles as WITH CHECK): InsufficientPrivilege sqlstate=42501 primary='new row violates row-level security policy for table "runs"'
count_runs_blank() [SET app.tenant_id=''] under the plain ::uuid policy: InvalidTextRepresentation sqlstate=22P02 primary='invalid input syntax for type uuid: ""'

-- policy rewritten with NULLIF(...,'')
GUC '' -> rows: OK -> []
T2 set -> rows: OK -> [('00000000-0000-0000-0000-000000000002', 2)]

-- table owner spike_migrator with FORCE
owner, GUC unset -> rows: OK -> []
owner, T1 -> rows: OK -> [('00000000-0000-0000-0000-000000000001', 1)]
owner, NO FORCE, unset -> rows: OK -> [('00000000-0000-0000-0000-000000000001', 1), ('00000000-0000-0000-0000-000000000002', 2)]

-- superuser ops
ops, unset -> rows: OK -> [('00000000-0000-0000-0000-000000000001', 1), ('00000000-0000-0000-0000-000000000002', 2)]

-- definer functions called by spike_api
count_runs_definer() with caller GUC 1: OK -> (1,)
count_runs_blank() (SET app.tenant_id=''): OK -> (0,)
count_runs_owner() (owned by table owner, FORCE on): OK -> (1,)
count_runs_definer() with caller GUC 2: OK -> (2,)
count_runs_blank() (SET app.tenant_id=''): OK -> (0,)
count_runs_owner() (owned by table owner, FORCE on): OK -> (2,)
count_runs_owner() with NO FORCE (owner bypasses): OK -> (3,)

-- BYPASSRLS on spike_migrator
spike_migrator ALTER ROLE self BYPASSRLS: InsufficientPrivilege sqlstate=42501 primary='permission denied to alter role'
migrator BYPASSRLS + FORCE, unset -> rows: OK -> [('00000000-0000-0000-0000-000000000001', 1), ('00000000-0000-0000-0000-000000000002', 2)]
count_runs_owner() (owner now BYPASSRLS) via spike_api: OK -> (3,)

-- sweeper_all permissive policy OR-ed with tenant_isolation
sweeper, unset -> rows: OK -> [('00000000-0000-0000-0000-000000000001', 1), ('00000000-0000-0000-0000-000000000002', 2)]
sweeper, T1 -> rows: OK -> [('00000000-0000-0000-0000-000000000001', 1), ('00000000-0000-0000-0000-000000000002', 2)]
spike_api still T1 only: OK -> [('00000000-0000-0000-0000-000000000001', 1)]
sweeper + RESTRICTIVE (state<>'DRAFTING') -> rows: OK -> [('00000000-0000-0000-0000-000000000001', 1), ('00000000-0000-0000-0000-000000000002', 1)]
pg_policies: [('sweeper_all', 'PERMISSIVE', ['spike_sweeper'], 'SELECT', 'true'), ('t_restrict', 'RESTRICTIVE', ['spike_sweeper'], 'SELECT', "(state <> 'DRAFTING'::text)"), ('tenant_isolation', 'PERMISSIVE', ['public'], 'ALL', "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)")]
```

Findings:

- **Unset vs empty GUC with the policy exactly as written (`current_setting('app.tenant_id', true)::uuid`).** A never-set GUC (NULL) returns **no rows**, which is the deny the spec wants. GUC `''` raises `InvalidTextRepresentation 22P02 'invalid input syntax for type uuid: ""'`. `''` is the *normal* state of any pooled or reused connection after its first committed transaction (measurement 1). A garbage value also raises 22P02 and echoes the value in `message_primary`. The error leaks nothing about rows, but it is an error, not a deny. **Use `NULLIF(current_setting('app.tenant_id', true), '')::uuid`.** After `ALTER POLICY` with that expression, `''` returns no rows. A garbage non-empty value still raises 22P02, which is acceptable because only the server sets the value.
- **Tenant filtering.** `spike_api` with `set_config(T1)` sees only T1's row; with T2 it sees T2's 2 rows. An UPDATE of a foreign row affects **0 rows silently** (no error). An INSERT of a foreign-tenant row gives `42501 new row violates row-level security policy` (USING doubles as WITH CHECK when no WITH CHECK is given).
- **The owner with FORCE is filtered too:** `spike_migrator` sees `[]` when the GUC is unset and only T1 when it is set. With `NO FORCE`, the owner sees all 3 rows. **Gotcha for T09:** under FORCE, a migration's data backfill run as the table owner sees and updates nothing unless it sets the tenant or the owner has BYPASSRLS.
- **The superuser `ops` bypasses RLS** (all rows, GUC unset).
- **Definer functions follow the session's GUC.** `count_runs_definer()`, owned by `spike_definer` and run with the caller's GUC, returned 1 (T1) and 2 (T2). The policy reads `current_setting` at execution time, so the caller's transaction-local value applies inside the function. With the `SET app.tenant_id = ''` attribute, the function sees `''` -> 0 rows (NULLIF policy) or 22P02 (plain policy). A definer function owned by the **table owner** is still filtered when FORCE is on (1 / 2) and sees everything with NO FORCE (3).
- **BYPASSRLS.** A non-superuser cannot grant BYPASSRLS to itself (`42501 permission denied to alter role`). Once a superuser grants it, `spike_migrator` sees all rows **even with FORCE**, and so does every SECURITY DEFINER function it owns, whoever calls it (`count_runs_owner()` via `spike_api` -> 3). So no definer function may be owned by a BYPASSRLS role unless it does its own tenant filtering.
- **Policies combine.** `sweeper_all` (`FOR SELECT TO spike_sweeper USING (true)`) is OR-ed with `tenant_isolation` (`TO public`). The sweeper sees every tenant with or without the GUC, and `spike_api` stays T1-only. An `AS RESTRICTIVE` policy is AND-ed: the sweeper lost the `DRAFTING` row. `pg_policies` shows `tenant_isolation` as `roles={public}, cmd=ALL`.

## 3. Grants table mechanics

Script `m3_grants.py`:

```python
"""M3: column grants, append-only grants, InsufficientPrivilege payload, custom-SQLSTATE class mapping,
non-superuser ALTER FUNCTION OWNER, session_user vs SET ROLE / SET SESSION AUTHORIZATION, CONNECT (read-only)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import psycopg
from common import SPIKE_PW, as_role, su, try_
from m1_definer import FUNC, R1, SETUP, T1

GRANTS = f"""
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='spike_member') THEN DROP OWNED BY spike_member; DROP ROLE spike_member; END IF;
END $$;
CREATE ROLE spike_member LOGIN PASSWORD '{SPIKE_PW}' IN ROLE spike_api;
SET ROLE spike_migrator;
GRANT UPDATE (state_version) ON spike_app.runs TO spike_api;
CREATE TABLE spike_app.audit (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, k text UNIQUE, v text);
GRANT INSERT ON spike_app.audit TO spike_api;
RESET ROLE;
"""


def diag(e: psycopg.Error) -> dict:
    d = e.diag
    return {k: getattr(d, k) for k in ("sqlstate", "message_primary", "message_detail", "message_hint",
                                       "schema_name", "table_name", "column_name", "constraint_name")}


def main():
    with su() as s:
        s.execute(SETUP); s.execute(FUNC); s.execute(GRANTS)
    api = as_role("spike_api")

    print("-- column-level UPDATE (state_version) only")
    try_("UPDATE SET state='X' (no WHERE)", lambda: api.execute("UPDATE spike_app.runs SET state='X'").rowcount)
    api.rollback()
    try_("UPDATE SET state_version=7 (no WHERE)", lambda: api.execute(
        "UPDATE spike_app.runs SET state_version=7").rowcount)
    api.rollback()
    try_("UPDATE SET state_version=7 WHERE run_id=... (needs SELECT(run_id))", lambda: api.execute(
        "UPDATE spike_app.runs SET state_version=7 WHERE run_id=%s", (R1,)).rowcount)
    api.rollback()
    try_("UPDATE SET state_version=state_version+1 (reads the column)", lambda: api.execute(
        "UPDATE spike_app.runs SET state_version=state_version+1").rowcount)
    api.rollback()
    with su() as s:
        s.execute("GRANT SELECT (run_id, state_version) ON spike_app.runs TO spike_api")
    try_("after GRANT SELECT(run_id,state_version): WHERE run_id + state_version+1", lambda: api.execute(
        "UPDATE spike_app.runs SET state_version=state_version+1 WHERE run_id=%s", (R1,)).rowcount)
    api.rollback()
    try_("SELECT * (state not granted)", lambda: api.execute("SELECT * FROM spike_app.runs").fetchall())
    api.rollback()
    with su() as s:
        print("column ACLs:", s.execute("SELECT attname, attacl FROM pg_attribute WHERE attrelid='spike_app.runs'::regclass "
                                         "AND attacl IS NOT NULL ORDER BY attnum").fetchall())

    print("\n-- append-only: INSERT only")
    try_("INSERT", lambda: api.execute("INSERT INTO spike_app.audit (k, v) VALUES ('a', '1')").rowcount)
    try_("INSERT ... RETURNING id (needs SELECT)", lambda: api.execute(
        "INSERT INTO spike_app.audit (k, v) VALUES ('b', '1') RETURNING id").fetchone())
    api.rollback()
    try_("INSERT ON CONFLICT (k) DO NOTHING", lambda: api.execute(
        "INSERT INTO spike_app.audit (k, v) VALUES ('a', '1') ON CONFLICT (k) DO NOTHING").rowcount)
    api.rollback()
    try_("INSERT ON CONFLICT DO NOTHING (no conflict target)", lambda: api.execute(
        "INSERT INTO spike_app.audit (k, v) VALUES ('a', '1') ON CONFLICT DO NOTHING").rowcount)
    api.rollback()
    try_("INSERT ON CONFLICT (k) DO UPDATE", lambda: api.execute(
        "INSERT INTO spike_app.audit (k, v) VALUES ('a', '1') ON CONFLICT (k) DO UPDATE SET v='2'").rowcount)
    api.rollback()
    try_("UPDATE audit", lambda: api.execute("UPDATE spike_app.audit SET v='x'").rowcount); api.rollback()
    try_("DELETE audit", lambda: api.execute("DELETE FROM spike_app.audit").rowcount); api.rollback()
    try_("TRUNCATE audit", lambda: api.execute("TRUNCATE spike_app.audit")); api.rollback()

    print("\n-- InsufficientPrivilege payload")
    try:
        api.execute("UPDATE spike_app.runs SET state='SECRET-VALUE' WHERE run_id=%s", (R1,))
    except psycopg.errors.InsufficientPrivilege as e:
        print("type:", type(e).__name__, "| str(e):", str(e).strip().replace("\n", " / "))
        print("diag:", diag(e))
        print("query echoed in str(e)? ", "SECRET-VALUE" in str(e))
    api.rollback()

    print("\n-- custom SQLSTATE class -> psycopg class")
    with su() as s:
        for code in ("OC001", "P0001", "P0OC1", "22OC1", "23OC1", "40OC1", "42OC1", "XXOC1", "57OC1"):
            try:
                s.execute(f"DO $$ BEGIN RAISE EXCEPTION 'x' USING ERRCODE = '{code}'; END $$")
            except psycopg.Error as e:
                print(f"  {code}: {type(e).__name__} (bases: {[c.__name__ for c in type(e).__mro__[1:3]]})")

    print("\n-- session_user vs SET ROLE / SET SESSION AUTHORIZATION calling transition_run")
    mem = as_role("spike_member")
    mem.add_notice_handler(lambda d: print("   NOTICE:", d.message_primary))
    mem.execute("SET ROLE spike_api")
    mem.execute("SELECT set_config('app.tenant_id', %s, true)", (str(T1),))
    try_("spike_member SET ROLE spike_api -> transition_run", lambda: mem.execute(
        "SELECT spike_app.transition_run(%s,'QUEUED','RETRIEVING',1)", (R1,)).fetchone())
    mem.rollback()
    try_("spike_member SET SESSION AUTHORIZATION spike_api", lambda: mem.execute(
        "SET SESSION AUTHORIZATION spike_api"))
    mem.rollback(); mem.close()
    with su(autocommit=False) as s:
        s.add_notice_handler(lambda d: print("   NOTICE:", d.message_primary))
        s.execute("SET SESSION AUTHORIZATION spike_api")
        s.execute("SELECT set_config('app.tenant_id', %s, true)", (str(T1),))
        try_("superuser SET SESSION AUTHORIZATION spike_api -> transition_run", lambda: s.execute(
            "SELECT spike_app.transition_run(%s,'QUEUED','RETRIEVING',1)", (R1,)).fetchone())
        s.rollback()

    print("\n-- non-superuser ALTER FUNCTION ... OWNER TO spike_definer (as spike_migrator)")
    mig = as_role("spike_migrator", autocommit=True)
    mig.execute("CREATE FUNCTION spike_app.f_own() RETURNS int LANGUAGE sql AS 'SELECT 1'")
    try_("1. migrator not member of spike_definer", lambda: mig.execute(
        "ALTER FUNCTION spike_app.f_own() OWNER TO spike_definer"))
    with su() as s:
        s.execute("GRANT spike_definer TO spike_migrator")
        s.execute("REVOKE CREATE ON SCHEMA spike_app FROM spike_definer")
    try_("2. member (default INHERIT/SET), spike_definer lacks CREATE on schema", lambda: mig.execute(
        "ALTER FUNCTION spike_app.f_own() OWNER TO spike_definer"))
    mig.execute("GRANT CREATE ON SCHEMA spike_app TO spike_definer")
    try_("3. + spike_definer has CREATE on schema", lambda: mig.execute(
        "ALTER FUNCTION spike_app.f_own() OWNER TO spike_definer"))
    with su() as s:
        print("   membership:", s.execute("SELECT roleid::regrole, member::regrole, inherit_option, set_option, admin_option "
                                        "FROM pg_auth_members WHERE member='spike_migrator'::regrole").fetchall())
    mig.close()

    print("\n-- CONNECT privilege (ops untouched; incident revoked+restored)")
    with su() as s:
        print("datacl:", s.execute("SELECT datname, datdba::regrole, datacl FROM pg_database "
                                   "WHERE datname IN ('ops','incident','postgres') ORDER BY 1").fetchall())
        print("has_database_privilege(spike_api, *, CONNECT):", s.execute(
            "SELECT d, has_database_privilege('spike_api', d, 'CONNECT') FROM unnest(array['ops','incident','postgres']) d"
        ).fetchall())
    def connect_incident(label):
        def go():
            with as_role("spike_api", dbname="incident") as c:
                return c.execute("SELECT current_database(), session_user").fetchone()
        try:
            print(f"{label}: OK -> {go()}")
        except psycopg.OperationalError as e:
            print(f"{label}: {type(e).__name__} sqlstate={e.sqlstate} msg={str(e).strip().splitlines()[-2:]!r}")

    connect_incident("spike_api -> incident (PUBLIC has CONNECT)")
    # Safe on `incident`: role incident holds an explicit `c` grant and ops is owner+superuser; CONNECT is checked
    # only at connection start, so live incident-sim sessions are unaffected. The ACL is restored and compared below.
    with su() as s:
        before = s.execute("SELECT datacl::text FROM pg_database WHERE datname='incident'").fetchone()[0]
        s.execute("REVOKE CONNECT ON DATABASE incident FROM PUBLIC")
        print("datacl after REVOKE FROM PUBLIC:", s.execute(
            "SELECT datacl FROM pg_database WHERE datname='incident'").fetchone()[0])
    try:
        connect_incident("spike_api -> incident after REVOKE CONNECT FROM PUBLIC")
        with su() as s:
            s.execute("GRANT CONNECT ON DATABASE incident TO spike_api")
        connect_incident("spike_api -> incident after GRANT CONNECT TO spike_api")
    finally:
        with su() as s:
            s.execute("REVOKE CONNECT ON DATABASE incident FROM spike_api")
            s.execute("GRANT CONNECT ON DATABASE incident TO PUBLIC")
            after = s.execute("SELECT datacl::text FROM pg_database WHERE datname='incident'").fetchone()[0]
            print("incident datacl restored identical:", before == after, after)
    api.close()


if __name__ == "__main__":
    main()
```

Output (complete):

```text
-- column-level UPDATE (state_version) only
UPDATE SET state='X' (no WHERE): InsufficientPrivilege sqlstate=42501 primary='permission denied for table runs'
UPDATE SET state_version=7 (no WHERE): OK -> 2
UPDATE SET state_version=7 WHERE run_id=... (needs SELECT(run_id)): InsufficientPrivilege sqlstate=42501 primary='permission denied for table runs'
UPDATE SET state_version=state_version+1 (reads the column): InsufficientPrivilege sqlstate=42501 primary='permission denied for table runs'
after GRANT SELECT(run_id,state_version): WHERE run_id + state_version+1: OK -> 1
SELECT * (state not granted): InsufficientPrivilege sqlstate=42501 primary='permission denied for table runs'
column ACLs: [('run_id', ['spike_api=r/spike_migrator']), ('state', ['spike_definer=w/spike_migrator']), ('state_version', ['spike_definer=w/spike_migrator', 'spike_api=rw/spike_migrator'])]

-- append-only: INSERT only
INSERT: OK -> 1
INSERT ... RETURNING id (needs SELECT): InsufficientPrivilege sqlstate=42501 primary='permission denied for table audit'
INSERT ON CONFLICT (k) DO NOTHING: InsufficientPrivilege sqlstate=42501 primary='permission denied for table audit'
INSERT ON CONFLICT DO NOTHING (no conflict target): OK -> 1
INSERT ON CONFLICT (k) DO UPDATE: InsufficientPrivilege sqlstate=42501 primary='permission denied for table audit'
UPDATE audit: InsufficientPrivilege sqlstate=42501 primary='permission denied for table audit'
DELETE audit: InsufficientPrivilege sqlstate=42501 primary='permission denied for table audit'
TRUNCATE audit: InsufficientPrivilege sqlstate=42501 primary='permission denied for table audit'

-- InsufficientPrivilege payload
type: InsufficientPrivilege | str(e): permission denied for table runs
diag: {'sqlstate': '42501', 'message_primary': 'permission denied for table runs', 'message_detail': None, 'message_hint': None, 'schema_name': None, 'table_name': None, 'column_name': None, 'constraint_name': None}
query echoed in str(e)?  False

-- custom SQLSTATE class -> psycopg class
  OC001: DatabaseError (bases: ['Error', 'Exception'])
  P0001: RaiseException (bases: ['ProgrammingError', 'DatabaseError'])
  P0OC1: ProgrammingError (bases: ['DatabaseError', 'Error'])
  22OC1: DataError (bases: ['DatabaseError', 'Error'])
  23OC1: IntegrityError (bases: ['DatabaseError', 'Error'])
  40OC1: OperationalError (bases: ['DatabaseError', 'Error'])
  42OC1: ProgrammingError (bases: ['DatabaseError', 'Error'])
  XXOC1: InternalError (bases: ['DatabaseError', 'Error'])
  57OC1: OperationalError (bases: ['DatabaseError', 'Error'])

-- session_user vs SET ROLE / SET SESSION AUTHORIZATION calling transition_run
   NOTICE: inside: session_user=spike_member current_user=spike_definer app.tenant_id=00000000-0000-0000-0000-000000000001
spike_member SET ROLE spike_api -> transition_run: DatabaseError sqlstate=OC001 primary='caller spike_member not allowed'
spike_member SET SESSION AUTHORIZATION spike_api: InsufficientPrivilege sqlstate=42501 primary='permission denied to set session authorization "spike_api"'
   NOTICE: inside: session_user=spike_api current_user=spike_definer app.tenant_id=00000000-0000-0000-0000-000000000001
superuser SET SESSION AUTHORIZATION spike_api -> transition_run: OK -> (2,)

-- non-superuser ALTER FUNCTION ... OWNER TO spike_definer (as spike_migrator)
1. migrator not member of spike_definer: InsufficientPrivilege sqlstate=42501 primary='must be able to SET ROLE "spike_definer"'
2. member (default INHERIT/SET), spike_definer lacks CREATE on schema: InsufficientPrivilege sqlstate=42501 primary='permission denied for schema spike_app'
3. + spike_definer has CREATE on schema: OK -> <psycopg.Cursor [COMMAND_OK] [IDLE] (host=127.0.0.1 port=15432 user=spike_migrator database=ops) at 0x29b6771ae10>
   membership: [('spike_definer', 'spike_migrator', True, True, False)]

-- CONNECT privilege (ops untouched; incident revoked+restored)
datacl: [('incident', 'ops', ['=Tc/ops', 'ops=CTc/ops', 'incident=c/ops']), ('ops', 'ops', None), ('postgres', 'ops', None)]
has_database_privilege(spike_api, *, CONNECT): [('ops', True), ('incident', True), ('postgres', True)]
spike_api -> incident (PUBLIC has CONNECT): OK -> ('incident', 'spike_api')
datacl after REVOKE FROM PUBLIC: ['=T/ops', 'ops=CTc/ops', 'incident=c/ops']
spike_api -> incident after REVOKE CONNECT FROM PUBLIC: OperationalError sqlstate=None msg=['connection failed: connection to server at "127.0.0.1", port 15432 failed: FATAL:  permission denied for database "incident"', 'DETAIL:  User does not have CONNECT privilege.']
spike_api -> incident after GRANT CONNECT TO spike_api: OK -> ('incident', 'spike_api')
incident datacl restored identical: True {=Tc/ops,ops=CTc/ops,incident=c/ops}
```

Findings:

- **Column-level UPDATE.** `GRANT UPDATE (state_version)`: `SET state = ...` -> 42501; `SET state_version = 7` with no WHERE works. **But** `... WHERE run_id = ...` and `SET state_version = state_version + 1` both fail with 42501, because UPDATE needs **SELECT on every column it reads**. After `GRANT SELECT (run_id, state_version)`, the compare-and-set works. `SELECT *` still fails because `state` is not readable. `attacl` shows `spike_api=rw` on `state_version` and `=r` on `run_id`.
- **Append-only (INSERT only).** Plain `INSERT` works. `INSERT ... RETURNING`, `ON CONFLICT (k) DO NOTHING` (arbiter columns need SELECT) and `ON CONFLICT DO UPDATE` all give 42501. `ON CONFLICT DO NOTHING` **without** a conflict target works. UPDATE/DELETE/TRUNCATE give 42501. A writer that needs an idempotent insert-and-read-back needs SELECT, or a definer function.
- **`InsufficientPrivilege` payload:** `sqlstate='42501'`, `message_primary='permission denied for table runs'`. detail, hint, schema, table, column and constraint are all `None`. `str(e)` does not echo the statement or its parameters (`'SECRET-VALUE' in str(e)` -> False). It names the table but no row data.
- **CONNECT.** By default PUBLIC has CONNECT on every database (`datacl` NULL on `ops`/`postgres`; `=Tc/ops` on `incident`), so a new LOGIN role like `spike_api` could connect to `incident`. The revoke was measured **on `incident` only**. It is safe there because role `incident` holds an explicit `c` grant, `ops` is owner and superuser, and CONNECT is checked only when a connection starts. After `REVOKE CONNECT ON DATABASE incident FROM PUBLIC`, `datacl` becomes `{=T/ops,...}` and `spike_api` fails at connect with `OperationalError` (`.sqlstate` is `None` on a connection failure; the text is `FATAL: permission denied for database "incident"`, `DETAIL: User does not have CONNECT privilege.`). After `GRANT CONNECT ... TO spike_api` it connects. The ACL was restored with `REVOKE ... FROM spike_api; GRANT CONNECT ... TO PUBLIC` and compared to the original string: identical. `ops` was not touched. Reasoning from the docs and the observed `datacl`: on `ops` the same REVOKE would turn `datacl` from NULL into explicit owner entries without `c` for PUBLIC. Every runtime role on `ops` (api, worker, mcp-*, migrator) then needs an explicit `GRANT CONNECT`. Superusers are not affected.

## 4. Alembic branches and profiles

Scratch tree `<scratch>/alembic_spike/` (no `script.py.mako` or ini: nothing was generated, only run). `env.py`:

```python
"""Scratch Alembic env: same connection-attribute pattern as migrations/app/env.py; version table in spike_alembic."""
from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("connection attribute required")

connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS spike_alembic")
context.configure(connection=connection, target_metadata=None,
                  version_table="alembic_version", version_table_schema="spike_alembic")
with context.begin_transaction():
    context.run_migrations()
```

`versions/a1_base.py`:

```python
"""base: a table plus a PL/pgSQL function passed as ONE op.execute string (no ; splitting)."""
from alembic import op

revision = "a1_base"
down_revision = None
branch_labels = None
depends_on = None

BODY = """
CREATE TABLE spike_alembic.runs (run_id int PRIMARY KEY, state text NOT NULL);
CREATE FUNCTION spike_alembic.bump(p int) RETURNS int LANGUAGE plpgsql AS $fn$
DECLARE
  v int;
BEGIN
  UPDATE spike_alembic.runs SET state = 'X' WHERE run_id = p;
  GET DIAGNOSTICS v = ROW_COUNT;
  RETURN v;
END $fn$;
INSERT INTO spike_alembic.runs VALUES (1, 'A');
"""


def upgrade() -> None:
    op.execute(BODY)


def downgrade() -> None:
    op.execute("DROP FUNCTION spike_alembic.bump(int); DROP TABLE spike_alembic.runs")
```

`versions/a2_main.py`:

```python
"""main line, second revision."""
from alembic import op

revision = "a2_main"
down_revision = "a1_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE spike_alembic.main2 (id int)")


def downgrade() -> None:
    op.execute("DROP TABLE spike_alembic.main2")
```

`versions/tc1_testclock.py`:

```python
"""testclock branch: its own root (down_revision=None), labelled, depends_on the base revision."""
from alembic import op

revision = "tc1_testclock"
down_revision = None
branch_labels = ("testclock",)
depends_on = "a1_base"


def upgrade() -> None:
    op.execute("CREATE TABLE spike_alembic.test_clock (offset_s interval NOT NULL)")


def downgrade() -> None:
    op.execute("DROP TABLE spike_alembic.test_clock")
```

Driver `m4_alembic.py`:

```python
"""M4: Alembic branch labels / depends_on / heads / current, and one-string PL/pgSQL vs the skeleton's ;\\n splitter."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import psycopg
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from common import su, su_kwargs
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

HERE = Path(__file__).parent
k = su_kwargs()
ENGINE = create_engine(URL.create("postgresql+psycopg", username=k["user"], password=k["password"],
                                  host=k["host"], port=k["port"], database=k["dbname"]))


def cfg_with(conn) -> Config:
    cfg = Config(stdout=sys.stdout)
    cfg.set_main_option("script_location", str(HERE / "alembic_spike"))
    cfg.attributes["connection"] = conn
    return cfg


def run(label, fn):
    print(f"\n>>> {label}")
    with ENGINE.begin() as conn:
        try:
            fn(cfg_with(conn))
        except CommandError as e:
            print("CommandError:", e)
    with su() as s:
        print("   version rows:", s.execute(
            "SELECT version_num FROM spike_alembic.alembic_version ORDER BY 1").fetchall()
              if s.execute("SELECT to_regclass('spike_alembic.alembic_version')").fetchone()[0] else "<no table>")
        print("   tables:", s.execute("SELECT tablename FROM pg_tables WHERE schemaname='spike_alembic' "
                                      "AND tablename <> 'alembic_version' ORDER BY 1").fetchall())


def reset():
    with su() as s:
        s.execute("DROP SCHEMA IF EXISTS spike_alembic CASCADE")


def main():
    reset()
    with ENGINE.begin() as conn:
        cfg = cfg_with(conn)
        print(">>> heads"); command.heads(cfg, verbose=False)
        print(">>> branches"); command.branches(cfg)
        print(">>> history"); command.history(cfg)
    run("upgrade 'head' (what scripts/skeleton.py calls)", lambda c: command.upgrade(c, "head"))
    reset()
    run("upgrade 'a2_main' (main line only)", lambda c: command.upgrade(c, "a2_main"))
    run("current (one head applied)", lambda c: command.current(c, verbose=False))
    reset()
    run("upgrade 'testclock@head' (labelled branch only)", lambda c: command.upgrade(c, "testclock@head"))
    run("then upgrade 'a2_main' (dependency a1 already applied, no a1 row stored)",
        lambda c: command.upgrade(c, "a2_main"))
    reset()
    run("upgrade 'a2_main' then 'testclock@head'", lambda c: (command.upgrade(c, "a2_main"),
                                                             command.upgrade(c, "testclock@head")))
    reset()
    run("upgrade 'heads'", lambda c: command.upgrade(c, "heads"))
    run("current (two heads applied)", lambda c: command.current(c, verbose=False))
    run("downgrade 'testclock@base' (drop only the branch)", lambda c: command.downgrade(c, "testclock@base"))
    run("upgrade 'heads' again", lambda c: command.upgrade(c, "heads"))
    run("downgrade 'base' (everything)", lambda c: command.downgrade(c, "base"))
    with su() as s:
        print("\nfunction from one-string op.execute existed & worked (re-run a1 standalone):")
    reset()
    run("upgrade 'a1_base'", lambda c: command.upgrade(c, "a1_base"))
    with su() as s:
        print("   bump(1) ->", s.execute("SELECT spike_alembic.bump(1)").fetchone())

    print("\n>>> the skeleton splitter (DDL.split(';\\n')) applied to the same body")
    from importlib import import_module
    body = import_module("alembic_spike.versions.a1_base").BODY.replace("spike_alembic.", "spike_alembic.s_")
    parts = [p for p in body.split(";\n") if p.strip()]
    print(f"   {len(parts)} pieces; piece 2 = {parts[1].strip()[:90]!r} ...")
    with su() as s:
        for i, p in enumerate(parts, 1):
            try:
                s.execute(p)
                print(f"   piece {i}: OK")
            except psycopg.Error as e:
                print(f"   piece {i}: {type(e).__name__} {e.sqlstate} {e.diag.message_primary!r}")
    reset()


if __name__ == "__main__":
    main()
```

Output (complete):

```text
>>> heads
a2_main (head)
tc1_testclock (testclock) (head)
>>> branches
>>> history
a1_base -> a2_main (head), main line, second revision.
<base> (a1_base) -> tc1_testclock (testclock) (head), testclock branch: its own root (down_revision=None), labelled, depends_on the base revision.
<base> -> a1_base, base: a table plus a PL/pgSQL function passed as ONE op.execute string (no ; splitting).

>>> upgrade 'head' (what scripts/skeleton.py calls)
CommandError: Multiple head revisions are present for given argument 'head'; please specify a specific target revision, '<branchname>@head' to narrow to a specific head, or 'heads' for all heads
   version rows: []
   tables: []

>>> upgrade 'a2_main' (main line only)
   version rows: [('a2_main',)]
   tables: [('main2',), ('runs',)]

>>> current (one head applied)
a2_main (head)
   version rows: [('a2_main',)]
   tables: [('main2',), ('runs',)]

>>> upgrade 'testclock@head' (labelled branch only)
   version rows: [('tc1_testclock',)]
   tables: [('runs',), ('test_clock',)]

>>> then upgrade 'a2_main' (dependency a1 already applied, no a1 row stored)
   version rows: [('a2_main',), ('tc1_testclock',)]
   tables: [('main2',), ('runs',), ('test_clock',)]

>>> upgrade 'a2_main' then 'testclock@head'
   version rows: [('a2_main',), ('tc1_testclock',)]
   tables: [('main2',), ('runs',), ('test_clock',)]

>>> upgrade 'heads'
   version rows: [('a2_main',), ('tc1_testclock',)]
   tables: [('main2',), ('runs',), ('test_clock',)]

>>> current (two heads applied)
tc1_testclock (head)
a2_main (head)
   version rows: [('a2_main',), ('tc1_testclock',)]
   tables: [('main2',), ('runs',), ('test_clock',)]

>>> downgrade 'testclock@base' (drop only the branch)
   version rows: [('a2_main',)]
   tables: [('main2',), ('runs',)]

>>> upgrade 'heads' again
   version rows: [('a2_main',), ('tc1_testclock',)]
   tables: [('main2',), ('runs',), ('test_clock',)]

>>> downgrade 'base' (everything)
   version rows: []
   tables: []

function from one-string op.execute existed & worked (re-run a1 standalone):

>>> upgrade 'a1_base'
   version rows: [('a1_base',)]
   tables: [('runs',)]
   bump(1) -> (1,)

>>> the skeleton splitter (DDL.split(';\n')) applied to the same body
   7 pieces; piece 2 = 'CREATE FUNCTION spike_alembic.s_bump(p int) RETURNS int LANGUAGE plpgsql AS $fn$\nDECLARE\n ' ...
   piece 1: OK
   piece 2: SyntaxError 42601 'unterminated dollar-quoted string at or near "$fn$\nDECLARE\n  v int"'
   piece 3: SyntaxError 42601 'syntax error at or near "UPDATE"'
   piece 4: SyntaxError 42601 'syntax error at or near "GET"'
   piece 5: SyntaxError 42601 'syntax error at or near "RETURN"'
   piece 6: SyntaxError 42601 'unterminated dollar-quoted string at or near "$fn$"'
   piece 7: OK
```

Findings:

- **The branch layout that works:** `tc1_testclock` has `down_revision = None` (its own root), `branch_labels = ("testclock",)` and `depends_on = "a1_base"`. `heads` lists `a2_main (head)` and `tc1_testclock (testclock) (head)`. `branches` prints nothing (there is no branch *point*, because the label is on a separate root). `history` shows `<base> (a1_base) -> tc1_testclock`.
- **`command.upgrade(cfg, "head")` fails** with `CommandError: Multiple head revisions are present for given argument 'head'; please specify ... '<branchname>@head' ... or 'heads'`, and it applies nothing. **`scripts/skeleton.py upgrade()` calls exactly `"head"`**, so adding a labelled branch to `migrations/app` breaks `skeleton.py migrate` until that call changes. The production profile should use the main-line head revision id (or a main-line branch label such as `app@head` if the main line gets one). The test profile should use `heads`.
- **Main line only:** `upgrade(cfg, "a2_main")` (the revision id) -> version rows `[a2_main]`, no `test_clock`. **Labelled branch only:** `upgrade(cfg, "testclock@head")` -> `[tc1_testclock]`. Its dependency `a1_base` **was applied** (table `runs` exists) but has **no row of its own**: Alembic stores only heads and treats a1 as satisfied through the dependency. A later `upgrade "a2_main"` correctly applied only a2 (`[a2_main, tc1_testclock]`). Applying the two in the reverse order gives the same end state.
- **`upgrade "heads"`** -> `[a2_main, tc1_testclock]`. **`current`** with two heads prints two lines, `a2_main (head)` and `tc1_testclock (head)`. **`downgrade "testclock@base"`** removes only the branch. `downgrade "base"` removes everything.
- **One-string PL/pgSQL.** `op.execute(BODY)`, where BODY holds `CREATE TABLE ...; CREATE FUNCTION ... $fn$ ... ; ... $fn$; INSERT ...;` as one string, works (psycopg sends it as one simple-query batch with no parameters). `bump(1)` returned 1.
- **The skeleton splitter breaks it.** `DDL.split(";\n")` on the same body gives 7 pieces. Piece 2 ends inside the dollar quote (`42601 unterminated dollar-quoted string`), and the next pieces are bare PL/pgSQL statements (`syntax error at or near "UPDATE"`, `"GET"`, `"RETURN"`). The splitter cuts at every `;` that ends a line, and a PL/pgSQL body always contains those. T09's revision must pass each function or DO block as a separate `op.execute` string (or the whole script as one string), never through `split(";\n")`. A one-string execute that mixes statements still runs in the migration's single transaction.

## 5. Advisory locks and `current_time()`

Script `m5_locks_clock.py`:

```python
"""M5: advisory xact locks (bigint vs int,int keyspaces, blocking between sessions) and an app.current_time()-style
function with an optional test_clock offset; clock_timestamp() vs now()."""
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import psycopg
from common import su, try_

TENANT, ASSET = uuid.UUID(int=1), "pump-7"
KEY_SQL = "hashtext(%s::text || %s)"


def main():
    with su() as s:
        print("hashtext type/value:", s.execute(f"SELECT pg_typeof({KEY_SQL}), {KEY_SQL}",
                                                (TENANT, ASSET, TENANT, ASSET)).fetchone())
        print("hashtextextended(...,0) (bigint):", s.execute("SELECT hashtextextended(%s::text || %s, 0)",
                                                           (TENANT, ASSET)).fetchone())
        print("signatures:", s.execute("SELECT oid::regprocedure FROM pg_proc WHERE proname='pg_advisory_xact_lock' "
                                       "ORDER BY 1").fetchall())

    a, b = su(autocommit=False), su(autocommit=False)
    key = a.execute(f"SELECT {KEY_SQL}", (TENANT, ASSET)).fetchone()[0]
    a.execute(f"SELECT pg_advisory_xact_lock({KEY_SQL})", (TENANT, ASSET))
    print("\nA holds bigint lock; pg_locks:", a.execute(
        "SELECT classid, objid, objsubid, mode, granted FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()"
    ).fetchall())
    print("B try bigint same key:", b.execute("SELECT pg_try_advisory_xact_lock(%s::bigint)", (key,)).fetchone())
    print("B try (int,int) = (0, key) [same 64 bits, other keyspace]:", b.execute(
        "SELECT pg_try_advisory_xact_lock(0, %s::int)", (key,)).fetchone())
    print("B try (int,int) = (-1, key) [other keyspace]:", b.execute(
        "SELECT pg_try_advisory_xact_lock(-1, %s::int)", (key,)).fetchone())
    b.rollback()
    b.execute("SET lock_timeout = '300ms'")
    try_("B blocking pg_advisory_xact_lock with lock_timeout=300ms", lambda: b.execute(
        f"SELECT pg_advisory_xact_lock({KEY_SQL})", (TENANT, ASSET)).fetchone())
    b.rollback()
    b.execute("SET lock_timeout = 0"); b.commit()

    waited = {}

    def waiter():
        t0 = time.perf_counter()
        b.execute(f"SELECT pg_advisory_xact_lock({KEY_SQL})", (TENANT, ASSET))
        waited["s"] = time.perf_counter() - t0
        b.commit()

    th = threading.Thread(target=waiter); th.start()
    time.sleep(1.0)
    print("B waiting? pg_stat_activity wait_event:", a.execute(
        "SELECT wait_event_type, wait_event FROM pg_stat_activity WHERE pid=%s", (b.info.backend_pid,)).fetchone())
    a.commit()     # xact lock released at COMMIT
    th.join()
    print(f"B acquired after A's COMMIT; blocked for {waited['s']:.2f}s")
    a.execute(f"SELECT pg_advisory_xact_lock({KEY_SQL})", (TENANT, ASSET)); a.rollback()
    print("lock released on ROLLBACK too; held now:", a.execute(
        "SELECT count(*) FROM pg_locks WHERE locktype='advisory'").fetchone())
    a.rollback(); a.close(); b.close()

    print("\n-- current_time() with optional test_clock")
    with su() as s:
        s.execute("DROP SCHEMA IF EXISTS spike_app CASCADE; CREATE SCHEMA spike_app")
        s.execute("""
CREATE FUNCTION spike_app.current_time() RETURNS timestamptz LANGUAGE plpgsql STABLE
  SET search_path = spike_app, pg_temp AS $fn$
DECLARE v_off interval;
BEGIN
  IF to_regclass('spike_app.test_clock') IS NULL THEN
    RETURN clock_timestamp();
  END IF;
  SELECT offset_s INTO v_off FROM spike_app.test_clock LIMIT 1;   -- planned lazily: absent table is fine
  RETURN clock_timestamp() + coalesce(v_off, interval '0');
END $fn$""")
        try_("SQL-language variant referencing absent test_clock", lambda: s.execute(
            "CREATE FUNCTION spike_app.current_time_sql() RETURNS timestamptz LANGUAGE sql STABLE AS "
            "$$ SELECT clock_timestamp() + coalesce((SELECT offset_s FROM spike_app.test_clock LIMIT 1), '0') $$"))
        try_("qualified spike_app.current_time()", lambda: s.execute(
            "SELECT spike_app.current_time()").fetchone())
        s.execute("SET search_path = spike_app, public")
        try_("unqualified current_time() with search_path=spike_app", lambda: s.execute(
            "SELECT current_time()").fetchone())
        s.execute("RESET search_path")
        s.execute("SET search_path = spike_app, public")
        try_("unqualified current_time (keyword, no parens)", lambda: s.execute(
            "SELECT current_time").fetchone())
        s.execute("RESET search_path")
        s.execute("SET search_path = spike_app, public")
        try_('quoted "current_time"() unqualified', lambda: s.execute(
            'SELECT "current_time"()').fetchone())
        s.execute("RESET search_path")
        s.execute("CREATE TABLE spike_app.test_clock (offset_s interval NOT NULL); "
                  "INSERT INTO spike_app.test_clock VALUES (interval '3 days')")
        print("with test_clock(+3 days): now()=%s current_time()=%s" % s.execute(
            "SELECT now(), spike_app.current_time()").fetchone())
        s.execute("DROP TABLE spike_app.test_clock")
        print("after DROP test_clock (same session, cached plan?):", s.execute(
            "SELECT spike_app.current_time() - clock_timestamp() < interval '1 second'").fetchone())

    print("\n-- clock_timestamp() vs now() inside one transaction")
    with su(autocommit=False) as t:
        r1 = t.execute("SELECT now(), clock_timestamp(), statement_timestamp()").fetchone()
        time.sleep(0.5)
        r2 = t.execute("SELECT now(), clock_timestamp(), statement_timestamp()").fetchone()
        print("now() constant:", r1[0] == r2[0], "| clock_timestamp advanced:",
              (r2[1] - r1[1]).total_seconds(), "| statement_timestamp advanced:", (r2[2] - r1[2]).total_seconds())
        rows = t.execute("SELECT spike_app.current_time() FROM generate_series(1,3)").fetchall()
        print("STABLE current_time() per row within one statement distinct values:", len({r[0] for r in rows}))
        t.rollback()
    with su() as s:
        s.execute("DROP SCHEMA spike_app CASCADE")


if __name__ == "__main__":
    main()
```

Output (complete):

```text
hashtext type/value: ('integer', 623534473)
hashtextextended(...,0) (bigint): (-3000562253710073463,)
signatures: [('pg_advisory_xact_lock(bigint)',), ('pg_advisory_xact_lock(integer,integer)',)]

A holds bigint lock; pg_locks: [(0, 623534473, 1, 'ExclusiveLock', True)]
B try bigint same key: (False,)
B try (int,int) = (0, key) [same 64 bits, other keyspace]: (True,)
B try (int,int) = (-1, key) [other keyspace]: (True,)
B blocking pg_advisory_xact_lock with lock_timeout=300ms: LockNotAvailable sqlstate=55P03 primary='canceling statement due to lock timeout'
B waiting? pg_stat_activity wait_event: ('Lock', 'advisory')
B acquired after A's COMMIT; blocked for 1.00s
lock released on ROLLBACK too; held now: (0,)

-- current_time() with optional test_clock
SQL-language variant referencing absent test_clock: UndefinedTable sqlstate=42P01 primary='relation "spike_app.test_clock" does not exist'
qualified spike_app.current_time(): OK -> (datetime.datetime(2026, 10, 8, 16, 23, 38, 867673, tzinfo=zoneinfo.ZoneInfo(key='Etc/UTC')),)
unqualified current_time() with search_path=spike_app: SyntaxError sqlstate=42601 primary='syntax error at or near ")"'
unqualified current_time (keyword, no parens): OK -> (datetime.time(16, 23, 38, 876533, tzinfo=datetime.timezone.utc),)
quoted "current_time"() unqualified: OK -> (datetime.datetime(2026, 10, 8, 16, 23, 38, 878291, tzinfo=zoneinfo.ZoneInfo(key='Etc/UTC')),)
with test_clock(+3 days): now()=2026-10-08 16:23:38.881710+00:00 current_time()=2026-10-11 16:23:38.882012+00:00
after DROP test_clock (same session, cached plan?): (True,)

-- clock_timestamp() vs now() inside one transaction
now() constant: True | clock_timestamp advanced: 0.501343 | statement_timestamp advanced: 0.50147
STABLE current_time() per row within one statement distinct values: 3
```

Findings:

- **Signatures:** `pg_advisory_xact_lock(bigint)` and `pg_advisory_xact_lock(integer, integer)`. `hashtext(text)` returns **integer**, so `pg_advisory_xact_lock(hashtext(tenant_id::text || asset_id))` resolves to the **bigint** form (`pg_locks`: `classid=0, objid=<hash>, objsubid=1`). The two-int form is a **separate keyspace** (`objsubid=2`): `(0, key)` and `(-1, key)` were both acquired while the bigint lock on `key` was held. Every caller must use the same form. `hashtextextended(text, 0)` returns a full 64-bit key (fewer collisions than the 32-bit `hashtext`). Choose one and use it everywhere.
- **Blocking:** session B's `pg_try_advisory_xact_lock` returned `false`. A blocking call with `lock_timeout = '300ms'` gave `LockNotAvailable 55P03 'canceling statement due to lock timeout'`. Without a timeout, B waited (`pg_stat_activity` shows `Lock / advisory`) and got the lock 1.00 s later, at A's COMMIT. Xact locks are also released at ROLLBACK.
- **`current_time()` function.** The PL/pgSQL version, `to_regclass('spike_app.test_clock')` followed by the static `SELECT ... FROM spike_app.test_clock`, works whether the table is absent or present, because PL/pgSQL plans statements lazily. With `test_clock = 3 days` it returned now()+3 days. After `DROP TABLE` it went back to the real clock in the same session. A **`LANGUAGE sql` variant fails at CREATE** (`42P01 relation ... does not exist`, because the body is checked when `check_function_bodies` is on), so the function must be PL/pgSQL (or use dynamic SQL).
- **Name clash (gotcha).** `current_time` is a reserved SQL keyword. `spike_app.current_time()` (qualified) works. Unqualified `current_time()` with `search_path` set is a **syntax error**. Unqualified `current_time` **silently returns the SQL `CURRENT_TIME`** (a `time with time zone`, not the app clock). `"current_time"()` (quoted) resolves to the function. Every caller, policy, default and job query has to write `app.current_time()`; consider a non-keyword name (for example `app.now_effective()`).
- **`clock_timestamp()` vs `now()`:** in one transaction, `now()` is constant, while `clock_timestamp()` and `statement_timestamp()` advanced 0.50 s across a 0.5 s sleep. The function is labelled `STABLE` but calls the volatile `clock_timestamp()`. It returned 3 distinct values over 3 rows of one statement, so `STABLE` gives no "one value per statement" guarantee. If a single query needs one consistent time, compute it once (a CTE or a parameter).

## 6. Destination (T10) mechanics on database `incident`

`ops` created schema `spike_incident` in database `incident` and granted `USAGE` and `SELECT, INSERT, UPDATE` to the existing role `incident`. The races ran **as role `incident`** (password read from `postgres_incident_password`, never printed). Script `m6_destination.py`:

```python
"""M6: destination (T10) mechanics on database `incident`, scratch schema spike_incident, as role `incident`:
create (ON CONFLICT DO NOTHING RETURNING) vs abort tombstone (ON CONFLICT DO UPDATE ... WHERE state='INTENT'),
a freeze trigger, trigger firing under ON CONFLICT, and an asyncio.gather race with two AsyncConnections."""
import asyncio
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import psycopg
from common import _secrets_dir, su, try_

KW = dict(host="127.0.0.1", port=15432, dbname="incident", user="incident",
          password=(_secrets_dir() / "postgres_incident_password").read_text(encoding="utf-8").strip())

DDL = """
DROP SCHEMA IF EXISTS spike_incident CASCADE;
CREATE SCHEMA spike_incident;
CREATE TABLE spike_incident.actions (action_id text PRIMARY KEY, state text NOT NULL, payload text,
                                     updated_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE spike_incident.fired (seq bigint GENERATED ALWAYS AS IDENTITY, trg text, action_id text);
CREATE FUNCTION spike_incident.freeze_state() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO spike_incident.fired (trg, action_id) VALUES (TG_NAME, NEW.action_id);
  IF OLD.state IS DISTINCT FROM NEW.state AND OLD.state <> 'INTENT' THEN
    RAISE EXCEPTION 'state is frozen at %', OLD.state USING ERRCODE = 'OC010';
  END IF;
  RETURN NEW;
END $$;
CREATE FUNCTION spike_incident.note_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO spike_incident.fired (trg, action_id) VALUES (TG_NAME, NEW.action_id);
  RETURN NEW;
END $$;
CREATE TRIGGER actions_freeze BEFORE UPDATE ON spike_incident.actions FOR EACH ROW EXECUTE FUNCTION spike_incident.freeze_state();
CREATE TRIGGER actions_bi BEFORE INSERT ON spike_incident.actions FOR EACH ROW EXECUTE FUNCTION spike_incident.note_insert();
GRANT USAGE ON SCHEMA spike_incident TO incident;
GRANT SELECT, INSERT, UPDATE ON spike_incident.actions TO incident;
GRANT INSERT ON spike_incident.fired TO incident;
"""

CREATE = ("INSERT INTO spike_incident.actions (action_id, state, payload) VALUES (%s, 'CREATED', 'p') "
          "ON CONFLICT (action_id) DO NOTHING RETURNING action_id, state")
ABORT = ("INSERT INTO spike_incident.actions AS a (action_id, state) VALUES (%s, 'ABORTED') "
         "ON CONFLICT (action_id) DO UPDATE SET state = 'ABORTED', updated_at = clock_timestamp() "
         "WHERE a.state = 'INTENT' RETURNING action_id, state")
READ = "SELECT state FROM spike_incident.actions WHERE action_id = %s"


def conn():
    return psycopg.connect(**KW)


def race(label, first_sql, second_sql, first_ends="commit", key=None, pre=None):
    """Session A runs first_sql and holds its transaction ~0.6s; B runs second_sql meanwhile (blocks)."""
    key = key or f"k-{uuid.uuid4().hex[:8]}"
    if pre:
        with conn() as c:
            c.execute(pre, (key,)); c.commit()
    a, b = conn(), conn()
    ra = a.execute(first_sql, (key,)).fetchall()
    out = {}

    def run_b():
        t0 = time.perf_counter()
        out["rows"] = b.execute(second_sql, (key,)).fetchall()
        out["t"] = time.perf_counter() - t0
        out["after"] = b.execute(READ, (key,)).fetchall()
        b.commit()

    th = threading.Thread(target=run_b); th.start()
    time.sleep(0.6)
    getattr(a, first_ends)()
    th.join()
    final = a.execute(READ, (key,)).fetchall(); a.commit()
    print(f"{label}\n   A rows={ra} ({first_ends})  B rows={out['rows']} blocked {out['t']:.2f}s  "
          f"B re-read={out['after']}  final={final}")
    a.close(); b.close()


async def async_race(n=20):
    ok = bad = 0
    tally = {}
    async with await psycopg.AsyncConnection.connect(**KW) as c1, await psycopg.AsyncConnection.connect(**KW) as c2:
        for i in range(n):
            key = f"ar-{i}-{uuid.uuid4().hex[:6]}"

            async def create():
                cur = await c1.execute(CREATE, (key,)); rows = await cur.fetchall(); await c1.commit(); return rows

            async def abort():
                cur = await c2.execute(ABORT, (key,)); rows = await cur.fetchall(); await c2.commit(); return rows

            cr, ab = await asyncio.gather(create(), abort())
            cur = await c1.execute(READ, (key,)); final = (await cur.fetchone())[0]; await c1.commit()
            outcome = ("create" if cr else "-") + "/" + ("abort" if ab else "-") + "->" + final
            tally[outcome] = tally.get(outcome, 0) + 1
            # invariant: exactly one writer reports success, and the final state names that writer
            if bool(cr) != bool(ab) and (final == "CREATED") == bool(cr):
                ok += 1
            else:
                bad += 1
    print(f"asyncio.gather race x{n}: tally={tally} invariant_ok={ok} violations={bad}")


def main():
    with su("incident") as s:
        s.execute(DDL)
    print("-- two sessions, READ COMMITTED (default):",
          conn().execute("SHOW transaction_isolation").fetchone()[0])
    race("1. create first (uncommitted), abort second", CREATE, ABORT)
    race("2. abort first (uncommitted tombstone), create second", ABORT, CREATE)
    race("3. abort first then ROLLBACK, create second", ABORT, CREATE, first_ends="rollback")
    race("4. two creates", CREATE, CREATE)
    race("5. row pre-exists as INTENT: abort first, create second", ABORT, CREATE,
         pre="INSERT INTO spike_incident.actions (action_id, state) VALUES (%s, 'INTENT')")
    race("6. row pre-exists as INTENT: creator promotes INTENT->CREATED first, abort second",
         "UPDATE spike_incident.actions SET state='CREATED' WHERE action_id=%s AND state='INTENT' RETURNING state",
         ABORT, pre="INSERT INTO spike_incident.actions (action_id, state) VALUES (%s, 'INTENT')")

    print("\n-- freeze trigger")
    with conn() as c:
        c.execute("INSERT INTO spike_incident.actions (action_id, state) VALUES ('fz', 'CREATED')"); c.commit()
        try_("UPDATE CREATED -> ABORTED", lambda: c.execute(
            "UPDATE spike_incident.actions SET state='ABORTED' WHERE action_id='fz'").rowcount)
        c.rollback()
        try_("UPDATE payload only (state unchanged)", lambda: c.execute(
            "UPDATE spike_incident.actions SET payload='q' WHERE action_id='fz'").rowcount)
        c.rollback()
        try_("ON CONFLICT DO UPDATE SET state='ABORTED' (no WHERE) on CREATED row", lambda: c.execute(
            "INSERT INTO spike_incident.actions (action_id, state) VALUES ('fz','ABORTED') "
            "ON CONFLICT (action_id) DO UPDATE SET state='ABORTED'").rowcount)
        c.rollback()
    with su("incident") as s:
        s.execute("TRUNCATE spike_incident.fired")
    with conn() as c:
        c.execute(CREATE, ("fz",)).fetchall()                       # conflict -> DO NOTHING
        c.execute(ABORT, ("fz",)).fetchall()                        # conflict -> WHERE false -> no update
        c.commit()
    with su("incident") as s:
        print("triggers fired for a DO NOTHING replay + a WHERE-false DO UPDATE on existing 'fz':",
              s.execute("SELECT trg, action_id FROM spike_incident.fired ORDER BY seq").fetchall())
        try_("CHECK constraint referencing OLD (not possible)", lambda: s.execute(
            "ALTER TABLE spike_incident.actions ADD CHECK (OLD.state IS NULL)"))

    print("\n-- psycopg async")
    if sys.platform == "win32":
        try:
            asyncio.run(async_race(1))
        except psycopg.InterfaceError as e:
            print("default ProactorEventLoop on Windows:", type(e).__name__, str(e)[:120])
    asyncio.run(async_race(20), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    main()
```

Output (complete):

```text
-- two sessions, READ COMMITTED (default): read committed
1. create first (uncommitted), abort second
   A rows=[('k-6e1e922a', 'CREATED')] (commit)  B rows=[] blocked 0.60s  B re-read=[('CREATED',)]  final=[('CREATED',)]
2. abort first (uncommitted tombstone), create second
   A rows=[('k-3433bb4b', 'ABORTED')] (commit)  B rows=[] blocked 0.60s  B re-read=[('ABORTED',)]  final=[('ABORTED',)]
3. abort first then ROLLBACK, create second
   A rows=[('k-ac41503a', 'ABORTED')] (rollback)  B rows=[('k-ac41503a', 'CREATED')] blocked 0.60s  B re-read=[('CREATED',)]  final=[('CREATED',)]
4. two creates
   A rows=[('k-92fe3624', 'CREATED')] (commit)  B rows=[] blocked 0.60s  B re-read=[('CREATED',)]  final=[('CREATED',)]
5. row pre-exists as INTENT: abort first, create second
   A rows=[('k-9ff79c49', 'ABORTED')] (commit)  B rows=[] blocked 0.60s  B re-read=[('ABORTED',)]  final=[('ABORTED',)]
6. row pre-exists as INTENT: creator promotes INTENT->CREATED first, abort second
   A rows=[('CREATED',)] (commit)  B rows=[] blocked 0.60s  B re-read=[('CREATED',)]  final=[('CREATED',)]

-- freeze trigger
UPDATE CREATED -> ABORTED: DatabaseError sqlstate=OC010 primary='state is frozen at CREATED'
UPDATE payload only (state unchanged): OK -> 1
ON CONFLICT DO UPDATE SET state='ABORTED' (no WHERE) on CREATED row: DatabaseError sqlstate=OC010 primary='state is frozen at CREATED'
triggers fired for a DO NOTHING replay + a WHERE-false DO UPDATE on existing 'fz': [('actions_bi', 'fz'), ('actions_bi', 'fz')]
CHECK constraint referencing OLD (not possible): UndefinedTable sqlstate=42P01 primary='missing FROM-clause entry for table "old"'

-- psycopg async
default ProactorEventLoop on Windows: InterfaceError Psycopg cannot use the 'ProactorEventLoop' to run in async mode. Please use a compatible event loop, for instance by run
asyncio.gather race x20: tally={'create/-->CREATED': 11, '-/abort->ABORTED': 9} invariant_ok=20 violations=0
```

Findings (READ COMMITTED, the default):

- **Create first, abort second:** the abort `INSERT ... ON CONFLICT DO UPDATE ... WHERE a.state='INTENT'` **blocks** on A's uncommitted row (0.60 s, until A commits). It then re-checks its WHERE against the committed `CREATED` row and updates nothing, so `RETURNING` is empty. Its next statement sees `CREATED`.
- **Abort first, create second:** the create `ON CONFLICT DO NOTHING RETURNING` blocks, then returns **no row**, and a follow-up `SELECT` in B sees `ABORTED`. **Abort, then ROLLBACK:** the blocked create proceeds and returns its row (`CREATED`). **Two creates:** the second blocks and returns no row, and its re-read sees the first. A pre-existing `INTENT` row: whichever of abort and promote-to-`CREATED` commits first wins, and the other matches nothing (0 rows). In all six orderings exactly one writer reported a row, and the final state named that writer.
- **asyncio:** two `psycopg.AsyncConnection`s x `asyncio.gather(create, abort)` x 20 runs gave 11 creates won and 9 aborts won, with **0 invariant violations**. **On Windows the default ProactorEventLoop is refused** (`InterfaceError: Psycopg cannot use the 'ProactorEventLoop'...`). Use `asyncio.run(..., loop_factory=asyncio.SelectorEventLoop)`, the same finding as Plan D's spike.
- **Freeze trigger** (`BEFORE UPDATE`, raising `OC010` when `OLD.state <> 'INTENT'` and the state changes): `CREATED -> ABORTED` is rejected with `OC010 'state is frozen at CREATED'`, a payload-only update passes, and an `ON CONFLICT DO UPDATE SET state='ABORTED'` with **no** WHERE fires the BEFORE UPDATE trigger and is rejected the same way. The literal rule "raise when `OLD.state IS NOT NULL`" would also block the legitimate `INTENT -> ABORTED` tombstone, so the trigger has to exempt `INTENT` (as here). A `CHECK` cannot reference `OLD` (`missing FROM-clause entry for table "old"`), so a trigger is the only way.
- **Trigger firing under ON CONFLICT (gotcha).** A replayed create (`DO NOTHING`) and a no-op abort (`DO UPDATE ... WHERE` false) on an existing row both **fired the BEFORE INSERT trigger** (`fired` has 2 `actions_bi` rows), and the BEFORE UPDATE trigger did not fire. A side effect in a BEFORE INSERT trigger (an audit row, a counter) therefore also runs for idempotent replays. Put such effects in AFTER triggers or in the statement's `RETURNING` path.

## Cross-cutting gotchas (most consequential first)

1. **`current_setting('app.tenant_id', true)::uuid` raises 22P02 on `''`.** `''` is what every reused connection holds after its first `set_config(..., true)` (commit *or* rollback), and what every definer function with `SET app.tenant_id = ''` sees. Write the policy, and every in-function check, with `NULLIF(..., '')::uuid` (or compare as text).
2. **`command.upgrade(cfg, "head")` in `scripts/skeleton.py` breaks as soon as a `testclock` branch adds a second head.** Change it to an explicit target per profile. The skeleton's `split(";\n")` cannot carry PL/pgSQL bodies either.
3. **Unqualified `current_time` is the SQL keyword, not the app function.** It returns `timetz` with no error. Always schema-qualify, or rename the function.
4. FORCE RLS filters the table owner's own backfills. A BYPASSRLS owner of a SECURITY DEFINER function unfilters it for every caller.
5. A column-level UPDATE grant needs SELECT on the columns it reads. `ON CONFLICT (target)` and `RETURNING` need SELECT. An insert-only role can use only target-less `ON CONFLICT DO NOTHING`.
6. A non-superuser migrator needs SET membership in the definer role and the definer role needs CREATE on the schema before `ALTER FUNCTION ... OWNER TO`.
7. Custom SQLSTATEs arrive as the class-mapped psycopg exception (unknown class -> `DatabaseError`). Map on `exc.sqlstate`.
8. BEFORE INSERT triggers fire on ON CONFLICT replays, and asyncio on Windows needs `SelectorEventLoop`.
9. The two advisory-lock signatures never block each other. Pick one key function (`hashtext` -> bigint, or `hashtextextended`) and use it everywhere.

## Cleanup proof

Script `cleanup.py`. It drops every `spike_*` schema in both databases, runs `DROP OWNED BY` for all spike roles in both databases, then `DROP ROLE`, and queries the catalogs:

```python
"""Drop every spike_ schema and role (DROP OWNED BY in each database, then DROP ROLE) and prove it from the catalogs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import su

ROLES_Q = "SELECT rolname FROM pg_roles WHERE rolname LIKE 'spike\\_%' ORDER BY 1"


def main():
    with su() as s:
        roles = [r[0] for r in s.execute(ROLES_Q).fetchall()]
    print("spike roles before:", roles)
    for db in ("ops", "incident"):
        with su(db) as s:
            for (n,) in s.execute("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'spike\\_%'").fetchall():
                s.execute(f'DROP SCHEMA "{n}" CASCADE'); print(f"dropped schema {db}.{n}")
            if roles:
                s.execute("DROP OWNED BY " + ", ".join(f'"{r}"' for r in roles))
                print(f"DROP OWNED BY {roles} in {db}")
    with su() as s:
        for r in roles:
            s.execute(f'DROP ROLE "{r}"')
        print("\n== Cleanup proof ==")
        print("pg_roles LIKE 'spike_%':", s.execute(ROLES_Q).fetchall())
        print("pg_shdepend rows for missing roles:", s.execute(
            "SELECT count(*) FROM pg_shdepend WHERE refclassid='pg_authid'::regclass "
            "AND refobjid NOT IN (SELECT oid FROM pg_authid)").fetchone()[0])
        print("pg_database datacl:", s.execute(
            "SELECT datname, datacl FROM pg_database WHERE datname IN ('ops','incident') ORDER BY 1").fetchall())
    for db in ("ops", "incident"):
        with su(db) as s:
            print(f"[{db}] spike schemas:", s.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'spike%'").fetchall(),
                  "| spike procs:", s.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                                             "WHERE nspname LIKE 'spike%'").fetchone()[0],
                  "| alembic_version tables:", s.execute(
                    "SELECT table_schema FROM information_schema.tables WHERE table_name='alembic_version'").fetchall())
    with su() as s:
        print("[ops] app schema intact, alembic head:", s.execute(
            "SELECT version_num FROM public.alembic_version").fetchall(),
              "| app tables:", s.execute("SELECT count(*) FROM pg_tables WHERE schemaname='app'").fetchone()[0])


if __name__ == "__main__":
    main()
```

Output (complete):

```text
spike roles before: ['spike_api', 'spike_definer', 'spike_member', 'spike_migrator', 'spike_sweeper']
DROP OWNED BY ['spike_api', 'spike_definer', 'spike_member', 'spike_migrator', 'spike_sweeper'] in ops
dropped schema incident.spike_incident
DROP OWNED BY ['spike_api', 'spike_definer', 'spike_member', 'spike_migrator', 'spike_sweeper'] in incident

== Cleanup proof ==
pg_roles LIKE 'spike_%': []
pg_shdepend rows for missing roles: 0
pg_database datacl: [('incident', ['=Tc/ops', 'ops=CTc/ops', 'incident=c/ops']), ('ops', None)]
[ops] spike schemas: [] | spike procs: 0 | alembic_version tables: [('public',)]
[incident] spike schemas: [] | spike procs: 0 | alembic_version tables: [('public',)]
[ops] app schema intact, alembic head: [('0001_walking_skeleton',)] | app tables: 15
```

`spike_app` had already been dropped by measurement 5 and `spike_alembic` by measurement 4's final reset. `git status --short` in `<repo>` printed nothing.
