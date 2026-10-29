"""Alembic migrations: they apply, reverse, and match models.py exactly."""
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

import config
import db as db_module
from conftest import alembic_config
from models import Base


def test_there_is_a_single_head():
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert len(heads) == 1


def test_database_is_at_head(database):
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with database.connect() as conn:
        assert MigrationContext.configure(conn).get_current_revision() == head


def test_migrations_match_the_models(database):
    """If this fails, models.py changed without a migration: run alembic revision --autogenerate."""
    with database.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_downgrade_to_base_and_upgrade_again(database):
    cfg = alembic_config()

    command.downgrade(cfg, "base")
    assert inspect(database).get_table_names() == ["alembic_version"]

    command.upgrade(cfg, "head")
    tables = set(inspect(database).get_table_names())
    assert {t.name for t in Base.metadata.sorted_tables} <= tables


def test_missing_database_url_fails_clearly(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config.get_settings.cache_clear()
    db_module.get_engine.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
            db_module.get_engine()
    finally:
        monkeypatch.undo()
        config.get_settings.cache_clear()
        db_module.get_engine.cache_clear()
