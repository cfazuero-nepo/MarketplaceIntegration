"""Sign-up and session lookup keep their existing behaviour, now backed by PostgreSQL."""
import datetime
import time
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select, text

import main
from conftest import add_session, make_marketplace_jwt
from models import MarketplaceSignupSession
from signup_sessions import hash_state

TTL = datetime.timedelta(seconds=main.get_settings().signup_session_ttl_seconds)


def signup(client, token):
    return client.post(
        "/marketplace/signup",
        data={"x-gcp-marketplace-token": token},
        follow_redirects=False,
    )


def state_from(response) -> str:
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


# ---- POST /marketplace/signup ------------------------------------------------------
def test_valid_signup_redirects_to_frontend_with_state(client, db):
    response = signup(client, make_marketplace_jwt())

    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == main.FRONTEND_URL
    assert list(parse_qs(location.query)) == ["state"]
    assert len(state_from(response)) == 43


def test_signup_stores_claims_under_the_state_hash(client, db):
    state = state_from(signup(client, make_marketplace_jwt()))

    row = db.scalar(select(MarketplaceSignupSession))
    assert row.state_hash == hash_state(state)
    assert row.procurement_account_id == "procurement-account-123"
    assert row.user_identity == "obfuscated-user-1"
    assert row.roles == ["account_admin"]
    assert row.orders == ["order-1"]
    assert row.expires_at - row.created_at == TTL


def test_signup_never_stores_the_raw_state_or_jwt(client, db):
    token = make_marketplace_jwt()
    state = state_from(signup(client, token))

    # Every column of every row, as text.
    dump = db.execute(text("SELECT row_to_json(s)::text FROM marketplace_signup_sessions s")).scalar()
    assert state not in dump
    assert token not in dump
    assert token.split(".")[2] not in dump  # not even the signature


def test_signup_url_carries_only_state(client, db):
    location = signup(client, make_marketplace_jwt()).headers["location"]

    assert "procurement-account-123" not in location
    assert "obfuscated-user-1" not in location


def test_invalid_token_is_rejected_and_nothing_stored(client, db):
    response = signup(client, "garbage")

    assert response.status_code == 401
    assert response.json()["detail"].startswith("Invalid token")
    assert db.scalar(select(MarketplaceSignupSession)) is None


def test_wrong_audience_is_rejected(client, db):
    assert signup(client, make_marketplace_jwt(aud="evil.example")).status_code == 401


def test_expired_token_is_rejected(client, db):
    now = int(time.time())
    assert signup(client, make_marketplace_jwt(iat=now - 3600, exp=now - 1800)).status_code == 401


def test_wrong_issuer_is_rejected(client, db):
    response = signup(client, make_marketplace_jwt(iss="https://evil.example"))
    assert response.status_code == 401
    assert response.json() == {"detail": "Bad issuer"}


def test_missing_sub_is_rejected(client, db):
    response = signup(client, make_marketplace_jwt(sub=""))
    assert response.status_code == 401
    assert response.json() == {"detail": "Missing sub"}


def test_missing_form_field_is_422(client, db):
    assert client.post("/marketplace/signup", data={}, follow_redirects=False).status_code == 422


# ---- GET /api/marketplace/session/{state} --------------------------------------------
def test_session_after_signup_returns_roles_and_orders_only(client, db):
    state = state_from(signup(client, make_marketplace_jwt()))

    response = client.get(f"/api/marketplace/session/{state}")

    assert response.status_code == 200
    assert response.json() == {"roles": ["account_admin"], "orders": ["order-1"]}


def test_session_with_no_orders_returns_null(client, db):
    state = state_from(signup(client, make_marketplace_jwt(google={"roles": ["project_editor"]})))

    assert client.get(f"/api/marketplace/session/{state}").json() == {
        "roles": ["project_editor"],
        "orders": None,
    }


def test_session_lookup_does_not_consume_state(client, db):
    state = add_session(db)

    first = client.get(f"/api/marketplace/session/{state}")
    second = client.get(f"/api/marketplace/session/{state}")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_unknown_state_is_404(client, db):
    response = client.get(f"/api/marketplace/session/{'u' * 43}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session expired"}


def test_expired_session_is_404(client, db):
    created = datetime.datetime.now(datetime.timezone.utc) - TTL - datetime.timedelta(seconds=1)
    state = add_session(db, created=created)

    response = client.get(f"/api/marketplace/session/{state}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session expired"}


def test_session_just_inside_ttl_is_valid(client, db):
    created = datetime.datetime.now(datetime.timezone.utc) - TTL + datetime.timedelta(seconds=5)
    state = add_session(db, created=created)

    assert client.get(f"/api/marketplace/session/{state}").status_code == 200


def test_cors_allows_frontend_origin_for_session_lookup(client, db):
    state = add_session(db)

    response = client.get(
        f"/api/marketplace/session/{state}", headers={"Origin": main.FRONTEND_ORIGIN}
    )

    assert response.headers["access-control-allow-origin"] == main.FRONTEND_ORIGIN
    assert "access-control-allow-credentials" not in response.headers


def test_healthz_needs_no_database(client):
    assert client.get("/healthz").json() == {"ok": True}
