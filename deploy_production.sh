#!/bin/bash

# Mini-Hub Production Deployment Script
# This script deploys Mini-Hub to production with all necessary components

set -e

echo "🚀 Starting Mini-Hub Production Deployment..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_NAME="mini-hub"
DOMAIN="your-domain.com"
SSL_EMAIL="admin@your-domain.com"

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo -e "${RED}This script should not be run as root${NC}"
   exit 1
fi

# Update system
echo -e "${YELLOW}Updating system packages...${NC}"
sudo apt update && sudo apt upgrade -y

# Install required packages
echo -e "${YELLOW}Installing required packages...${NC}"
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    postgresql \
    postgresql-contrib \
    nginx \
    certbot \
    python3-certbot-nginx \
    redis-server \
    git \
    curl \
    wget \
    unzip

# Create application directory
echo -e "${YELLOW}Setting up application directory...${NC}"
sudo mkdir -p /opt/$PROJECT_NAME
sudo chown $USER:$USER /opt/$PROJECT_NAME

# Clone or update repository
if [ -d "/opt/$PROJECT_NAME/.git" ]; then
    echo -e "${YELLOW}Updating existing repository...${NC}"
    cd /opt/$PROJECT_NAME
    git pull origin main
else
    echo -e "${YELLOW}Cloning repository...${NC}"
    git clone https://github.com/your-username/$PROJECT_NAME.git /opt/$PROJECT_NAME
    cd /opt/$PROJECT_NAME
fi

# Set up Python virtual environment
echo -e "${YELLOW}Setting up Python virtual environment...${NC}"
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo -e "${YELLOW}Installing Python dependencies...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# Set up PostgreSQL
echo -e "${YELLOW}Setting up PostgreSQL...${NC}"
sudo -u postgres psql -c "CREATE DATABASE minihub;"
sudo -u postgres psql -c "CREATE USER minihub WITH PASSWORD 'your_secure_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE minihub TO minihub;"

# Set up environment variables
echo -e "${YELLOW}Setting up environment variables...${NC}"
if [ ! -f ".env" ]; then
    cp env.example .env
    echo -e "${YELLOW}Please edit .env file with your production values${NC}"
    echo -e "${YELLOW}Key variables to update:${NC}"
    echo -e "  - DATABASE_URL"
    echo -e "  - SECRET_KEY"
    echo -e "  - STRIPE_SECRET_KEY"
    echo -e "  - MPESA_CONSUMER_KEY"
    echo -e "  - HUBSPOT_API_KEY"
    echo -e "  - GA4_PROPERTY_ID"
    echo -e "  - SLACK_BOT_TOKEN"
fi

# Run database migrations
echo -e "${YELLOW}Running database migrations...${NC}"
source venv/bin/activate
alembic upgrade head

# Set up systemd service
echo -e "${YELLOW}Setting up systemd service...${NC}"
sudo tee /etc/systemd/system/$PROJECT_NAME.service > /dev/null <<EOF
[Unit]
Description=Mini-Hub FastAPI Application
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/opt/$PROJECT_NAME
Environment=PATH=/opt/$PROJECT_NAME/venv/bin
ExecStart=/opt/$PROJECT_NAME/venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Set up Nginx configuration
echo -e "${YELLOW}Setting up Nginx configuration...${NC}"
sudo tee /etc/nginx/sites-available/$PROJECT_NAME > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /static/ {
        alias /opt/$PROJECT_NAME/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
EOF

# Enable Nginx site
sudo ln -sf /etc/nginx/sites-available/$PROJECT_NAME /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test Nginx configuration
sudo nginx -t

# Set up SSL certificate
echo -e "${YELLOW}Setting up SSL certificate...${NC}"
sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos --email $SSL_EMAIL

# Set up SSL renewal cron job
echo -e "${YELLOW}Setting up SSL renewal cron job...${NC}"
(crontab -l 2>/dev/null; echo "0 12 * * * /usr/bin/certbot renew --quiet") | crontab -

# Start and enable services
echo -e "${YELLOW}Starting and enabling services...${NC}"
sudo systemctl daemon-reload
sudo systemctl enable $PROJECT_NAME
sudo systemctl start $PROJECT_NAME
sudo systemctl enable nginx
sudo systemctl restart nginx
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Set up firewall
echo -e "${YELLOW}Setting up firewall...${NC}"
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

# Set up monitoring
echo -e "${YELLOW}Setting up basic monitoring...${NC}"
sudo apt install -y htop iotop

# Create backup script
echo -e "${YELLOW}Creating backup script...${NC}"
sudo tee /opt/$PROJECT_NAME/backup.sh > /dev/null <<EOF
#!/bin/bash
BACKUP_DIR="/opt/backups"
DATE=\$(date +%Y%m%d_%H%M%S)
mkdir -p \$BACKUP_DIR

# Backup database
pg_dump minihub > \$BACKUP_DIR/minihub_\$DATE.sql

# Backup application files
tar -czf \$BACKUP_DIR/minihub_\$DATE.tar.gz /opt/$PROJECT_NAME

# Keep only last 7 days of backups
find \$BACKUP_DIR -name "minihub_*" -mtime +7 -delete

echo "Backup completed: \$DATE"
EOF

sudo chmod +x /opt/$PROJECT_NAME/backup.sh

# Set up daily backup cron job
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/$PROJECT_NAME/backup.sh") | crontab -

# Create health check script
echo -e "${YELLOW}Creating health check script...${NC}"
sudo tee /opt/$PROJECT_NAME/health_check.sh > /dev/null <<EOF
#!/bin/bash
HEALTH_URL="https://arrotech-hub.onrender.com/health"
RESPONSE=\$(curl -s -o /dev/null -w "%{http_code}" \$HEALTH_URL)

if [ \$RESPONSE -ne 200 ]; then
    echo "Health check failed: \$RESPONSE"
    systemctl restart $PROJECT_NAME
    echo "Service restarted at \$(date)" >> /var/log/$PROJECT_NAME/health.log
fi
EOF

sudo chmod +x /opt/$PROJECT_NAME/health_check.sh

# Set up health check cron job
(crontab -l 2>/dev/null; echo "*/5 * * * * /opt/$PROJECT_NAME/health_check.sh") | crontab -

# Create log directory
sudo mkdir -p /var/log/$PROJECT_NAME
sudo chown $USER:$USER /var/log/$PROJECT_NAME

echo -e "${GREEN}✅ Production deployment completed!${NC}"
echo -e "${YELLOW}Next steps:${NC}"
echo -e "1. Update .env file with production values"
echo -e "2. Test the application: https://$DOMAIN"
echo -e "3. Set up monitoring and alerting"
echo -e "4. Configure backup storage"
echo -e "5. Set up CI/CD pipeline"

# Show service status
echo -e "${YELLOW}Service Status:${NC}"
sudo systemctl status $PROJECT_NAME --no-pager -l
sudo systemctl status nginx --no-pager -l 