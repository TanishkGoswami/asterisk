# Quick Start Testing Guide
## Inbound & Outbound Call Testing with Exact Commands

---

## 📋 Prerequisites

Before starting tests, verify all prerequisites are in place:

```bash
# 1. Run validation script
bash validate_setup.sh

# Expected output: "All critical checks passed!"

# 2. Check local backend .env
cat .env | grep -E "ASTERISK_MODE|AUDIOSOCKET_ENABLED|AUDIOSOCKET_HOST|AUDIOSOCKET_PORT"

# Expected output:
# ASTERISK_MODE=vps
# ASTERISK_AUDIOSOCKET_ENABLED=true
# ASTERISK_AUDIOSOCKET_HOST=127.0.0.1
# ASTERISK_AUDIOSOCKET_PORT=9092

# 3. Check VPS backend .env (if running)
ssh root@72.60.202.148 'cat /path/to/vps/backend/.env | grep AUDIOSOCKET_ENABLED'

# Expected output:
# ASTERISK_AUDIOSOCKET_ENABLED=false
```

---

## 🚀 TEST 1: INBOUND CALL (Step-by-Step)

### Prerequisites Checklist
- [ ] Local backend running on port 8000
- [ ] SSH tunnel established (port 9092)
- [ ] VPS Asterisk running
- [ ] Inbound dialplan configured

### Terminal Setup

**Terminal 1 - Start Local Backend** (stays open)

```bash
cd ~/project  # or your project path

# Check logs directory exists
mkdir -p logs

# Start FastAPI backend
python main.py

# Expected output:
# [INFO] Starting server...
# [INFO] AudioSocket server listening on 127.0.0.1:9092
# [INFO] Server ready to accept AudioSocket connections
# [INFO] Uvicorn running on http://0.0.0.0:8000
```

**Terminal 2 - Establish SSH Tunnel** (stays open)

```bash
# In a new terminal (or tmux/screen session)
ssh -N -R 9092:127.0.0.1:9092 root@72.60.202.148

# Expected output: (none - tunnel silently runs in background)
# If you get an error, common fixes:
#   - SSH key permissions: chmod 600 ~/.ssh/id_rsa
#   - SSH key not in authorized_keys: Add your public key to VPS
#   - Port 9092 already in use: lsof -i :9092 and kill process

# To verify tunnel is active (in another terminal):
ssh root@72.60.202.148 "curl -s http://127.0.0.1:9092/health | jq ."
# Expected: { "status": "ok", ... }
```

**Terminal 3 - Run Inbound Test**

```bash
# SSH into VPS
ssh root@72.60.202.148

# Enter Asterisk console
asterisk -r

# You should see the Asterisk prompt:
asterisk*CLI>

# Check Asterisk is ready
asterisk*CLI> core show version
# Expected output: Asterisk 16.X.X or higher

# Option A: Make a real inbound call (using SIP trunk)
# This depends on your SIP configuration - skip if not available

# Option B: Simulate inbound call using Local channel
asterisk*CLI> channel originate Local/9999@inbound-context extension voicemail@default

# This will:
# 1. Route to inbound dialplan
# 2. Connect to AudioSocket at 127.0.0.1:9092 (through SSH tunnel)
# 3. Backend receives AudioSocket connection
# 4. Backend generates greeting
# 5. Greeting played (in Asterisk console log)

# Check if call was processed
asterisk*CLI> core show channels

# Expected output: (channel processing or completed)
# Channel              State (Current   )  State (Ring  )  Bridge
# No active channels
# SIP/trunk/+14155552671  Up             (Dialing)       (nothing)

# Exit Asterisk console
asterisk*CLI> exit
```

### Monitoring During Test

**Check Local Backend Logs (Terminal 1)**

Watch for these log messages (in order):

