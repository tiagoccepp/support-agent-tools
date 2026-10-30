"""Central configuration for the support-agent service."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings (see ``.env.example``)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    model: str = "gpt-4o-mini"
    mock_mode: bool = True
    max_steps: int = 12
    max_input_chars: int = 4000
    db_path: str = "data/support.db"
    kb_path: str = "data/kb.json"
    log_level: str = "INFO"
    eval_pass_threshold: float = 0.8


settings = Settings()
