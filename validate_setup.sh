#!/bin/bash

###############################################################################
# Asterisk + FastAPI + AudioSocket Setup Validation Script
# Runs all 11 checks in sequence with clear pass/fail indicators
###############################################################################

set -o pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNING=0

# Configuration
VPS_HOST="72.60.202.148"
VPS_USER="root"
AUDIOSOCKET_HOST="127.0.0.1"
AUDIOSOCKET_PORT=9092
VPS_BACKEND_PORT=8010
LOCAL_BACKEND_PORT=8000

###############################################################################
# Helper Functions
###############################################################################

print_header() {
    echo -e "\n${BLUE}=== $1 ===${NC}\n"
}

print_pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
    ((CHECKS_PASSED++))
}

print_fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    ((CHECKS_FAILED++))
}

print_warn() {
    echo -e "${YELLOW}⚠ WARN${NC}: $1"
    ((CHECKS_WARNING++))
}

print_info() {
    echo -e "${BLUE}ℹ INFO${NC}: $1"
}

print_summary() {
    echo -e "\n${BLUE}=== SUMMARY ===${NC}"
    echo -e "Passed: ${GREEN}$CHECKS_PASSED${NC}"
    echo -e "Failed: ${RED}$CHECKS_FAILED${NC}"
    echo -e "Warned: ${YELLOW}$CHECKS_WARNING${NC}"
    
    if [ $CHECKS_FAILED -eq 0 ]; then
        echo -e "\n${GREEN}✓ All critical checks passed!${NC}"
        return 0
    else
        echo -e "\n${RED}✗ Some checks failed. See recommendations above.${NC}"
        return 1
    fi
}

###############################################################################
# CHECK 1: SSH Tunnel Active
###############################################################################

check_ssh_tunnel() {
    print_header "CHECK 1: SSH Reverse Tunnel"
    
    echo "Verifying SSH tunnel is established (127.0.0.1:9092 → VPS)..."
    
    if ssh -o ConnectTimeout=5 "${VPS_USER}@${VPS_HOST}" \
        "curl -s http://127.0.0.1:9092/health > /dev/null 2>&1" 2>/dev/null; then
        print_pass "SSH tunnel is active and responding"
    else
        print_fail "SSH tunnel not responding. Expected: ssh -N -R 9092:127.0.0.1:9092 root@${VPS_HOST}"
        echo "  Run in a separate terminal: ssh -N -R 9092:127.0.0.1:9092 root@${VPS_HOST}"
    fi
    
    # Also check local netstat
    if netstat -an 2>/dev/null | grep -q "127.0.0.1:9092.*LISTEN\|:9092.*LISTEN"; then
        print_info "Port 9092 is listening locally"
    fi
}

###############################################################################
# CHECK 2: Local AudioSocket Server
###############################################################################

check_local_audiosocket() {
    print_header "CHECK 2: Local AudioSocket Listening"
    
    echo "Checking if AudioSocket server is listening on ${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT}..."
    
    # Try different methods to check
    if command -v lsof &> /dev/null; then
        if lsof -i :${AUDIOSOCKET_PORT} 2>/dev/null | grep -q LISTEN; then
            PID=$(lsof -i :${AUDIOSOCKET_PORT} 2>/dev/null | grep LISTEN | awk '{print $2}' | head -1)
            print_pass "AudioSocket listening on ${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT} (PID: $PID)"
        else
            print_fail "AudioSocket not listening on ${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT}"
            echo "  → Start FastAPI backend: python main.py"
            echo "  → Check .env has: ASTERISK_AUDIOSOCKET_ENABLED=true"
        fi
    elif command -v netstat &> /dev/null; then
        if netstat -tulnp 2>/dev/null | grep -q ":${AUDIOSOCKET_PORT}"; then
            print_pass "AudioSocket listening on ${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT}"
        else
            print_fail "AudioSocket not listening on ${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT}"
            echo "  → Start FastAPI backend: python main.py"
        fi
    else
        # Try connecting to port as fallback
        if timeout 2 bash -c "echo > /dev/tcp/${AUDIOSOCKET_HOST}/${AUDIOSOCKET_PORT}" 2>/dev/null; then
            print_pass "AudioSocket accepting connections on ${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT}"
        else
            print_fail "Cannot connect to ${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT}"
        fi
    fi
}

###############################################################################
# CHECK 3: VPS Port 9092 NOT Bound Locally
###############################################################################

