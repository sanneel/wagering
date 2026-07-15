"""IP geolocation (ipinfo.io) + VPN/proxy detection (IPQualityScore).

Results are cached in Redis to avoid hammering the providers on every request.
"""
import ipaddress
import logging

import httpx

from app.config import settings
from app.redis_client import redis_client

logger = logging.getLogger("geo")

_TIMEOUT = httpx.Timeout(5.0)
_CACHE_TTL = 60 * 60 * 6  # 6h


class GeoResult:
    def __init__(
        self,
        *,
        ip: str,
        country: str | None,
        region_code: str | None,
        is_vpn: bool,
        lookup_ok: bool,
    ):
        self.ip = ip
        self.country = country
        self.region_code = region_code  # e.g. "US-WA"
        self.is_vpn = is_vpn
        self.lookup_ok = lookup_ok


def is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_loopback or addr.is_reserved
    except ValueError:
        return False


async def _ipinfo_lookup(ip: str) -> dict | None:
    url = f"{settings.ipinfo_base}/{ip}/json"
    params = {"token": settings.ipinfo_token} if settings.ipinfo_token else {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("ipinfo lookup %s -> %s", ip, resp.status_code)
    except httpx.HTTPError as exc:
        logger.warning("ipinfo error for %s: %s", ip, exc)
    return None


async def _ipqs_lookup(ip: str) -> dict | None:
    if not settings.ipqs_api_key:
        return None
    url = f"{settings.ipqs_base}/{settings.ipqs_api_key}/{ip}"
    params = {"strictness": 1, "allow_public_access_points": "true"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("ipqs lookup %s -> %s", ip, resp.status_code)
    except httpx.HTTPError as exc:
        logger.warning("ipqs error for %s: %s", ip, exc)
    return None


async def lookup(ip: str) -> GeoResult:
    """Resolve country/region and VPN status for an IP, with Redis caching."""
    cache_key = f"geo:{ip}"
    cached = await redis_client.hgetall(cache_key)
    if cached:
        return GeoResult(
            ip=ip,
            country=cached.get("country") or None,
            region_code=cached.get("region_code") or None,
            is_vpn=cached.get("is_vpn") == "1",
            lookup_ok=cached.get("lookup_ok") == "1",
        )

    ipinfo = await _ipinfo_lookup(ip)
    country = None
    region_code = None
    if ipinfo:
        country = (ipinfo.get("country") or "").upper() or None
        region = ipinfo.get("region")
        if country and region:
            # ipinfo returns full region names; keep a coarse country-scoped key.
            region_code = f"{country}-{_region_abbrev(region)}"

    is_vpn = False
    ipqs = await _ipqs_lookup(ip) if settings.block_vpn else None
    if ipqs:
        is_vpn = bool(
            ipqs.get("vpn") or ipqs.get("proxy") or ipqs.get("tor")
        )

    lookup_ok = ipinfo is not None and (ipqs is not None or not settings.block_vpn)

    await redis_client.hset(
        cache_key,
        mapping={
            "country": country or "",
            "region_code": region_code or "",
            "is_vpn": "1" if is_vpn else "0",
            "lookup_ok": "1" if lookup_ok else "0",
        },
    )
    await redis_client.expire(cache_key, _CACHE_TTL)

    return GeoResult(
        ip=ip,
        country=country,
        region_code=region_code,
        is_vpn=is_vpn,
        lookup_ok=lookup_ok,
    )


# Minimal US state name -> abbrev map for region-level blocking. Extend as needed.
_US_STATES = {
    "washington": "WA", "idaho": "ID", "nevada": "NV", "louisiana": "LA",
    "michigan": "MI", "montana": "MT", "delaware": "DE", "connecticut": "CT",
    "new jersey": "NJ", "pennsylvania": "PA", "west virginia": "WV",
    "arizona": "AZ", "new york": "NY", "tennessee": "TN", "indiana": "IN",
}


def _region_abbrev(region: str) -> str:
    return _US_STATES.get(region.strip().lower(), region.strip().upper()[:2])
