# Enhanced Asterisk + FastAPI + AudioSocket Debugging Guide
**Role:** Senior Asterisk + FastAPI + AudioSocket Engineer
**Problem:** Inbound/outbound calls reach Asterisk but AI agent is non-responsive and calls drop automatically

---

## 🏗️ ARCHITECTURE (Distributed)

```
┌─────────────────────────────────────────────────────────────┐
│  VPS (72.60.202.148)                                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Asterisk (SIP signaling only)                        │  │
│  │ - Inbound: PSTN/SIP → Asterisk dialplan             │  │
│  │ - Outbound: Originate → Asterisk dialplan           │  │
│  │ - Both → AudioSocket://127.0.0.1:9092               │  │
│  │ - Backend API: :8010 (ARI/REST)                      │  │
│  └──────────────────────────────────────────────────────┘  │
│         ↓ (reverse SSH tunnel)                              │
│    9092:127.0.0.1:9092 ← ← ← ← ← ← ←                      │
└─────────────────────────────────────────────────────────────┘
                         ↑
        SSH Tunnel Forward (reverse)
                         ↑
┌─────────────────────────────────────────────────────────────┐
│  Local Dev Machine (Windows/WSL)                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ FastAPI Backend                                      │  │
│  │ - AudioSocket server listening: 127.0.0.1:9092      │  │
│  │ - AI/TTS pipeline                                    │  │
│  │ - Session management (inbound + outbound)           │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 ENVIRONMENT CONFIGURATION

### Local Backend (.env) - MUST HAVE
```env
# Mode
ASTERISK_MODE=vps
ASTERISK_VPS_URL=http://72.60.202.148:8010

# AudioSocket Configuration
ASTERISK_AUDIOSOCKET_ENABLED=true
ASTERISK_AUDIOSOCKET_HOST=127.0.0.1
ASTERISK_AUDIOSOCKET_PORT=9092
ASTERISK_AUDIOSOCKET_TIMEOUT=30

# SSH (disabled in local debug mode)
USE_SSH_FOR_ASTERISK=false

# Logging
LOG_LEVEL=DEBUG
ASTERISK_LOG_LEVEL=DEBUG

# Audio
AUDIO_FORMAT=slin16
AUDIO_SAMPLE_RATE=16000

# TTS
TTS_PROVIDER=google  # or your choice
TTS_TIMEOUT=10
```

### VPS Backend (.env) - MUST HAVE
```env
# AudioSocket disabled on VPS (only local processes)
ASTERISK_AUDIOSOCKET_ENABLED=false

# No local binding on VPS
# ASTERISK_AUDIOSOCKET_HOST should NOT be set
# ASTERISK_AUDIOSOCKET_PORT should NOT be set
```

### SSH Tunnel Setup - PREREQUISITE
```bash
# Establish reverse tunnel (run on local machine)
ssh -N -R 9092:127.0.0.1:9092 root@72.60.202.148

# Verify tunnel is active (in another terminal)
ssh root@72.60.202.148 "netstat -tulnp | grep 9092"
# Expected: tcp 0 0 127.0.0.1:9092 0.0.0.0:* LISTEN
```

---

## 🔍 DIAGNOSTIC CHECKLIST (In Order)

### Phase 0: Prerequisites
- [ ] SSH tunnel established and verified
- [ ] VPS Asterisk running (`asterisk -r` → `core show version`)
- [ ] Local FastAPI backend running
- [ ] Local backend is in debug mode (not production)
- [ ] VPS backend NOT running (to avoid port conflicts)

---

### Phase 1: Network Layer (Bottom-Up)

#### Check 1.1: Local AudioSocket Listening
**Expected:** Backend listening on 127.0.0.1:9092

**Local Terminal:**
```bash
# Windows/WSL
netstat -ano | findstr :9092
# or
lsof -i :9092

# Expected Output:
# LISTEN 127.0.0.1:9092 (process=FastAPI_PID)
```

**If FAILED:**
- Backend crashed or not started
- Port already bound by another process
- .env `ASTERISK_AUDIOSOCKET_ENABLED=false`

---

#### Check 1.2: VPS Port 9092 Not Bound Locally
**Expected:** VPS 127.0.0.1:9092 is NOT listening (only via reverse tunnel)

**VPS Terminal:**
```bash
netstat -tulnp | grep 9092
# Expected: NO output (or only tunnel listening)

lsof -i :9092
# Expected: NO output or only SSH tunnel
```

**If FAILED:**
- VPS backend is running and bound to 9092
- Kill it: `pkill -f "python.*main.py"` or `systemctl stop backend`

---

#### Check 1.3: Reverse SSH Tunnel Active
**Expected:** VPS can reach 127.0.0.1:9092 via tunnel

**VPS Terminal:**
```bash
curl -v http://127.0.0.1:9092/health

# Expected HTTP Response:
# 200 OK or connection accepted (not refused)
# If timeout: tunnel is dead
# If refused: no listener on local end
```

**If FAILED:**
- Restart tunnel on local machine
- Check SSH key permissions (600)
- Verify `-N -R` flags are correct

---

### Phase 2: Asterisk Dialplan Layer

#### Check 2.1: Inbound Dialplan Configuration
**Expected:** Dialplan routes calls to AudioSocket with correct IP:port

**VPS Asterisk CLI:**
```bash
asterisk -r
asterisk*CLI> dialplan show [context-name]
```

**Expected Dialplan:**
```
exten => _X.,1,NoOp(Inbound call from ${CALLERID(num)})
exten => _X.,n,Set(CHANNEL(audiosocket)=127.0.0.1:9092)
exten => _X.,n,Answer()
exten => _X.,n,AudioSocket()
exten => _X.,n,Hangup()
```

**Verify:**
```bash
asterisk*CLI> dialplan show context-name
# Output should show AudioSocket exten
```

**If FAILED:**
- Dialplan file not loaded: `asterisk -r → dialplan reload`
- Syntax error: Check `extensions.conf` for typos
- Wrong IP/port in dialplan

---

#### Check 2.2: Outbound Originate Configuration
**Expected:** Outbound calls also use AudioSocket 127.0.0.1:9092

**VPS Backend or Script:**
```bash
# Test via ARI REST (from VPS or via tunnel)
curl -X POST http://72.60.202.148:8010/channels \
  -d '{
    "endpoint": "SIP/outbound-number",
    "extension": "audiosocket-app",
    "context": "outbound-context",
    "priority": 1,
    "variables": {
      "CHANNEL(audiosocket)": "127.0.0.1:9092"
    }
  }'
```

**Expected Dialplan for Outbound Context:**
```
exten => audiosocket-app,1,NoOp(Outbound via AudioSocket)
exten => audiosocket-app,n,Set(CHANNEL(audiosocket)=127.0.0.1:9092)
exten => audiosocket-app,n,Answer()
exten => audiosocket-app,n,AudioSocket()
exten => audiosocket-app,n,Hangup()
```

**If FAILED:**
- Outbound dialplan not defined
- AudioSocket not set in outbound context

---

### Phase 3: AudioSocket Protocol Layer

#### Check 3.1: AudioSocket Server Accepts Connections
**Expected:** Backend logs show connection accepted

**Local Backend Logs:**
```
[DEBUG] AudioSocket server started on 127.0.0.1:9092
[INFO] AudioSocket connection accepted from 127.0.0.1:XXXXX
[DEBUG] UUID received: <channel-uuid>
```

**If NOT in logs:**
- Backend AudioSocket handler not implemented
- Connection rejected before UUID read

**Test Manually:**
```bash
# From VPS (through tunnel)
ssh root@72.60.202.148
telnet 127.0.0.1 9092

