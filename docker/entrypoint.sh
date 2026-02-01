#!/usr/bin/env sh
set -e

# Wait a bit just in case (db healthcheck already used)

# Run alembic migrations
python -m app.migrate
# Start bot
python -m app
