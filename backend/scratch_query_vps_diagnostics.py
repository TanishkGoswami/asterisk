import httpx
import json

vps_url = "http://72.60.202.148:8010/api/v1/telephony/asterisk/diagnostics"
print(f"Fetching diagnostics from VPS: {vps_url}")

try:
    resp = httpx.get(vps_url, timeout=10.0)
    print(f"Status Code: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print("\n=== PJSIP REGISTRATIONS ===")
        print(data.get("pjsip_registrations", "None"))
        
        print("\n=== PJSIP ENDPOINTS ===")
        print(data.get("pjsip_endpoints", "None"))
        
        print("\n=== DETECTED ERRORS ===")
        print(json.dumps(data.get("detected_errors", []), indent=2))
        
        print("\n=== OTHER STATS ===")
        print(f"Asterisk Running: {data.get('asterisk_running')}")
        print(f"Asterisk Version: {data.get('asterisk_version')}")
        print(f"CLI Executable: {data.get('can_execute_asterisk_cli')}")
    else:
        print(f"Error response: {resp.text}")
except Exception as e:
    print(f"Request failed: {e}")
