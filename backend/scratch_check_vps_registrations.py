import httpx
import json

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyNDNhYzgxNy1lY2JjLTQ3MjQtYTY0OC02MGIwZTdlMmYwM2EiLCJlbWFpbCI6InNod2V0Y2hvdXJleTNAZ21haWwuY29tIiwicm9sZSI6ImF1dGhlbnRpY2F0ZWQiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzgyOTgzODgyfQ.WMwIuZZSfTF8Nd6xDBXz1FyvHYWl8moXAskPrXG-jwU"

base_url = "http://72.60.202.148:8010"

headers = {
    "Authorization": f"Bearer {token}"
}

def query_endpoint(path):
    url = f"{base_url}{path}"
    print(f"\nFetching: {url}")
    try:
        resp = httpx.get(url, headers=headers, timeout=10.0)
        print(f"Status Code: {resp.status_code}")
        if resp.status_code == 200:
            try:
                print(json.dumps(resp.json(), indent=2))
            except Exception:
                print(resp.text[:1000])
        else:
            print(f"Error: {resp.text}")
    except Exception as e:
        print(f"Failed: {e}")

# Query system health and trunk registrations
query_endpoint("/api/admin/sip-trunks/registrations")
