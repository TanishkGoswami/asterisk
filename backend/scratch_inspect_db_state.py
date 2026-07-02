from app.db.client import get_supabase_client
import json

db = get_supabase_client()

agent_id = "fee34fc7-1c3d-4554-9c81-da4111df3651"

print("--- AGENT INFO ---")
agent = db.table("agents").select("*").eq("id", agent_id).execute()
print(json.dumps(agent.data, indent=2))

print("\n--- DID NUMBERS ---")
dids = db.table("did_numbers").select("*").eq("agent_id", agent_id).execute()
print(json.dumps(dids.data, indent=2))

print("\n--- SIP TRUNKS ---")
trunks = db.table("sip_trunk_providers").select("*").execute()
print(json.dumps(trunks.data, indent=2))

print("\n--- LATEST CALLS ---")
calls = db.table("calls").select("*").eq("agent_id", agent_id).order("created_at", desc=True).limit(3).execute()
print(json.dumps(calls.data, indent=2))
