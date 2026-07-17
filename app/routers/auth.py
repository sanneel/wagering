"""FACEIT OAuth login/registration + demo login."""
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User
from app.ratelimit import rate_limit
from app.schemas import FaceitAuthRequest, TokenResponse, UserOut
from app.security import create_access_token
from app.services import demo, faceit

logger = logging.getLogger("auth")
router = APIRouter(prefix="/auth", tags=["auth"])


def _frontend_token_redirect(token: str) -> RedirectResponse:
    return RedirectResponse(url=f"{settings.frontend_url}/auth/callback?token={token}")


async def _upsert_user(db: AsyncSession, userinfo: dict) -> User:
    faceit_id = userinfo.get("guid") or userinfo.get("sub")
    username = (
        userinfo.get("nickname")
        or userinfo.get("preferred_username")
        or userinfo.get("name")
        or "unknown"
    )
    avatar = userinfo.get("picture") or userinfo.get("avatar")
    if not faceit_id:
        raise HTTPException(status_code=401, detail="FACEIT userinfo missing id")

    elo = await faceit.get_player_cs2_elo(faceit_id)

    user = (
        await db.execute(select(User).where(User.faceit_id == faceit_id))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            faceit_id=faceit_id,
            faceit_username=username,
            faceit_elo=elo,
            avatar=avatar,
            is_verified=bool(userinfo.get("email_verified", False)),
        )
        db.add(user)
    else:
        user.faceit_username = username
        if avatar:
            user.avatar = avatar
        if elo:
            user.faceit_elo = elo

    await db.commit()
    await db.refresh(user)
    return user


@router.get("/faceit")
async def faceit_start():
    """Begin the FACEIT OAuth flow (the landing button points here).

    In demo mode (or when no OAuth client is configured) we skip FACEIT entirely,
    mint a demo guest, and bounce straight back to the frontend with a token.
    """
    if settings.demo_mode or not settings.faceit_client_id:
        user = await demo.create_demo_user()
        token, _ = create_access_token(user.id)
        return _frontend_token_redirect(token)

    params = {
        "client_id": settings.faceit_client_id,
        "response_type": "code",
        "redirect_uri": settings.faceit_redirect_uri,
        "scope": settings.faceit_oauth_scope,
    }
    return RedirectResponse(
        url=f"{settings.faceit_oauth_authorize_url}?{urlencode(params)}"
    )


@router.get("/faceit/callback")
async def faceit_callback(
    code: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """FACEIT redirects here after the user authorizes; finish login and hand a
    JWT back to the frontend at /auth/callback?token=<jwt>."""
    if error:
        return RedirectResponse(url=f"{settings.frontend_url}/auth/callback?error={error}")
    if not code:
        return RedirectResponse(
            url=f"{settings.frontend_url}/auth/callback?error=missing_code"
        )
    try:
        tokens = await faceit.exchange_code(code)
        access_token = tokens.get("access_token")
        if not access_token:
            raise faceit.FaceitError("no access_token in response")
        userinfo = await faceit.get_userinfo(access_token)
        user = await _upsert_user(db, userinfo)
    except faceit.FaceitError:
        return RedirectResponse(
            url=f"{settings.frontend_url}/auth/callback?error=faceit_auth_failed"
        )

    token, _ = create_access_token(user.id)
    return _frontend_token_redirect(token)


@router.post("/faceit", response_model=TokenResponse)
async def faceit_auth(
    body: FaceitAuthRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    """Programmatic OAuth exchange: trade a code for a JWT + user (JSON)."""
    try:
        tokens = await faceit.exchange_code(body.code, body.redirect_uri)
        access_token = tokens.get("access_token")
        if not access_token:
            raise faceit.FaceitError("no access_token in response")
        userinfo = await faceit.get_userinfo(access_token)
    except faceit.FaceitError as exc:
        raise HTTPException(status_code=401, detail=f"FACEIT auth failed: {exc}")

    user = await _upsert_user(db, userinfo)
    token, expires_in = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/demo",
    response_model=TokenResponse,
    dependencies=[rate_limit(limit=5, window_seconds=60, scope="auth-demo")],
)
async def demo_login() -> TokenResponse:
    """Create a throwaway guest account with a starting balance (demo mode only)."""
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="demo mode disabled")
    user = await demo.create_demo_user()
    token, expires_in = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )
