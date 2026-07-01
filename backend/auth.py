"""
Authentication helpers for server-side session auth.
"""

import json
from base64 import b64decode
from http.cookies import SimpleCookie
from typing import Optional

from fastapi import HTTPException, Request, WebSocket
from itsdangerous import BadSignature, TimestampSigner

try:
    from .config import config
except ImportError:
    from config import config


def _read_signed_session_cookie(connection: Request | WebSocket) -> dict:
    """Decode the signed session cookie directly when needed."""
    if not config.SESSION_SECRET:
        return {}

    cookie_header = connection.headers.get("cookie", "")
    if not cookie_header:
        return {}

    cookie = SimpleCookie()
    cookie.load(cookie_header)
    morsel = cookie.get("session")
    if not morsel or not morsel.value:
        return {}

    signer = TimestampSigner(str(config.SESSION_SECRET))
    try:
        payload = signer.unsign(morsel.value.encode("utf-8"))
        return json.loads(b64decode(payload))
    except (BadSignature, ValueError, json.JSONDecodeError):
        return {}


def get_current_user(connection: Request | WebSocket) -> Optional[str]:
    """Return the authenticated username from the signed session cookie."""
    if not config.AUTH_REQUIRED:
        return config.AUTH_USERNAME or "local"

    session = getattr(connection, "session", None) or {}
    user = session.get("user")
    if not user:
        user = _read_signed_session_cookie(connection).get("user")
    if isinstance(user, str) and user.strip():
        return user
    return None


def is_authenticated(connection: Request | WebSocket) -> bool:
    """Check whether the current request/websocket is authenticated."""
    return bool(get_current_user(connection))


def ensure_auth_configured() -> None:
    """Raise a clear error if auth is enabled but missing required secrets."""
    if config.AUTH_REQUIRED and not config.auth_configured():
        raise HTTPException(
            status_code=503,
            detail="Authentication is enabled but not fully configured on the server.",
        )


def require_authenticated_request(request: Request) -> str:
    """Require an authenticated HTTP request and return the username."""
    ensure_auth_configured()
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


async def require_authenticated_websocket(websocket: WebSocket) -> bool:
    """Require an authenticated WebSocket session."""
    try:
        ensure_auth_configured()
    except HTTPException as exc:
        await websocket.close(code=1011, reason=exc.detail)
        return False

    if not is_authenticated(websocket):
        await websocket.close(code=1008, reason="Authentication required.")
        return False
    return True
