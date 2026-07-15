"""Application configuration loaded from environment / .env."""
from decimal import Decimal
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_name: str = "1v1wager"
    environment: str = "development"
    debug: bool = False
    api_base_url: str = "https://api.1v1wager.com"
    # Where the browser app lives — OAuth callback redirects here with ?token=.
    frontend_url: str = "http://localhost:5173"

    # Demo mode: bypass real FACEIT/Payed calls so the app is clickable end-to-end.
    demo_mode: bool = True
    demo_start_balance: Decimal = Decimal("500.00")

    # Security
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # Database
    database_url: str = "postgresql+asyncpg://wager:wager@localhost:5432/onev1wager"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    # Set false to run without Redis (demo/local). Match-state caching and
    # webhook idempotency become no-ops — do not disable in production.
    redis_enabled: bool = True

    # FACEIT
    faceit_client_id: str = ""
    faceit_client_secret: str = ""
    # redirect_uri FACEIT calls back after the user authorizes.
    faceit_redirect_uri: str = "http://localhost:8000/auth/faceit/callback"
    faceit_api_key: str = ""
    faceit_webhook_secret: str = ""
    faceit_oauth_authorize_url: str = "https://accounts.faceit.com"
    faceit_oauth_scope: str = "openid profile email"
    faceit_oauth_token_url: str = "https://api.faceit.com/auth/v1/oauth/token"
    faceit_oauth_userinfo_url: str = (
        "https://api.faceit.com/auth/v1/resources/userinfo"
    )
    faceit_api_base: str = "https://open.faceit.com/data/v4"

    # Payed.co
    payed_api_key: str = ""
    payed_api_secret: str = ""
    payed_api_base: str = "https://api.payed.co/v1"
    payed_webhook_secret: str = ""
    deposit_return_url: str = "https://1v1wager.com/wallet/deposit/complete"
    withdrawal_return_url: str = "https://1v1wager.com/wallet/withdraw/complete"

    # ipinfo
    ipinfo_token: str = ""
    ipinfo_base: str = "https://ipinfo.io"

    # IPQualityScore
    ipqs_api_key: str = ""
    ipqs_base: str = "https://ipqualityscore.com/api/json/ip"

    # Geofencing
    blocked_regions: str = ""
    block_vpn: bool = True
    geo_fail_open: bool = False
    geo_exempt_paths: str = "/health,/webhook/faceit,/webhook/payed,/docs,/openapi.json"

    # Economics
    rake_percent: Decimal = Decimal("10")
    min_wager: Decimal = Decimal("1.00")
    max_wager: Decimal = Decimal("1000.00")
    min_deposit: Decimal = Decimal("5.00")
    min_withdrawal: Decimal = Decimal("10.00")

    @field_validator("blocked_regions", "geo_exempt_paths")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def blocked_regions_set(self) -> set[str]:
        return {
            r.strip().upper() for r in self.blocked_regions.split(",") if r.strip()
        }

    @property
    def geo_exempt_paths_list(self) -> list[str]:
        return [p.strip() for p in self.geo_exempt_paths.split(",") if p.strip()]

    @property
    def rake_fraction(self) -> Decimal:
        return self.rake_percent / Decimal("100")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
