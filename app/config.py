"""Application configuration loaded from environment / .env."""
from decimal import Decimal
from functools import lru_cache

from pydantic import field_validator
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
    # Create tables on startup (fail-soft). Fine for the demo; use Alembic in a
    # real production deployment instead.
    auto_create_tables: bool = True

    # Comma-separated extra CORS origins to allow (beyond FRONTEND_URL). Handy
    # when the frontend has both a stable and a per-deploy Vercel domain.
    cors_origins: str = ""

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
    #
    # Matches are 100% RTP: the winning side takes the whole pot. The house is
    # paid on withdrawal instead (see withdrawal_fee_percent), so rake stays at
    # 0 — the column and the maths remain, so reintroducing one is config, not
    # a migration.
    rake_percent: Decimal = Decimal("0")
    min_wager: Decimal = Decimal("1.00")
    max_wager: Decimal = Decimal("1000.00")
    min_deposit: Decimal = Decimal("5.00")
    min_withdrawal: Decimal = Decimal("10.00")

    # Charged only on the part of a withdrawal that is ABOVE what the user has
    # deposited and not yet taken back (User.principal). Getting your own money
    # back is free; the house is paid on profit. Taxing gross withdrawals would
    # tax returned principal — a player who deposits 100, wagers it, loses 50
    # and withdraws the rest would pay a fee on their own money.
    withdrawal_fee_percent: Decimal = Decimal("20")

    # Deposits must be wagered through once before they can be withdrawn.
    # Requirement burns down only when a match SETTLES — crediting it at escrow
    # would let anyone open a table, cancel it for a refund, and clear the
    # requirement without ever playing.
    rollover_multiplier: Decimal = Decimal("1")

    # Table formats: seats per side. 1 => 1v1, 2 => 2v2, 5 => 5v5. Nothing in
    # the schema is per-format, so opening a new format is this list plus a
    # label in the frontend's FORMATS map — no migration.
    allowed_team_sizes: str = "1,2,5"

    # ── SpinCounter (1v1 bracket tournaments with a Wheel of Fortune) ──
    #
    # Bracket sizes (players): must be powers of two so the bracket is byeless.
    # 2 => final only, 4 => semis + final, 8 => quarters + semis + final.
    # 2 is intentionally disabled: a 2-player bracket is just one 1v1 with no
    # semifinal suspense, which reads as weak engagement. The code path still
    # supports it — put "2," back at the front of the list to re-enable it.
    spin_sizes: str = "4,8"
    # Buy-in bounds, per player.
    spin_min_entry: Decimal = Decimal("1.00")
    spin_max_entry: Decimal = Decimal("500.00")
    # Rounds each 1v1 is played to (best-of). A player needs (n//2 + 1) wins.
    spin_rounds_best_of: int = 3
    # House rake on the tournament prize pool. 0 keeps SpinCounter 100% RTP like
    # tables — the house is paid on withdrawal, not here.
    spin_rake_percent: Decimal = Decimal("0")

    # Wheel of Fortune segments: `amount:weight` pairs. When the bracket locks
    # the wheel draws one segment (weighted) and awards that amount to a random
    # entrant as a house-funded promotional jackpot — deliberately larger than
    # the buy-in, which is why it can't come out of the pot. The weights govern
    # the house's expected promo cost: bigger prizes carry smaller weights.
    spin_wheel_segments: str = "10:40,20:28,50:18,100:9,250:4,1000:1"
    # Promo bonuses raise the winner's rollover requirement so they can't be
    # cashed straight out — the jackpot has to be wagered through first.
    spin_wheel_rollover: bool = True

    # Trusted proxy IPs that can set X-Forwarded-For. Comma-separated.
    # Only these IPs' X-Forwarded-For headers are trusted for geo lookup.
    # In production, set to your load balancer/reverse proxy IP(s).
    trusted_proxies: str = "127.0.0.1,::1"

    @field_validator("blocked_regions", "geo_exempt_paths")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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

    @property
    def withdrawal_fee_fraction(self) -> Decimal:
        return self.withdrawal_fee_percent / Decimal("100")

    @property
    def allowed_team_sizes_list(self) -> list[int]:
        return sorted(
            {int(s.strip()) for s in self.allowed_team_sizes.split(",") if s.strip()}
        )

    @property
    def spin_sizes_list(self) -> list[int]:
        return sorted(
            {int(s.strip()) for s in self.spin_sizes.split(",") if s.strip()}
        )

    @property
    def spin_rake_fraction(self) -> Decimal:
        return self.spin_rake_percent / Decimal("100")

    @property
    def spin_wheel_list(self) -> list[tuple[Decimal, int]]:
        """(amount, weight) pairs parsed from `spin_wheel_segments`.

        Order is preserved so the frontend wheel and the backend draw agree on
        which segment index maps to which prize.
        """
        out: list[tuple[Decimal, int]] = []
        for pair in self.spin_wheel_segments.split(","):
            pair = pair.strip()
            if not pair:
                continue
            amount, _, weight = pair.partition(":")
            out.append((Decimal(amount.strip()), int(weight.strip() or "1")))
        return out

    @property
    def trusted_proxies_set(self) -> set[str]:
        return {p.strip() for p in self.trusted_proxies.split(",") if p.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
