#!/bin/bash
if [ -z "$1" ]; then
  echo "Usage: ./scripts/generate_migration.sh \"Description of changes\""
  exit 1
fi

echo "Generating migration script for: $1"
docker-compose run --rm app python -m alembic revision --autogenerate -m "$1"
echo "Done! Migration file created in alembic/versions."