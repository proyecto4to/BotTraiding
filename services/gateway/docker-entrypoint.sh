#!/bin/sh
set -e

# Applies the Alembic schema to whatever Postgres DATABASE_URL points at
# before the API starts serving traffic. Idempotent: alembic upgrade head
# is a no-op if the schema is already current. Uses the gateway-specific
# version table (alembic_version_gateway) so it coexists with other
# services migrating the same database.
echo "[gateway] running alembic upgrade head..."
alembic upgrade head

exec "$@"
