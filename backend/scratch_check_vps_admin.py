import httpx
import json

base_url = "http://72.60.202.148:8010"

headers = {
    "Authorization": "Bearer sso_secret_or_whatever_if_needed"  # SSO / Auth bypass might be needed
}

def query_endpoint(path):
    url = f"{base_url}{path}"
    print(f"\nFetching: {url}")
    try:
        resp = httpx.get(url, timeout=5.0)
        print(f"Status Code: {resp.status_code}")
        if resp.status_code == 200:
            try:
                print(json.dumps(resp.json(), indent=2))
            except Exception:
                print(resp.text[:500])
        else:
            print(f"Error: {resp.text}")
    except Exception as e:
        print(f"Failed: {e}")

# Query system health and trunk registrations
query_endpoint("/api/admin/system/health")
query_endpoint("/api/admin/sip-trunks/registrations")
