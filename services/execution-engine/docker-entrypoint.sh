#!/bin/sh
set -e

# Applies the Alembic schema to whatever Postgres DATABASE_URL points at
# before the API starts serving traffic. Idempotent: alembic upgrade head
# is a no-op if the schema is already current.
echo "[execution-engine] running alembic upgrade head..."
alembic upgrade head

exec "$@"
