import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthSession, User


router = APIRouter(prefix="/api/auth", tags=["auth"])
GITHUB_API = "https://api.github.com"
SESSION_COOKIE = "prism_session"
STATE_COOKIE = "prism_oauth_state"
SESSION_DAYS = 7

# Shared async HTTP client (created once, reused across requests)
_http_client: httpx.AsyncClient | None = None

# In-memory TTL cache for github_repository_ids: user_id -> (repo_ids, expiry)
_repo_cache: dict[int, tuple[set[int], float]] = {}
_REPO_CACHE_TTL = 60.0  # seconds


async def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def invalidate_repo_cache(user_id: int | None = None) -> None:
    if user_id is None:
        _repo_cache.clear()
    else:
        _repo_cache.pop(user_id, None)


@dataclass
class AuthContext:
    user: User
    access_token: str


def _required_setting(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise HTTPException(status_code=503, detail=f"Server is missing {name}")
    return value


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _secure_cookies() -> bool:
    return os.environ.get("COOKIE_SECURE", "false").lower() == "true"


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not session_token:
        raise HTTPException(status_code=401, detail="Sign in with GitHub to continue")

    session = db.query(AuthSession).filter(
        AuthSession.token_hash == _token_hash(session_token),
        AuthSession.expires_at > datetime.now(timezone.utc),
    ).first()
    if not session:
        raise HTTPException(status_code=401, detail="Your session has expired")

    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Your session is invalid")
    return AuthContext(user=user, access_token=session.github_access_token)


async def github_repository_ids(auth: AuthContext) -> set[int]:
    """Return repos where GitHub says the user has an explicit affiliation.

    Results are cached in-memory for _REPO_CACHE_TTL seconds per user to
    avoid hitting the GitHub API on every request.
    """
    now = time.monotonic()
    cached = _repo_cache.get(auth.user.id)
    if cached and cached[1] > now:
        return cached[0]

    repo_ids: set[int] = set()
    params = {
        "affiliation": "owner,collaborator,organization_member",
        "per_page": 100,
        "page": 1,
    }
    client = await get_http_client()
    while True:
        response = await client.get(
            f"{GITHUB_API}/user/repos",
            headers=_github_headers(auth.access_token),
            params=params,
        )
        if response.status_code == 401:
            _repo_cache.pop(auth.user.id, None)
            raise HTTPException(status_code=401, detail="GitHub authorization expired; sign in again")
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Could not verify repository access with GitHub")
        repos = response.json()
        repo_ids.update(repo["id"] for repo in repos)
        if len(repos) < 100:
            break
        params["page"] += 1

    _repo_cache[auth.user.id] = (repo_ids, now + _REPO_CACHE_TTL)
    return repo_ids


@router.get("/login")
def login(request: Request):
    state = secrets.token_urlsafe(32)
    callback_url = os.environ.get(
        "GITHUB_OAUTH_CALLBACK_URL",
        str(request.url_for("github_oauth_callback")),
    )
    query = urlencode({
        "client_id": _required_setting("GITHUB_CLIENT_ID"),
        "redirect_uri": callback_url,
        "scope": "read:user repo read:org",
        "state": state,
    })
    response = RedirectResponse(f"https://github.com/login/oauth/authorize?{query}")
    response.set_cookie(
        STATE_COOKIE, state, max_age=600, httponly=True,
        secure=_secure_cookies(), samesite="lax", path="/api/auth",
    )
    return response


@router.get("/callback", name="github_oauth_callback")
async def callback(
    code: str,
    state: str,
    request: Request,
    db: Session = Depends(get_db),
):
    expected_state = request.cookies.get(STATE_COOKIE)
    if not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    callback_url = os.environ.get("GITHUB_OAUTH_CALLBACK_URL", str(request.url_for("github_oauth_callback")))
    client = await get_http_client()
    token_response = await client.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": _required_setting("GITHUB_CLIENT_ID"),
            "client_secret": _required_setting("GITHUB_AUTH_SECRET"),
            "code": code,
            "redirect_uri": callback_url,
        },
    )
    token_data = token_response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="GitHub did not authorize this login")
    user_response = await client.get(
        f"{GITHUB_API}/user", headers=_github_headers(access_token),
    )
    if user_response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Could not load your GitHub profile")
    github_user = user_response.json()

    user = db.query(User).filter(User.github_id == github_user["id"]).first()
    if not user:
        user = User(github_id=github_user["id"], login=github_user["login"])
        db.add(user)
        db.flush()
    user.login = github_user["login"]
    user.avatar_url = github_user.get("avatar_url")

    raw_token = secrets.token_urlsafe(48)
    db.add(AuthSession(
        token_hash=_token_hash(raw_token),
        user_id=user.id,
        github_access_token=access_token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
    ))
    db.commit()

    response = RedirectResponse(os.environ.get("FRONTEND_URL", "http://localhost:5173"))
    response.delete_cookie(STATE_COOKIE, path="/api/auth")
    response.set_cookie(
        SESSION_COOKIE, raw_token, max_age=SESSION_DAYS * 86400,
        httponly=True, secure=_secure_cookies(), samesite="lax", path="/",
    )
    return response


@router.get("/me")
def me(auth: AuthContext = Depends(get_current_user)):
    return {
        "id": auth.user.id,
        "github_id": auth.user.github_id,
        "login": auth.user.login,
        "avatar_url": auth.user.avatar_url,
    }


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
):
    if session_token:
        session = db.query(AuthSession).filter(AuthSession.token_hash == _token_hash(session_token)).first()
        if session:
            invalidate_repo_cache(session.user_id)
            db.delete(session)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
