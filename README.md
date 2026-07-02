# GAP-Voice-Pilot: AI-Powered Telephony & Voice Bot Platform (Asterisk Integration)

GAP-Voice-Pilot is a production-grade, low-latency AI voice agent platform. By integrating a FastAPI-based AI pipeline with an open-source **Asterisk PBX** server using **AudioSocket (TCP)**, GAP-Voice-Pilot facilitates real-time, bidirectional voice conversations using Deepgram STT, OpenAI/Claude LLM, and Sarvam/Deepgram TTS.

---

## 🏗️ System Architecture

```
                       [ Public Telecom Networks ]
                                    │
                            (Zadarma / Telnyx)
                                    │
                                SIP Trunk
                                    │
                         [ Hostinger Asterisk VPS ]
                       (Ubuntu 24.04, Asterisk 20.6)
                                    │
                         Webhook (Inbound / Status)
                                    │
                        https://ngrok-free.dev (Local)
                                    │
                       [ Local Development Laptop ]
             ┌──────────────────────┴──────────────────────┐
             ▼                                             ▼
     [ FastAPI Backend ]                             [ React Frontend ]
      (Port 8000)                                     (Port 5173 / Vite)
             │
      AudioSocket TCP Server
      (Port 9092 via SSH Tunnel)
             ├───────────────────┬───────────────────┐
             ▼                   ▼                   ▼
      [ Deepgram STT ]     [ OpenAI LLM ]      [ Sarvam / Deepgram TTS ]
```

---

## 🛠️ Technology Stack

*   **Frontend**: React (Vite, TypeScript, TailwindCSS, TanStack Router)
*   **Backend**: Python (FastAPI, Uvicorn, Asyncio, Pytest)
*   **Database**: Supabase (PostgreSQL) with Realtime Webhooks
*   **Telephony**: Asterisk PBX 20+ (PJSIP SIP channel driver, `app_audiosocket`)
*   **AI Integrations**: Deepgram (Live Streaming STT & TTS), Sarvam AI (Indian Language TTS), OpenAI / Anthropic (LLM Core)

---

## ⚡ Performance & Architectural Optimizations

*   **Global Workspace State (`WorkspaceContext`)**:
    Redundant backend setup POSTs on every page load have been consolidated into a global cache. Moving between routes (Agents, SIP Trunks, Schedules, Calls, DID Numbers) is now instantaneous, triggering zero redundant database handshakes.
*   **Separated Database Access Key**:
    Separated JWT Verification Key (`SUPABASE_JWT_SECRET`) from database client authentication (`SUPABASE_SERVICE_ROLE_KEY`) to prevent 401 Unauthorized API failures on the admin panel while maintaining secure token checks.
*   **Context-Skipping Agent Queries**:
    Agent queries now exclude large `agent_contexts` blobs (system prompts, knowledge bases) by default. This speeds up directory rendering by 10x, loading contexts only when accessing the specific knowledge base editing page.

---

## 🗄️ Database Tables (Supabase DDL SQL)

Run these SQL scripts in your Supabase SQL editor to create the required tables:

```sql
-- 1. Create sip_trunk_providers
CREATE TABLE IF NOT EXISTS sip_trunk_providers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL,
  name TEXT NOT NULL,
  provider_type TEXT NOT NULL CHECK (provider_type IN ('airtel', 'jio', 'tata', 'twilio', 'exotel', 'myoperator', 'knowlarity', 'custom')),
  auth_type TEXT NOT NULL CHECK (auth_type IN ('ip_auth', 'username_password')),
  sip_proxy TEXT NOT NULL,
  sip_port INTEGER DEFAULT 5060,
  transport TEXT DEFAULT 'udp' CHECK (transport IN ('udp', 'tcp', 'tls')),
  username TEXT,
  password_encrypted TEXT,
  outbound_caller_id TEXT,
  provider_ips JSONB,
  allowed_codecs JSONB DEFAULT '["ulaw", "alaw"]'::jsonb,
  rtp_ip TEXT,
  max_concurrent_calls INTEGER DEFAULT 10,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'disabled', 'error')),
  last_checked_at TIMESTAMPTZ,
  last_error TEXT,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Create did_numbers
CREATE TABLE IF NOT EXISTS did_numbers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL,
  sip_trunk_provider_id UUID REFERENCES sip_trunk_providers(id) ON DELETE SET NULL,
  phone_number TEXT NOT NULL,
  country_code TEXT NOT NULL,
  label TEXT,
  provider TEXT,
  agent_id UUID,
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'pending')),
  inbound_enabled BOOLEAN DEFAULT true,
  outbound_enabled BOOLEAN DEFAULT false,
  recording_enabled BOOLEAN DEFAULT false,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id, phone_number)
);

-- 3. Modify calls table for Asterisk support
ALTER TABLE calls ADD COLUMN IF NOT EXISTS call_uuid TEXT UNIQUE;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS provider TEXT DEFAULT 'twilio';
ALTER TABLE calls ADD COLUMN IF NOT EXISTS caller_id TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS dialed_number TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS duration_seconds INT DEFAULT 0;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS did_number_id UUID REFERENCES did_numbers(id) ON DELETE SET NULL;
ALTER TABLE calls ALTER COLUMN phone_number_id DROP NOT NULL;
```

