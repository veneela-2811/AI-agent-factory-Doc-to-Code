from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from config.settings import settings
from src.storage.database import init_db, AsyncSessionLocal
from src.storage.pattern_seed import seed_patterns_if_needed
from src.api.error_handlers import (
    http_exception_handler, validation_exception_handler, generic_exception_handler
)
from src.api.routes.auth_routes import router as auth_router
from src.api.routes.health_routes import router as health_router
from src.api.routes.project_routes import router as project_router
from src.api.routes.document_routes import router as document_router
from src.api.routes.pattern_routes import router as pattern_router
from src.api.routes.workflow_routes import router as workflow_router
from src.api.routes.ws_hitl import router as ws_hitl_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure directories, initialize SQLite tables, and seed canonical patterns
    settings.ensure_directories()
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_patterns_if_needed(session)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    description="Backend-only AI Agent Factory: Document-Driven, Pattern-Aware Code Generator",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={"persistAuthorization": True},
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception Handlers
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# Root redirect to Swagger UI
@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/docs")

# Include API Routers
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(project_router)
app.include_router(document_router)
app.include_router(pattern_router)
app.include_router(workflow_router)
app.include_router(ws_hitl_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
