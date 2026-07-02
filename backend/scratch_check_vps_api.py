import httpx

vps_docs_url = "http://72.60.202.148:8010/openapi.json"
print(f"Fetching openapi.json from VPS: {vps_docs_url}")

try:
    resp = httpx.get(vps_docs_url, timeout=5.0)
    print(f"Status Code: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print("\n=== VPS API ENDPOINTS ===")
        paths = data.get("paths", {})
        for path, methods in paths.items():
            print(f"{path}: {list(methods.keys())}")
    else:
        print(f"Error response: {resp.text}")
except Exception as e:
    print(f"Request failed: {e}")
