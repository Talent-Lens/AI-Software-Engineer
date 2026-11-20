"""
Authentication token provider and security dependencies.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from src.db.crud import get_user_by_id
from src.db.models import User
from src.db.session import get_db

AUTH_SECRET = os.getenv("JWT_SECRET_KEY", "fallback-secret-key-3029482934-development-only")
AUTH_ALGO = "HS256"
ACCESS_EXP_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_EXP_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

bearer_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def issue_token(subject: str, token_kind: str, lifetime: timedelta) -> str:
    expires = datetime.now(timezone.utc) + lifetime
    claims = {
        "sub": subject,
        "type": token_kind,
        "exp": expires,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(claims, AUTH_SECRET, algorithm=AUTH_ALGO)


def create_access_token(data: Dict[str, Any]) -> str:
    return issue_token(
        subject=str(data.get("sub", "")),
        token_kind="access",
        lifetime=timedelta(minutes=ACCESS_EXP_MINUTES),
    )


def create_refresh_token(data: Dict[str, Any]) -> str:
    return issue_token(
        subject=str(data.get("sub", "")),
        token_kind="refresh",
        lifetime=timedelta(days=REFRESH_EXP_DAYS),
    )


def parse_token(raw_token: str, required_kind: str = "access") -> Dict[str, Any]:
    unauthorized_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials or session expired",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        decoded = jwt.decode(raw_token, AUTH_SECRET, algorithms=[AUTH_ALGO])
        if decoded.get("type") != required_kind or not decoded.get("sub"):
            raise unauthorized_exc
        return decoded
    except JWTError:
        raise unauthorized_exc


async def get_current_user(
    token: Optional[str] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token missing",
        )
    claims = parse_token(token, required_kind="access")
    uid = claims["sub"]
    user_record = get_user_by_id(db, uid)
    if not user_record or not user_record.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User unavailable or deactivated",
        )
    return user_record