# Expected: connection opens (no immediate close)
# Type something, wait for response or hang up
# Check local backend logs for connection attempt
```

---

#### Check 3.2: UUID/Call ID Mapping Valid
**Expected:** UUID received and mapped to session

**Local Backend Logs:**
```
[DEBUG] UUID received: 12345678-1234-1234-1234-123456789abc
[DEBUG] Inbound direction detected
[DEBUG] Session created: session_id=12345678-1234-1234-1234-123456789abc
[DEBUG] Agent ID loaded: agent_id=<agent-uuid>
[DEBUG] Caller number: +1234567890
```

**If NOT in logs:**
- AudioSocket not receiving UUID
- Session creation failed
- Agent ID not found in database

---

#### Check 3.3: TTS Greeting Generated Immediately
**Expected:** Greeting text → TTS → audio bytes sent within 2-3 seconds

**Local Backend Logs:**
```
[DEBUG] AudioSocket connected, generating greeting...
[INFO] TTS generating: "Hello, this is an AI agent. How can I help?"
[DEBUG] TTS provider: google
[INFO] TTS completed: 12345 bytes generated in 1.2s
[DEBUG] Sending audio chunk 1: 2048 bytes
[DEBUG] Sending audio chunk 2: 2048 bytes
...
[INFO] All greeting chunks sent (6 chunks, 12345 bytes total)
```

**If NOT in logs:**
- TTS not triggered
- TTS timeout or error
- Audio not being sent

**VPS Asterisk CLI Check:**
```bash
asterisk*CLI> core show channels
# Should show channel in AudioSocket state
```

**If channel hangs up before greeting:**
- Audio not being sent (socket closes)
- Audio format mismatch

---

### Phase 4: Audio Flow Layer

#### Check 4.1: Audio Format Matches Asterisk Expectation
**Expected:** slin16 (signed 16-bit linear PCM at 16kHz)

**Local Backend Logs:**
```
[DEBUG] AudioSocket audio format: slin16 (16-bit signed linear, 16000 Hz)
[DEBUG] TTS output format: slin16
[DEBUG] Sending chunk: 2048 bytes (64ms at 16kHz)
```

**Verify Asterisk Default:**
```bash
asterisk*CLI> channel originate SIP/trunk application Wait 60
asterisk*CLI> core show config audiosocket
```

**If MISMATCH:**
- Convert audio format before sending
- Set AudioSocket preferred format in dialplan

---

#### Check 4.2: Audio Chunks Sent Completely
**Expected:** Greeting audio sent in 2048-byte chunks, no interruption

**Local Backend Logs:**
```
[DEBUG] Starting audio stream to AudioSocket
[DEBUG] Chunk 1: 2048 bytes sent (offset: 0)
[DEBUG] Chunk 2: 2048 bytes sent (offset: 2048)
[DEBUG] Chunk 3: 2048 bytes sent (offset: 4096)
[DEBUG] Greeting complete: 6 chunks, 12288 bytes
[DEBUG] Waiting for caller input...
```

**If chunks are small or fragmented:**
- Inefficient, but should still work
- Check for socket write errors

---

#### Check 4.3: Barge-In Does Not Cancel Greeting Instantly
**Expected:** Caller can interrupt greeting, not dropped immediately

**Local Backend Logs:**
```
[INFO] Greeting audio being sent...
[DEBUG] Audio data received from caller (barge-in)
[DEBUG] Greeting interrupted gracefully
[INFO] Switching to speech-to-text...
```

**If call drops:**
- Barge-in handler closing socket incorrectly
- No graceful interrupt logic

---

### Phase 5: Socket & Connection Layer

#### Check 5.1: Socket Disconnect Reason Logged
**Expected:** Clear reason when AudioSocket closes

**Local Backend Logs:**
```
[INFO] AudioSocket disconnected: reason=call_ended
# or
[INFO] AudioSocket disconnected: reason=barge_in_completed
# or
[WARNING] AudioSocket disconnected: reason=timeout
# or
[ERROR] AudioSocket disconnected: reason=read_error (Connection reset by peer)
```

**If "Unknown" reason:**
- Add try/catch around socket operations
- Log exception traceback

---

#### Check 5.2: Call Not Dropping Due to Socket Close
**Expected:** Asterisk keeps call alive even if AudioSocket closes gracefully

**VPS Asterisk CLI:**
```bash
asterisk*CLI> core show channels
# Call should remain active until Hangup() exten reached
```

**If call drops immediately:**
- AudioSocket handler not returning control to dialplan
- Exception in AudioSocket handler
- Asterisk version doesn't support AudioSocket properly

---

### Phase 6: Error Handling & Logging

#### Check 6.1: Errors Logged (Not Hidden)
**Expected:** All exceptions logged with traceback

**Local Backend Logs:**
```
[ERROR] AudioSocket connection failed
Traceback (most recent call last):
  File "audiosocket.py", line 42, in handle_connection
    uuid = await socket.recv(36)
ConnectionResetError: [Errno 104] Connection reset by peer
```

**If silent failures:**
- Add try/catch in AudioSocket handler
- Log `exc_info=True` in logger
- Enable DEBUG log level

---

#### Check 6.2: Asterisk Logs Show AudioSocket Activity
**Expected:** Asterisk logs indicate AudioSocket initiated/completed

**VPS Asterisk Log File:**
```bash
tail -f /var/log/asterisk/full

