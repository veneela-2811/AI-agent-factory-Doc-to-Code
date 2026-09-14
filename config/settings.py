import os
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General App Config
    APP_NAME: str = "AI Agent Factory v2"
    APP_ENV: str = "development"
    DEBUG: bool = True
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # Security & JWT
    JWT_SECRET: str = "super-secret-key-change-in-production-at-least-32-chars-long!"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Storage Paths
    DATA_ROOT: Path = Path("./data")
    SQLITE_DB_PATH: Path = Path("./data/app.db")
    CHECKPOINT_DB_PATH: Path = Path("./data/checkpoints.sqlite")
    CHROMA_PERSIST_DIR: Path = Path("./data/chroma")
    PROVIDERS_CONFIG_PATH: Path = Path("./config/providers.yaml")

    # Ingestion Configuration
    MAX_UPLOAD_SIZE_MB: int = 50
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    ALLOWED_MIME_TYPES: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/markdown",
        "text/plain"
    ]
    ALLOWED_EXTENSIONS: list[str] = [".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt"]

    # LLM Router Settings
    LLM_ROUTING_MODE: str = "development"  # "development" | "production"
    DEFAULT_EMBEDDING_MODEL: str = "text-embedding-3-small"
    FALLBACK_MAX_RETRIES: int = 3
    PROVIDER_COOLDOWN_SECONDS: int = 60

    # Optional API Keys
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    def ensure_directories(self) -> None:
        self.DATA_ROOT.mkdir(parents=True, exist_ok=True)
        self.SQLITE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        (self.DATA_ROOT / "projects").mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
