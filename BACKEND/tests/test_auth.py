"""Auth0 access-token verification and GET /api/me.

Tokens are signed with a local RSA key whose public half is served as a fake
Auth0 JWKS, so the real verification code runs without network access.
"""
import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import func, select, text

import auth
import config
import main
from models import User

SETTINGS = config.get_settings()
ISSUER = f"https://{SETTINGS.auth0_domain}/"
NS = SETTINGS.auth0_claim_namespace
KID = "auth0-test-key"

AUTH0_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(public_key) -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    return {"keys": [{**jwk, "kid": KID, "use": "sig", "alg": "RS256"}]}


@pytest.fixture(autouse=True)
def fake_auth0_jwks(monkeypatch):
    """Serve the test public key as Auth0's JWKS, and start each test with an empty key cache."""
    auth._jwks_client.cache_clear()
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda self: _jwks(AUTH0_KEY.public_key()))
    yield
    auth._jwks_client.cache_clear()


def make_token(*, key=AUTH0_KEY, kid=KID, **overrides) -> str:
    """An Auth0-style access token. Pass claim=None to leave a claim out."""
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": [SETTINGS.auth0_audience, f"{ISSUER}userinfo"],
        "sub": "auth0|alice",
        "iat": now,
        "exp": now + 600,
        "scope": "openid profile email",
        f"{NS}email": "Alice@Example.com",
        f"{NS}email_verified": True,
        f"{NS}name": "Alice Example",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unsigned_token(header: dict, payload: dict, signature: bytes = b"") -> str:
    body = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(payload).encode())}"
    return f"{body}.{_b64(signature)}"


def _valid_payload() -> dict:
    return jwt.decode(make_token(), options={"verify_signature": False})


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- verify_access_token (no database needed) ---------------------------------------
def test_valid_token_returns_claims():
    claims = auth.verify_access_token(make_token())
    assert claims["sub"] == "auth0|alice"


def test_token_with_single_string_audience_is_accepted():
    assert auth.verify_access_token(make_token(aud=SETTINGS.auth0_audience))["sub"] == "auth0|alice"


def test_small_clock_difference_is_tolerated():
    now = int(time.time())
    assert auth.verify_access_token(make_token(exp=now - 10, iat=now - 600))


