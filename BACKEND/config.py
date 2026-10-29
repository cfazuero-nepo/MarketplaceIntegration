"""Settings, read from environment variables.

For local development, values can also come from BACKEND/.env (copy
.env.example). Real environment variables always win over .env, so deployed
environments never depend on that file. No secret has a default here.
"""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    # Expected "aud" claim: the domain that hosts your product (Producer Portal)
    marketplace_audience: str
    # Provider ID used in the Procurement API path
    marketplace_provider_id: str
    # React page the browser is redirected to after the JWT is verified
    frontend_url: str
    # React origin allowed by CORS (scheme + host, no path, no trailing slash)
    frontend_origin: str
    # SQLAlchemy URL, e.g. postgresql+psycopg://user:password@host:5432/db.
    # None until set; the database layer refuses to start without it.
    database_url: str | None
    # How long a verified sign-up stays usable
    signup_session_ttl_seconds: int
    # Auth0 tenant domain without scheme, e.g. your-tenant.eu.auth0.com.
    # None until set; authenticated routes answer 503 without it.
    auth0_domain: str | None
    # Auth0 API identifier: the "aud" every access token must carry
    auth0_audience: str | None
    # Prefix of the custom claims the Auth0 Action adds (see README.md)
    auth0_claim_namespace: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read settings once. Tests call get_settings.cache_clear() after changing env."""
    return Settings(
        marketplace_audience=os.environ.get("MARKETPLACE_AUDIENCE", "example.com"),
        marketplace_provider_id=os.environ.get("MARKETPLACE_PROVIDER_ID", "YOUR_PROVIDER_ID"),
        frontend_url=os.environ.get(
            "FRONTEND_URL", "https://app.example.com/marketplace/signup"
        ),
        frontend_origin=os.environ.get("FRONTEND_ORIGIN", "https://app.example.com"),
        database_url=os.environ.get("DATABASE_URL") or None,
        signup_session_ttl_seconds=int(
            os.environ.get("SIGNUP_SESSION_TTL_SECONDS", str(15 * 60))
        ),
        auth0_domain=os.environ.get("AUTH0_DOMAIN") or None,
        auth0_audience=os.environ.get("AUTH0_AUDIENCE") or None,
        auth0_claim_namespace=os.environ.get(
            "AUTH0_CLAIM_NAMESPACE", "https://marketplace.netpoleon.com/"
        ),
    )
