"""
Authentication routes for server-side login/logout/session checks.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

try:
    from ..auth import ensure_auth_configured, get_current_user
    from ..config import config
except ImportError:
    from auth import ensure_auth_configured, get_current_user
    from config import config

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/me")
async def get_session_state(request: Request):
    """Return the current session state for the frontend gate."""
    user = get_current_user(request)
    return {
        "authenticated": bool(user),
        "username": user,
        "auth_required": config.AUTH_REQUIRED,
        "auth_configured": config.auth_configured(),
        "app_mode": config.APP_MODE,
        "capabilities": config.capabilities(),
    }


@router.post("/login")
async def login(payload: LoginRequest, request: Request):
    """Create an authenticated session."""
    ensure_auth_configured()

    username = payload.username.strip()
    password = payload.password

    if username != config.AUTH_USERNAME or password != config.AUTH_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    session = getattr(request, "session", None)
    if session is None:
        raise HTTPException(status_code=503, detail="Session middleware is not active on the server.")

    session.clear()
    session["user"] = username
    return {
        "success": True,
        "username": username,
        "app_mode": config.APP_MODE,
        "capabilities": config.capabilities(),
    }


@router.post("/logout")
async def logout(request: Request):
    """Destroy the current authenticated session."""
    session = getattr(request, "session", None)
    if session is not None:
        session.clear()
    return {"success": True}