```
[DEBUG] AudioSocket connection accepted from 72.60.202.148:XXXXX
[DEBUG] UUID read started (expecting 36 bytes)
[INFO] UUID received: 12345678-1234-1234-1234-123456789abc
[DEBUG] Call direction: INBOUND
[INFO] Session created: 12345678-1234-1234-1234-123456789abc
[INFO] Caller: +14155552671, Callee: +18005551234
[INFO] Agent ID: agent_uuid_123
[INFO] Generating greeting: "Hello, this is an AI agent..."
[DEBUG] TTS request: provider=google, timeout=10s
[INFO] TTS completed: 1234ms, 12345 bytes
[DEBUG] Audio format validated: slin16@16kHz
[DEBUG] Starting audio stream to AudioSocket
[DEBUG] Audio chunk 1: 2048 bytes
[DEBUG] Audio chunk 2: 2048 bytes
...
[INFO] Audio stream completed: 6 chunks, 12288 bytes
[DEBUG] Waiting for audio input from caller
[INFO] Call duration: 45s
[INFO] AudioSocket disconnected: reason=call_ended
```

**Check VPS Asterisk Logs (Terminal 3)**

```bash
# In another VPS terminal (keep open)
tail -f /var/log/asterisk/full

# Expected lines:
# [NOTICE] Channel SIP/xxx answering from <context>
# [DEBUG] AudioSocket started for channel
# [DEBUG] AudioSocket completed
# [NOTICE] Hangup() executed
```

### Verification Checklist

After running the test, verify each step:

```bash
# 1. Check call was processed
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.recent_metrics.last_inbound_connect'
# Expected: timestamp of your test call

# 2. Check no errors
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.detected_errors'
# Expected: [] (empty array)

# 3. Check session was recorded
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.audiosocket_runtime.total_sessions_handled'
# Expected: >= 1

# 4. Check TTS succeeded
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.recent_metrics.last_tts_generation'
# Expected: status=success
```

### Troubleshooting Inbound

| Problem | Symptom | Fix |
|---------|---------|-----|
| **Call drops immediately** | No UUID in logs | Check dialplan has `Set(CHANNEL(audiosocket)=...)` |
| **No greeting heard** | UUID received, no TTS logs | Check TTS service (API keys, network) |
| **Socket timeout** | "TimeoutError" in logs | SSH tunnel down or backend slow |
| **Barge-in cancels call** | Call hangs when speaking | Check barge-in handler doesn't close socket |

---

## 📞 TEST 2: OUTBOUND CALL (Step-by-Step)

### Prerequisites Checklist
- [ ] Local backend running on port 8000
- [ ] SSH tunnel established (port 9092)
- [ ] VPS Asterisk running
- [ ] Outbound dialplan configured
- [ ] Valid SIP trunk or termination provider

### Outbound Dialplan Configuration

Ensure this is in your VPS Asterisk extensions.conf:

```
[outbound-context]
exten => _X.,1,NoOp(Outbound call)
exten => _X.,n,Set(CHANNEL(audiosocket)=127.0.0.1:9092)
exten => _X.,n,Answer()
exten => _X.,n,AudioSocket()
exten => _X.,n,Hangup()
```

### Terminal Setup

**Terminal 1 & 2:** Same as Inbound Test
- Local backend running
- SSH tunnel established

**Terminal 3 - Run Outbound Test**

```bash
# SSH into VPS
ssh root@72.60.202.148

# Enter Asterisk console
asterisk -r

# Originate outbound call (replace number with valid phone)
asterisk*CLI> channel originate SIP/trunk/+14155552671 extension outbound-app@outbound-context

# Where:
# - SIP/trunk = your SIP trunk (configured in sip.conf)
# - +14155552671 = destination phone number
# - outbound-context = dialplan context with AudioSocket

# This will:
# 1. Place SIP INVITE to +14155552671
# 2. Wait for 180 Ringing, then 200 OK (call answered)
# 3. Route to AudioSocket at 127.0.0.1:9092
# 4. Backend generates greeting
# 5. Greeting sent to called party's phone
# 6. Called party can speak (captured via STT)
# 7. Backend generates response and sends audio back

# Check call progress
asterisk*CLI> core show channels

# Expected: Call should be UP and active
```

### Monitoring During Test

**Check Local Backend Logs (Terminal 1)**

Watch for these log messages (in order):

