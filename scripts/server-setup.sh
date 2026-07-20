#!/bin/bash
# =============================================================================
# Arrotech Hub — EC2 Server Bootstrap Script
# =============================================================================
# Run this ONCE on a fresh Ubuntu 22.04 EC2 instance.
# It installs all prerequisites for running the Arrotech Hub backend.
#
# Usage:
#   ssh -i arrotech-hub-key.pem ubuntu@<elastic-ip>
#   curl -sSL https://raw.githubusercontent.com/<org>/arrotech-hub-backend/main/scripts/server-setup.sh | bash
#   OR
#   scp scripts/server-setup.sh ubuntu@<elastic-ip>:/tmp/ && ssh ubuntu@<elastic-ip> 'bash /tmp/server-setup.sh'
# =============================================================================

set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=========================================="
echo -e "  Arrotech Hub — Server Setup"
echo -e "==========================================${NC}"

# ── 1. System Updates ──────────────────────────────────────────────────────
echo -e "${YELLOW}[1/7] Updating system packages...${NC}"
sudo apt update && sudo apt upgrade -y

# ── 2. Install Docker ─────────────────────────────────────────────────────
echo -e "${YELLOW}[2/7] Installing Docker...${NC}"
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker ubuntu
    echo -e "${GREEN}  Docker installed. You may need to log out and back in for group changes.${NC}"
else
    echo -e "${GREEN}  Docker already installed: $(docker --version)${NC}"
fi

# ── 3. Install Docker Compose Plugin ──────────────────────────────────────
echo -e "${YELLOW}[3/7] Installing Docker Compose plugin...${NC}"
if ! docker compose version &> /dev/null; then
    sudo apt install -y docker-compose-plugin
fi
echo -e "${GREEN}  Docker Compose: $(docker compose version)${NC}"

# ── 4. Install AWS CLI ────────────────────────────────────────────────────
echo -e "${YELLOW}[4/7] Installing AWS CLI...${NC}"
if ! command -v aws &> /dev/null; then
    sudo apt install -y awscli
fi
echo -e "${GREEN}  AWS CLI: $(aws --version)${NC}"

# ── 5. Install Certbot ───────────────────────────────────────────────────
echo -e "${YELLOW}[5/7] Installing Certbot (Let's Encrypt)...${NC}"
if ! command -v certbot &> /dev/null; then
    sudo apt install -y certbot
fi
echo -e "${GREEN}  Certbot: $(certbot --version 2>&1)${NC}"

# ── 6. Install utilities ─────────────────────────────────────────────────
echo -e "${YELLOW}[6/7] Installing utilities...${NC}"
sudo apt install -y \
    git \
    curl \
    htop \
    jq \
    dnsutils \
    unzip \
    fail2ban

# Configure fail2ban for SSH protection
if ! systemctl is-active --quiet fail2ban; then
    sudo systemctl enable fail2ban
    sudo systemctl start fail2ban
fi

# ── 7. Configure system limits ───────────────────────────────────────────
echo -e "${YELLOW}[7/7] Configuring system limits...${NC}"

# Increase file descriptor limits for Docker containers
if ! grep -q "fs.file-max = 65536" /etc/sysctl.conf 2>/dev/null; then
    echo "fs.file-max = 65536" | sudo tee -a /etc/sysctl.conf
    echo "vm.overcommit_memory = 1" | sudo tee -a /etc/sysctl.conf
    sudo sysctl -p
fi

# ── Create directories ───────────────────────────────────────────────────
mkdir -p /home/ubuntu/backups
mkdir -p /var/www/certbot

# ── Setup swap (2GB — important for t3.small with 2GB RAM) ──────────────
echo -e "${YELLOW}Setting up 2GB swap file...${NC}"
if [[ ! -f /swapfile ]]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo -e "${GREEN}  Swap enabled: 2GB${NC}"
else
    echo -e "${GREEN}  Swap already configured${NC}"
fi

# ── Configure log rotation for Docker ────────────────────────────────────
sudo tee /etc/docker/daemon.json > /dev/null << 'EOF'
{
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "10m",
        "max-file": "5"
    },
    "storage-driver": "overlay2"
}
EOF
sudo systemctl restart docker

# ── Summary ──────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}=========================================="
echo -e "  Server Setup Complete!"
echo -e "=========================================="
echo -e ""
echo -e "  Next steps:"
echo -e "  1. Clone your repo:"
echo -e "     git clone <repo-url> /home/ubuntu/arrotech-hub-backend"
echo -e ""
echo -e "  2. Create production env file:"
echo -e "     cp .env.production.template .env.production"
echo -e "     # Fill in all secrets"
echo -e ""
echo -e "  3. Configure AWS CLI for S3 backups:"
echo -e "     aws configure"
echo -e ""
echo -e "  4. Point DNS to this server:"
echo -e "     $(curl -s ifconfig.me 2>/dev/null || echo '<server-ip>')"
echo -e ""
echo -e "  5. Run SSL setup:"
echo -e "     sudo ./scripts/ssl-setup.sh"
echo -e ""
echo -e "  6. Start the application:"
echo -e "     docker compose -f docker-compose.prod.yml up -d"
echo -e ""
echo -e "  7. Set up cron jobs:"
echo -e "     crontab -e"
echo -e "     # Add these lines:"
echo -e "     0 3 * * * /home/ubuntu/arrotech-hub-backend/scripts/backup-db.sh >> /var/log/arrotech-backup.log 2>&1"
echo -e "     */5 * * * * /home/ubuntu/arrotech-hub-backend/scripts/check-resources.sh >> /var/log/arrotech-monitor.log 2>&1"
echo -e "==========================================${NC}"
