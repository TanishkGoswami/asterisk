#!/bin/bash

# ==============================================================================
# GAP-Voice-Pilot VPS Deployment Script
# This script automates the installation and configuration of the production environment.
# Target OS: Ubuntu 22.04 / 24.04 LTS
# Run this script as root: sudo bash deploy_vps.sh
# ==============================================================================

# Exit immediately if a command exits with a non-zero status
set -e

# Setup colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}====================================================${NC}"
echo -e "${GREEN}🚀 Starting GAP-Voice-Pilot VPS Deployment Script${NC}"
echo -e "${BLUE}====================================================${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}❌ Please run this script as root (sudo).${NC}"
  exit 1
fi

# Define path variables
APP_DIR="/root/voice/GAP-voice-pilot"
BACKEND_DIR="$APP_DIR/backend"
FRONTEND_DIR="$APP_DIR/frontend"

# Step 1: Update System Packages
echo -e "\n${YELLOW}📦 Step 1: Updating system packages...${NC}"
apt update && apt upgrade -y

# Step 2: Install System Dependencies
echo -e "\n${YELLOW}📦 Step 2: Installing core dependencies (Python3, Git, Nginx, curl, uuid-runtime)...${NC}"
apt install -y python3 python3-pip python3-venv git nginx curl certbot python3-certbot-nginx uuid-runtime ufw

# Step 3: Install Node.js & NPM (required for frontend build)
if ! command -v node &> /dev/null; then
  echo -e "\n${YELLOW}📦 Installing Node.js & NPM via NodeSource...${NC}"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt install -y nodejs
else
  echo -e "${GREEN}✓ Node.js is already installed ($(node -v))${NC}"
fi

# Step 4: Install PM2 globally
if ! command -v pm2 &> /dev/null; then
  echo -e "\n${YELLOW}📦 Installing PM2 globally...${NC}"
  npm install -y -g pm2
else
  echo -e "${GREEN}✓ PM2 is already installed ($(pm2 -v))${NC}"
fi

# Step 5: Check Asterisk Installation
if ! command -v asterisk &> /dev/null; then
  echo -e "\n${YELLOW}📞 Installing Asterisk 20+...${NC}"
  apt install -y asterisk asterisk-modules
else
  echo -e "${GREEN}✓ Asterisk is already installed ($(asterisk -V))${NC}"
fi

# Step 6: Create Virtual Environment and Install Backend Dependencies
echo -e "\n${YELLOW}🐍 Step 6: Setting up Python virtual environment and dependencies...${NC}"
mkdir -p "$BACKEND_DIR"
cd "$BACKEND_DIR"

if [ ! -d "venv" ]; then
  python3 -m venv venv
  echo -e "${GREEN}✓ Virtual environment created${NC}"
fi

source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
echo -e "${GREEN}✓ Python dependencies installed${NC}"

# Step 7: Create Backend Environment Variables (.env)
if [ ! -f ".env" ]; then
  echo -e "\n${YELLOW}⚙️ Step 7: Creating backend environment template (.env)...${NC}"
  if [ -f ".env.example" ]; then
    cp .env.example .env
  else
    # Create default production .env template
    cat <<EOT > .env
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_JWT_SECRET=your-jwt-secret
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SIP_ENCRYPTION_KEY=your-sip-encryption-key-32-bytes

# AI Keys
OPENAI_API_KEY=your-openai-api-key
DEEPGRAM_API_KEY=your-deepgram-api-key
SARVAM_API_KEY=your-sarvam-api-key

# Production Host Details
PUBLIC_BASE_URL=https://api.yourdomain.com
WS_STREAM_URL=wss://api.yourdomain.com/ws/voice

# Local Asterisk & AudioSocket Settings
ASTERISK_AUDIOSOCKET_ENABLED=true
ASTERISK_AUDIOSOCKET_HOST=127.0.0.1
ASTERISK_AUDIOSOCKET_PORT=9092
ASTERISK_SSH_HOST=127.0.0.1
ASTERISK_SSH_USER=root

