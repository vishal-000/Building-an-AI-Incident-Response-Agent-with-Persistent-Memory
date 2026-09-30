"""FastAPI application entrypoint for Incident Memory Agent backend."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.v1 import api_v1_router
from backend.app.config import settings
from backend.app.database.session import Base, check_db_health, engine, init_db
import backend.app.database.models  # Ensure all models are registered on Base.metadata
from backend.app.logging_config import logger
from backend.app.memory.hindsight_service import hindsight_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manages application startup and graceful shutdown sequences."""
    logger.info("Initializing Incident Memory Agent backend...")
    logger.info(f"Environment: {settings.ENVIRONMENT} | Log Level: {settings.LOG_LEVEL}")

    # Create tables if not present
    await init_db()
    logger.info("Database tables verified/created.")

    # Check database connectivity on boot
    db_health = await check_db_health()
    if db_health.get("connected"):
        logger.info(
            f"Database initialized successfully: {db_health.get('engine')} (latency: {db_health.get('latency_ms')}ms)"
        )
    else:
        logger.error(f"Database initialization warning: {db_health.get('details')}")

    # Inspect Hindsight connectivity on boot
    hindsight_health = await hindsight_service.check_health()
    if hindsight_health.get("connected"):
        logger.info(
            f"Hindsight Agent Memory connected at {settings.HINDSIGHT_BASE_URL} (API v{hindsight_health.get('api_version')})"
        )
    else:
        logger.warning(
            f"Hindsight memory server not detected at {settings.HINDSIGHT_BASE_URL}. "
            "Memory operations will be unavailable or run in baseline mode until Hindsight is started."
        )

    yield

    logger.info("Shutting down Incident Memory Agent backend...")
    # Clean up database connection pool
    await engine.dispose()
    logger.info("Database engine connections disposed cleanly.")


app = FastAPI(
    title="Incident Memory Agent API",
    description=(
        "Production-grade Incident Response AI Agent leveraging Hindsight agent memory "
        "to retain operational experience, recall historical incident context, and assist SREs."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Centralized Exception Handlers
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Standardized HTTP exception response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "message": exc.detail,
            "path": request.url.path,
        },
    )


from fastapi.encoders import jsonable_encoder

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Standardized validation error response."""
    logger.warning(f"Validation error on {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "status_code": 422,
            "message": "Request validation failed",
            "details": jsonable_encoder(exc.errors()),
            "path": request.url.path,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all unhandled exception handler to prevent leaking raw server internals."""
    logger.error(f"Unhandled exception during {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "message": "Internal server error occurred",
            "path": request.url.path,
        },
    )


# Mount API routers
app.include_router(api_v1_router)


@app.get("/", tags=["Root"])
async def root():
    """Root metadata endpoint with system links."""
    return {
        "name": "Incident Memory Agent API",
        "version": "0.1.0",
        "description": "Memory-driven AI Incident Response Agent powered by Hindsight",
        "documentation": "/docs",
        "health": "/api/v1/health",
    }
