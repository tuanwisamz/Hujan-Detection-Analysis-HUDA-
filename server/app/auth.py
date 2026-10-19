"""Clerk session-JWT verification (architecture.md §7).

The role is read from profiles.role (the source of truth). Clerk publicMetadata only
mirrors it so the UI can hide admin routes.
"""

from dataclasses import dataclass, field
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, Request

from . import repo
from .config import get_settings
from .errors import ApiError


@dataclass
class User:
    id: str
    role: str = "user"
    profile: dict = field(default_factory=dict)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@lru_cache
def _jwk_client() -> jwt.PyJWKClient:
    url = get_settings().clerk_jwks_url
    if not url:
        raise ApiError(503, "Auth is not configured (CLERK_JWKS_URL)")
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def verify_token(token: str, jwk_client: jwt.PyJWKClient | None = None) -> dict:
    s = get_settings()
    try:
        key = (jwk_client or _jwk_client()).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=s.clerk_issuer or None,
            options={"require": ["exp", "sub"], "verify_iss": bool(s.clerk_issuer)},
            leeway=10,
        )
    except ApiError:
        raise
    except jwt.PyJWTError as exc:
        raise ApiError(401, f"Invalid session token: {exc}") from exc
    # Clerk sets azp to the origin that requested the token.
    azp = claims.get("azp")
    if azp and azp not in s.allowed_origins:
        raise ApiError(401, "Token was issued for a different origin")
    return claims


def _bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise ApiError(401, "Missing bearer token")
    return header.split(" ", 1)[1].strip()


def current_user(request: Request) -> User:
    cached = getattr(request.state, "user", None)
    if cached:
        return cached
    claims = verify_token(_bearer(request))
    profile = repo.get_profile(claims["sub"]) or {}
    user = User(id=claims["sub"], role=profile.get("role", "user"), profile=profile)
    request.state.user = user
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise ApiError(403, "Admin role required")
    return user


# ---- Clerk Backend API (email lookup on sync, role mirror on promote) ----

def clerk_user(user_id: str) -> dict | None:
    secret = get_settings().clerk_secret_key
    if not secret:
        return None
    r = httpx.get(f"https://api.clerk.com/v1/users/{user_id}",
                  headers={"Authorization": f"Bearer {secret}"}, timeout=10)
    return r.json() if r.status_code == 200 else None


def clerk_set_role(user_id: str, role: str) -> None:
    secret = get_settings().clerk_secret_key
    if not secret:
        return
    httpx.patch(f"https://api.clerk.com/v1/users/{user_id}/metadata",
                headers={"Authorization": f"Bearer {secret}"},
                json={"public_metadata": {"role": role}}, timeout=10).raise_for_status()
