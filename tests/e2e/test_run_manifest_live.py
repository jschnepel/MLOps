"""Revision 0014 against the per-session test database (OPS_LIVE=1; T19, R130): who may write and read a run manifest.

Catches: any role but the worker able to write a manifest, the api unable to read one, the worker able to change or
delete one (a manifest is immutable) or to write another tenant's, a second manifest for the same run, and a
manifest the schema forbids (a real route without a digest) stored. The worker's own writes on both routes are
tests/e2e/test_worker_live.py's.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

import psycopg
import pytest
from ops_core import persistence
from ops_core.routing import ModelRoute, RunManifest
from ops_core.settings import Role

from tests.e2e.conftest import purge_run
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
BETA = UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
INSERT = (
    "INSERT INTO app.run_manifests (run_id, tenant_id, model_route, model_digest, prompt_version, corpus_version,"
    " retrieval_mode) VALUES (%s, %s, %s, %s, 'incident-draft-v2', 'corpus-1', 'lexical')"
)


async def test_only_the_worker_writes_a_manifest_once_and_nobody_changes_it(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    api = await role_conn(Role.API)
    run = None
    try:
        _, _, run = await new_run(app_conn, ALPHA, api=api)
        for role in (Role.API, Role.SWEEPER, Role.MCP_READ, Role.MCP_EXEC, Role.OPERATOR):
            other = await role_conn(role)
            # The tenant is set, so a row-level refusal cannot stand in for the missing grant: only "permission
            # denied for table" passes (the message test_roles_live.py matches too).
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
                async with other.transaction():
                    await persistence.set_tenant(other, ALPHA)
                    await other.execute(INSERT, (run, ALPHA, "fake", None))
        worker = await role_conn(Role.WORKER)
        with pytest.raises(psycopg.errors.CheckViolation):  # schemas/run-manifest.schema.json: a real route's digest
            async with worker.transaction():
                await persistence.set_tenant(worker, ALPHA)
                await worker.execute(INSERT, (run, ALPHA, "qwen3:8b", None))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # RLS WITH CHECK: another tenant's row
            async with worker.transaction():
                await persistence.set_tenant(worker, ALPHA)
                await worker.execute(INSERT, (run, BETA, "fake", None))
        manifest = RunManifest(
            run_id=run,
            model_route=ModelRoute.QWEN3_8B,
            model_digest=DIGEST,
            prompt_version="incident-draft-v2",
            corpus_version="corpus-1",
            retrieval_mode="lexical",
        )
        async with worker.transaction():
            await persistence.set_tenant(worker, ALPHA)
            await persistence.insert_run_manifest(worker, tenant_id=ALPHA, manifest=manifest)
        with pytest.raises(psycopg.errors.UniqueViolation):  # one manifest per run
            async with worker.transaction():
                await persistence.set_tenant(worker, ALPHA)
                await persistence.insert_run_manifest(worker, tenant_id=ALPHA, manifest=manifest)
        for statement in ("UPDATE app.run_manifests SET model_digest = NULL", "DELETE FROM app.run_manifests"):
            assert await refused(worker, statement, ()) == "42501", statement  # immutable
        async with api.transaction():
            await persistence.set_tenant(api, ALPHA)
            cur = await api.execute("SELECT model_route, model_digest FROM app.run_manifests WHERE run_id = %s", (run,))
            assert [dict(r) for r in await cur.fetchall()] == [{"model_route": "qwen3:8b", "model_digest": DIGEST}]
        async with api.transaction():
            await persistence.set_tenant(api, BETA)
            cur = await api.execute("SELECT count(*) AS n FROM app.run_manifests WHERE run_id = %s", (run,))
            assert (await cur.fetchone() or {})["n"] == 0  # the policy: another tenant sees nothing
    finally:
        if run is not None:
            await purge_run(app_conn, run)