# Expected lines:
# [NOTICE] Channel SIP/... answering from <context>
# [DEBUG] AudioSocket started for channel
# [DEBUG] AudioSocket completed
# [NOTICE] Hangup() executed
```

**If no AudioSocket logs:**
- Asterisk not reaching AudioSocket exten
- AudioSocket module not loaded: `asterisk -r → module show like audiosocket`

---

---

## 📊 NEW DIAGNOSTICS ENDPOINT

### Endpoint Definition
```http
GET /api/v1/asterisk/call-flow-diagnostics
```

### Response Schema (JSON)
```json
{
  "timestamp": "2025-07-02T14:30:45.123Z",
  "mode": "vps",
  "status": "operational",
  
  "audiosocket_config": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 9092,
    "timeout_seconds": 30,
    "audio_format": "slin16",
    "audio_sample_rate": 16000
  },
  
  "audiosocket_runtime": {
    "listening": true,
    "listening_address": "127.0.0.1:9092",
    "accepting_connections": true,
    "active_sessions": 1,
    "total_sessions_handled": 42,
    "uptime_seconds": 3600
  },
  
  "active_sessions": [
    {
      "session_uuid": "12345678-1234-1234-1234-123456789abc",
      "direction": "inbound",
      "state": "greeting",
      "caller": "+14155552671",
      "callee": "+18005551234",
      "agent_id": "agent_uuid_123",
      "connected_at": "2025-07-02T14:30:30.000Z",
      "audio_bytes_sent": 24576,
      "audio_bytes_received": 8192,
      "last_activity": "2025-07-02T14:30:44.500Z"
    }
  ],
  
  "vps_connection": {
    "vps_url": "http://72.60.202.148:8010",
    "reachable": true,
    "latency_ms": 45,
    "last_check": "2025-07-02T14:30:44.000Z"
  },
  
  "ssh_tunnel": {
    "expected": true,
    "required_for_mode": true,
    "command": "ssh -N -R 9092:127.0.0.1:9092 root@72.60.202.148"
  },
  
  "dialplan_checks": {
    "inbound_dialplan_exists": true,
    "inbound_uses_audiosocket": true,
    "inbound_correct_host_port": true,
    "outbound_dialplan_exists": true,
    "outbound_uses_audiosocket": true,
    "outbound_correct_host_port": true,
    "dialplan_last_verified": "2025-07-02T14:30:00.000Z"
  },
  
  "recent_metrics": {
    "last_inbound_connect": "2025-07-02T14:30:30.000Z",
    "last_outbound_connect": "2025-07-02T14:25:15.000Z",
    "last_tts_generation": {
      "timestamp": "2025-07-02T14:30:31.000Z",
      "status": "success",
      "provider": "google",
      "duration_ms": 1200,
      "output_bytes": 12345,
      "text": "Hello, how can I help?"
    },
    "last_audio_send": {
      "timestamp": "2025-07-02T14:30:31.500Z",
      "status": "success",
      "chunks_sent": 6,
      "bytes_sent": 12288,
      "duration_ms": 800
    },
    "last_call_drop": {
      "timestamp": "2025-07-02T14:29:00.000Z",
      "reason": "barge_in_completed",
      "session_uuid": "prev-session-uuid",
      "duration_seconds": 35
    }
  },
  
  "detected_errors": [
    // Empty if no errors, otherwise:
    {
      "severity": "error",
      "component": "audiosocket",
      "message": "Socket read timeout after 30s",
      "timestamp": "2025-07-02T14:20:00.000Z",
      "affected_sessions": 1,
      "recovery_attempted": true
    }
  ],
  
  "recommendations": [
    // Empty if healthy, otherwise:
    "SSH tunnel is inactive. Re-establish with: ssh -N -R 9092:127.0.0.1:9092 root@72.60.202.148",
    "AudioSocket not found in inbound dialplan. Check extensions.conf",
    "TTS timeout exceeded. Check TTS service connectivity."
  ]
}
```

---

## 📝 ENHANCED LOGGING REQUIREMENTS

### Log Levels & Messages

#### Server Startup
```
[INFO] AudioSocket server starting...
[DEBUG] Config loaded: ASTERISK_MODE=vps, AUDIOSOCKET_ENABLED=true
[INFO] AudioSocket server listening on 127.0.0.1:9092
[INFO] Server ready to accept AudioSocket connections
```

#### Connection Lifecycle (Inbound)
```
[DEBUG] AudioSocket connection accepted from 127.0.0.1:51234
[DEBUG] Attempting to read UUID (36 bytes)...
[INFO] UUID received: 12345678-1234-1234-1234-123456789abc
[DEBUG] Call direction: INBOUND (detected from channel state)
[DEBUG] Looking up session by UUID...
[INFO] Session loaded: session_id=12345678-1234-1234-1234-123456789abc
[DEBUG] Loading agent for session...
[INFO] Agent ID: f47ac10b-58cc-4372-a567-0e02b2c3d479
[INFO] Caller: +14155552671 | Callee: +18005551234
[DEBUG] Initializing AI pipeline...
[INFO] Generating greeting: "Hello, this is an AI assistant. How can I help you today?"
```

#### TTS Generation
```
[DEBUG] TTS request: text="Hello, this is an AI assistant...", provider=google
[DEBUG] TTS API call initiated (timeout=10s)
[INFO] TTS completed in 1234ms, output=15360 bytes
[DEBUG] Audio format validated: slin16@16kHz
```

#### Audio Transmission
```
[DEBUG] Starting greeting audio stream to AudioSocket
[DEBUG] Frame 1: offset=0, bytes=2048, cumulative=2048
[DEBUG] Frame 2: offset=2048, bytes=2048, cumulative=4096
[DEBUG] Frame 3: offset=4096, bytes=2048, cumulative=6144
...
[INFO] Greeting complete: 6 frames, 12288 bytes sent in 782ms
[DEBUG] Waiting for audio input from caller...
```

#### Speech Recognition
```
[DEBUG] Audio input detected from caller (245 bytes)
[DEBUG] Barge-in triggered, greeting interrupted
[INFO] Streaming audio to speech-to-text (Google Cloud Speech)
[DEBUG] Transcript (interim): "Hi, I"
[DEBUG] Transcript (interim): "Hi, I'd like to"
[INFO] Transcript (final): "Hi, I'd like to speak to sales"
[DEBUG] Confidence: 0.98
```

#### LLM Processing
```
[DEBUG] Sending to LLM: transcript="Hi, I'd like to speak to sales", context={...}
[DEBUG] LLM API call initiated (model=gpt-4, timeout=15s)
[INFO] LLM response: "I'll transfer you to our sales team. Please hold."
[DEBUG] Response tokens: 14, latency=892ms
```

#### Response Audio
```
[INFO] Generating response audio: "I'll transfer you to our sales team. Please hold."
[DEBUG] TTS initiated for response
[INFO] TTS completed: 8192 bytes in 654ms
[DEBUG] Sending response audio...
[DEBUG] Frame 1: offset=0, bytes=2048, cumulative=2048
[DEBUG] Frame 2: offset=2048, bytes=2048, cumulative=4096
[DEBUG] Frame 3: offset=4096, bytes=2048, cumulative=6144
[DEBUG] Frame 4: offset=6144, bytes=2048, cumulative=8192
[INFO] Response audio sent: 4 frames, 8192 bytes in 512ms
```

#### Disconnect
```
[DEBUG] AudioSocket read operation returned 0 bytes (EOF)
[INFO] AudioSocket disconnected: reason=call_ended
[DEBUG] Session cleanup: UUID=12345678-1234-1234-1234-123456789abc
[INFO] Call duration: 45s, total_audio_exchanged=28KB
```

#### Errors
```
[ERROR] AudioSocket connection error
[ERROR] Exception: Connection reset by peer
[ERROR] Traceback:
  File "audiosocket.py", line 127, in handle_connection
    data = await reader.readexactly(36)