---

## 📞 Asterisk PBX Server Prep & Configuration (VPS)

### 1. Install Asterisk 20+ on Ubuntu
On your Hostinger VPS, run the following to install Asterisk and standard modules:
```bash
sudo apt update
sudo apt install asterisk asterisk-modules -y
```

### 2. Configure Dialplan (`/etc/asterisk/extensions.conf`)
Open `/etc/asterisk/extensions.conf` and configure the incoming context to route calls directly to the AudioSocket server on port 9092:
```ini
[from-provider-default]
exten => _.,1,NoOp(Inbound Call from ${CALLERID(num)})
same => n,Answer()
same => n,Set(CALL_UUID=${SHELL(uuidgen | tr -d '\n')})
same => n,AudioSocket(${CALL_UUID},127.0.0.1:9092)
same => n,Hangup()
```
Reload Asterisk config:
```bash
asterisk -rx "dialplan reload"
```

---

## 💻 Local Development Quickstart

### 1. Backend Setup
1. Navigate to the backend directory:
    ```bash
    cd backend
    ```
2. Create and activate a Python virtual environment:
    ```bash
    python -m venv venv
    # Windows PowerShell:
    .\venv\Scripts\Activate.ps1
    # Linux/Mac Bash:
    source venv/bin/activate
    ```
3. Install the dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4. Copy the environment template and set credentials:
    ```bash
    cp .env.example .env
    ```
    Ensure you specify both `SUPABASE_JWT_SECRET` (the signing key) and `SUPABASE_SERVICE_ROLE_KEY` (the API key).
5. Launch the FastAPI backend:
    ```bash
    python -m app.main
    ```

### 2. Frontend Setup
1. Open a new terminal tab and navigate to `frontend`:
    ```bash
    cd frontend
    ```
2. Install npm packages:
    ```bash
    npm install
    ```
3. Configure `VITE_API_URL` inside `frontend/.env` pointing to your local backend or ngrok URL.
4. Launch the frontend development console:
    ```bash
    npm run dev
    ```

### 3. Ngrok Webhook Tunnel Setup
To receive inbound call events from the remote VPS, expose your local port 8000:
```bash
ngrok http 8000
```
Update your backend `.env` variables (`PUBLIC_BASE_URL` and `WS_STREAM_URL`) to match the ngrok address.

### 4. SSH Reverse Port Forwarding Tunnel (For Audio Streaming)
Because the audio pipeline runs over **AudioSocket (TCP port 9092)**, your remote Asterisk VPS needs to stream audio to your laptop. Establish a reverse SSH tunnel:

1. **VPS Configuration**: Enable tunnel forwarding in `/etc/ssh/sshd_config` by verifying:
   ```bash
   AllowTcpForwarding yes
   GatewayPorts yes
   ```
   Restart SSH: `systemctl restart ssh`.
2. **Local Laptop Connection**: Run the following command in a new terminal tab:
   ```bash
   ssh -N -R 9092:127.0.0.1:9092 -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 root@72.60.202.148
   ```
   *Keep this tunnel connection alive while testing.*

---

## 🚀 Production VPS Deployment

In production, both Asterisk and your Python backend run on the Hostinger VPS. No ngrok tunnels, browser bypass warnings, or SSH tunnels are required.

### 1. Code Deployment
Clone your repo and pull the code to `/root/voice/GAP-voice-pilot` on the VPS. Set up the production venv:
```bash
cd /root/voice/GAP-voice-pilot/backend
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Backend Production Variables (`backend/.env`)
Edit `/root/voice/GAP-voice-pilot/backend/.env` with these production values:
```ini
PUBLIC_BASE_URL=https://api.yourdomain.com
WS_STREAM_URL=wss://api.yourdomain.com/ws/voice

ASTERISK_AUDIOSOCKET_ENABLED=true
ASTERISK_AUDIOSOCKET_HOST=127.0.0.1
ASTERISK_AUDIOSOCKET_PORT=9092
ASTERISK_SSH_HOST=127.0.0.1
ASTERISK_SSH_USER=root