check_vps_port_9092() {
    print_header "CHECK 3: VPS Port 9092 (Should NOT be locally bound)"
    
    echo "Checking VPS doesn't have local binding on 9092 (only via SSH tunnel)..."
    
    # Query VPS for local binding (excluding SSH tunnel)
    OUTPUT=$(ssh -o ConnectTimeout=5 "${VPS_USER}@${VPS_HOST}" \
        "netstat -tulnp 2>/dev/null | grep 9092 | grep -v ssh || true" 2>/dev/null)
    
    if [ -z "$OUTPUT" ]; then
        print_pass "VPS port 9092 not locally bound (correct - only via SSH tunnel)"
    else
        print_fail "VPS has process binding port 9092 locally (should be SSH tunnel only)"
        echo "  → Output: $OUTPUT"
        echo "  → If this is your backend, run on VPS: pkill -f 'python.*main.py'"
        echo "  → Ensure VPS .env has: ASTERISK_AUDIOSOCKET_ENABLED=false"
    fi
}

###############################################################################
# CHECK 4: Asterisk Running on VPS
###############################################################################

check_asterisk_running() {
    print_header "CHECK 4: Asterisk Running on VPS"
    
    echo "Checking if Asterisk is running..."
    
    if ssh -o ConnectTimeout=5 "${VPS_USER}@${VPS_HOST}" \
        "asterisk -r -x 'core show version' 2>&1 | grep -q 'Asterisk'" 2>/dev/null; then
        ASTERISK_VERSION=$(ssh -o ConnectTimeout=5 "${VPS_USER}@${VPS_HOST}" \
            "asterisk -r -x 'core show version' 2>&1 | head -1" 2>/dev/null)
        print_pass "Asterisk running on VPS: $ASTERISK_VERSION"
    else
        print_fail "Asterisk not running on VPS"
        echo "  → Start Asterisk: systemctl start asterisk"
        echo "  → Or: asterisk -f (foreground, for debugging)"
    fi
}

###############################################################################
# CHECK 5: Inbound Dialplan Routes to AudioSocket
###############################################################################

check_inbound_dialplan() {
    print_header "CHECK 5: Inbound Dialplan → AudioSocket"
    
    echo "Verifying inbound dialplan routes to AudioSocket 127.0.0.1:9092..."
    
    DIALPLAN=$(ssh -o ConnectTimeout=5 "${VPS_USER}@${VPS_HOST}" \
        "asterisk -r -x 'dialplan show' 2>&1" 2>/dev/null)
    
    HAS_INBOUND=$(echo "$DIALPLAN" | grep -i "inbound\|context.*from-" | wc -l)
    HAS_AUDIOSOCKET=$(echo "$DIALPLAN" | grep -i "audiosocket" | wc -l)
    HAS_CORRECT_IP=$(echo "$DIALPLAN" | grep "127.0.0.1" | wc -l)
    
    if [ "$HAS_INBOUND" -gt 0 ] && [ "$HAS_AUDIOSOCKET" -gt 0 ] && [ "$HAS_CORRECT_IP" -gt 0 ]; then
        print_pass "Inbound dialplan configured correctly"
    else
        print_fail "Inbound dialplan not properly configured"
        echo "  → HAS_INBOUND: $HAS_INBOUND, HAS_AUDIOSOCKET: $HAS_AUDIOSOCKET, HAS_CORRECT_IP: $HAS_CORRECT_IP"
        echo "  → Expected dialplan pattern:"
        echo "      exten => _X.,1,NoOp(Inbound call)"
        echo "      exten => _X.,n,Set(CHANNEL(audiosocket)=127.0.0.1:9092)"
        echo "      exten => _X.,n,Answer()"
        echo "      exten => _X.,n,AudioSocket()"
        echo "      exten => _X.,n,Hangup()"
        echo "  → Check: /etc/asterisk/extensions.conf"
        echo "  → Reload: asterisk -r -x 'dialplan reload'"
    fi
}

###############################################################################
# CHECK 6: Outbound Dialplan Routes to AudioSocket
###############################################################################

check_outbound_dialplan() {
    print_header "CHECK 6: Outbound Dialplan → AudioSocket"
    
    echo "Verifying outbound dialplan routes to AudioSocket 127.0.0.1:9092..."
    
    DIALPLAN=$(ssh -o ConnectTimeout=5 "${VPS_USER}@${VPS_HOST}" \
        "asterisk -r -x 'dialplan show' 2>&1" 2>/dev/null)
    
    HAS_OUTBOUND=$(echo "$DIALPLAN" | grep -i "outbound\|to-" | wc -l)
    HAS_AUDIOSOCKET=$(echo "$DIALPLAN" | grep -i "audiosocket" | wc -l)
    
    if [ "$HAS_OUTBOUND" -gt 0 ] && [ "$HAS_AUDIOSOCKET" -gt 0 ]; then
        print_pass "Outbound dialplan configured"
    else
        print_warn "Outbound dialplan may not be configured properly"
        echo "  → Expected dialplan pattern in outbound context:"
        echo "      exten => _X.,1,Set(CHANNEL(audiosocket)=127.0.0.1:9092)"
        echo "      exten => _X.,n,Answer()"
        echo "      exten => _X.,n,AudioSocket()"
        echo "      exten => _X.,n,Hangup()"
    fi
}

