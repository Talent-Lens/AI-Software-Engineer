"""
Authentication router handling account signup, signin, refresh, and profile queries.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.schemas import (
    AuthMessageResponse,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserPublic,
)
from src.api.services.auth_service import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    parse_token,
)
from src.db.crud import (
    authenticate_user,
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    update_last_login,
)
from src.db.models import User
from src.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def handle_register(body: RegisterRequest, db: Session = Depends(get_db)):
    if get_user_by_email(db, body.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )
    if get_user_by_username(db, body.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This username is already taken.",
        )

    user = create_user(
        db=db,
        email=body.email,
        username=body.username,
        password=body.password,
        display_name=body.display_name,
    )

    access_token = create_access_token({"sub": user.id})
    refresh_token = create_refresh_token({"sub": user.id})
    update_last_login(db, user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserPublic(**user.to_dict()),
    )


@router.post("/login", response_model=TokenResponse)
def handle_login(body: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, body.login, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )

    access_token = create_access_token({"sub": user.id})
    refresh_token = create_refresh_token({"sub": user.id})
    update_last_login(db, user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserPublic(**user.to_dict()),
    )


@router.post("/refresh", response_model=TokenResponse)
def handle_refresh(body: RefreshTokenRequest, db: Session = Depends(get_db)):
    claims = parse_token(body.refresh_token, required_kind="refresh")
    user_id = claims["sub"]
    user = get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User session is no longer active.",
        )

    new_access = create_access_token({"sub": user.id})
    new_refresh = create_refresh_token({"sub": user.id})

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        user=UserPublic(**user.to_dict()),
    )


@router.get("/me", response_model=UserPublic)
def get_current_user_profile(user: User = Depends(get_current_user)):
    return UserPublic(**user.to_dict())


@router.post("/logout", response_model=AuthMessageResponse)
def handle_logout():
    return AuthMessageResponse(message="Logged out successfully.")
