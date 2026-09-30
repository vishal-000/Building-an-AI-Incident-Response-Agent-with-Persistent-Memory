"""Async SQLAlchemy database engine, session factory, and lifecycle management."""

import time
from typing import AsyncGenerator, Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from backend.app.config import settings
from backend.app.logging_config import logger


class Base(AsyncAttrs, DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


def _normalize_database_url(url: str) -> str:
    """Ensures database URL uses the appropriate async driver."""
    # Convert postgresql:// or postgres:// to postgresql+asyncpg://
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    # Ensure SQLite uses aiosqlite
    if url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


def create_engine_and_session(db_url: str):
    """Creates an async engine and session factory with driver-specific configurations."""
    normalized_url = _normalize_database_url(db_url)
    engine_kwargs: Dict[str, Any] = {
        "echo": settings.LOG_LEVEL.upper() == "DEBUG",
        "future": True,
    }

    if "sqlite" in normalized_url:
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in normalized_url:
            from sqlalchemy.pool import StaticPool
            engine_kwargs["poolclass"] = StaticPool
    else:
        # PostgreSQL pool configuration
        engine_kwargs["pool_pre_ping"] = True
        engine_kwargs["pool_size"] = 10
        engine_kwargs["max_overflow"] = 20

    engine = create_async_engine(normalized_url, **engine_kwargs)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return engine, session_factory


# Global engine and session factory initialized with application settings
engine, AsyncSessionLocal = create_engine_and_session(settings.DATABASE_URL)


async def init_db() -> None:
    """Creates all database tables defined in Base metadata."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_db_health(test_engine=None) -> Dict[str, Any]:
    """Tests database connectivity and reports latency and engine dialect."""
    target_engine = test_engine or engine
    start_time = time.perf_counter()
    try:
        async with target_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        dialect_name = target_engine.dialect.name
        return {
            "status": "connected",
            "connected": True,
            "engine": dialect_name,
            "latency_ms": latency_ms,
            "details": f"Database connection active ({dialect_name})",
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        dialect_name = getattr(target_engine, "dialect", None)
        engine_str = dialect_name.name if dialect_name else "unknown"
        logger.error(f"Database health check failed: {exc}")
        return {
            "status": "error",
            "connected": False,
            "engine": engine_str,
            "latency_ms": latency_ms,
            "error": str(exc),
            "details": f"Database connection failed: {exc}",
        }
