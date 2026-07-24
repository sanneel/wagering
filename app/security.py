"""JWT issuance/verification and the current-user dependency."""
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=True)


def create_access_token(user_id: int) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    expires_in = settings.jwt_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict:
    """
    Decode a JWT token and return the payload.
    Raises JWTError if the token is invalid.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        raise


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown user")
    return user


async def get_active_user(user: User = Depends(get_current_user)) -> User:
    """A current user who is not self-excluded — the gate for wagering actions.

    Self-excluded players can still sign in, view, and withdraw; they just can't
    stake money until the exclusion lifts.
    """
    from datetime import datetime, timezone

    excluded = user.self_excluded_until
    if excluded is not None:
        if excluded.tzinfo is None:
            excluded = excluded.replace(tzinfo=timezone.utc)
        if excluded > datetime.now(timezone.utc):
            raise HTTPException(
                status_code=403,
                detail=f"self-excluded until {excluded.date().isoformat()}",
            )
    return user