```
[DEBUG] AudioSocket connection accepted from 72.60.202.148:XXXXX
[DEBUG] UUID read started
[INFO] UUID received: 87654321-4321-4321-4321-098765432109
[DEBUG] Call direction: OUTBOUND
[INFO] Session created: 87654321-4321-4321-4321-098765432109
[INFO] Caller: +18005551234, Callee: +14155552671
[INFO] Agent ID: agent_uuid_456
[INFO] Generating greeting: "Hello, I'm calling from XYZ company..."
[DEBUG] TTS request
[INFO] TTS completed: 1567ms, 15678 bytes
[DEBUG] Starting audio stream to AudioSocket
[DEBUG] Audio chunk 1: 2048 bytes
...
[INFO] Audio stream completed
[DEBUG] Waiting for input from called party
[DEBUG] Audio input received from called party: 3456 bytes
[INFO] Transcript (final): "Hi, can I help you?" (confidence=0.95)
[INFO] LLM response: "Yes, I'm calling about your account..."
[INFO] Response audio completed: 12345 bytes
[DEBUG] Response audio sent: 4 chunks
[INFO] AudioSocket disconnected: reason=call_ended
```

### Verification Checklist

```bash
# 1. Check outbound call was processed
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.recent_metrics.last_outbound_connect'
# Expected: timestamp of your test call

# 2. Check active session during call
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.active_sessions'
# Expected: Array with one session, direction=outbound

# 3. Check both inbound and outbound handled
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.audiosocket_runtime'
# Expected:
# {
#   "active_sessions": 0,  # After call completes
#   "total_sessions_handled": >= 2  # Inbound + Outbound
# }
```

### Troubleshooting Outbound

| Problem | Symptom | Fix |
|---------|---------|-----|
| **Call not placed** | No SIP INVITE sent | Check SIP trunk config, test manually |
| **Called party doesn't answer** | Call never reaches AudioSocket | Check SIP trunk routing |
| **Greeting not heard by called party** | AudioSocket connects, no audio | Check audio format, TTS |
| **Called party can't speak** | No STT transcript | Check microphone/audio input path |

---

## 🔄 TEST 3: SEQUENTIAL INBOUND → OUTBOUND

This test ensures both directions work in sequence:

```bash
# Terminal 3 (Asterisk console)

# Step 1: Inbound call
asterisk*CLI> channel originate Local/9999@inbound-context extension voicemail@default
# Wait for completion (~30-45 seconds)

# Check logs between calls
# - Verify first session ended cleanly
# - Verify "total_sessions_handled" = 1

# Step 2: Outbound call (after inbound completes)
asterisk*CLI> channel originate SIP/trunk/+14155552671 extension outbound-app@outbound-context
# Wait for completion

# Check final state
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.audiosocket_runtime.total_sessions_handled'
# Expected: 2 (one inbound, one outbound)
```

---

## 📊 DIAGNOSTICS ENDPOINT TESTING

### Real-Time Status Monitoring

```bash
# Get full diagnostics (pretty-printed)
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq .

# Watch specific fields
# 1. Runtime status
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.audiosocket_runtime'

# 2. Active sessions
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.active_sessions'

# 3. Recent metrics
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.recent_metrics'

# 4. Detected errors
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.detected_errors'

# 5. Recommendations
curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq '.recommendations'

# Monitor in real-time (every 2 seconds)
watch -n 2 'curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq ".audiosocket_runtime, .active_sessions"'
```

### Diagnostics During Active Call

While a call is in progress (another terminal):

```bash
# Check real-time session data
watch -n 1 'curl -s http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq ".active_sessions[0]"'

# Output shows:
# {
#   "session_uuid": "12345678-...",
#   "direction": "inbound",
#   "state": "greeting",  # Changes as call progresses
#   "audio_bytes_sent": 12345,  # Increasing
#   "audio_bytes_received": 2048,
#   "last_activity": "2025-07-02T14:30:44.123Z"
# }
```

---

## ✅ SUCCESS CRITERIA

### Inbound Call Success
- [x] Call reaches Asterisk (SIP 200 OK)
- [x] AudioSocket connects locally
- [x] UUID received in logs
- [x] Greeting generated by TTS
- [x] Greeting audio sent to caller
- [x] Caller receives audio (can hear greeting)
- [x] Call doesn't drop on audio
- [x] Caller can interrupt (barge-in)
- [x] Call completes gracefully
- [x] Logs show no errors

### Outbound Call Success
- [x] SIP INVITE sent to trunk
- [x] Remote party answers (SIP 200 OK)
- [x] AudioSocket connects locally
- [x] Greeting generated and sent
- [x] Called party hears greeting
- [x] Called party can speak
- [x] Speech captured and transcribed
- [x] LLM generates response
- [x] Response audio sent to called party
- [x] Call completes gracefully

---

## 🐛 TROUBLESHOOTING QUICK REFERENCE

### AudioSocket Not Responding
```bash
# Check tunnel
ssh root@72.60.202.148 "curl -s http://127.0.0.1:9092/health"
# If fails: Re-establish tunnel

# Check local listening
lsof -i :9092
# If fails: Start backend (python main.py)

# Check backend logs
tail -f logs/app.log | grep -i "audiosocket\|error"
```

### TTS Generation Failing
```bash
# Check TTS credentials
echo $GOOGLE_APPLICATION_CREDENTIALS
# If not set: export path to credentials JSON

# Test TTS separately
python -c "from ai.tts import generate_greeting; print(generate_greeting('Hello'))"

# Check TTS logs
tail -f logs/app.log | grep -i "tts\|google\|speech"
```

### Session UUID Not Received
```bash
# Check dialplan sets AudioSocket
ssh root@72.60.202.148 "asterisk -r -x 'dialplan show' | grep -i audiosocket"

# Reload dialplan
ssh root@72.60.202.148 "asterisk -r -x 'dialplan reload'"

# Check Asterisk error logs
ssh root@72.60.202.148 "tail -50 /var/log/asterisk/full | grep -i error"
```

### Call Drops Immediately
```bash
# Check audio format
grep "AUDIO_FORMAT" .env

# Check TTS is running
tail -f logs/app.log | grep -i "tts\|greeting"

# Check socket send errors
tail -f logs/app.log | grep -i "socket\|send"

# Verify SSH tunnel active
ssh root@72.60.202.148 "netstat -tulnp | grep 9092"
```

---

## 📝 Testing Checklist Template

Use this for each test run:

```
[ ] Date/Time: _______________
[ ] Test Type: [ ] Inbound  [ ] Outbound  [ ] Sequential

Pre-Test:
[ ] Backend running (python main.py)
[ ] SSH tunnel established
[ ] Asterisk running on VPS
[ ] Validation script passed (bash validate_setup.sh)

Execution:
[ ] Command executed successfully
[ ] No immediate errors in logs
[ ] Audio files generated/sent correctly

Post-Test:
[ ] Call completed without drops
[ ] Session cleanup successful
[ ] Total sessions incremented
[ ] No unresolved errors in logs
[ ] Diagnostics endpoint reports success

Issues Encountered:
___________________________________________________________________________
___________________________________________________________________________

Resolution:
___________________________________________________________________________
___________________________________________________________________________
```

---

## 🚨 Emergency Debug Mode

If tests are failing, enable emergency diagnostics:

```bash
# 1. Stop backend
pkill -f "python main.py"

# 2. Enable maximum verbosity
cat > .env << 'EOF'
ASTERISK_MODE=vps
ASTERISK_VPS_URL=http://72.60.202.148:8010
ASTERISK_AUDIOSOCKET_ENABLED=true
ASTERISK_AUDIOSOCKET_HOST=127.0.0.1
ASTERISK_AUDIOSOCKET_PORT=9092
LOG_LEVEL=DEBUG
ASTERISK_LOG_LEVEL=DEBUG
DEBUG_AUDIOSOCKET=true
DEBUG_TTS=true
DEBUG_STT=true
DEBUG_LLM=true
EOF

# 3. Start with verbose logging
python main.py 2>&1 | tee -a logs/debug.log

# 4. In another terminal, run test and capture full logs
bash validate_setup.sh > validation_report.txt 2>&1
```

All logs will be available in:
- `logs/app.log` - Full application logs
- `logs/debug.log` - Debug-level logs
- `validation_report.txt` - Validation script output

Share these files if seeking support.
