#!/usr/bin/env sh
set -e

# Wait a bit just in case (db healthcheck already used)

# Run alembic migrations
alembic upgrade head

# Start bot
python -m app
