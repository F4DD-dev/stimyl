from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def existing_ca_path() -> str | None:
    candidate = Path("certs/russian_trusted_root_ca.pem")
    if candidate.is_file():
        return str(candidate)
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    max_token: str | None = None
    max_webhook_secret: str | None = None
    max_webhook_url: str | None = None
    max_root_ca_path: str | None = None
    session_secret: str = "change-me"
    teacher_max_user_id: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "qwen2.5"
    cookie_secure: bool = False
    app_timezone: str = "Asia/Vladivostok"
    photo_ttl_days: int = 7
    status_repeat_below: float = 0.5
    status_mastered_from: float = 0.8

    @field_validator(
        "max_token",
        "max_webhook_secret",
        "max_webhook_url",
        "llm_base_url",
        "llm_api_key",
        "teacher_max_user_id",
        mode="before",
    )
    @classmethod
    def empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    def resolved_ca_path(self) -> str | None:
        if self.max_root_ca_path:
            return self.max_root_ca_path
        return existing_ca_path()


@lru_cache
def get_settings() -> Settings:
    return Settings()
