from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.api.v1 import (
    agents,
    auth,
    webhooks,
    calls,
    workspaces,
    conversations,
    local_agent,
    phone_numbers,
    scheduled_tasks,
    voice_ws,
    sip_trunks,
    admin,
    diagnostics as diagnostics_module,
)

# Setup logging
setup_logging(log_level=settings.log_level, log_file="logs/app.log")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="OmniDim Voice AI Agent Platform",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://gapvoicepilot.online",
        "https://social.getaipilot.in",
        "https://voice.getaipilot.online",
        "https://voice.getaipilot.in",
        "http://localhost:8010",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600,
)


@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    """Handle CORS preflight requests"""
    return {"status": "ok"}


# Include routers
app.include_router(workspaces.router, prefix="/api/v1/workspaces", tags=["workspaces"])
app.include_router(agents.router, prefix="/api/v1/workspaces", tags=["agents"])
app.include_router(
    conversations.router, prefix="/api/v1/agents", tags=["conversations"]
)
app.include_router(calls.router, prefix="/api/v1/workspaces", tags=["calls"])
app.include_router(calls.asterisk_router, tags=["asterisk-calls"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])
app.include_router(webhooks.router, prefix="/api/webhook", tags=["webhooks-legacy"])
app.include_router(local_agent.router, prefix="/api/v1", tags=["local-agent"])
app.include_router(local_agent.test_router, prefix="/api/test", tags=["test"])
app.include_router(
    phone_numbers.router, prefix="/api/v1/workspaces", tags=["phone-numbers"]
)
app.include_router(
    sip_trunks.router, prefix="/api/v1/workspaces", tags=["sip-trunks"]
)
app.include_router(
    scheduled_tasks.router, prefix="/api/v1/scheduled-tasks", tags=["scheduled-tasks"]
)
app.include_router(voice_ws.router, tags=["voice-ws"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth-legacy"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(diagnostics_module.router)



@app.exception_handler(Exception)
async def global_exception_handler(_request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.environment}


@app.get("/health/db")
async def health_db():
    """Test Supabase connection"""
    from app.db.client import get_supabase_client

    try:
        db = get_supabase_client()
        logger.info(f"Supabase URL: {settings.supabase_url}")
        logger.info(f"Key starts with: {settings.supabase_jwt_secret[:20]}...")
        result = db.table("profiles").select("id").limit(1).execute()
        return {"status": "connected", "sample_row_count": len(result.data)}
    except Exception as e:
        logger.error(f"DB health check failed: {e}", exc_info=True)
        return {"status": "error", "detail": str(e)}


@app.get("/api/health/asterisk")
async def health_asterisk():
    """Expose health and metrics for Asterisk Audiosocket server."""
    from app.services.asterisk_audiosocket import get_audiosocket_stats
    return get_audiosocket_stats()


@app.on_event("startup")
async def startup_event():
    """Run background tasks on startup"""
    import asyncio
    from datetime import datetime, timezone
    from app.tasks.scheduler import start_local_scheduler
    from app.api.v1.diagnostics import diagnostics
    diagnostics.audiosocket_start_time = datetime.now(timezone.utc)

    # Start the local scheduler loop in the background
    asyncio.create_task(start_local_scheduler())

    # Start the Asterisk Audiosocket TCP server if enabled
    if settings.asterisk_audiosocket_enabled:
        from app.services.asterisk_audiosocket import start_audiosocket_server
        asyncio.create_task(
            start_audiosocket_server(
                host=settings.asterisk_audiosocket_host,
                port=settings.asterisk_audiosocket_port
            )
        )


@app.on_event("shutdown")
async def shutdown_event():
    """Stop the Audiosocket TCP server gracefully on server shutdown."""
    if settings.asterisk_audiosocket_enabled:
        try:
            from app.services.asterisk_audiosocket import stop_audiosocket_server
            await stop_audiosocket_server()
        except Exception as e:
            logger.error(f"Error stopping Audiosocket server: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
