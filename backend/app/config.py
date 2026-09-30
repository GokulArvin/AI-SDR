from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase (used only as a hosted Postgres instance -- see app/db.py)
    database_url: str

    # LLM / research
    gemini_api_key: str
    tavily_api_key: str

    # Gmail OAuth
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8000/gmail/callback"
    token_encryption_key: str

    # App
    backend_public_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    cron_secret: str
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
