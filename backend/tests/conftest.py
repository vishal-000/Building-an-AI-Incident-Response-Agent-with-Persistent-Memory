"""Pytest test configuration and shared test fixtures."""

import os
from typing import AsyncGenerator
import pytest
from httpx import ASGITransport, AsyncClient

# Ensure testing environment flags
os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["HINDSIGHT_BASE_URL"] = "http://localhost:8888"
os.environ["HINDSIGHT_BANK_ID"] = "test-incident-memory-bank"

from backend.app.config import Settings, settings
from backend.app.database.session import Base, engine
import backend.app.database.models  # Register all models on Base.metadata
from backend.app.main import app


@pytest.fixture(autouse=True)
async def init_tables():
    """Ensures test database tables exist before each test and are clean."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Clean up tables between test runs
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
def test_settings() -> Settings:
    """Fixture providing clean test settings."""
    return settings


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provides an async HTTP client bound to the FastAPI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
