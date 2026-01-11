#!/bin/bash
set -e

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting migration process...${NC}"

# Function to check database connection
wait_for_db() {
    echo -e "${YELLOW}Waiting for database connection...${NC}"
    python -c "
import sys
import os
import time
import socket
from urllib.parse import urlparse

# Gets host and port from DATABASE_URL if available
db_url = os.getenv('DATABASE_URL')
host = None
port = 5432

if db_url:
    try:
        if db_url.startswith('postgres://'):
             db_url = db_url.replace('postgres://', 'postgresql://', 1)
        result = urlparse(db_url)
        host = result.hostname
        if result.port:
            port = result.port
    except Exception:
        pass

if not host:
    host = os.getenv('POSTGRES_HOST', 'postgres')
    port = int(os.getenv('POSTGRES_PORT', 5432))

retries = 60

print(f'Attempting to connect to {host}:{port}...')

for i in range(retries):
    try:
        # socket.create_connection handles DNS resolution (IPv4/IPv6) automatically
        s = socket.create_connection((host, port), timeout=1)
        s.close()
        print('Database connection successful!')
        sys.exit(0)
    except Exception as e:
        print(f'Waiting for database... ({i+1}/{retries})')
        time.sleep(2)

print('Could not connect to database.')
sys.exit(1)
"
}

# Wait for DB to be ready
wait_for_db

# Check if we are in development environment
ENVIRONMENT=${ENVIRONMENT:-development}

if [ "$ENVIRONMENT" = "development" ]; then
    echo -e "${YELLOW}Development environment detected. Checking for schema changes...${NC}"
    # Try to generate a migration. If no changes, alembic/env.py will prevent file creation.
    # We use a timestamp in the message to avoid collisions if multiple devs run it (though collisions are still possible)
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    python -m alembic revision --autogenerate -m "auto_generated_${TIMESTAMP}" || true
fi

echo -e "${GREEN}Database is ready. Running Alembic migrations...${NC}"

# Run migrations
# Using python -m alembic to ensure it runs in the python context
python -m alembic upgrade head

echo -e "${GREEN}Migrations completed successfully!${NC}"