asyncio.IncompleteReadError: 32 bytes read on a total of 36 expected bytes

[ERROR] Session recovery: Attempting graceful shutdown
[DEBUG] Closing socket and releasing session resources
```

---

## 🧪 TESTING PROCEDURES

### Test 1: Local AudioSocket Server Health
**Terminal:**
```bash
# From local machine
python -m pytest tests/test_audiosocket_server.py -v

# Expected:
# test_server_listening_on_9092 PASSED
# test_accepts_connection PASSED
# test_uuid_handshake PASSED
```

### Test 2: Inbound Call (Manual)
**Terminal 1 - Local Backend:**
```bash
python main.py
# Expected:
# [INFO] AudioSocket server listening on 127.0.0.1:9092
```

**Terminal 2 - VPS via SSH:**
```bash
ssh root@72.60.202.148

# Originate a test inbound call
asterisk -r
asterisk*CLI> channel originate Local/9999@inbound-context extension ai-app@inbound-context
# Expected:
# Channel created
# AudioSocket connects to 127.0.0.1:9092
# Greeting plays
```

**Verify Local Backend Logs:**
```
[INFO] UUID received: <uuid>
[INFO] Inbound direction detected
[INFO] TTS completed...
[DEBUG] Audio chunks sent...
```

### Test 3: Outbound Call (Manual)
**Terminal - Local Backend Running:**

**Terminal - VPS:**
```bash
ssh root@72.60.202.148
asterisk -r

