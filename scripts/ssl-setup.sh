#!/bin/bash
# =============================================================================
# Arrotech Hub — SSL Certificate Setup (Let's Encrypt)
# =============================================================================
# Run this ONCE after:
#   1. DNS A record for prod.api.arrotechsolutions.com points to this server
#   2. Nginx is running on port 80 (for ACME challenge)
#
# Usage:
#   sudo ./scripts/ssl-setup.sh
#   sudo ./scripts/ssl-setup.sh --staging    # Test with staging certs first
# =============================================================================

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
DOMAIN="prod.api.arrotechsolutions.com"
EMAIL="admin@arrotechsolutions.com"
WEBROOT="/var/www/certbot"
COMPOSE_DIR="/home/ubuntu/arrotech-hub-backend"
COMPOSE_FILE="docker-compose.prod.yml"

# ── Colors ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ── Parse arguments ────────────────────────────────────────────────────────
STAGING_FLAG=""
if [[ "${1:-}" == "--staging" ]]; then
    STAGING_FLAG="--staging"
    echo -e "${YELLOW}Using Let's Encrypt STAGING environment (test certificates)${NC}"
fi

# ── Pre-flight checks ──────────────────────────────────────────────────────
echo -e "${YELLOW}Pre-flight checks...${NC}"

# Check if certbot is installed
if ! command -v certbot &> /dev/null; then
    echo -e "${YELLOW}Installing certbot...${NC}"
    apt-get update && apt-get install -y certbot
fi

# Check if domain resolves to this server
SERVER_IP=$(curl -s ifconfig.me)
DNS_IP=$(dig +short "$DOMAIN" | head -1)

echo "  Server IP: $SERVER_IP"
echo "  DNS resolves to: ${DNS_IP:-NOT FOUND}"

if [[ "$DNS_IP" != "$SERVER_IP" ]]; then
    echo -e "${RED}ERROR: $DOMAIN does not resolve to this server ($SERVER_IP)${NC}"
    echo -e "${RED}Please update DNS A record and wait for propagation.${NC}"
    exit 1
fi

# ── Create webroot directory ───────────────────────────────────────────────
mkdir -p "$WEBROOT"

# ── Ensure Nginx is running (HTTP only for ACME challenge) ──────────────────
echo -e "${YELLOW}Ensuring Nginx is running for ACME challenge...${NC}"

# If SSL certs don't exist yet, we need a temporary Nginx config without SSL
if [[ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
    echo -e "${YELLOW}Creating temporary HTTP-only Nginx config for initial cert issuance...${NC}"

    # Create a minimal temp config
    cat > /tmp/nginx-temp.conf << 'TEMPCONF'
events { worker_connections 1024; }
http {
    server {
        listen 80;
        server_name _;

        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }

        location /health-nginx {
            return 200 'ok';
            add_header Content-Type text/plain;
        }

        location / {
            return 200 'Arrotech Hub - SSL setup in progress';
            add_header Content-Type text/plain;
        }
    }
}
TEMPCONF

    # Start a temporary Nginx container for the ACME challenge
    docker run -d --name nginx-acme-temp \
        -p 80:80 \
        -v /tmp/nginx-temp.conf:/etc/nginx/nginx.conf:ro \
        -v "$WEBROOT:/var/www/certbot" \
        nginx:alpine

    echo -e "${GREEN}Temporary Nginx started for ACME challenge${NC}"
fi

# ── Request certificate ───────────────────────────────────────────────────
echo -e "${YELLOW}Requesting SSL certificate for ${DOMAIN}...${NC}"

certbot certonly --webroot \
    -w "$WEBROOT" \
    -d "$DOMAIN" \
    --non-interactive \
    --agree-tos \
    -m "$EMAIL" \
    $STAGING_FLAG

# ── Cleanup temporary Nginx ───────────────────────────────────────────────
if docker ps -q -f name=nginx-acme-temp &> /dev/null; then
    docker stop nginx-acme-temp && docker rm nginx-acme-temp
    echo -e "${GREEN}Temporary Nginx removed${NC}"
fi
rm -f /tmp/nginx-temp.conf

# ── Verify certificate ───────────────────────────────────────────────────
echo -e "${YELLOW}Verifying certificate...${NC}"
if [[ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
    echo -e "${GREEN}Certificate installed successfully!${NC}"
    openssl x509 -in "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" -noout -dates
else
    echo -e "${RED}Certificate not found! Check certbot output above.${NC}"
    exit 1
fi

# ── Start full production stack ────────────────────────────────────────────
echo -e "${YELLOW}Starting production stack with SSL...${NC}"
cd "$COMPOSE_DIR"
docker compose -f "$COMPOSE_FILE" up -d

# ── Setup auto-renewal ────────────────────────────────────────────────────
echo -e "${YELLOW}Setting up auto-renewal cron...${NC}"

# Add renewal cron if not already present
CRON_CMD="0 12 * * * certbot renew --quiet --post-hook 'docker compose -f $COMPOSE_DIR/$COMPOSE_FILE restart nginx'"
(crontab -l 2>/dev/null | grep -v "certbot renew" || true; echo "$CRON_CMD") | crontab -

# Test renewal
echo -e "${YELLOW}Testing certificate renewal (dry run)...${NC}"
certbot renew --dry-run

echo ""
echo -e "${GREEN}=========================================="
echo -e "  SSL Setup Complete!"
echo -e "=========================================="
echo -e "  Domain:       https://${DOMAIN}"
echo -e "  Certificate:  /etc/letsencrypt/live/${DOMAIN}/"
echo -e "  Auto-renewal: Cron job added (daily at noon)"
echo -e "==========================================${NC}"
