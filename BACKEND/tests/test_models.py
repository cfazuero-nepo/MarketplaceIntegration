"""Database tables: keys, relationships, constraints and what is never stored."""
import datetime
import uuid

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from models import (
    Base,
    MarketplaceAccountLink,
    MarketplaceSignupSession,
    Organisation,
    OrganisationMember,
    User,
)
from signup_sessions import create_signup_session, find_active_signup_session, hash_state

NOW = datetime.datetime.now(datetime.timezone.utc)


def make_user(db, subject="idp|alice", email="alice@example.com") -> User:
    user = User(idp_subject=subject, email=email)
    db.add(user)
    db.commit()
    return user


def make_org(db, name="Example Ltd") -> Organisation:
    org = Organisation(name=name)
    db.add(org)
    db.commit()
    return org


def make_signup(db, state="s" * 43) -> MarketplaceSignupSession:
    row = MarketplaceSignupSession(
        state_hash=hash_state(state),
        procurement_account_id="acct-1",
        roles=["account_admin"],
        created_at=NOW,
        expires_at=NOW + datetime.timedelta(minutes=15),
    )
    db.add(row)
    db.commit()
    return row


def assert_rejected(db, obj):
    db.add(obj)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ---- Static checks (no database) ---------------------------------------------------
def test_every_table_has_a_uuid_primary_key():
    for table in Base.metadata.sorted_tables:
        (pk,) = table.primary_key.columns
        assert pk.name == "id"
        assert pk.type.python_type is uuid.UUID, table.name


def test_no_table_stores_passwords_tokens_or_raw_state():
    forbidden = ("password", "jwt", "token", "secret")
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            assert not any(word in column.name for word in forbidden), f"{table.name}.{column.name}"
            assert column.name != "state", f"{table.name} stores the raw state"


def test_hash_state_is_sha256_hex():
    digest = hash_state("abc")
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


# ---- Users and organisations ----------------------------------------------------------
def test_ids_are_generated_uuids(db):
    user = make_user(db)
    org = make_org(db)
    assert isinstance(user.id, uuid.UUID)
    assert isinstance(org.id, uuid.UUID)
    assert user.created_at is not None and user.created_at.tzinfo is not None


def test_idp_subject_is_unique(db):
    make_user(db)
    assert_rejected(db, User(idp_subject="idp|alice", email="other@example.com"))


def test_membership_links_user_and_organisation(db):
    user, org = make_user(db), make_org(db)
    db.add(OrganisationMember(organisation=org, user=user, role="owner"))
    db.commit()

    db.expire_all()
    assert [m.user.email for m in db.get(Organisation, org.id).members] == ["alice@example.com"]
    assert db.get(User, user.id).memberships[0].role == "owner"


def test_membership_is_unique_per_user_and_organisation(db):
    user, org = make_user(db), make_org(db)
    db.add(OrganisationMember(organisation_id=org.id, user_id=user.id, role="owner"))
    db.commit()

    assert_rejected(db, OrganisationMember(organisation_id=org.id, user_id=user.id, role="member"))


def test_membership_role_must_be_known(db):
    user, org = make_user(db), make_org(db)
    assert_rejected(db, OrganisationMember(organisation_id=org.id, user_id=user.id, role="superuser"))


def test_membership_requires_existing_user_and_organisation(db):
    assert_rejected(db, OrganisationMember(organisation_id=uuid.uuid4(), user_id=uuid.uuid4()))


def test_deleting_an_organisation_deletes_its_memberships(db):
    user, org = make_user(db), make_org(db)
    db.add(OrganisationMember(organisation_id=org.id, user_id=user.id, role="owner"))
    db.commit()

    db.delete(org)
    db.commit()

    assert db.scalar(select(OrganisationMember)) is None
    assert db.get(User, user.id) is not None


# ---- Marketplace sign-up sessions ---------------------------------------------------
def test_state_hash_is_unique(db):
    make_signup(db)
    assert_rejected(
        db,
        MarketplaceSignupSession(
            state_hash=hash_state("s" * 43),
            procurement_account_id="acct-2",
            roles=[],
            created_at=NOW,
            expires_at=NOW + datetime.timedelta(minutes=15),
        ),
    )


def test_state_hash_must_be_a_sha256_hex_digest(db):
    assert_rejected(
        db,
        MarketplaceSignupSession(
            state_hash="raw-state-value",
            procurement_account_id="acct-1",
            roles=[],
            created_at=NOW,
            expires_at=NOW + datetime.timedelta(minutes=15),
        ),
    )


def test_expiry_must_be_after_creation(db):
    assert_rejected(
        db,
        MarketplaceSignupSession(
            state_hash=hash_state("x" * 43),
            procurement_account_id="acct-1",
            roles=[],
            created_at=NOW,
            expires_at=NOW,
        ),
    )


def test_create_and_find_signup_session(db):
    claims = {"sub": "acct-9", "google": {"roles": ["project_editor"], "orders": ["o-1"]}}

    state = create_signup_session(db, claims, now=NOW)

    found = find_active_signup_session(db, state, now=NOW)
    assert found.procurement_account_id == "acct-9"
    assert found.roles == ["project_editor"]
    assert found.orders == ["o-1"]
    assert found.state_hash == hash_state(state)
    assert find_active_signup_session(db, state, now=found.expires_at) is None
    assert find_active_signup_session(db, "not-the-state", now=NOW) is None


def test_deleting_a_claiming_user_keeps_the_signup(db):
    user = make_user(db)
    signup = make_signup(db)
    signup.claimed_by_user_id, signup.claimed_at = user.id, NOW
    db.commit()

    db.delete(user)
    db.commit()

    db.expire_all()
    assert db.get(MarketplaceSignupSession, signup.id).claimed_by_user_id is None


# ---- Marketplace account links ------------------------------------------------------
def test_link_defaults_to_pending_approval(db):
    org = make_org(db)
    link = MarketplaceAccountLink(procurement_account_id="acct-1", organisation_id=org.id)
    db.add(link)
    db.commit()

    assert link.approval_status == "pending"


def test_procurement_account_links_to_only_one_organisation(db):
    first, second = make_org(db, "First"), make_org(db, "Second")
    db.add(MarketplaceAccountLink(procurement_account_id="acct-1", organisation_id=first.id))
    db.commit()

    assert_rejected(
        db, MarketplaceAccountLink(procurement_account_id="acct-1", organisation_id=second.id)
    )


def test_link_approval_status_must_be_known(db):
    org = make_org(db)
    assert_rejected(
        db,
        MarketplaceAccountLink(
            procurement_account_id="acct-1", organisation_id=org.id, approval_status="done"
        ),
    )


def test_organisation_with_a_link_cannot_be_deleted(db):
    org = make_org(db)
    db.add(MarketplaceAccountLink(procurement_account_id="acct-1", organisation_id=org.id))
    db.commit()

    db.delete(org)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_link_survives_deletion_of_its_signup_session(db):
    org, signup = make_org(db), make_signup(db)
    link = MarketplaceAccountLink(
        procurement_account_id="acct-1", organisation_id=org.id, signup_session_id=signup.id
    )
    db.add(link)
    db.commit()

    db.delete(signup)
    db.commit()

    db.expire_all()
    assert db.get(MarketplaceAccountLink, link.id).signup_session_id is None


def test_database_has_the_expected_tables(db):
    tables = set(inspect(db.get_bind()).get_table_names())
    assert {t.name for t in Base.metadata.sorted_tables} | {"alembic_version"} == tables