# Originate outbound call
asterisk*CLI> channel originate SIP/trunk/+14155552671 extension ai-app@outbound-context
# Expected:
# Outbound call placed to +14155552671
# AudioSocket connects
# Greeting plays to recipient
```

### Test 4: Call Diagnostics
**Terminal - Any Machine:**
```bash
curl http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq

# Expected:
# {
#   "mode": "vps",
#   "audiosocket_runtime": {
#     "listening": true,
#     "active_sessions": 1
#   },
#   "detected_errors": [],
#   ...
# }
```

### Test 5: SSH Tunnel Verification
**Terminal - Any Machine:**
```bash
# Verify tunnel is active
ssh root@72.60.202.148 "curl http://127.0.0.1:9092/health"

# Expected:
# 200 OK
```

---

## 🚨 COMMON FAILURE SCENARIOS & FIXES

| Scenario | Symptoms | Root Cause | Fix |
|----------|----------|-----------|-----|
| **Call drops immediately** | AudioSocket connects, no greeting, instant hang-up | TTS not triggered or socket closes after greeting | Enable DEBUG logs, check TTS service, verify audio send loop |
| **No audio heard** | Call connects, greeting doesn't play | Audio format mismatch or chunks not sent | Verify `slin16` format, check chunk send logs |
| **Barge-in cancels call** | Speaking over greeting hangs up the call | Barge-in handler closing socket incorrectly | Add graceful interrupt, don't close socket on DTMF |
| **VPS 9092 already in use** | SSH tunnel fails or port conflict | VPS backend running, occupying port | `pkill -f "python.*main.py"` on VPS |
| **SSH tunnel unreachable** | AudioSocket times out connecting | Reverse tunnel not established or SSH key issues | Re-run SSH tunnel command, check permissions |
| **UUID never received** | Connection accepted, but no UUID in logs | AudioSocket not sending UUID, or wrong protocol | Verify Asterisk AudioSocket module version, check dialplan |
| **Agent ID not found** | UUID received, session creation fails | Agent not in database or wrong lookup | Query DB: `SELECT * FROM agents WHERE id = ?` |
| **TTS timeout** | Greeting generation hangs > 10s | TTS service unreachable or overloaded | Test TTS separately, increase timeout, check credentials |

---

## 💻 FILE STRUCTURE & EXACT CODE LOCATIONS

### Backend File Structure
```
project/
├── main.py                          # FastAPI app
├── config.py                        # .env loading
├── audiosocket/
│   ├── __init__.py
│   ├── server.py                    # AudioSocket server (listen on 9092)
│   ├── handler.py                   # AudioSocket connection logic
│   └── protocol.py                  # UUID, frame encoding
├── ai/
│   ├── tts.py                       # TTS generation
│   ├── stt.py                       # Speech-to-text
│   └── llm.py                       # LLM interaction
├── models/
│   └── session.py                   # Session management
├── routers/
│   └── diagnostics.py               # /api/v1/asterisk/call-flow-diagnostics
└── tests/
    ├── test_audiosocket_server.py
    ├── test_inbound_flow.py
    └── test_outbound_flow.py
