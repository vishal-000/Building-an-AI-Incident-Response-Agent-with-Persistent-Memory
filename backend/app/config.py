"""Application configuration management using Pydantic Settings."""

from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for Incident Memory Agent backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server Configuration
    BACKEND_HOST: str = Field(default="0.0.0.0", description="Backend bind host")
    BACKEND_PORT: int = Field(default=8000, description="Backend bind port")
    ENVIRONMENT: str = Field(default="development", description="App environment")
    LOG_LEVEL: str = Field(default="INFO", description="Log level")
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
        description="Allowed CORS origins",
    )

    # Database Configuration
    # SQLite by default for zero-docker local dev; PostgreSQL supported seamlessly via DATABASE_URL
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./incident_memory.db",
        description="Async SQLAlchemy database connection string",
    )

    # Hindsight Agent Memory Service Configuration
    HINDSIGHT_BASE_URL: str = Field(
        default="http://localhost:8888",
        description="Base URL for Hindsight memory server or cloud instance",
    )
    HINDSIGHT_API_KEY: Optional[str] = Field(
        default=None,
        description="Optional API key for authenticated Hindsight deployments",
    )
    HINDSIGHT_BANK_ID: str = Field(
        default="incident-memory-bank",
        description="Memory bank namespace for incident operational knowledge",
    )

    # LLM Provider Configuration
    LLM_PROVIDER: str = Field(
        default="openai",
        description="LLM provider: 'openai', 'gemini', 'anthropic', or 'mock'",
    )
    LLM_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Model name/id to query for incident root-cause investigations",
    )
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI API key")
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Google Gemini API key")
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None, description="Anthropic API key")

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


# Cached global settings instance
settings = Settings()
