"""Shared test setup.

Database tests use a separate PostgreSQL database whose name must end in
"_test": TEST_DATABASE_URL if set, otherwise DATABASE_URL with "_test" added
to the database name. It is created if missing, migrated with Alembic, and
emptied after every test. If PostgreSQL is not reachable, database tests are
skipped (with the reason shown) and the other tests still run.
"""
import datetime
import os
import sys
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from google.auth import crypt
from google.auth import jwt as google_jwt
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402  (loads BACKEND/.env)


def _test_database_url() -> str | None:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("DATABASE_URL")
    if not base:
        return None
    url = make_url(base)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


TEST_DATABASE_URL = _test_database_url()
if TEST_DATABASE_URL:
    if not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
        raise RuntimeError("Refusing to run tests: the test database name must end in '_test'.")
    # Point the app at the test database before it is imported.
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# Fixed Auth0 settings, so a developer's .env never changes test results.
os.environ["AUTH0_DOMAIN"] = "test-tenant.auth0.example"
os.environ["AUTH0_AUDIENCE"] = "https://api.test.example"
os.environ["AUTH0_CLAIM_NAMESPACE"] = "https://claims.test.example/"
config.get_settings.cache_clear()

import db as db_module  # noqa: E402
import main  # noqa: E402
from models import Base, MarketplaceSignupSession  # noqa: E402
from signup_sessions import hash_state  # noqa: E402

# ---- Marketplace JWT signing -------------------------------------------------
KEY_ID = "test-key"


def _make_signing_material():
    """A throwaway RSA key and self-signed certificate, like Google's {kid: PEM}."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-signer")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return crypt.RSASigner.from_string(private_pem, key_id=KEY_ID), {KEY_ID: cert_pem}


SIGNER, CERTS = _make_signing_material()


def make_marketplace_jwt(**overrides) -> str:
    """A Marketplace sign-up JWT signed by the test key; override any claim."""
    now = int(time.time())
    claims = {
        "iss": main.ISSUER,
        "aud": main.AUDIENCE,
        "sub": "procurement-account-123",
        "iat": now,
        "exp": now + 300,
        "google": {
            "roles": ["account_admin"],
            "user_identity": "obfuscated-user-1",
            "orders": ["order-1"],
        },
    }
    claims.update(overrides)
    return google_jwt.encode(SIGNER, claims).decode()


# ---- Database ------------------------------------------------------------------
def alembic_config() -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def _ensure_database_exists(url: str) -> str | None:
    """Create the test database if needed. Returns a reason string on failure."""
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    except Exception as error:  # noqa: BLE001 - any failure means "no database available"
        return f"{type(error).__name__}: {error}".splitlines()[0]
    finally:
        admin.dispose()
    return None


@pytest.fixture(scope="session")
def database():
    """A migrated, empty test database. Skips the test if PostgreSQL is unavailable."""
    if not TEST_DATABASE_URL:
        pytest.skip("No database configured: set DATABASE_URL or TEST_DATABASE_URL (see README).")
    problem = _ensure_database_exists(TEST_DATABASE_URL)
    if problem:
        pytest.skip(f"PostgreSQL is not reachable ({problem}). Start it with docker compose up -d.")
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield db_module.get_engine()


@pytest.fixture
def db(database):
    """A database session for one test. Every table is emptied afterwards."""
    session = db_module.get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        with database.begin() as conn:
            conn.execute(text(f"TRUNCATE {tables} CASCADE"))


def add_session(
    db,
    state: str = "s" * 43,
    *,
    created: datetime.datetime | None = None,
    roles: list[str] | None = None,
    orders: list[str] | None = None,
) -> str:
    """Store a sign-up session directly, as a successful sign-up would."""
    created = created or datetime.datetime.now(datetime.timezone.utc)
    ttl = config.get_settings().signup_session_ttl_seconds
    db.add(
        MarketplaceSignupSession(
            state_hash=hash_state(state),
            procurement_account_id="procurement-account-123",
            user_identity="obfuscated-user-1",
            roles=["account_admin"] if roles is None else roles,
            orders=orders,
            created_at=created,
            expires_at=created + datetime.timedelta(seconds=ttl),
        )
    )
    db.commit()
    return state


# ---- App -----------------------------------------------------------------------
@pytest.fixture(autouse=True)
def no_google(monkeypatch):
    """Use the local signing certificates, and fail the test on any real Google call."""
    monkeypatch.setattr(main, "get_certs", lambda: CERTS)

    def fail(*_args, **_kwargs):
        raise AssertionError("Google must not be called in tests")

    monkeypatch.setattr(main.google.auth, "default", fail)
    monkeypatch.setattr(main.AuthorizedSession, "post", fail)


@pytest.fixture
def client():
    return TestClient(main.app)