```

---

## 🔧 DEPLOYMENT CHECKLIST

### Pre-Production
- [ ] Local testing passed (inbound + outbound)
- [ ] SSH tunnel stable for 1+ hour
- [ ] Diagnostics endpoint returning healthy status
- [ ] All logs structured and DEBUG-level complete
- [ ] Audio quality tested (clarity, no dropouts)
- [ ] Barge-in tested (smooth interrupt, no crashes)
- [ ] 10 consecutive calls without drop
- [ ] Error messages logged, not silent failures
- [ ] Asterisk dialplan verified on VPS
- [ ] VPS backend NOT running (only local)
- [ ] Performance baseline established (latency, memory)

### Production Handoff
- [ ] SSH tunnel run as systemd service (with restart)
- [ ] Local backend run as systemd service (with restart)
- [ ] Log rotation configured (logrotate)
- [ ] Monitoring/alerting set up (e.g., Datadog, CloudWatch)
- [ ] Disaster recovery procedure documented
- [ ] Rollback plan in place

---

## 📞 TROUBLESHOOTING DECISION TREE

```
SYMPTOM: Call drops immediately

├─ CHECK: AudioSocket server listening?
│  ├─ YES → Continue
│  └─ NO → Start FastAPI backend, check .env AUDIOSOCKET_ENABLED=true
│
├─ CHECK: UUID received in logs?
│  ├─ YES → Continue
│  └─ NO → Verify Asterisk dialplan has `AudioSocket()` exten
│
├─ CHECK: Greeting TTS generated?
│  ├─ YES → Continue
│  └─ NO → Check TTS service, increase timeout
│
├─ CHECK: Audio chunks sent?
│  ├─ YES → Audio format likely wrong
│  │       Fix: Verify slin16@16kHz format
│  └─ NO → Socket closing after greeting
│          Fix: Ensure AudioSocket handler doesn't return after TTS
│
├─ CHECK: Call remains active in `core show channels`?
│  ├─ YES → Issue after AudioSocket (dialplan hangup?)
│  │       Fix: Check dialplan after AudioSocket() exten
│  └─ NO → Asterisk hanging up immediately
│          Fix: Check Asterisk error logs in /var/log/asterisk/full

SYMPTOM: No greeting heard

├─ CHECK: AudioSocket connected? (logs show UUID)
│  ├─ YES → Continue
│  └─ NO → See "Call drops immediately" tree
│
├─ CHECK: TTS generated? (logs show "TTS completed")
│  ├─ YES → Continue
│  └─ NO → TTS service issue, check API keys/network
│
├─ CHECK: Audio sent? (logs show "Frame 1:", "Frame 2:", etc)
│  ├─ YES → Audio format mismatch
│  │       Fix: Verify Asterisk and backend use same format
│  └─ NO → Socket closing before send
│          Fix: Debug socket lifecycle, add logging

SYMPTOM: Caller cannot interrupt greeting

├─ CHECK: DTMF/voice input being read?
│  ├─ YES → Continue
│  └─ NO → Input handler not running
│
├─ CHECK: Barge-in handler closing socket?
│  ├─ NO → Barge-in logic broken
│  │      Fix: Implement graceful interrupt
│  └─ YES → Socket closed incorrectly
│           Fix: Keep socket open, switch to STT mode
```

---

## 📋 FINAL VALIDATION SCRIPT

**Run this script to validate entire setup:**

```bash
#!/bin/bash
set -e

echo "=== ASTERISK + FastAPI + AudioSocket Validation ==="

# 1. SSH Tunnel
echo "[1/10] Checking SSH tunnel..."
if ssh root@72.60.202.148 "curl -s http://127.0.0.1:9092/health" > /dev/null 2>&1; then
    echo "✓ SSH tunnel active"
else
    echo "✗ SSH tunnel inactive. Run: ssh -N -R 9092:127.0.0.1:9092 root@72.60.202.148"
    exit 1
fi

# 2. Local AudioSocket
echo "[2/10] Checking local AudioSocket..."
if netstat -an | grep -q "127.0.0.1:9092.*LISTEN"; then
    echo "✓ AudioSocket listening locally"
else
    echo "✗ AudioSocket not listening. Start FastAPI backend"
    exit 1
fi

# 3. VPS Port Check
echo "[3/10] Checking VPS doesn't bind 9092..."
if ! ssh root@72.60.202.148 "netstat -tulnp 2>/dev/null | grep -v ssh | grep 9092"; then
    echo "✓ VPS 9092 not locally bound (only via tunnel)"
else
    echo "⚠ Warning: VPS has process on 9092. Ensure it's not the backend"
fi

# 4. Asterisk Running
echo "[4/10] Checking Asterisk running..."
if ssh root@72.60.202.148 "asterisk -r -x 'core show version' 2>&1 | grep -q Asterisk"; then
    echo "✓ Asterisk running on VPS"
