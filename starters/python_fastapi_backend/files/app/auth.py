"""Demo authentication: salted PBKDF2 passwords and HMAC-signed tokens.

Good enough to demo flows locally. Replace with the tech pack's JWT/OTP flow before production;
SECRET_KEY must come from the environment there.
"""
import base64
import hashlib
import hmac
import os
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import User

SECRET_KEY = os.getenv("SECRET_KEY", "local-demo-only")


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    salt, _, _ = stored.partition("$")
    return hmac.compare_digest(hash_password(password, salt), stored)


def make_token(user_id: int) -> str:
    sig = hmac.new(SECRET_KEY.encode(), str(user_id).encode(), hashlib.sha256).digest()
    return f"{user_id}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    uid, _, _ = token.partition(".")
    if not uid.isdigit() or not hmac.compare_digest(make_token(int(uid)), token):
        raise HTTPException(401, "Log in first")
    user = db.get(User, int(uid))
    if user is None or not user.active:
        raise HTTPException(401, "Account not found or blocked")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admins only")
    return user
