"""Typed, environment-driven configuration for ULTRON.

Pydantic settings with a stdlib-only dataclass fallback, so the framework
still boots when optional dependencies are missing. Configuration failures
raise :class:`ConfigurationError` and are logged at CRITICAL level.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from ultron.secrets import resolve_google_api_key

_LOGGER = logging.getLogger(__name__)

GEMINI_BASE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
)


class ConfigurationError(Exception):
    """Raised when runtime configuration is missing or invalid."""


try:  # pragma: no cover - exercised via both paths in tests
    from pydantic import Field, ValidationError
    from pydantic_settings import BaseSettings, SettingsConfigDict

    HAS_PYDANTIC = True
except ImportError:  # pragma: no cover - exercised via both paths in tests
    HAS_PYDANTIC = False


if HAS_PYDANTIC:

    class GoogleAIConfig(BaseSettings):
        """Google AI API configuration with validation."""

        model_config = SettingsConfigDict(env_prefix="ULTRON_", extra="ignore")

        api_keys: list[str] = Field(
            default_factory=list, description="List of Gemini API keys"
        )
        model: str = Field(default="gemini-1.5-flash", description="Gemini model")
        base_url: str = Field(
            default=GEMINI_BASE_URL,
            description="Google AI OpenAI-compatible endpoint",
        )
        max_rpm_per_key: int = Field(
            default=14, ge=1, description="Max requests per minute per key"
        )
        max_rpd_per_key: int = Field(
            default=1400, ge=1, description="Max requests per day per key"
        )
        temperature: float = Field(default=0.3, ge=0.0, le=2.0)
        max_tokens: int = Field(default=3000, ge=1, le=8192)
        timeout_seconds: int = Field(default=120, ge=5, le=300)

        @staticmethod
        def _env_api_keys() -> list[str]:
            """Collect API keys from GOOGLE_API_KEY and GOOGLE_API_KEY_1..10."""
            keys: list[str] = []
            for i in range(1, 11):
                key = os.getenv(f"GOOGLE_API_KEY_{i}", "")
                if not key and i == 1:
                    key = os.getenv("GOOGLE_API_KEY", "")
                if key:
                    keys.append(key)
            return keys

        def load_keys_from_env(self) -> list[str]:
            """Populate ``api_keys`` from the environment if not set."""
            if not self.api_keys:
                self.api_keys = self._env_api_keys()
            return self.api_keys

    class BudgetConfig(BaseSettings):
        """Budget guardrails configuration."""

        model_config = SettingsConfigDict(env_prefix="ULTRON_BUDGET_", extra="ignore")

        max_tokens_per_minute: int = Field(
            default=10000, ge=1, description="Token budget per minute"
        )
        max_tokens_per_hour: int = Field(
            default=100000, ge=1, description="Token budget per hour"
        )
        max_tokens_per_session: int = Field(
            default=500000, ge=1, description="Token budget per session"
        )
        max_cost_per_session_usd: float = Field(
            default=1.0, ge=0.0, description="Max cost in USD"
        )
        warn_at_percent: float = Field(
            default=80.0, ge=0.0, le=100.0, description="Warn at usage percent"
        )

    class DatabaseConfig(BaseSettings):
        """Database configuration."""

        model_config = SettingsConfigDict(env_prefix="ULTRON_DB_", extra="ignore")

        url: str = Field(
            default="sqlite:///ultron_v6.db", description="SQLAlchemy database URL"
        )
        echo: bool = Field(default=False, description="SQL query logging")
        pool_size: int = Field(default=5, ge=1, description="Connection pool size")

    class ULTRONSettings(BaseSettings):
        """Master configuration - validates everything at startup."""

        model_config = SettingsConfigDict(env_prefix="ULTRON_", extra="ignore")

        google_ai: GoogleAIConfig = Field(default_factory=GoogleAIConfig)
        budget: BudgetConfig = Field(default_factory=BudgetConfig)
        database: DatabaseConfig = Field(default_factory=DatabaseConfig)
        max_iterations: int = Field(default=30, ge=1, le=100)
        max_lateral_depth: int = Field(default=2, ge=0, le=5)
        output_max_chars: int = Field(default=4000, ge=500, le=10000)
        cache_ttl_hours: int = Field(default=24, ge=1, le=168)
        log_level: str = Field(default="INFO", description="Logging level")
        target: str = Field(default="", description="Target IP or domain")

    def load_settings(overrides: dict[str, Any] | None = None) -> ULTRONSettings:
        """Load and validate all settings. Fails fast with clear errors.

        Raises ``ConfigurationError`` when required configuration is missing
        so callers (the CLI) can report it and exit cleanly.
        """
        overrides = overrides or {}
        try:
            resolve_google_api_key()
            settings = ULTRONSettings(**overrides)
            settings.google_ai.load_keys_from_env()
            if not settings.google_ai.api_keys:
                _LOGGER.critical("No GOOGLE_API_KEY configured.")
                _LOGGER.critical("  Set with: export GOOGLE_API_KEY='AIza...'")
                _LOGGER.critical(
                    "  Or: export GOOGLE_API_KEY_1='AIza...' "
                    "GOOGLE_API_KEY_2='AIza...'"
                )
                raise ConfigurationError(
                    "No GOOGLE_API_KEY configured. Set GOOGLE_API_KEY or "
                    "GOOGLE_API_KEY_1..GOOGLE_API_KEY_10."
                )
            return settings
        except ValidationError as exc:
            _LOGGER.critical("Configuration validation failed:")
            for error in exc.errors():
                _LOGGER.critical("  - %s: %s", error.get("loc"), error.get("msg"))
            raise ConfigurationError(
                f"Configuration validation failed: {exc}"
            ) from exc

else:

    @dataclass
    class GoogleAIConfig:  # type: ignore[no-redef]
        api_keys: list[str] = field(default_factory=list)
        model: str = "gemini-1.5-flash"
        base_url: str = GEMINI_BASE_URL
        max_rpm_per_key: int = 14
        max_rpd_per_key: int = 1400
        temperature: float = 0.3
        max_tokens: int = 3000
        timeout_seconds: int = 120

        @staticmethod
        def _env_api_keys() -> list[str]:
            keys: list[str] = []
            for i in range(1, 11):
                key = os.getenv(f"GOOGLE_API_KEY_{i}", "")
                if not key and i == 1:
                    key = os.getenv("GOOGLE_API_KEY", "")
                if key:
                    keys.append(key)
            return keys

        def load_keys_from_env(self) -> list[str]:
            if not self.api_keys:
                self.api_keys = self._env_api_keys()
            return self.api_keys

    @dataclass
    class BudgetConfig:  # type: ignore[no-redef]
        max_tokens_per_minute: int = 10000
        max_tokens_per_hour: int = 100000
        max_tokens_per_session: int = 500000
        max_cost_per_session_usd: float = 1.0
        warn_at_percent: float = 80.0

    @dataclass
    class DatabaseConfig:  # type: ignore[no-redef]
        url: str = "sqlite:///ultron_v6.db"
        echo: bool = False
        pool_size: int = 5

    @dataclass
    class ULTRONSettings:  # type: ignore[no-redef]
        google_ai: GoogleAIConfig = field(default_factory=GoogleAIConfig)
        budget: BudgetConfig = field(default_factory=BudgetConfig)
        database: DatabaseConfig = field(default_factory=DatabaseConfig)
        max_iterations: int = 30
        max_lateral_depth: int = 2
        output_max_chars: int = 4000
        cache_ttl_hours: int = 24
        log_level: str = "INFO"
        target: str = ""

    def load_settings(overrides: dict[str, Any] | None = None) -> ULTRONSettings:
        """Manual configuration fallback (no Pydantic installed)."""
        overrides = overrides or {}
        resolve_google_api_key()
        settings = ULTRONSettings(**overrides)
        settings.google_ai.load_keys_from_env()
        if not settings.google_ai.api_keys:
            _LOGGER.critical("No GOOGLE_API_KEY configured.")
            _LOGGER.critical("  Set with: export GOOGLE_API_KEY='AIza...'")
            raise ConfigurationError(
                "No GOOGLE_API_KEY configured. Set GOOGLE_API_KEY or "
                "GOOGLE_API_KEY_1..GOOGLE_API_KEY_10."
            )
        return settings


__all__ = [
    "BudgetConfig",
    "ConfigurationError",
    "DatabaseConfig",
    "GEMINI_BASE_URL",
    "GoogleAIConfig",
    "HAS_PYDANTIC",
    "ULTRONSettings",
    "load_settings",
]
