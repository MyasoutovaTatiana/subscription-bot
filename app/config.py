"""Application configuration via environment variables."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from `.env` and process environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(..., min_length=10, description="Telegram Bot API token")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./subscription_bot.db",
        description="SQLAlchemy async database URL",
    )
    timezone: str = Field(default="Europe/Moscow")
    default_reminder_time: str = Field(default="10:00")
    scheduler_interval_minutes: int = Field(default=10, ge=1, le=60)
    log_level: str = Field(default="INFO")

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid timezone: {value}") from exc
        return value

    @field_validator("default_reminder_time")
    @classmethod
    def validate_reminder_time(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("DEFAULT_REMINDER_TIME must be HH:MM")
        hour, minute = parts
        if not (hour.isdigit() and minute.isdigit()):
            raise ValueError("DEFAULT_REMINDER_TIME must be HH:MM")
        h, m = int(hour), int(minute)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("DEFAULT_REMINDER_TIME must be a valid time")
        return f"{h:02d}:{m:02d}"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return upper

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance (validated on first access)."""
    return Settings()