else
    echo "✗ Asterisk not running on VPS"
    exit 1
fi

# 5. Dialplan Exists
echo "[5/10] Checking inbound dialplan..."
if ssh root@72.60.202.148 "asterisk -r -x 'dialplan show' 2>&1 | grep -q AudioSocket"; then
    echo "✓ AudioSocket in dialplan"
else
    echo "⚠ Warning: AudioSocket not found in dialplan"
fi

# 6. Diagnostics Endpoint
echo "[6/10] Checking diagnostics endpoint..."
if curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq -e '.mode == "vps"' > /dev/null; then
    echo "✓ Diagnostics endpoint healthy"
else
    echo "✗ Diagnostics endpoint not responding"
    exit 1
fi

# 7. VPS Connectivity
echo "[7/10] Checking VPS backend connectivity..."
if curl -s http://72.60.202.148:8010/health > /dev/null 2>&1; then
    echo "✓ VPS backend reachable"
else
    echo "⚠ Warning: VPS backend not responding (may be normal if not running)"
fi

# 8. Local Backend Health
echo "[8/10] Checking local backend health..."
if curl -s http://localhost:8000/health | jq -e '.status == "ok"' > /dev/null; then
    echo "✓ Local backend healthy"
else
    echo "✗ Local backend not responding"
    exit 1
fi

# 9. Logging
echo "[9/10] Checking DEBUG logging enabled..."
if grep -q "LOG_LEVEL=DEBUG" .env; then
    echo "✓ DEBUG logging enabled"
else
    echo "⚠ Warning: DEBUG logging not enabled. Set LOG_LEVEL=DEBUG in .env"
fi

# 10. Summary
echo "[10/10] All checks passed!"
echo ""
echo "✓ Setup is ready for inbound/outbound call testing"
```

---

## 📞 QUICK START INBOUND TEST

```bash
# Terminal 1: Start local FastAPI backend
cd ~/project
source venv/bin/activate
python main.py
# Expected: [INFO] AudioSocket server listening on 127.0.0.1:9092

# Terminal 2: Establish SSH tunnel
ssh -N -R 9092:127.0.0.1:9092 root@72.60.202.148

# Terminal 3: Originate test inbound call
ssh root@72.60.202.148
asterisk -r
asterisk*CLI> channel originate Local/9999@inbound-context extension voicemail@default

# Check local backend logs for:
# [INFO] UUID received
# [INFO] TTS completed
# [DEBUG] Audio chunks sent
```

---

## 📞 QUICK START OUTBOUND TEST

```bash
# Prerequisites: Local backend + SSH tunnel running (see above)

# Terminal 3: Originate test outbound call
ssh root@72.60.202.148
asterisk -r
asterisk*CLI> channel originate SIP/trunk/+14155552671 extension ai-app@outbound

# Check local backend logs for:
# [INFO] UUID received
# [INFO] Outbound direction detected
# [INFO] TTS completed
# [DEBUG] Audio chunks sent
# [INFO] Call connected to +14155552671
```

---

## ✅ SUCCESS CRITERIA

**Inbound Call:**
1. Call reaches Asterisk (SIP signal)
2. AudioSocket connects locally (TCP 127.0.0.1:9092)
3. Backend logs UUID received
4. Backend logs greeting generated
5. Caller hears greeting within 2 seconds
6. Caller can speak (barge-in)
7. Backend logs transcript
8. Backend logs LLM response
9. Caller hears response audio
10. Call completes without drop

**Outbound Call:**
1. Originate command issued to Asterisk ARI
2. Outbound number rings (SIP signal)
3. Called party answers
4. AudioSocket connects locally
5. Backend logs UUID received
6. Backend logs greeting generated
7. Called party hears greeting within 2 seconds
8. Called party can speak
9. Backend logs transcript
10. Called party hears response audio
11. Call completes without drop

---

## 🆘 ESCALATION CONTACTS

- **Asterisk Issues:** Verify dialplan, check `/var/log/asterisk/full`
- **Network Issues:** Test SSH tunnel, verify reverse proxy
- **Audio Issues:** Check format (slin16@16kHz), TTS service
- **Backend Issues:** Review application logs, check `.env` config
- **Session Issues:** Query database, verify agent lookup

