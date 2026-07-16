"""Thin async client around FACEIT OAuth + Data APIs."""
import logging

import httpx

from app.config import settings

logger = logging.getLogger("faceit")

_TIMEOUT = httpx.Timeout(10.0)


class FaceitError(Exception):
    pass


async def exchange_code(code: str, redirect_uri: str | None = None) -> dict:
    """Exchange an OAuth authorization code for tokens."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri or settings.faceit_redirect_uri,
    }
    auth = (settings.faceit_client_id, settings.faceit_client_secret)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            settings.faceit_oauth_token_url, data=data, auth=auth
        )
    if resp.status_code != 200:
        logger.warning("FACEIT token exchange failed: %s %s", resp.status_code, resp.text)
        raise FaceitError("FACEIT token exchange failed")
    return resp.json()


async def get_userinfo(access_token: str) -> dict:
    """Fetch the OpenID userinfo for the authenticated FACEIT user."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(settings.faceit_oauth_userinfo_url, headers=headers)
    if resp.status_code != 200:
        logger.warning("FACEIT userinfo failed: %s %s", resp.status_code, resp.text)
        raise FaceitError("FACEIT userinfo failed")
    return resp.json()


async def get_player_cs2_elo(faceit_id: str) -> int:
    """Look up a player's current CS2 elo via the Data API (best-effort)."""
    headers = {"Authorization": f"Bearer {settings.faceit_api_key}"}
    url = f"{settings.faceit_api_base}/players/{faceit_id}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            games = resp.json().get("games", {})
            cs2 = games.get("cs2") or games.get("csgo") or {}
            return int(cs2.get("faceit_elo", 0) or 0)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("FACEIT elo lookup failed for %s: %s", faceit_id, exc)
    return 0


async def create_private_match(
    team_a: list[str], team_b: list[str], match_ref: str
) -> str:
    """Create a private CS2 match on FACEIT and return its faceit_match_id.

    Takes a roster per side, so the same call covers 1v1, 2v2 and 5v5 — the
    format is implied by the roster length.

    NOTE: The exact FACEIT matchmaking/hub payload depends on your organizer
    integration. This encapsulates that call so callers stay agnostic. Verify
    the field names against your organizer account before going live.
    """
    size = len(team_a)
    headers = {"Authorization": f"Bearer {settings.faceit_api_key}"}
    payload = {
        "game": "cs2",
        "type": f"{size}v{size}",
        "reference": match_ref,
        "teams": {"faction1": team_a, "faction2": team_b},
        # Kept for 1v1 compatibility with integrations that expect a flat list.
        "players": [*team_a, *team_b],
    }
    url = f"{settings.faceit_api_base}/matches"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code not in (200, 201):
        logger.error("FACEIT match creation failed: %s %s", resp.status_code, resp.text)
        raise FaceitError("FACEIT match creation failed")
    body = resp.json()
    match_id = body.get("match_id") or body.get("id")
    if not match_id:
        raise FaceitError("FACEIT match creation returned no match id")
    return str(match_id)
