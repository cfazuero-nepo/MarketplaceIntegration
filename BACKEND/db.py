"""Database connection: one engine per process, one session per request."""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the engine on first use, so importing the app needs no database."""
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set. See BACKEND/.env.example.")
    # pool_pre_ping replaces connections the database has closed (e.g. after a restart).
    return create_engine(url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: a session that is closed when the request ends."""
    with get_session_factory()() as session:
        yield session
