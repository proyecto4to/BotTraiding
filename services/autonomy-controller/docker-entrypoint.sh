#!/bin/sh
set -e

echo "[autonomy-controller] running alembic upgrade head..."
alembic upgrade head

exec "$@"
