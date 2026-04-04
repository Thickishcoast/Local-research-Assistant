"""Configuration loading for the research agent service."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven runtime settings."""

    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str | None = Field(default=None, alias="GEMINI_MODEL")
    tavily_api_key: SecretStr | None = Field(default=None, alias="TAVILY_API_KEY")
    sqlite_path: str = Field(default="research_agent.sqlite", alias="SQLITE_PATH")
    local_only: bool = Field(default=True, alias="LOCAL_ONLY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @staticmethod
    def _secret_is_set(value: SecretStr | None) -> bool:
        if value is None:
            return False
        return bool(value.get_secret_value().strip())

    def missing_required_for_research(self) -> list[str]:
        """Return required env vars missing for the app runtime."""
        missing: list[str] = []
        if not self._secret_is_set(self.gemini_api_key):
            missing.append("GEMINI_API_KEY")
        if not (self.gemini_model or "").strip():
            missing.append("GEMINI_MODEL")
        if not self._secret_is_set(self.tavily_api_key):
            missing.append("TAVILY_API_KEY")
        return missing

    def is_research_ready(self) -> bool:
        return not self.missing_required_for_research()