def _hs256_with_public_key() -> str:
    """Algorithm-confusion attack: HMAC-sign with the public key as the secret."""
    public_pem = AUTH0_KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    header = {"alg": "HS256", "typ": "JWT", "kid": KID}
    body = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(_valid_payload()).encode())}"
    signature = hmac.new(public_pem, body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def _tampered_payload() -> str:
    """A genuine signature on a payload the attacker changed."""
    header, _payload, signature = make_token().split(".")
    payload = {**_valid_payload(), "sub": "auth0|mallory"}
    return f"{header}.{_b64(json.dumps(payload).encode())}.{signature}"


REJECTED_TOKENS = {
    "expired": lambda: make_token(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200),
    "wrong-audience": lambda: make_token(aud="https://some-other-api.example"),
    "wrong-issuer": lambda: make_token(iss="https://evil-tenant.auth0.example/"),
    "missing-sub": lambda: make_token(sub=None),
    "missing-exp": lambda: make_token(exp=None),
    "missing-iat": lambda: make_token(iat=None),
    "missing-aud": lambda: make_token(aud=None),
    "forged-signature-same-kid": lambda: make_token(key=OTHER_KEY),
    "unknown-kid": lambda: make_token(kid="not-published"),
    "alg-none": lambda: _unsigned_token({"alg": "none", "typ": "JWT", "kid": KID}, _valid_payload()),
    "hs256-with-public-key": _hs256_with_public_key,
    "tampered-payload": _tampered_payload,
    "garbage": lambda: "not-a-jwt",
}


@pytest.mark.parametrize("make", REJECTED_TOKENS.values(), ids=REJECTED_TOKENS.keys())
def test_invalid_tokens_are_rejected_with_401(make):
    with pytest.raises(HTTPException) as caught:
        auth.verify_access_token(make())

    assert caught.value.status_code == 401
    assert caught.value.headers == {"WWW-Authenticate": 'Bearer error="invalid_token"'}


def test_expired_token_says_so():
    with pytest.raises(HTTPException) as caught:
        auth.verify_access_token(REJECTED_TOKENS["expired"]())
    assert caught.value.detail == "Access token has expired."


def test_unreachable_auth0_is_503(monkeypatch):
    def unreachable(self):
        raise jwt.PyJWKClientConnectionError("connection refused")

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", unreachable)

    with pytest.raises(HTTPException) as caught:
        auth.verify_access_token(make_token())
    assert caught.value.status_code == 503


def test_missing_auth0_configuration_is_503(monkeypatch):
    monkeypatch.delenv("AUTH0_DOMAIN")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(HTTPException) as caught:
            auth.verify_access_token(make_token())
        assert caught.value.status_code == 503
    finally:
        monkeypatch.undo()
        config.get_settings.cache_clear()


def test_jwks_is_fetched_from_the_configured_tenant(monkeypatch):
    urls = []
    real_init = jwt.PyJWKClient.__init__

    def recording_init(self, uri, *args, **kwargs):
        urls.append(uri)
        real_init(self, uri, *args, **kwargs)

    monkeypatch.setattr(jwt.PyJWKClient, "__init__", recording_init)
    auth.verify_access_token(make_token())

    assert urls == [f"{ISSUER}.well-known/jwks.json"]


# ---- GET /api/me -------------------------------------------------------------------
def user_count(db) -> int:
    return db.scalar(select(func.count()).select_from(User))


def test_me_without_token_is_401(client, db):
    response = client.get("/api/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert user_count(db) == 0


def test_me_with_non_bearer_scheme_is_401(client, db):
    response = client.get("/api/me", headers={"Authorization": "Basic YWxpY2U6c2VjcmV0"})
    assert response.status_code == 401


@pytest.mark.parametrize("name", ["expired", "wrong-audience", "forged-signature-same-kid"])
def test_me_with_invalid_token_is_401_and_creates_no_user(client, db, name):
    response = client.get("/api/me", headers=bearer(REJECTED_TOKENS[name]()))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert user_count(db) == 0


def test_me_creates_the_user_on_first_sign_in(client, db):
    response = client.get("/api/me", headers=bearer(make_token()))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["emailVerified"] is True
    assert body["user"]["name"] == "Alice Example"

    user = db.scalar(select(User))
    assert str(user.id) == body["user"]["id"]
    assert user.idp_subject == "auth0|alice"
    assert user.email == "alice@example.com"


def test_me_updates_the_same_user_on_later_sign_ins(client, db):
    first = client.get("/api/me", headers=bearer(make_token())).json()
    second = client.get(
        "/api/me",
        headers=bearer(make_token(**{f"{NS}email": "alice@new.example", f"{NS}name": "Alice N"})),
    ).json()

    assert second["user"]["id"] == first["user"]["id"]
    assert second["user"]["email"] == "alice@new.example"
    assert second["user"]["name"] == "Alice N"
    assert user_count(db) == 1


def test_different_auth0_users_get_different_rows(client, db):
    client.get("/api/me", headers=bearer(make_token()))
    client.get("/api/me", headers=bearer(make_token(sub="google-oauth2|bob", **{f"{NS}email": "bob@example.com"})))

    assert user_count(db) == 2


def test_me_reports_unverified_email(client, db):
    response = client.get("/api/me", headers=bearer(make_token(**{f"{NS}email_verified": False})))
    assert response.json()["user"]["emailVerified"] is False


def test_me_without_email_claim_is_401(client, db):
    response = client.get("/api/me", headers=bearer(make_token(**{f"{NS}email": None})))

    assert response.status_code == 401
    assert user_count(db) == 0


def test_me_without_name_claim_stores_no_name(client, db):
    response = client.get("/api/me", headers=bearer(make_token(**{f"{NS}name": None})))
    assert response.json()["user"]["name"] is None


def test_access_token_is_never_stored(client, db):
    token = make_token()
    client.get("/api/me", headers=bearer(token))

    dump = db.execute(text("SELECT row_to_json(u)::text FROM users u")).scalar()
    assert token not in dump
    assert token.split(".")[2] not in dump


def test_cors_allows_authorization_header_from_frontend(client):
    response = client.options(
        "/api/me",
        headers={
            "Origin": main.FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers


def test_approval_stays_disabled_for_signed_in_users(client, db):
    response = client.post(f"/api/marketplace/approve/{'s' * 43}", headers=bearer(make_token()))
    assert response.status_code == 403
