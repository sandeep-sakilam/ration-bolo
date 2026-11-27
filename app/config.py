"""Settings. Every value is optional so the app always starts without keys."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/ration_bolo.db"
    dealer_pin: str = "1234"
    public_base_url: str = ""
    seed_demo: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