###############################################################################
# CHECK 7: Backend AudioSocket Handler Implemented
###############################################################################

check_backend_audiosocket_handler() {
    print_header "CHECK 7: Backend AudioSocket Handler"
    
    echo "Checking if backend has AudioSocket handler implemented..."
    
    # Check if there's an audiosocket directory/module
    if [ -d "audiosocket" ] || [ -f "audiosocket.py" ] || [ -f "audiosocket/__init__.py" ]; then
        print_pass "AudioSocket module/directory found in backend"
        
        # Check if handler accepts connections
        if grep -r "async def.*handle\|@app.route.*audiosocket\|AudioSocket.*server" \
            audiosocket* 2>/dev/null | grep -q "def\|async"; then
            print_pass "AudioSocket handler function found"
        else
            print_warn "AudioSocket handler not clearly found in code"
        fi
    else
        print_fail "AudioSocket module not found in backend"
        echo "  → Create: audiosocket/handler.py with async socket handler"
    fi
}

###############################################################################
# CHECK 8: Session UUID Mapping
###############################################################################

check_session_uuid_mapping() {
    print_header "CHECK 8: Session UUID Mapping"
    
    echo "Checking if backend has session UUID mapping..."
    
    if [ -d "models" ] && [ -f "models/session.py" ]; then
        print_pass "Session model found"
        
        if grep -q "uuid\|call_id\|session_id" models/session.py 2>/dev/null; then
            print_pass "Session model includes UUID/call ID tracking"
        else
            print_warn "Session model doesn't clearly track UUIDs"
        fi
    else
        print_warn "Session model directory/file not found in expected location"
    fi
}

###############################################################################
# CHECK 9: TTS Greeting Generated Immediately
###############################################################################

check_tts_greeting() {
    print_header "CHECK 9: TTS Greeting Immediate Generation"
    
    echo "Checking backend logs for TTS generation..."
    
    # Look for recent log file
    if [ -f "logs/app.log" ]; then
        # Check for TTS-related logs in last 100 lines
        if tail -100 logs/app.log 2>/dev/null | grep -i "TTS\|greeting\|generate" > /dev/null; then
            print_pass "TTS activity found in logs"
            tail -5 logs/app.log 2>/dev/null | grep -i "TTS\|greeting" | head -3
        else
            print_warn "No recent TTS activity in logs"
            echo "  → Tip: Make a test call to generate TTS logs"
        fi
    else
        print_info "Log file not found yet (normal on first run)"
    fi
}

###############################################################################
# CHECK 10: Audio Format Validation
###############################################################################

check_audio_format() {
    print_header "CHECK 10: Audio Format (slin16@16kHz)"
    
    echo "Checking backend audio format configuration..."
    
    if [ -f ".env" ]; then
        if grep -q "AUDIO_FORMAT" .env; then
            FORMAT=$(grep "AUDIO_FORMAT" .env | cut -d= -f2)
            print_pass "Audio format configured: $FORMAT"
            
            if [ "$FORMAT" = "slin16" ]; then
                print_pass "Audio format is slin16 (correct)"
            else
                print_warn "Audio format is $FORMAT (expected slin16)"
            fi
        else
            print_warn "AUDIO_FORMAT not set in .env (using default)"
        fi
        
        if grep -q "AUDIO_SAMPLE_RATE" .env; then
            RATE=$(grep "AUDIO_SAMPLE_RATE" .env | cut -d= -f2)
            print_pass "Sample rate configured: ${RATE}Hz"
            
            if [ "$RATE" = "16000" ]; then
                print_pass "Sample rate is 16kHz (correct)"
            else
                print_warn "Sample rate is ${RATE}Hz (expected 16000)"
            fi
        fi
    else
        print_fail ".env file not found"
        echo "  → Create .env with AUDIO_FORMAT=slin16 and AUDIO_SAMPLE_RATE=16000"
    fi
}

###############################################################################
# CHECK 11: Errors Logged (Not Hidden)
###############################################################################

