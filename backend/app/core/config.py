"""Application settings and configuration."""
from __future__ import annotations

from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    SECRET_KEY: str
    ACCESS_TOKEN_MINUTES: int = 60
    CORS_ORIGIN: str = "http://localhost:5173"
    STORAGE_DIR: str = "storage"
    MAX_UPLOAD_MB: int = 500
    MAX_WORKERS: int = 1

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if not v or len(v.strip()) < 32:
            raise ValueError("SECRET_KEY is missing or shorter than 32 characters")
        return v.strip()

    @property
    def storage_path(self) -> Path:
        path = Path(self.STORAGE_DIR)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def data_dir(self) -> Path:
        d = self.storage_path / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def logs_dir(self) -> Path:
        d = self.storage_path / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def uploads_dir(self) -> Path:
        d = self.storage_path / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def evidence_dir(self) -> Path:
        d = self.storage_path / "evidence"
        d.mkdir(parents=True, exist_ok=True)
        return d


settings = Settings()
