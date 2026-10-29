"""The approval endpoint must reject every caller: no authentication exists yet."""
import datetime

import pytest

import db as db_module
import main
from conftest import add_session, make_marketplace_jwt

APPROVE = "/api/marketplace/approve/{}"


# ---- No database needed ----------------------------------------------------------
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer anything"},
        {"Cookie": "session=anything"},
        {"Origin": main.FRONTEND_ORIGIN},
    ],
    ids=["no-credentials", "bearer-token", "cookie", "allowed-origin"],
)
def test_no_request_shape_can_approve(client, headers):
    response = client.post(APPROVE.format("x" * 43), headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": main.APPROVAL_DISABLED_DETAIL}


def test_approve_never_calls_the_procurement_helper(client, monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_approve_procurement_account", lambda *a: calls.append(a))

    client.post(APPROVE.format("x" * 43))

    assert calls == []


def test_approve_does_not_touch_the_database(client, monkeypatch):
    def no_database():
        raise AssertionError("approve must not use the database")

    monkeypatch.setattr(db_module, "get_session_factory", no_database)

    assert client.post(APPROVE.format("x" * 43)).status_code == 403


# ---- With a database -------------------------------------------------------------
def test_approve_with_valid_state_is_rejected_and_session_kept(client, db):
    state = add_session(db)

    assert client.post(APPROVE.format(state)).status_code == 403
    assert client.get(f"/api/marketplace/session/{state}").status_code == 200


def test_response_does_not_reveal_whether_state_exists(client, db):
    valid = add_session(db, "v" * 43)
    expired = add_session(
        db, "e" * 43,
        created=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1),
    )

    responses = [client.post(APPROVE.format(s)) for s in (valid, expired, "u" * 43)]

    assert {r.status_code for r in responses} == {403}
    assert len({r.text for r in responses}) == 1


def test_approval_after_a_real_signup_is_rejected(client, db):
    signup = client.post(
        "/marketplace/signup",
        data={"x-gcp-marketplace-token": make_marketplace_jwt()},
        follow_redirects=False,
    )
    state = signup.headers["location"].split("state=", 1)[1]

    assert client.post(APPROVE.format(state)).status_code == 403
    assert client.get(f"/api/marketplace/session/{state}").status_code == 200
