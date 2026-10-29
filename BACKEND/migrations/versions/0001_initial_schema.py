"""Initial schema: users, organisations, members, Marketplace sign-ups and links.

Revision ID: 0001
Revises:
Create Date: 2026-10-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idp_subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("idp_subject", name="uq_users_idp_subject"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "organisations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_organisations"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            name="fk_organisations_created_by_user_id_users", ondelete="SET NULL",
        ),
    )

    op.create_table(
        "organisation_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_organisation_members"),
        sa.ForeignKeyConstraint(
            ["organisation_id"], ["organisations.id"],
            name="fk_organisation_members_organisation_id_organisations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_organisation_members_user_id_users", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organisation_id", "user_id", name="uq_organisation_members_organisation_id_user_id"
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member')", name="ck_organisation_members_role"
        ),
    )
    op.create_index("ix_organisation_members_user_id", "organisation_members", ["user_id"])

    op.create_table(
        "marketplace_signup_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("procurement_account_id", sa.String(255), nullable=False),
        sa.Column("user_identity", sa.String(255), nullable=True),
        sa.Column("roles", postgresql.JSONB(), nullable=False),
        sa.Column("orders", postgresql.JSONB(), nullable=True),
        _timestamp("created_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_marketplace_signup_sessions"),
        sa.UniqueConstraint("state_hash", name="uq_marketplace_signup_sessions_state_hash"),
        sa.ForeignKeyConstraint(
            ["claimed_by_user_id"], ["users.id"],
            name="fk_marketplace_signup_sessions_claimed_by_user_id_users", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "char_length(state_hash) = 64", name="ck_marketplace_signup_sessions_state_hash_length"
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_marketplace_signup_sessions_expires_after_created"
        ),
    )
    op.create_index(
        "ix_marketplace_signup_sessions_procurement_account_id",
        "marketplace_signup_sessions", ["procurement_account_id"],
    )
    op.create_index(
        "ix_marketplace_signup_sessions_expires_at", "marketplace_signup_sessions", ["expires_at"]
    )

    op.create_table(
        "marketplace_account_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("procurement_account_id", sa.String(255), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("signup_session_id", sa.Uuid(), nullable=True),
        sa.Column("linked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approval_status", sa.String(20), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_marketplace_account_links"),
        sa.UniqueConstraint(
            "procurement_account_id", name="uq_marketplace_account_links_procurement_account_id"
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"], ["organisations.id"],
            name="fk_marketplace_account_links_organisation_id_organisations", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["signup_session_id"], ["marketplace_signup_sessions.id"],
            name="fk_marketplace_account_links_signup_session_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linked_by_user_id"], ["users.id"],
            name="fk_marketplace_account_links_linked_by_user_id_users", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected')",
            name="ck_marketplace_account_links_approval_status",
        ),
    )
    op.create_index(
        "ix_marketplace_account_links_organisation_id",
        "marketplace_account_links", ["organisation_id"],
    )


def downgrade() -> None:
    op.drop_table("marketplace_account_links")
    op.drop_table("marketplace_signup_sessions")
    op.drop_table("organisation_members")
    op.drop_table("organisations")
    op.drop_table("users")
