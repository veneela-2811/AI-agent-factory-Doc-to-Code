from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from src.storage.database import get_db
from src.storage.vector_store import vector_store
from src.storage.filestore import file_store
from src.api.schemas import HealthCheckResponse
from config.settings import settings

router = APIRouter(tags=["Health"])


@router.get("/healthz", response_model=HealthCheckResponse, summary="System Health Check")
async def health_check(db: AsyncSession = Depends(get_db)):
    sqlite_ok = False
    try:
        res = await db.execute(text("SELECT 1"))
        sqlite_ok = bool(res.scalar())
    except Exception:
        sqlite_ok = False

    chroma_ok = False
    try:
        vector_store.client.heartbeat()
        chroma_ok = True
    except Exception:
        chroma_ok = False

    filestore_ok = file_store.root.exists()

    overall = "healthy" if (sqlite_ok and chroma_ok and filestore_ok) else "degraded"
    return HealthCheckResponse(
        status=overall,
        app_name=settings.APP_NAME,
        version="2.0.0",
        sqlite_healthy=sqlite_ok,
        chromadb_healthy=chroma_ok,
        filestore_healthy=filestore_ok
    )


@router.get("/llm/status", summary="Diagnostic: Check LLM Provider and API Key Status")
async def llm_status():
    from src.llm.router import router as llm_router
    from src.llm.schemas import LLMRequest, LLMMessage, TaskCategory

    providers_status = {}
    for name, adapter in llm_router.adapters.items():
        is_avail = adapter.is_available()
        providers_status[name] = {
            "available": is_avail
        }

    # Run a test generation to determine the active provider & model
    active_test = {}
    try:
        req = LLMRequest(
            task_category=TaskCategory.SIMPLE,
            task_name="health_diagnostic",
            messages=[LLMMessage(role="user", content="Respond with: LLM is operational.")]
        )
        resp = await llm_router.generate(req)
        active_test = {
            "status": "success",
            "active_provider": resp.provider_used,
            "active_model": resp.model_used,
            "test_response": resp.content.strip()[:100],
            "latency_ms": round(resp.latency_ms, 2)
        }
    except Exception as e:
        active_test = {
            "status": "error",
            "error_message": str(e)
        }

    return {
        "routing_mode": settings.LLM_ROUTING_MODE,
        "providers": providers_status,
        "active_llm": active_test
    }

