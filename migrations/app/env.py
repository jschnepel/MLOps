"""Alembic environment for the application database (schema `app`).

The connection is handed in by scripts/skeleton.py through `config.attributes["connection"]` (Alembic's documented
pattern for programmatic runs); the engine behind it is built from a SQLAlchemy `URL` object whose password is never
rendered into a string or logged. Offline mode is not supported: the skeleton always migrates against a live database.
"""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("migrations/app runs only through scripts/skeleton.py migrate (no URL mode)")

# The version table stays in `public`: Alembic writes it before revision 0001 runs `CREATE SCHEMA app`.
context.configure(connection=connection, target_metadata=None, version_table="alembic_version")
with context.begin_transaction():
    context.run_migrations()
