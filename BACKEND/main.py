"""
Google Cloud Marketplace SaaS - sign-up service (test version)
==============================================================

What this service does
----------------------
Receives Google Cloud Marketplace sign-ups, verifies Google's signed JWT,
and hands the user's browser to the React frontend (hosted on a different
server) with a short-lived, opaque reference called ``state``. Approving the
Marketplace account through the Procurement API is disabled until the service
can authenticate and authorize the caller (see "Approval is disabled" below).

The JWT, the procurement account ID and the user identity never leave this
service. The browser and the React app only ever see ``state``.

End-to-end flow
---------------
 1. User clicks "Register" in Marketplace. Google POSTs the JWT (form field
    ``x-gcp-marketplace-token``) to POST /marketplace/signup.
 2. The service verifies the JWT and stores the claims in PostgreSQL
    (table marketplace_signup_sessions), keyed by a SHA-256 hash of state.
 3. The service answers 303 -> FRONTEND_URL?state=<state>.
 4. The browser does a GET on the React page.
 5. React calls GET  /api/marketplace/session/{state}  (returns roles/orders).
 6. The customer signs in or registers through Auth0, and React calls
    GET /api/me with the Auth0 access token.
 7. (Disabled) approve the account through the Procurement API.

Routes
------
 POST /marketplace/signup               Google -> verify JWT -> 303 to React
 GET  /api/marketplace/session/{state}  React: validate state, show roles
 GET  /api/me                           React: the signed-in user (Auth0 token)
 POST /api/marketplace/approve/{state}  Always 403: approval is disabled
 GET  /healthz                          Kubernetes / ALB health check

Approval is disabled
--------------------
``state`` is a bearer value: it travels in a URL and anyone holding it could
call the API. Approving on possession of ``state`` alone would let anyone who
saw it approve someone else's Procurement account. The approve route therefore
rejects every request with 403, before looking up ``state`` (so it cannot be
used to test whether a state is valid) and without calling Google. It stays
disabled until approval requires an authenticated, authorized user.

Logging
-------
uvicorn's access log records request paths, which contain ``state``. A filter
on the "uvicorn.access" and "uvicorn.error" loggers replaces it with
"[REDACTED]". Logs written outside this process (load balancer access logs,
for example) are not covered: see "Security considerations" in README.md.

Configuration
-------------
Settings are environment variables, read in config.py; see .env.example.
The database layer is in db.py, the tables in models.py, sign-up session
storage in signup_sessions.py, and Auth0 token verification in auth.py. Schema changes go through Alembic
(migrations/). README.md explains how to run everything locally.

Producer Portal "Sign up URL":  https://<your-domain>/marketplace/signup
(must be public HTTPS: Google's request comes from the user's browser).

Known limitations
-----------------
 - Account approval is disabled (see above); no route calls the Procurement
   API.
 - The Procurement API path/body below were written from memory; verify them
   against Google's backend integration guide.
"""
import logging
import re
import time
from functools import lru_cache

import google.auth
import requests
from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from google.auth import jwt as google_jwt
from google.auth.transport.requests import AuthorizedSession
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import CurrentUser, get_current_user
from config import get_settings
from db import get_db
from signup_sessions import create_signup_session, find_active_signup_session

# ---- Config ---------------------------------------------------------------
_settings = get_settings()
# aud claim = the domain that hosts your product (as configured in Producer Portal)
AUDIENCE = _settings.marketplace_audience
# React page (on the OTHER server) the user lands on after the JWT is verified
FRONTEND_URL = _settings.frontend_url
# Origin of the React app, used for CORS (scheme + host, no path, no trailing slash)
FRONTEND_ORIGIN = _settings.frontend_origin
# Your Marketplace provider ID (used in the Procurement API path)
PROVIDER_ID = _settings.marketplace_provider_id

# Both the expected "iss" claim AND the URL that serves Google's public
# signing certificates (JSON: {kid: x509 PEM}).
ISSUER = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "cloud-commerce-partner@system.gserviceaccount.com"
)
PROCUREMENT_BASE = "https://cloudcommerceprocurement.googleapis.com/v1"


