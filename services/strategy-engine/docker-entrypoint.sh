#!/bin/sh
set -e

# Applies the Alembic schema to whatever Postgres DATABASE_URL points at
# before the API starts serving traffic. Idempotent: alembic upgrade head
# is a no-op if the schema is already current. Uses its own version table
# (alembic_version_strategy) so it never collides with other services.
echo "[strategy-engine] running alembic upgrade head..."
alembic upgrade head

exec "$@"
