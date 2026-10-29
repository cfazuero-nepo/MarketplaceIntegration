"""Auth0 access-token verification and the signed-in user.

Every authenticated route depends on ``get_current_user``. It:
  1. reads ``Authorization: Bearer <access token>`` (401 if missing),
  2. verifies the token: RS256 signature against Auth0's published keys,
     issuer, audience, expiry and required claims (401 if any check fails),
  3. creates or updates the user's row in ``users`` and returns it.

Auth0 owns passwords, password reset and email verification; this service
never sees a password and never stores tokens.

The access token carries the user's email through custom claims added by an
Auth0 Action (see README.md, "Authentication with Auth0").
"""
import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from config import get_settings
from db import get_db
from models import User

# Only asymmetric RS256: rejects "none" and HS256 tokens signed with the public key.
ALGORITHMS = ["RS256"]
# Allowed clock difference between Auth0 and this server, in seconds.
CLOCK_LEEWAY_SECONDS = 30
REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub"]

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user: User
    # From the token on every request, so it reflects Auth0's latest value.
    email_verified: bool


def _unauthorized(detail: str, *, invalid_token: bool = True) -> HTTPException:
    challenge = 'Bearer error="invalid_token"' if invalid_token else "Bearer"
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": challenge})


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """Fetches Auth0's public keys and caches them for an hour (one client per URL)."""
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=10)


def verify_access_token(token: str) -> dict:
    """Return the claims of a valid Auth0 access token, or raise 401/503."""
    settings = get_settings()
    if not settings.auth0_domain or not settings.auth0_audience:
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    issuer = f"https://{settings.auth0_domain}/"

    try:
        signing_key = _jwks_client(f"{issuer}.well-known/jwks.json").get_signing_key_from_jwt(token)
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(status_code=503, detail="Could not reach the identity provider.")
    except jwt.PyJWTError:
        # Malformed token, or signed with a key Auth0 does not publish.
        raise _unauthorized("Invalid access token.")

    try:
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=ALGORITHMS,
            audience=settings.auth0_audience,
            issuer=issuer,
            leeway=CLOCK_LEEWAY_SECONDS,
            options={"require": REQUIRED_CLAIMS},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Access token has expired.")
    except jwt.PyJWTError:
        # Bad signature, audience, issuer or missing claim. Details are not
        # returned, so callers cannot probe which check failed.
        raise _unauthorized("Invalid access token.")


def upsert_user(db: Session, *, subject: str, email: str, display_name: str | None) -> User:
    """Create the user on first sign-in, otherwise refresh their email and name.

    A single INSERT ... ON CONFLICT statement, so two simultaneous first
    requests cannot create duplicate users.
    """
    statement = insert(User).values(
        id=uuid.uuid4(), idp_subject=subject, email=email, display_name=display_name
    )
    statement = (
        statement.on_conflict_do_update(
            index_elements=[User.idp_subject],
            set_={
                "email": statement.excluded.email,
                "display_name": statement.excluded.display_name,
                "updated_at": func.now(),
            },
        )
        .returning(User)
        .execution_options(populate_existing=True)
    )
    user = db.scalars(statement).one()
    db.commit()
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """FastAPI dependency for routes that need a signed-in user."""
    if credentials is None:
        raise _unauthorized("Sign-in required.", invalid_token=False)

    claims = verify_access_token(credentials.credentials)
    namespace = get_settings().auth0_claim_namespace

    email = claims.get(f"{namespace}email")
    if not isinstance(email, str) or not email.strip() or len(email) > 320:
        raise _unauthorized("Access token has no valid email claim.")
    name = claims.get(f"{namespace}name")
    display_name = None
    if isinstance(name, str) and name.strip():
        display_name = name.strip()[:200]

    user = upsert_user(
        db, subject=claims["sub"], email=email.strip().lower(), display_name=display_name
    )
    return CurrentUser(user=user, email_verified=claims.get(f"{namespace}email_verified") is True)