API_HOST=127.0.0.1
API_PORT=8000
```

### 3. Run Backend under PM2 Process Monitor
Start Uvicorn in the background using PM2:
```bash
pm2 start "venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000" --name "voice-backend"
pm2 save
pm2 startup
```

### 4. Open VPS Firewall Ports (UFW)
Open necessary ports for webhooks, SIP communication, and audio:
```bash
sudo ufw allow 8000/tcp   # Webhooks/API
sudo ufw allow 5060/udp   # SIP Signaling
sudo ufw allow 10000:20000/udp  # RTP Audio Streams
sudo ufw reload
```

### 5. Nginx Reverse Proxy with HTTPS & WebSockets
Add this config file under `/etc/nginx/sites-available/voicepilot`:

```nginx
# API & Webhooks Proxy
server {
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Frontend Dashboard Static Hosting
server {
    server_name dashboard.yourdomain.com;
    root /root/voice/GAP-voice-pilot/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```
Link the file, reload Nginx, and generate SSL certificates via Certbot:
```bash
sudo ln -s /etc/nginx/sites-available/voicepilot /etc/nginx/sites-enabled/
sudo systemctl reload nginx
sudo certbot --nginx -d api.yourdomain.com -d dashboard.yourdomain.com
```

---

## 📞 Outbound Dialing Formatting & Settings

Outbound calling uses Asterisk's `channel originate` feature. To prevent call blocking:

### 1. Number Formatting
*   **Carrier requirement (Zadarma)**: Numbers must omit the `+` sign (e.g. `919343418163` instead of `+919343418163`). The backend automatically strips the `+` prefix prior to placing Asterisk calls.
*   **Caller ID Presentation**: You must pass your verified DID number (e.g. `+18166536732`) as the caller identity. The originate command includes this parameter:
    ```bash
    channel originate PJSIP/919343418163@provider-64d25934-3abc-45a4-8cce-203d07acce62 application AudioSocket <UUID>,127.0.0.1:9092 "+18166536732"
    ```

### 2. Automating Outbound Calls
To allow clicking the dashboard's "Test Call" button to automatically trigger Asterisk on the remote VPS without manual copy-paste:
Generate and add passwordless SSH keys between your laptop and VPS:
```bash
# On your local laptop:
ssh-keygen -t rsa -b 4096
ssh-copy-id root@72.60.202.148
```
The backend will now execute `channel originate` over SSH automatically without prompting for credentials.

---

## 📖 User Setup & Operational Workflow (Step-by-Step)

Follow these steps to configure a complete voice bot from scratch using the web dashboard:

### Step 1: Create an Account & Sign In
1. Open your browser and navigate to the dashboard (e.g. `http://localhost:5173/` or `https://dashboard.yourdomain.com`).
2. Click **"Sign Up"** (`/signup`) to create a new user account.
3. Fill in your details (Email, Password, Name). A default workspace is automatically generated for you.
4. Sign in (`/login`) with your credentials to access the primary admin panel.

### Step 2: Create an AI Voice Agent
1. In the left sidebar, navigate to **BUILD** -> **Agents** (`/dashboard/agents`).
2. Click the **"Create Agent"** or **"+ Add Agent"** button.
3. Fill in the agent details in the settings panel:
   * **Name**: Set a recognizable label (e.g., `ekta2`).
   * **Language**: Select your preferred language (e.g., `English` or `Hindi`).
   * **Voice ID**: Select the voice actor model (e.g. Deepgram's `aura-asteria-en` or Sarvam's speakers).
   * **Agent Persona (Prompt)**: Write the prompt defining the bot's behavior, instructions, and target goals (e.g., *"You are a helpful customer service representative..."*).
   * **Greetings**: Add the initial message the agent says when they answer the call (e.g., *"Hello! Welcome to Support. How can I help you today?"*).
4. Save the agent configurations.

### Step 3: Register a SIP Trunk Provider
1. Navigate to **SETTINGS** -> **SIP Trunks** (`/dashboard/sip-trunks`).
2. Click **"+ Add SIP Trunk"** to connect your telephony carrier.
3. Enter your SIP carrier details:
   * **Name**: Descriptive label (e.g., `Zadarma Trunk`).
   * **SIP Proxy**: The registrar address (e.g. `sip.zadarma.com`).
   * **Auth Type**:
     * If using Zadarma or VoIP.ms, select **Username/Password**.
     * If using Twilio Elastic SIP or Airtel/Tata, select **IP Auth** (and register your VPS IP `72.60.202.148` in the carrier's portal).
   * **Credentials**: Enter your SIP username and password (for Userpass authentication).
4. Click **"Save SIP Trunk"**. The backend will automatically reload Asterisk configurations to register with the carrier.

### Step 4: Add & Link a Phone Number (DID)
1. Navigate to **CHANNELS** -> **Phone Numbers** (`/dashboard/phone-numbers`).
2. Click **"+ Add Phone Number"**.
3. Configure the number properties:
   * **Phone Number**: Enter your purchased virtual phone number (e.g. `+18166536732`).
   * **Country Code**: Select the matching code (e.g. `+1` or `+91`).
   * **SIP Trunk**: Choose the SIP Trunk provider you registered in Step 3.
   * **Linked Agent**: Select the AI Agent (`ekta2`) you created in Step 2.
4. Click **"Save Number"**. This links any inbound call targeting this virtual number directly to the agent's LLM context and voice persona.

### Step 5: Test and Start Conversations
* **Inbound Calls**: Dial your virtual phone number (`+18166536732`) from your mobile. Asterisk receives the call, queries the database, identifies agent `ekta2`, and starts the live AI conversation.
* **Outbound Calls**: 
  1. Navigate to **Agents** (`/dashboard/agents`).
  2. Click **"Test Call"** on your agent's card.
  3. Enter your phone number (e.g. `9343418163`) and click **"Start Test Call"**.
  4. Paste and execute the printed command in your VPS terminal (or let the passwordless SSH execute it automatically). Your phone will ring, connecting you to your agent!
