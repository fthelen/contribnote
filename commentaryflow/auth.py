"""
JWT authentication for CommentaryFlow.
Username/password → JWT in localStorage.
IT replaces POST /auth/token with Azure AD MSAL flow.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from . import db

SECRET_KEY = os.getenv("CF_SECRET_KEY", "dev-secret-change-in-production-32chars!!")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8-hour working day

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def authenticate_user(username: str, password: str) -> dict | None:
    user = db.get_user_by_username(username)
    if not user:
        return None
    if not db.verify_password(password, user["hashed_password"]):
        return None
    return user


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.get_user_by_id(user_id)
    if user is None:
        raise credentials_exception
    return user


def require_writer(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] not in ("writer",):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Writer role required"
        )
    return current_user


def require_reviewer(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] not in ("reviewer",):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer role required"
        )
    return current_user


def require_any_role(current_user: dict = Depends(get_current_user)) -> dict:
    return current_user
