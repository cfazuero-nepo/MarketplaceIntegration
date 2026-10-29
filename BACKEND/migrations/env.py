"""Alembic runtime: connects with DATABASE_URL and compares against models.py."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from config import get_settings
from models import Base

config = context.config

# disable_existing_loggers=False keeps the app's loggers (and their filters) working
# when migrations run inside the same process, e.g. in tests.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set. See BACKEND/.env.example.")
    return url


def run_migrations_offline() -> None:
    """Print SQL instead of running it: alembic upgrade head --sql."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
