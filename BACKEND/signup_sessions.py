"""Create and look up Marketplace sign-up sessions.

The raw ``state`` goes to the browser and is never stored: the database keeps
only its SHA-256 hash. ``state`` is 32 random bytes, so a plain hash is enough
(it cannot be brute-forced) and a database leak does not reveal usable states.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import get_settings
from models import MarketplaceSignupSession


def hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_signup_session(db: Session, claims: dict, now: datetime | None = None) -> str:
    """Store the verified JWT claims and return a new raw ``state`` for the browser."""
    now = now or _now()
    state = secrets.token_urlsafe(32)
    google = claims.get("google", {})
    db.add(
        MarketplaceSignupSession(
            state_hash=hash_state(state),
            procurement_account_id=claims["sub"],
            user_identity=google.get("user_identity"),
            roles=google.get("roles", []),
            orders=google.get("orders"),
            created_at=now,
            expires_at=now + timedelta(seconds=get_settings().signup_session_ttl_seconds),
        )
    )
    db.commit()
    return state


def find_active_signup_session(
    db: Session, state: str, now: datetime | None = None
) -> MarketplaceSignupSession | None:
    """Return the unexpired session for ``state``, or None."""
    return db.scalar(
        select(MarketplaceSignupSession).where(
            MarketplaceSignupSession.state_hash == hash_state(state),
            MarketplaceSignupSession.expires_at > (now or _now()),
        )
    )