# ---- Log redaction ----------------------------------------------------------
# ``state`` appears in the path of /api/marketplace/{session,approve}/{state}
# and in the ?state= query of the frontend URL. Either form is redacted.
_STATE_IN_PATH = re.compile(r"(/api/marketplace/(?:session|approve)/)[^/?#\s\"']+")
_STATE_IN_QUERY = re.compile(r"([?&]state=)[^&#\s\"']+")
REDACTED = "[REDACTED]"


def redact_state(text: str) -> str:
    """Return ``text`` with any Marketplace ``state`` value replaced."""
    text = _STATE_IN_PATH.sub(rf"\g<1>{REDACTED}", text)
    return _STATE_IN_QUERY.sub(rf"\g<1>{REDACTED}", text)


class RedactStateFilter(logging.Filter):
    """Logging filter that removes ``state`` from a record's message and args.

    uvicorn's access log passes the request path as one of the record's args,
    so both the format string and every string argument are redacted.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_state(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_state(a) if isinstance(a, str) else a for a in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                k: redact_state(v) if isinstance(v, str) else v
                for k, v in record.args.items()
            }
        return True


def install_log_redaction() -> None:
    """Attach RedactStateFilter to uvicorn's loggers (once per logger).

    Logger filters survive uvicorn's logging dictConfig, which replaces
    handlers but not filters, so this works whether it runs before or after
    uvicorn configures logging.
    """
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactStateFilter) for f in logger.filters):
            logger.addFilter(RedactStateFilter())


install_log_redaction()

app = FastAPI()

# The React app calls /api/* from a different origin, so allow it explicitly.
# /marketplace/signup is hit by a browser navigation from Google, not by fetch,
# so it doesn't need CORS. Credentials are not allowed, so cookies are never
# sent cross-origin; the React app authenticates with an Authorization header
# instead. CORS only restricts browsers; it is not authentication.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---- JWT verification -------------------------------------------------------
@lru_cache(maxsize=1)
def _certs_cached(bucket: int) -> dict:
    """Download Google's signing certificates ({kid: x509 PEM}).

    ``bucket`` is not used in the body: it only forms the cache key. Because
    the cache holds one entry, a new bucket value evicts the old result and
    forces a fresh download. Raises on a network error or an HTTP error.
    """
    # bucket changes hourly so the cache refreshes (Google rotates keys)
    r = requests.get(ISSUER, timeout=10)
    r.raise_for_status()
    return r.json()  # {kid: x509 PEM}


def get_certs() -> dict:
    """Return Google's certificates, refreshed at most once per hour."""
    return _certs_cached(int(time.time() // 3600))


def verify_marketplace_jwt(token: str) -> dict:
    """Verify a Marketplace JWT and return its claims.

    Checks (matching Google's documentation):
      1. Signature (RS256) against the certificate chosen by the token's
         "kid" header.
      2. "exp" / "iat": the token has not expired.
      3. "aud" equals AUDIENCE (your product domain).
      4. "iss" equals ISSUER.
      5. "sub" (the procurement account ID) is not empty.

    Unknown extra claims are ignored on purpose: Google may add fields.

    Raises HTTPException(401) on any failure. Note that get_certs() is called
    inside the try block, so a failed certificate download is also reported
    as "Invalid token", which can hide a network problem.
    """
    try:
        # Checks signature (by kid), exp/iat, and aud
        claims = google_jwt.decode(token, certs=get_certs(), audience=AUDIENCE)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # google-auth does not check the issuer, so it is checked explicitly.
    if claims.get("iss") != ISSUER:
        raise HTTPException(status_code=401, detail="Bad issuer")
    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Missing sub")
    return claims


# ---- Endpoints --------------------------------------------------------------
# The database routes are plain ``def``: FastAPI runs them in a thread pool,
# so the synchronous database calls do not block other requests.
@app.post("/marketplace/signup")
def marketplace_signup(
    token: str = Form(..., alias="x-gcp-marketplace-token"),
    db: Session = Depends(get_db),
):
    """Sign up URL: the endpoint Google POSTs to (set it in Producer Portal).

    The JWT arrives in the form field "x-gcp-marketplace-token" (the alias is
    needed because that name is not a valid Python identifier; this route
    requires the python-multipart package).

    On success the claims are stored under a new random ``state`` (only its
    hash is saved; the JWT itself is not) and the browser is redirected to
    the React page. Failures: 401 (invalid JWT), 422 (form field missing).
    """
    claims = verify_marketplace_jwt(token)

    # 32 random bytes (about 43 URL-safe characters): unguessable, and
    # meaningless on its own. It only points at the stored sign-up.
    state = create_signup_session(db, claims)

    # 303 turns Google's POST into a GET for the frontend. (FastAPI's default,
    # 307, would repeat the POST, JWT included, against the React server.)
    # Never put the JWT or account IDs in the URL, only the opaque state.
    return RedirectResponse(f"{FRONTEND_URL}?state={state}", status_code=303)


@app.get("/api/marketplace/session/{state}")
def get_session(state: str, db: Session = Depends(get_db)):
    """Frontend calls this to show who is signing up (no secrets returned).

    Returns only "roles" ("account_admin" and/or "project_editor") and
    "orders" (order IDs, or None unless multiple orders of the same product
    are enabled). The account ID and user identity are never returned.
    Does not consume the state. Unknown and expired states both get
    404 "Session expired".
    """
    session = find_active_signup_session(db, state)
    if session is None:
        raise HTTPException(status_code=404, detail="Session expired")
    return {"roles": session.roles, "orders": session.orders}


class MeUser(BaseModel):
    id: str
    email: str
    emailVerified: bool
    name: str | None


class MeResponse(BaseModel):
    user: MeUser


@app.get("/api/me", response_model=MeResponse)
def get_me(response: Response, current: CurrentUser = Depends(get_current_user)):
    """The signed-in user, created in ``users`` on first sign-in.

    Requires ``Authorization: Bearer <Auth0 access token>``. Failures: 401
    (missing, invalid or expired token), 503 (Auth0 unreachable or not
    configured).
    """
    response.headers["Cache-Control"] = "no-store"
    user = current.user
    return MeResponse(
        user=MeUser(
            id=str(user.id),
            email=user.email,
            emailVerified=current.email_verified,
            name=user.display_name,
        )
    )


APPROVAL_DISABLED_DETAIL = (
    "Account approval requires an authenticated, authorized user and is "
    "not available yet."
)


@app.post("/api/marketplace/approve/{state}")
async def approve(state: str):
    """Rejects every request with 403: approval is disabled.

    Possession of ``state`` is not authorization, and this service cannot yet
    authenticate the caller. The route fails closed: it does not look up
    ``state`` (so the response is the same for valid, expired and made-up
    values), does not touch the database, and does not call Google.
    _approve_procurement_account is kept for when approval is re-enabled
    behind authentication and authorization.
    """
    raise HTTPException(status_code=403, detail=APPROVAL_DISABLED_DETAIL)


def _approve_procurement_account(procurement_account_id: str) -> None:
    """Approve an account through the Procurement API. Not called by any route.

    Uses Application Default Credentials (the service account key from
    GOOGLE_APPLICATION_CREDENTIALS). Raises HTTPException(502) if the
    Procurement API returns an error. Only wire this up behind a check that
    the caller is an authenticated user authorized for this account.
    """
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = AuthorizedSession(creds)
    # Verify this path and body against the Procurement API reference.
    url = (
        f"{PROCUREMENT_BASE}/providers/{PROVIDER_ID}"
        f"/accounts/{procurement_account_id}:approve"
    )
    resp = session.post(url, json={"approvalName": "signup"}, timeout=15)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=resp.text)


@app.get("/healthz")
async def healthz():
    """Health check for the Kubernetes probes and the ALB. No dependencies."""
    return {"ok": True}