# API Server Settings
API_HOST=127.0.0.1
API_PORT=8000
API_WORKERS=4
LOG_LEVEL=INFO
DEBUG=False
EOT
  fi
  echo -e "${YELLOW}⚠️  A default .env was created at $BACKEND_DIR/.env. Please edit it with your production keys!${NC}"
else
  echo -e "${GREEN}✓ Backend .env already exists${NC}"
fi

# Step 8: Build Frontend Production Assets
echo -e "\n${YELLOW}💻 Step 8: Building Frontend production assets...${NC}"
cd "$FRONTEND_DIR"
if [ -f ".env" ]; then
  echo -e "${GREEN}✓ Frontend .env exists${NC}"
else
  cat <<EOT > .env
VITE_API_URL=https://api.yourdomain.com
EOT
  echo -e "${YELLOW}⚠️  A default frontend .env was created at $FRONTEND_DIR/.env. Make sure VITE_API_URL points to your production API domain.${NC}"
fi

npm install
npm run build
echo -e "${GREEN}✓ Frontend built successfully${NC}"

# Step 9: Configure Nginx Reverse Proxy
echo -e "\n${YELLOW}🌐 Step 9: Configuring Nginx reverse proxy...${NC}"
NGINX_CONF="/etc/nginx/sites-available/voicepilot"

cat <<EOT > "$NGINX_CONF"
# API & Webhooks Proxy
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}

# Frontend Dashboard Static Hosting
server {
    listen 80;
    server_name dashboard.yourdomain.com;
    root $FRONTEND_DIR/dist;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOT

# Link site configuration
if [ ! -f "/etc/nginx/sites-enabled/voicepilot" ]; then
  ln -s "$NGINX_CONF" "/etc/nginx/sites-enabled/"
fi

# Remove default nginx config if active
if [ -f "/etc/nginx/sites-enabled/default" ]; then
  rm "/etc/nginx/sites-enabled/default"
fi

# Test Nginx and reload
nginx -t
systemctl reload nginx
echo -e "${GREEN}✓ Nginx configured and reloaded${NC}"

# Step 10: Setup PM2 Process for Backend
echo -e "\n${YELLOW}⚙️ Step 10: Launching backend FastAPI application using PM2...${NC}"
cd "$BACKEND_DIR"

# Check if PM2 process already exists
if pm2 list | grep -q "voice-backend"; then
  echo -e "${YELLOW}PM2 process 'voice-backend' already exists, restarting it...${NC}"
  pm2 restart voice-backend
else
  pm2 start "venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000" --name "voice-backend"
fi

# Save list and configure startup
pm2 save
pm2 startup || true
echo -e "${GREEN}✓ Backend process running under PM2${NC}"

# Step 11: Configure Firewall (UFW)
echo -e "\n${YELLOW}🛡️ Step 11: Configuring UFW firewall rules...${NC}"
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw allow 5060/udp
ufw allow 10000:20000/udp
echo "y" | ufw enable
ufw status
echo -e "${GREEN}✓ Firewall configuration active${NC}"

echo -e "\n${BLUE}====================================================${NC}"
echo -e "${GREEN}🎉 Deployment Environment Setup Completed!${NC}"
echo -e "${BLUE}====================================================${NC}"
echo -e "${YELLOW}Next Steps to Complete Deployment Manually:${NC}"
echo -e "1. Edit your production backend settings at: ${BLUE}$BACKEND_DIR/.env${NC}"
echo -e "2. Edit your production frontend settings at: ${BLUE}$FRONTEND_DIR/.env${NC}"
echo -e "   and run ${BLUE}npm run build${NC} inside ${BLUE}$FRONTEND_DIR${NC} to rebuild static files."
echo -e "3. Generate free SSL certificates for your domains:"
echo -e "   ${BLUE}sudo certbot --nginx -d api.yourdomain.com -d dashboard.yourdomain.com${NC}"
echo -e "4. Restart the backend process after changing env configurations:"
echo -e "   ${BLUE}pm2 restart voice-backend${NC}"
echo -e "${BLUE}====================================================${NC}"