check_error_logging() {
    print_header "CHECK 11: Error Logging Enabled (DEBUG level)"
    
    echo "Checking if DEBUG logging is enabled..."
    
    if [ -f ".env" ]; then
        if grep -q "LOG_LEVEL" .env; then
            LOG_LEVEL=$(grep "LOG_LEVEL" .env | cut -d= -f2)
            print_pass "Log level configured: $LOG_LEVEL"
            
            if [ "$LOG_LEVEL" = "DEBUG" ]; then
                print_pass "DEBUG logging enabled (correct)"
            else
                print_warn "Log level is $LOG_LEVEL (recommended: DEBUG for troubleshooting)"
            fi
        else
            print_warn "LOG_LEVEL not set in .env (using default)"
        fi
    fi
    
    if grep -r "import logging\|logger = logging\|logging.debug" . \
        --include="*.py" 2>/dev/null | grep -q "logging"; then
        print_pass "Logging module imported in backend code"
    else
        print_warn "Logging setup not clearly found in code"
    fi
}

###############################################################################
# BONUS: Local Backend Health Check
###############################################################################

check_backend_health() {
    print_header "BONUS: Local Backend Health"
    
    echo "Checking if local backend is running on localhost:${LOCAL_BACKEND_PORT}..."
    
    if timeout 5 curl -s "http://localhost:${LOCAL_BACKEND_PORT}/health" > /dev/null 2>&1; then
        print_pass "Local backend healthy on localhost:${LOCAL_BACKEND_PORT}"
    else
        print_warn "Local backend not responding on localhost:${LOCAL_BACKEND_PORT}"
        echo "  → Start with: python main.py"
    fi
}

###############################################################################
# BONUS: VPS Backend Health Check
###############################################################################

check_vps_backend_health() {
    print_header "BONUS: VPS Backend Health"
    
    echo "Checking if VPS backend is running on ${VPS_HOST}:${VPS_BACKEND_PORT}..."
    
    if timeout 5 curl -s "http://${VPS_HOST}:${VPS_BACKEND_PORT}/health" > /dev/null 2>&1; then
        print_warn "VPS backend is running (should NOT run in local debug mode)"
        echo "  → Stop VPS backend: ssh root@${VPS_HOST} pkill -f 'python.*main.py'"
    else
        print_pass "VPS backend is NOT running (correct for local debug mode)"
    fi
}

###############################################################################
# BONUS: Diagnostics Endpoint
###############################################################################

check_diagnostics_endpoint() {
    print_header "BONUS: Diagnostics Endpoint"
    
    echo "Checking if diagnostics endpoint is available..."
    
    if timeout 5 curl -s "http://localhost:${LOCAL_BACKEND_PORT}/api/v1/asterisk/call-flow-diagnostics" \
        | grep -q "mode\|audiosocket" 2>/dev/null; then
        print_pass "Diagnostics endpoint available"
    else
        print_warn "Diagnostics endpoint not responding"
        echo "  → Check backend logs for errors"
    fi
}

###############################################################################
# Main Execution
###############################################################################

main() {
    echo -e "${BLUE}"
    cat << "EOF"
╔════════════════════════════════════════════════════════════════════╗
║   Asterisk + FastAPI + AudioSocket Setup Validation               ║
║   All 11 Critical Checks                                          ║
╚════════════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
    
    # Run all checks
    check_ssh_tunnel
    check_local_audiosocket
    check_vps_port_9092
    check_asterisk_running
    check_inbound_dialplan
    check_outbound_dialplan
    check_backend_audiosocket_handler
    check_session_uuid_mapping
    check_tts_greeting
    check_audio_format
    check_error_logging
    
    # Bonus checks
    check_backend_health
    check_vps_backend_health
    check_diagnostics_endpoint
    
    # Print summary
    print_summary
    EXIT_CODE=$?
    
    # Additional recommendations
    if [ $CHECKS_FAILED -gt 0 ]; then
        echo -e "\n${YELLOW}=== QUICK FIXES ===${NC}"
        echo "1. Start local backend: python main.py"
        echo "2. Establish SSH tunnel: ssh -N -R 9092:127.0.0.1:9092 root@${VPS_HOST}"
        echo "3. Check Asterisk dialplan: ssh root@${VPS_HOST} asterisk -r -x 'dialplan show'"
        echo "4. View backend logs: tail -f logs/app.log"
        echo "5. Test diagnostics: curl http://localhost:8000/api/v1/asterisk/call-flow-diagnostics | jq"
    fi
    
    exit $EXIT_CODE
}

# Run
main "$@"
