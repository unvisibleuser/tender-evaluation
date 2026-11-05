"""Application settings. All values come from environment (prefix ``TENDER_``) or ``.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TENDER_", env_file=".env", extra="ignore")

    environment: str = Field(default="demo", pattern="^(demo|staging|production|test)$")
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'var' / 'tender.db').as_posix()}"
    storage_root: Path = BACKEND_DIR / "var" / "storage"

    # Officer identity. "dev" = demo login without password (MVP only; refused in production).
    auth_mode: str = Field(default="dev", pattern="^(dev|oidc)$")
    token_secret: str = Field(default="dev-only-insecure-secret-change-me", min_length=16)
    token_ttl_seconds: int = 8 * 3600

    # Base64 32-byte key-encryption key for sealed commercial envelopes.
    # Demo: auto-generated into storage_root/../commercial.kek when empty.
    commercial_master_key: str = ""

    max_upload_bytes: int = 50 * 1024 * 1024
    max_pdf_pages: int = 500
    review_confidence_threshold: float = 0.90
    allow_demo_early_close: bool = True
    cors_origins: list[str] = ["http://localhost:5173"]

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment == "production":
            if self.auth_mode == "dev":
                raise ValueError("auth_mode=dev is not permitted in production")
            if self.token_secret.startswith("dev-only"):
                raise ValueError("token_secret must be set in production")
            if not self.commercial_master_key:
                raise ValueError("commercial_master_key must be provided by a secret manager in production")
            if self.allow_demo_early_close:
                raise ValueError("allow_demo_early_close must be false in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
