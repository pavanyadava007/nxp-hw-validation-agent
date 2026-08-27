"""Central configuration for the hardware-validation agent.

Every runtime knob is an environment variable so the same image runs locally
(docker-compose + Postgres), in CI (SQLite), and on Streamlit Cloud (Neon).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # ---- database -------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg2://hwval:hwval@localhost:5432/hwval",
        description="SQLAlchemy URL. Use sqlite:///./hwval.db for a zero-infra demo.",
    )
    db_schema: str = "public"
    sql_echo: bool = False

    # ---- LLM ------------------------------------------------------------
    llm_provider: str = Field(
        default="auto",
        description="auto | anthropic | openai | groq | google | ollama | rulebased",
    )
    llm_model: str = ""
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048
    agent_max_iterations: int = 12

    # ---- safety ---------------------------------------------------------
    sql_read_only: bool = True
    sql_row_limit: int = 500
    maintenance_dry_run: bool = True

    # ---- ML -------------------------------------------------------------
    anomaly_contamination: float = 0.08
    sequence_length: int = 32
    random_seed: int = 42

    # ---- paths ----------------------------------------------------------
    artifacts_dir: Path = REPO_ROOT / "artifacts"

    @property
    def models_dir(self) -> Path:
        return self.artifacts_dir / "models"

    @property
    def figures_dir(self) -> Path:
        return self.artifacts_dir / "figures"

    @property
    def reports_dir(self) -> Path:
        return self.artifacts_dir / "reports"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")

    def ensure_dirs(self) -> None:
        for d in (self.models_dir, self.figures_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


def reset_settings_cache() -> None:
    """Used by tests that mutate the environment."""
    get_settings.cache_clear()


def available_llm_keys() -> dict[str, bool]:
    return {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "groq": bool(os.getenv("GROQ_API_KEY")),
        "google": bool(os.getenv("GOOGLE_API_KEY")),
        "ollama": bool(os.getenv("OLLAMA_BASE_URL")),
    }
