import time
from secrets import token_urlsafe
from threading import Lock
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pymongo import MongoClient
from pymongo.collection import Collection

from app.config import settings


COOKIE_NAME = "traderbot_session"
_SESSIONS: dict[str, dict[str, Any]] = {}
_SESSIONS_LOCK = Lock()
_MONGO_CLIENT: MongoClient | None = None
_MONGO_CLIENT_LOCK = Lock()

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


class GoogleTokenRequest(BaseModel):
    credential: str


class LocalLoginRequest(BaseModel):
    name: str | None = None
    email: str | None = None


def _mongo_sessions_collection() -> Collection | None:
    global _MONGO_CLIENT

    with _MONGO_CLIENT_LOCK:
        if _MONGO_CLIENT is None:
            try:
                _MONGO_CLIENT = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=2000)
                _MONGO_CLIENT.admin.command("ping")
            except Exception:
                _MONGO_CLIENT = None
                return None

    try:
        db = _MONGO_CLIENT[settings.mongodb_db_name]
        collection = db["auth_sessions"]
        collection.create_index("expires_at", expireAfterSeconds=0)
        collection.create_index("token", unique=True)
        return collection
    except Exception:
        return None


def _get_session_data(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None

    collection = _mongo_sessions_collection()
    if collection is not None:
        now = int(time.time())
        doc = collection.find_one({"token": token})
        if not doc:
            return None
        if int(doc.get("expires_at", 0)) <= now:
            collection.delete_one({"token": token})
            return None
        return {
            "user": doc.get("user") or {},
            "expires_at": int(doc.get("expires_at", 0)),
        }

    now = int(time.time())
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(token)
        if not session:
            return None
        if session.get("expires_at", 0) <= now:
            _SESSIONS.pop(token, None)
            return None
        return session


def _create_session(user: dict[str, Any]) -> str:
    ttl = max(300, settings.auth_session_max_age_seconds)
    token = token_urlsafe(32)
    expires_at = int(time.time()) + ttl

    collection = _mongo_sessions_collection()
    if collection is not None:
        collection.replace_one(
            {"token": token},
            {
                "token": token,
                "user": user,
                "expires_at": expires_at,
            },
            upsert=True,
        )
        return token

    with _SESSIONS_LOCK:
        _SESSIONS[token] = {
            "user": user,
            "expires_at": expires_at,
        }
    return token


def _clear_session(token: str | None) -> None:
    if not token:
        return

    collection = _mongo_sessions_collection()
    if collection is not None:
        collection.delete_one({"token": token})
        return

    with _SESSIONS_LOCK:
        _SESSIONS.pop(token, None)


def get_authenticated_user(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(COOKIE_NAME)
    session = _get_session_data(token)
    if not session:
        return None
    return session["user"]


@auth_router.get("/session")
def get_session(request: Request):
    user = get_authenticated_user(request)
    return {
        "authenticated": bool(user),
        "user": user,
        "google_enabled": bool(settings.google_client_id),
        "local_login_enabled": bool(settings.enable_local_login),
    }


@auth_router.post("/google")
def login_with_google(payload: GoogleTokenRequest, response: Response):
    if not settings.google_client_id:
        raise HTTPException(503, "Google login is not configured")

    try:
        idinfo = id_token.verify_oauth2_token(
            payload.credential,
            google_requests.Request(),
            settings.google_client_id,
        )
    except Exception as exc:
        raise HTTPException(401, f"Invalid Google token: {exc}") from exc

    if not idinfo.get("email_verified"):
        raise HTTPException(401, "Google account email is not verified")

    user = {
        "sub": idinfo.get("sub"),
        "name": idinfo.get("name") or idinfo.get("email") or "Trader",
        "email": idinfo.get("email"),
        "picture": idinfo.get("picture"),
    }

    # Auto-create default profile on first login
    user_id = user.get("sub") or user.get("email")
    if user_id:
        try:
            from app.api.profile import _get_or_create_profile
            _get_or_create_profile(user_id)
        except Exception as exc:
            # Profile creation failed, but don't block login
            pass

    session_token = _create_session(user)
    max_age = max(300, settings.auth_session_max_age_seconds)
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_token,
        max_age=max_age,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )

    return {
        "ok": True,
        "user": user,
    }


@auth_router.post("/login")
def login_local(payload: LocalLoginRequest, response: Response):
    """Local fallback login when Google SSO is not configured."""
    if not settings.enable_local_login:
        raise HTTPException(503, "Local login is not enabled")

    raw_name = (payload.name or "").strip()
    raw_email = (payload.email or "").strip().lower()

    user_id = raw_email or f"local-{token_urlsafe(10)}"
    display_name = raw_name or raw_email or "Trader"

    user = {
        "sub": user_id,
        "name": display_name,
        "email": raw_email or None,
        "picture": None,
        "auth_provider": "local",
    }

    # Auto-create default profile on first login
    try:
        from app.api.profile import _get_or_create_profile
        _get_or_create_profile(user_id)
    except Exception as exc:
        # Profile creation failed, but don't block login
        pass

    session_token = _create_session(user)
    max_age = max(300, settings.auth_session_max_age_seconds)
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_token,
        max_age=max_age,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )

    return {
        "ok": True,
        "user": user,
    }


@auth_router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    _clear_session(token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}
