#!/bin/bash
# =============================================================================
# Arrotech Hub — Production Deployment Script
# =============================================================================
# Deploys the latest code from the main branch to the EC2 server.
# Can be run manually or triggered by GitHub Actions via SSH.
#
# Usage:
#   ./scripts/deploy.sh              # Full deploy (pull + build + restart)
#   ./scripts/deploy.sh --quick      # Quick deploy (pull + restart, no rebuild)
#   ./scripts/deploy.sh --rollback   # Rollback to previous commit
# =============================================================================

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
APP_DIR="/home/ubuntu/arrotech-hub-backend"
COMPOSE_FILE="docker-compose.prod.yml"
HEALTH_URL="http://localhost:8000/health"
HEALTH_TIMEOUT=60  # seconds to wait for health check
LOG_FILE="/var/log/arrotech-deploy.log"

# ── Colors ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"; }
warn() { echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1" | tee -a "$LOG_FILE"; }
error() { echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" | tee -a "$LOG_FILE"; }

# ── Parse arguments ────────────────────────────────────────────────────────
MODE="full"
if [[ "${1:-}" == "--quick" ]]; then
    MODE="quick"
elif [[ "${1:-}" == "--rollback" ]]; then
    MODE="rollback"
fi

cd "$APP_DIR"

# ── Save current commit for rollback ────────────────────────────────────────
PREVIOUS_COMMIT=$(git rev-parse HEAD)
log "Current commit: $PREVIOUS_COMMIT"

# ── Rollback mode ──────────────────────────────────────────────────────────
if [[ "$MODE" == "rollback" ]]; then
    log "Rolling back to previous commit..."
    git checkout HEAD~1
    docker compose -f "$COMPOSE_FILE" up -d --build app celery-worker
    log "Rollback complete. Verifying health..."
    sleep 10
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        log "Rollback successful — app is healthy"
    else
        error "Rollback health check failed!"
        exit 1
    fi
    exit 0
fi

# ── Pull latest code ──────────────────────────────────────────────────────
log "Pulling latest code from main..."
git fetch origin main
git reset --hard origin/main
NEW_COMMIT=$(git rev-parse HEAD)
log "Updated to commit: $NEW_COMMIT"

if [[ "$PREVIOUS_COMMIT" == "$NEW_COMMIT" ]]; then
    warn "No new commits. Redeploying anyway..."
fi

# ── Build and restart ──────────────────────────────────────────────────────
if [[ "$MODE" == "full" ]]; then
    log "Building Docker images..."
    docker compose -f "$COMPOSE_FILE" build --no-cache app
    log "Build complete."
fi

log "Restarting services..."
docker compose -f "$COMPOSE_FILE" up -d --force-recreate app celery-worker celery-beat nginx

# ── Wait for health check ─────────────────────────────────────────────────
log "Waiting for application to become healthy..."
ELAPSED=0
while [[ $ELAPSED -lt $HEALTH_TIMEOUT ]]; do
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        log "Health check passed after ${ELAPSED}s"
        break
    fi
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

if [[ $ELAPSED -ge $HEALTH_TIMEOUT ]]; then
    error "Health check failed after ${HEALTH_TIMEOUT}s!"
    error "Rolling back to previous commit: $PREVIOUS_COMMIT"
    git checkout "$PREVIOUS_COMMIT"
    docker compose -f "$COMPOSE_FILE" up -d --build app celery-worker
    exit 1
fi

# ── Cleanup ────────────────────────────────────────────────────────────────
log "Pruning unused Docker images..."
docker image prune -f --filter "until=72h" 2>/dev/null || true

# ── Summary ────────────────────────────────────────────────────────────────
log "=========================================="
log "Deployment successful!"
log "  Commit: $NEW_COMMIT"
log "  Mode:   $MODE"
log "  Time:   $(date)"
log "=========================================="

# Show service status
docker compose -f "$COMPOSE_FILE" ps
