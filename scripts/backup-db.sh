#!/bin/bash
# =============================================================================
# Arrotech Hub — PostgreSQL Backup to S3
# =============================================================================
# Dumps the database, compresses, uploads to S3, and cleans up old local copies.
#
# Cron setup (run daily at 3 AM UTC):
#   0 3 * * * /home/ubuntu/arrotech-hub-backend/scripts/backup-db.sh >> /var/log/arrotech-backup.log 2>&1
#
# Prerequisites:
#   - AWS CLI configured with S3 write permissions
#   - S3 bucket created: aws s3 mb s3://arrotech-hub-backups
# =============================================================================

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/home/ubuntu/backups"
S3_BUCKET="s3://arrotech-hub-backups/db-backups"
COMPOSE_FILE="/home/ubuntu/arrotech-hub-backend/docker-compose.prod.yml"
DB_USER="${POSTGRES_USER:-minihub}"
DB_NAME="${POSTGRES_DB:-minihub}"
RETENTION_DAYS=7  # Local retention; S3 lifecycle handles remote

# ── Colors ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}[$(date)] Starting database backup...${NC}"

# ── Create backup directory ─────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"

# ── Dump database from Docker container ─────────────────────────────────────
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql.gz"

echo -e "${YELLOW}  Dumping ${DB_NAME}...${NC}"
docker compose -f "$COMPOSE_FILE" exec -T postgres \
    pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-privileges \
    | gzip > "$BACKUP_FILE"

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo -e "${GREEN}  Dump complete: ${BACKUP_FILE} (${BACKUP_SIZE})${NC}"

# ── Upload to S3 ───────────────────────────────────────────────────────────
echo -e "${YELLOW}  Uploading to S3...${NC}"
if aws s3 cp "$BACKUP_FILE" "$S3_BUCKET/" --quiet; then
    echo -e "${GREEN}  Upload successful: ${S3_BUCKET}/${DB_NAME}_${TIMESTAMP}.sql.gz${NC}"
else
    echo -e "${RED}  S3 upload failed! Local backup retained at: ${BACKUP_FILE}${NC}"
    exit 1
fi

# ── Cleanup old local backups ──────────────────────────────────────────────
echo -e "${YELLOW}  Cleaning up local backups older than ${RETENTION_DAYS} days...${NC}"
DELETED=$(find "$BACKUP_DIR" -name "*.sql.gz" -mtime +"$RETENTION_DAYS" -delete -print | wc -l)
echo -e "${GREEN}  Removed ${DELETED} old local backup(s)${NC}"

echo -e "${GREEN}[$(date)] Backup completed successfully!${NC}"
