#!/bin/sh
set -e

# Applies the Alembic schema (broker_credentials) to whatever Postgres
# DATABASE_URL points at before the API starts. Idempotent: alembic upgrade
# head is a no-op if the schema is already current. The table is only used
# when CREDENTIAL_STORE=db, but migrating unconditionally keeps startup simple.
echo "[broker-connectors] running alembic upgrade head..."
alembic upgrade head

exec "$@"
