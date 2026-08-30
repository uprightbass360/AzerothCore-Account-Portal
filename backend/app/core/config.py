from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PORTAL_", env_file=".env", extra="ignore", populate_by_name=True
    )

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
    # Realm display name: email subjects/bodies and the TOTP issuer label in
    # authenticator apps. PORTAL_TOTP_ISSUER is the deprecated pre-rename alias.
    server_name: str = Field(
        default="AzerothCore",
        validation_alias=AliasChoices("PORTAL_SERVER_NAME", "PORTAL_TOTP_ISSUER"),
    )
    admin_usernames: str = ""
    bot_prefixes: str = "RNDBOT,PLAYERBOT"

    @property
    def admin_username_list(self) -> list[str]:
        return [u.strip().upper() for u in self.admin_usernames.split(",") if u.strip()]

    @property
    def bot_prefix_list(self) -> list[str]:
        return [p.strip().upper() for p in self.bot_prefixes.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
