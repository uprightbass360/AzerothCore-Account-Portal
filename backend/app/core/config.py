from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PORTAL_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./portal.db"
    acore_auth_url: str = "mysql+asyncmy://portal_ro:change-me@ac-mysql:3306/acore_auth"
    soap_url: str = "http://ac-worldserver:7878/"
    soap_user: str = ""
    soap_pass: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = "noreply@example.com"
    smtp_starttls: bool = True
    internal_api_key: str = "change-me"
    public_base_url: str = "http://localhost:3000"
    invite_ttl_days: int = 7
    session_ttl_days: int = 7
    totp_issuer: str = "AzerothCore"
    admin_usernames: str = ""

    @property
    def admin_username_list(self) -> list[str]:
        return [u.strip().upper() for u in self.admin_usernames.split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
