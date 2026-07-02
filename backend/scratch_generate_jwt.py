import jwt
import time
import base64
from app.db.client import get_supabase_client
from app.core.config import settings

db = get_supabase_client()

# Fetch a super admin profile
res = db.table("profiles").select("id, email, role").eq("role", "super_admin").execute()
print("Super Admins:")
print(res.data)

if res.data:
    user = res.data[0]
    user_id = user["id"]
    email = user["email"]
    
    # Generate JWT
    # Supabase JWT secret is base64 encoded or plain
    try:
        secret = base64.b64decode(settings.supabase_jwt_secret)
    except Exception:
        secret = settings.supabase_jwt_secret
        
    payload = {
        "sub": user_id,
        "email": email,
        "role": "authenticated",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600  # 1 hour expiry
    }
    
    token = jwt.encode(payload, secret, algorithm="HS256")
    print("\nGenerated Super Admin JWT Token:")
    print(token)
else:
    print("No super_admin user found. Let's check all profiles.")
    res = db.table("profiles").select("id, email, role").limit(10).execute()
    print(res.data)
