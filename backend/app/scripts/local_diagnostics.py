import sys
import os
import socket
import logging

# Set logging to warning only for dependencies to keep output concise
logging.basicConfig(level=logging.WARNING)

def main():
    print("=" * 60)
    print("GETAIPILOT ASTERISK BACKEND - LOCAL DIAGNOSTICS")
    print("=" * 60)
    
    # 1. Load Settings
    try:
        from app.core.config import settings
        print("[ OK ] Settings loaded successfully.")
    except Exception as e:
        print(f"[FAIL] Settings loading failed: {e}")
        sys.exit(1)
        
    # 2. Check API Health (port 8000)
    api_url = "http://127.0.0.1:8000/health"
    api_up = False
    try:
        import urllib.request
        import json
        with urllib.request.urlopen(api_url, timeout=2.0) as response:
            status = json.loads(response.read().decode())["status"]
            if status == "ok":
                print("[ OK ] Backend API is healthy on port 8000.")
                api_up = True
            else:
                print(f"[WARN] Backend API health returned status: {status}")
    except Exception as e:
        print(f"[WARN] Backend API is not reachable on port 8000 (is uvicorn running?): {e}")

    # 3. Check Supabase connection (REQUIRED)
    try:
        from app.db.client import get_supabase_client
        db = get_supabase_client()
        # Simple query to verify connection
        res = db.table("profiles").select("id").limit(1).execute()
        print("[ OK ] Supabase is reachable (profiles queried).")
    except Exception as e:
        print(f"[FAIL] Supabase connection failed: {e}")
        sys.exit(1)

    # 4. Check OpenAI API Key & client (REQUIRED)
    openai_ok = False
    try:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set in environment.")
        from app.services.llm_service import LLMService
        llm = LLMService(openai_key=settings.openai_api_key)
        if llm.openai_client:
            print("[ OK ] OpenAI API key and LLM client initialized successfully.")
            openai_ok = True
        else:
            raise ValueError("LLM client could not be initialized.")
    except Exception as e:
        print(f"[FAIL] OpenAI initialization failed: {e}")
        sys.exit(1)

    # 5. Check Redis Connection (OPTIONAL by default)
    redis_required = getattr(settings, "redis_required", False)
    redis_ok = False
    try:
        import redis
        r_client = redis.from_url(settings.redis_url, decode_responses=True)
        r_client.ping()
        print("[ OK ] Redis is reachable.")
        redis_ok = True
    except Exception as e:
        status_str = "FAIL" if redis_required else "WARN"
        print(f"[{status_str}] Redis connection failed: {e}")
        if redis_required:
            sys.exit(1)

    # 6. Check AudioSocket Listener status (port 9092)
    audiosocket_listening = False
    try:
        with socket.create_connection(("127.0.0.1", 9092), timeout=1.0) as s:
            audiosocket_listening = True
            print("[ OK ] AudioSocket server is listening on 127.0.0.1:9092.")
    except Exception as e:
        print(f"[WARN] AudioSocket server is NOT listening on 127.0.0.1:9092: {e}")

    # 7. Check Asterisk CLI & Version
    from app.services.asterisk_cli import execute_asterisk_cli_cmd
    cli_res = execute_asterisk_cli_cmd("core show version")
    if cli_res["returncode"] == 0:
        print(f"[ OK ] Asterisk CLI is reachable. Version: {cli_res['stdout'].strip()}")
        
        # Check target PJSIP endpoint
        endpoint_name = os.getenv("ASTERISK_TEST_ENDPOINT", "provider-7d9e5f61-a681-46c5-8998-490084821b78")
        from app.services.asterisk_cli import verify_endpoint_status
        ep_res = verify_endpoint_status(endpoint_name)
        if ep_res["status"] == "valid":
            print(f"[ OK ] Target PJSIP endpoint '{endpoint_name}' is valid in Asterisk.")
        else:
            print(f"[WARN] Target PJSIP endpoint check status: {ep_res['status']}. Message: {ep_res['message']}")
    else:
        print(f"[WARN] Asterisk CLI unreachable or failed (code {cli_res['returncode']}): {cli_res['stderr'].strip()}")

    print("=" * 60)
    print("Diagnostics completed successfully.")
    sys.exit(0)

if __name__ == "__main__":
    main()
