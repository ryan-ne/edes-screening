"""Shared-password login.

Enabled when APP_PASSWORD is set. Browser users log in once and get a
signed, HttpOnly session cookie. API clients may instead send
`Authorization: Bearer <API_TOKEN>` (if API_TOKEN is set).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings

COOKIE = "session"
SESSION_TTL = 60 * 60 * 12  # 12 hours
PUBLIC_PATHS = {"/login", "/api/health"}

# Brute-force protection: max failures per IP within window
MAX_FAILS = 5
FAIL_WINDOW = 15 * 60
_fails: dict[str, list[float]] = defaultdict(list)


def _secret() -> bytes:
    return settings.secret_key.encode()


def make_token() -> str:
    exp = str(int(time.time()) + SESSION_TTL)
    sig = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    good = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and exp.isdigit() and int(exp) > time.time()


def check_password(pw: str) -> bool:
    return bool(settings.app_password) and hmac.compare_digest(
        pw.encode(), settings.app_password.encode())


def client_ip(request: Request) -> str:
    # Behind Caddy: uvicorn --proxy-headers sets request.client from X-Forwarded-For
    return request.client.host if request.client else "unknown"


def locked_out(ip: str) -> bool:
    now = time.time()
    _fails[ip] = [t for t in _fails[ip] if now - t < FAIL_WINDOW]
    return len(_fails[ip]) >= MAX_FAILS


def record_fail(ip: str) -> None:
    _fails[ip].append(time.time())


def clear_fails(ip: str) -> None:
    _fails.pop(ip, None)


def _bearer_ok(request: Request) -> bool:
    if not settings.api_token:
        return False
    h = request.headers.get("authorization", "")
    return h.startswith("Bearer ") and hmac.compare_digest(h[7:].encode(), settings.api_token.encode())


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.auth_enabled or request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        if valid_token(request.cookies.get(COOKIE)) or _bearer_ok(request):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return RedirectResponse("/login", status_code=303)


def new_secret() -> str:
    return secrets.token_urlsafe(32)
