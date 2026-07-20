#!/bin/bash
# =============================================================================
# Arrotech Hub — Lightweight Resource Monitor
# =============================================================================
# Checks disk, memory, and Docker container health.
# Sends alerts via email if thresholds are exceeded.
#
# Cron setup (every 5 minutes):
#   */5 * * * * /home/ubuntu/arrotech-hub-backend/scripts/check-resources.sh >> /var/log/arrotech-monitor.log 2>&1
# =============================================================================

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
DISK_THRESHOLD=85       # Alert if disk usage exceeds this %
MEMORY_THRESHOLD=90     # Alert if memory usage exceeds this %
COMPOSE_FILE="/home/ubuntu/arrotech-hub-backend/docker-compose.prod.yml"
ALERT_EMAIL="admin@arrotechsolutions.com"

# Alert cooldown: don't send more than 1 alert per hour
ALERT_LOCK="/tmp/arrotech-resource-alert.lock"
ALERT_COOLDOWN=3600  # seconds

# ── Colors (for interactive use) ────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

ALERTS=""

# ── Check Disk Usage ──────────────────────────────────────────────────────
DISK_USAGE=$(df / | awk 'NR==2 {print $5}' | tr -d '%')
if [[ "$DISK_USAGE" -ge "$DISK_THRESHOLD" ]]; then
    ALERTS+="⚠️ DISK: ${DISK_USAGE}% used (threshold: ${DISK_THRESHOLD}%)\n"
    echo -e "${RED}[$(date)] ALERT: Disk usage at ${DISK_USAGE}%${NC}"

    # Auto-cleanup: remove old Docker images and logs
    docker image prune -f --filter "until=48h" 2>/dev/null || true
    docker system prune -f --filter "until=48h" 2>/dev/null || true
    journalctl --vacuum-time=3d 2>/dev/null || true
fi

# ── Check Memory Usage ───────────────────────────────────────────────────
MEMORY_USAGE=$(free | awk '/Mem:/ {printf "%.0f", $3/$2 * 100}')
if [[ "$MEMORY_USAGE" -ge "$MEMORY_THRESHOLD" ]]; then
    ALERTS+="⚠️ MEMORY: ${MEMORY_USAGE}% used (threshold: ${MEMORY_THRESHOLD}%)\n"
    echo -e "${RED}[$(date)] ALERT: Memory usage at ${MEMORY_USAGE}%${NC}"
fi

# ── Check Docker Container Health ────────────────────────────────────────
UNHEALTHY=$(docker ps --filter "health=unhealthy" --format "{{.Names}}" 2>/dev/null || true)
if [[ -n "$UNHEALTHY" ]]; then
    ALERTS+="⚠️ UNHEALTHY CONTAINERS:\n"
    while IFS= read -r container; do
        ALERTS+="  - $container\n"
        echo -e "${RED}[$(date)] ALERT: Container unhealthy: ${container}${NC}"
    done <<< "$UNHEALTHY"
fi

# ── Check if critical services are running ──────────────────────────────
REQUIRED_SERVICES=("app" "postgres" "redis" "celery-worker" "celery-beat" "nginx")
STOPPED=""
for svc in "${REQUIRED_SERVICES[@]}"; do
    # Check if service container is running
    if ! docker compose -f "$COMPOSE_FILE" ps --status running "$svc" 2>/dev/null | grep -q "$svc"; then
        STOPPED+="  - $svc\n"
    fi
done

if [[ -n "$STOPPED" ]]; then
    ALERTS+="⚠️ STOPPED SERVICES:\n${STOPPED}"
    echo -e "${RED}[$(date)] ALERT: Services not running:${NC}"
    echo -e "$STOPPED"

    # Auto-restart stopped services
    echo -e "${YELLOW}Attempting to restart stopped services...${NC}"
    docker compose -f "$COMPOSE_FILE" up -d
fi

# ── Send alert if needed ──────────────────────────────────────────────────
if [[ -n "$ALERTS" ]]; then
    # Check cooldown
    if [[ -f "$ALERT_LOCK" ]]; then
        LAST_ALERT=$(stat -c %Y "$ALERT_LOCK" 2>/dev/null || echo 0)
        NOW=$(date +%s)
        DIFF=$((NOW - LAST_ALERT))
        if [[ "$DIFF" -lt "$ALERT_COOLDOWN" ]]; then
            echo "[$(date)] Alert suppressed (cooldown: ${DIFF}s / ${ALERT_COOLDOWN}s)"
            exit 0
        fi
    fi

    # Send email alert (requires mail/sendmail configured, or use curl to a webhook)
    SUBJECT="🚨 Arrotech Hub Server Alert"
    BODY="Server Resource Alert — $(date)\n\n${ALERTS}\n\nServer: $(hostname)\nIP: $(curl -s ifconfig.me 2>/dev/null || echo 'unknown')\n\nDisk: ${DISK_USAGE}%\nMemory: ${MEMORY_USAGE}%"

    # Try sending via mail command
    if command -v mail &> /dev/null; then
        echo -e "$BODY" | mail -s "$SUBJECT" "$ALERT_EMAIL" 2>/dev/null || true
    fi

    # Log the alert
    echo -e "[$(date)] ALERTS TRIGGERED:\n$ALERTS"

    # Update cooldown lock
    touch "$ALERT_LOCK"
else
    echo "[$(date)] All systems healthy. Disk: ${DISK_USAGE}% | Memory: ${MEMORY_USAGE}%"
fi
