"""Geofencing + VPN-blocking middleware.

For every non-exempt request:
  1. Determine the client IP (honouring X-Forwarded-For when behind a proxy).
  2. Look up country/region via ipinfo.io and VPN/proxy status via IPQualityScore.
  3. Reject with 451 if the region is blocked or (when enabled) a VPN is detected.

Lookups are cached in Redis (see services.geo) so this adds ~0ms for repeat IPs.
"""
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.services import geo

logger = logging.getLogger("geofence")


def _client_ip(request: Request) -> str:
    # Trust the left-most X-Forwarded-For entry only if set by your edge proxy.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else ""


def _is_blocked_region(result: geo.GeoResult) -> bool:
    blocked = settings.blocked_regions_set
    if not blocked:
        return False
    if result.country and result.country in blocked:
        return True
    if result.region_code and result.region_code in blocked:
        return True
    return False


class GeofencingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in settings.geo_exempt_paths_list):
            return await call_next(request)

        ip = _client_ip(request)

        # Local/private IPs (dev, internal health checks) bypass geo checks.
        if not ip or geo.is_private_ip(ip):
            return await call_next(request)

        try:
            result = await geo.lookup(ip)
        except Exception:  # noqa: BLE001 - provider failure must not 500 blindly
            logger.exception("geo lookup crashed for %s", ip)
            if settings.geo_fail_open:
                return await call_next(request)
            return _blocked("geo verification unavailable")

        if not result.lookup_ok and not settings.geo_fail_open:
            return _blocked("could not verify your location")

        if _is_blocked_region(result):
            logger.info("blocked region %s / %s for ip %s",
                        result.country, result.region_code, ip)
            return _blocked("wagering is not available in your region")

        if settings.block_vpn and result.is_vpn:
            logger.info("blocked VPN/proxy for ip %s", ip)
            return _blocked("VPN/proxy connections are not permitted")

        return await call_next(request)


def _blocked(reason: str) -> JSONResponse:
    # 451 Unavailable For Legal Reasons is the correct status for geo-blocking.
    return JSONResponse(status_code=451, content={"detail": reason})
