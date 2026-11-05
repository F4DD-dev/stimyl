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

    database_url: str = ""
    max_token: str | None = None
    max_webhook_secret: str | None = None
    max_webhook_url: str | None = None
    max_root_ca_path: str | None = None
    session_secret: str = "change-me"
    teacher_max_user_id: str | None = None
    admin_max_ids: str = ""
    bot_username: str | None = None
    bot_contact_id: int = 0
    allow_id_match: bool = False
    public_base_url: str | None = None
    seed_demo: bool = False
    cors_origins: str = ""
    feature_photo: bool = True
    feature_ocr: bool = False
    feature_quiz: bool = True
    feature_llm: bool = True
    training_aggregate_to_teacher: bool = True
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "google/gemma-4-31b-it:free"
    llm_vision_model: str | None = None
    llm_fallback_models: str = "google/gemma-4-26b-a4b-it:free,nvidia/nemotron-3.5-super-vl:free"
    llm_reasoning: bool = False
    llm_explain_topics: bool = False
    llm_explain_mistakes: bool = False
    llm_verify: bool = True
    llm_timeout: float = 90
    material_max_mb: int = 15
    cookie_secure: bool = False
    dev: bool = False
    env: str = "dev"
    worker_stale_seconds: int = 30
    class_join_requires_approval: bool = True
    first_teacher_bootstrap: bool = False
    database_ssl_ca: str | None = None
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
        "llm_vision_model",
        "teacher_max_user_id",
        "bot_username",
        "public_base_url",
        "database_ssl_ca",
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
