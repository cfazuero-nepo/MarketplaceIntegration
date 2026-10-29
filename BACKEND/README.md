# Marketplace Back-end Service: main.py Documentation

October 22, 2026

## Overview

`main.py` is a FastAPI service that receives Google Cloud Marketplace sign-ups, verifies Google's signed JWT, and hands the user's browser to your React app with a short-lived reference to the verified sign-up.

It does three jobs:

- Receives the `POST` Google sends to your Sign up URL, with the JWT in the `x-gcp-marketplace-token` form field.
- Verifies the JWT (signature, expiry, audience, issuer, subject) and stores the claims server-side.
- Will approve the customer's procurement account through the Procurement API once registration is complete. **This is currently disabled:** the approve route rejects every request with `403` until the service can authenticate and authorize the caller (see [Approval is disabled](#post-apimarketplaceapprovestate)).

The service does not create customer accounts. That belongs to your product and happens on the React page, after the session lookup.

| Component | Role | Runs on |
| --- | --- | --- |
| Google Cloud Marketplace | Sends the signed JWT by browser `POST` to the Sign up URL | Google |
| FastAPI service (`main.py`) | Verifies the JWT, keeps the claims, calls the Procurement API | AWS EKS |
| React frontend | Looks up the sign-up, collects registration | Separate server |
| Procurement API | Records the account approval | Google |

## End-to-end flow

A sign-up crosses three parties in six steps today, and only the opaque `state` value ever reaches the browser or the React app. Approval through the Procurement API is disabled until it can be tied to an authenticated, authorized user.

```mermaid
sequenceDiagram
    participant B as Browser
    participant F as FastAPI service
    participant R as React app
    B->>F: 1 POST sign-up + JWT
    Note over F: 2 Verify, store claims
    F->>B: 3 303 redirect, state
    B->>R: 4 GET page with state
    R->>F: 5 GET session by state
    F-->>R: 6 roles, orders
    Note over R,F: Approval disabled (403)
```

Steps 1 to 4 run when the customer clicks Register in Marketplace; steps 5 and 6 run on the React page. The JWT is seen only in steps 1 and 2, and dashed arrows are responses.

## Configuration

Settings are environment variables, read once by `config.py`. For local development they can also live in `BACKEND/.env` (copy `.env.example`); real environment variables always take precedence, and `.env` is git-ignored. No secret has a default in code.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | none (required) | SQLAlchemy URL, e.g. `postgresql+psycopg://user:password@host:5432/db`. The app fails with a clear error on the first database request if it is missing. |
| `MARKETPLACE_AUDIENCE` | `example.com` | Expected `aud` claim: the domain that hosts your product, as configured in Producer Portal |
| `MARKETPLACE_PROVIDER_ID` | `YOUR_PROVIDER_ID` | Provider ID used in the Procurement API path when approving an account |
| `FRONTEND_URL` | `https://app.example.com/marketplace/signup` | React page the browser is redirected to after verification |
| `FRONTEND_ORIGIN` | `https://app.example.com` | React origin allowed by CORS: scheme and host only, no path or trailing slash |
| `SIGNUP_SESSION_TTL_SECONDS` | `900` | How long a verified sign-up stays usable |
| `TEST_DATABASE_URL` | `DATABASE_URL` + `_test` | Tests only. The database name must end in `_test`. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | none | Local Docker Compose only |
| `GOOGLE_APPLICATION_CREDENTIALS` | none | Read by `google-auth`, not by `main.py`: path to the service account key used for the Procurement API call |

Two constants are fixed in the code:

- `ISSUER`: the `cloud-commerce-partner@system.gserviceaccount.com` certificate URL. It is both the expected `iss` claim and the place the signing certificates are fetched from.
- `PROCUREMENT_BASE`: `https://cloudcommerceprocurement.googleapis.com/v1`.

## Running locally

You need Python 3.12 and Docker (for PostgreSQL). All commands run from `BACKEND/`. The `export` lines are not needed: the app, Alembic and Docker Compose all read `.env`.

**1. Create your local settings.** Then edit `.env` and replace both `change-me` values with the same new local password (one in `POSTGRES_PASSWORD`, one inside `DATABASE_URL`).

```bash
cp .env.example .env
```

**2. Start PostgreSQL** (local only, listening on `127.0.0.1:5432`), and wait until it reports `healthy`:

```bash
docker compose up -d
docker compose ps
```

**3. Install the Python packages**, ideally in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

**4. Create the tables:**

```bash
alembic upgrade head
alembic current                    # shows: 0001 (head)
```

**5. Start FastAPI:**

```bash
uvicorn main:app --reload --port 8080
```

**6. Check it:**

```bash
curl http://localhost:8080/healthz                                   # {"ok":true}
curl -i -X POST http://localhost:8080/marketplace/signup -d "x-gcp-marketplace-token=garbage"   # 401
curl -i http://localhost:8080/api/marketplace/session/unknown        # 404 Session expired
curl -i -X POST http://localhost:8080/api/marketplace/approve/unknown   # 403
```

**7. Run the tests** (they create and use a separate `marketplace_test` database):

```bash
python -m pytest
```

To stop PostgreSQL: `docker compose down` (data kept) or `docker compose down -v` (data deleted).

Google can only reach a public HTTPS URL, so a real Marketplace sign-up needs a deployed service or a tunnel such as ngrok or cloudflared.

### Changing the database schema

1. Edit `models.py`.
2. `alembic revision --autogenerate -m "describe the change"` creates a file in `migrations/versions/`. Read it and fix anything Alembic guessed wrong.
3. `alembic upgrade head` applies it. `alembic downgrade -1` undoes the last one.
4. `alembic check` (and the `test_migrations_match_the_models` test) fail if `models.py` and the migrations disagree.

## Code reference

| File | What it does |
| --- | --- |
| `main.py` | The FastAPI app: routes, CORS, JWT verification, log redaction |
| `config.py` | Reads the environment variables above |
| `db.py` | Creates the database engine on first use; `get_db` gives each request its own session |
| `models.py` | The database tables |
| `signup_sessions.py` | Creates and finds sign-up sessions by the hash of `state` |
| `migrations/` | Alembic migrations (`versions/0001_initial_schema.py` creates every table) |
| `docker-compose.yml` | Local PostgreSQL only; not used in AWS |
| `tests/` | Automated tests |

The database routes are plain `def` functions: FastAPI runs them in a thread pool, so the synchronous SQLAlchemy calls do not block other requests.

### CORS middleware

`CORSMiddleware` allows only `FRONTEND_ORIGIN`, with `GET` and `POST` and the `Content-Type` header. It is needed because the React app calls `/api/*` from a different origin. `/marketplace/signup` does not need it: Google's request is a browser navigation, not a `fetch`. Credentials are not allowed, so cookies are never sent cross-origin.

### Certificate cache: `get_certs()` and `_certs_cached(bucket)`

Google signs each JWT with a key identified by `kid`. The public certificates for those keys are published at the `ISSUER` URL as a JSON object mapping `kid` to an X.509 PEM certificate.

- `_certs_cached` downloads that JSON with a 10-second timeout and raises on an HTTP error.
- It is wrapped in `lru_cache(maxsize=1)` and keyed on `bucket`, so the same result is reused until the bucket changes.
- `get_certs()` passes `int(time.time() // 3600)` as the bucket, so the cache refreshes once an hour. This keeps up with Google's key rotation without a download per request.

### JWT verifier: `verify_marketplace_jwt(token)`

Returns the decoded claims, or raises `HTTPException(401)`.

1. `google.auth.jwt.decode` picks the certificate by the token's `kid` and verifies the RS256 signature. It also checks `exp` and `iat`, and that `aud` equals `MARKETPLACE_AUDIENCE`. Any failure is returned as `401 Invalid token: <reason>`.
2. `iss` must equal `ISSUER` exactly, otherwise `401 Bad issuer`. The library does not check this, so the code does.
3. `sub` (the procurement account ID) must be non-empty, otherwise `401 Missing sub`.

Extra claims Google may add later are ignored, as Google's documentation requires. Because `get_certs()` is called inside the same `try` block as the decode, a failed certificate download also surfaces as a `401 Invalid token`, which can hide a network problem.

### Database tables (`models.py`)

Every table has a UUID `id`, timezone-aware timestamps, foreign keys and named constraints. **No table stores passwords, raw JWTs or the raw `state`.** Passwords will belong to the identity provider; the JWT is verified and discarded.

| Table | Purpose | Key rules |
| --- | --- | --- |
| `users` | A person who signs in (filled in once authentication exists) | `idp_subject` unique (the identity provider's user ID) |
| `organisations` | A customer company | `created_by_user_id` → `users`, set to null if the user is deleted |
| `organisation_members` | Which users belong to which organisation | Unique (`organisation_id`, `user_id`); `role` is `owner`, `admin` or `member`; deleted with the organisation or user |
| `marketplace_signup_sessions` | A verified Marketplace sign-up (replaces the old in-memory `SESSIONS`) | `state_hash` unique and exactly 64 hex characters; `expires_at` after `created_at`; `claimed_by_user_id` for a later milestone |
| `marketplace_account_links` | Which organisation owns a Procurement account | `procurement_account_id` unique (one owner per account); an organisation with a link cannot be deleted; `approval_status` is `pending`, `approved` or `rejected` (record only: nothing approves yet) |

What a sign-up session holds:

| Column | Source | Returned to the frontend |
| --- | --- | --- |
| `state_hash` | SHA-256 of the random `state` | No |
| `procurement_account_id` | JWT `sub` | No |
| `roles` | JWT `google.roles` | Yes |
| `user_identity` | JWT `google.user_identity` | No |
| `orders` | JWT `google.orders` (only with multiple orders enabled, otherwise `null`) | Yes |
| `created_at`, `expires_at` | Server clock; `expires_at` = `created_at` + `SIGNUP_SESSION_TTL_SECONDS` | No |

### Sign-up session storage (`signup_sessions.py`)

- `create_signup_session(db, claims)` generates `state = secrets.token_urlsafe(32)`, stores the claims under `hash_state(state)` (hex SHA-256), and returns the raw `state` for the redirect. A plain hash is enough because `state` is 256 random bits: it cannot be brute-forced, and a database leak reveals no usable `state`.
- `find_active_signup_session(db, state)` hashes the incoming `state` and returns the row only if `expires_at` is in the future.

Expired rows are not deleted automatically; see the hardening checklist.

### Log redaction: `redact_state`, `RedactStateFilter`, `install_log_redaction()`

uvicorn's access log writes every request path, and the session and approve paths contain `state`. At import, `install_log_redaction()` attaches `RedactStateFilter` to the `uvicorn.access` and `uvicorn.error` loggers. The filter rewrites each record's message and arguments through `redact_state`, which replaces the value in `/api/marketplace/session/<state>`, `/api/marketplace/approve/<state>` and any `?state=` / `&state=` query parameter with `[REDACTED]`:

```text
203.0.113.5:1234 - "GET /api/marketplace/session/[REDACTED] HTTP/1.1" 200
```

Logger filters survive uvicorn's logging `dictConfig` (which replaces handlers, not filters), so this works with the Dockerfile's `uvicorn main:app` command. It only covers logs written by this process; see [Remaining log exposure](#remaining-log-exposure-outside-the-application).

## Endpoint reference

The service exposes four routes: one for Google, two for the React app, and one health check.

| Route | Caller | Input | Success | Errors |
| --- | --- | --- | --- | --- |
| `POST /marketplace/signup` | Google, through the user's browser | Form field `x-gcp-marketplace-token` | `303` redirect to `FRONTEND_URL?state=<state>` | `401` invalid JWT; `422` field missing |
| `GET /api/marketplace/session/{state}` | React app | `state` in the path | `200` JSON `{roles, orders}` | `404` unknown or expired |
| `POST /api/marketplace/approve/{state}` | Nobody (disabled) | `state` in the path | none | Always `403` |
| `GET /healthz` | Kubernetes probes, ALB | none | `200` JSON `{"ok": true}` | none |

### `POST /marketplace/signup`

This is the URL you enter as the Sign up URL in Producer Portal. The handler reads the JWT from the form field (declared with `alias="x-gcp-marketplace-token"` because the name is not a valid Python identifier), runs `verify_marketplace_jwt`, then creates a session:

```python
state = create_signup_session(db, claims)   # stores only sha256(state)
return RedirectResponse(f"{FRONTEND_URL}?state={state}", status_code=303)
```

`303 See Other` tells the browser to turn Google's `POST` into a `GET` on the React page. FastAPI's default of `307` would repeat the `POST`, JWT included, against your frontend server, which is what this design avoids. Only `state` appears in the URL; the JWT, account ID and `user_identity` stay on the server.

### `GET /api/marketplace/session/{state}`

The React page calls this on load. It confirms the sign-up is real and unexpired and returns only `roles` and `orders`. The account ID and `user_identity` are never returned.

### `POST /api/marketplace/approve/{state}`

**Approval is disabled.** Every request gets:

```json
HTTP 403
{"detail": "Account approval requires an authenticated, authorized user and is not available yet."}
```

Previously this route approved the Procurement account for anyone who presented a valid `state`. `state` travels in a URL, so possession of it is not proof of who the caller is, and anyone who saw it within 15 minutes could approve someone else's account. The route now fails closed:

- It does not look `state` up, so valid, expired and made-up values get the same response and the route cannot be used to test whether a `state` is live.
- It does not delete or expire the session, so the customer's sign-up keeps working.
- It does not load credentials or call the Procurement API.

The Procurement call itself is kept in `_approve_procurement_account(procurement_account_id)`, which no route calls. Re-enable approval only behind an authenticated user who is authorized for the account (and, if required, whose session `roles` include `account_admin`), checked in the backend. The approve path and body in that helper were written from memory of the Procurement API; confirm them against Google's backend integration guide before relying on them.

### `GET /healthz`

Returns `{"ok": true}` with no dependencies. The Deployment's readiness and liveness probes and the ALB health check all use it.

## Security considerations

The design keeps the JWT and the account ID on the server; the main exposure is the `state` value, which works like a short-lived bearer token.

### What is verified

Every sign-up JWT must pass all five checks from Google's documentation: signature against Google's public key, `exp` not passed, `aud` equal to your product domain, `iss` equal to the `cloud-commerce-partner` certificate URL, and `sub` not empty. A token that fails any of them gets a `401` and no session is created.

### The `state` token

- It is 32 random bytes from `secrets.token_urlsafe`, so it cannot be guessed, and it expires after 15 minutes.
- Anyone who holds the URL within that window can call the session route and read `roles` and `orders`. The URL can appear in browser history, access logs and `Referer` headers.
- Reduce that by calling `history.replaceState` on the React page to strip the query string after reading it, and by sending `Referrer-Policy: no-referrer` on that page.
- Reading the session does not consume `state`. A session stops working when it expires. Only its SHA-256 hash is stored, so a database leak reveals no usable `state`.

### Authorisation

- No route trusts possession of `state` to change anything. The approve route is disabled (`403`) until approval is tied to an authenticated, authorized user.
- When approval is re-enabled, check `roles` in the backend if only billing administrators may complete sign-up (reject sessions without `account_admin`), since a user can bypass any check in React.
- CORS limits which websites a browser lets call the API. It is not authentication and does not stop non-browser clients.

### Credentials

- The service account key is mounted from a Kubernetes Secret as a read-only file and referenced by `GOOGLE_APPLICATION_CREDENTIALS`. Never commit it or bake it into the image.
- A long-lived key is acceptable for testing. For production, prefer workload identity federation from EKS so no key file exists.
- Do not log the JWT or `state`. The application never logs the JWT, and `state` is redacted from uvicorn's logs (see [Log redaction](#log-redaction-redact_state-redactstatefilter-install_log_redaction)).

### Remaining log exposure outside the application

The redaction filter only covers logs written by the uvicorn process. These places still record `state` unless they are configured not to. They belong to the infrastructure and frontend hosting, not to `main.py`:

| Where | What is recorded | Mitigation |
| --- | --- | --- |
| ALB access logs (if enabled on the Ingress) | Full request line, including `/api/marketplace/session/<state>` | Leave ALB access logging off for this load balancer, or restrict the S3 bucket to a small group with a short lifecycle (for example 1 day). |
| AWS WAF logs (if WAF is attached) | Request URI | Add a redaction rule for the URI path, or exclude these paths from logging. |
| Frontend host request logs (e.g. Vercel) | `GET /marketplace/signup?state=<state>` from the 303 redirect | Limit log retention and access on the hosting platform. The React page strips the query after reading it, but the initial request is still logged by the host. |
| Any proxy, APM or tracing agent added later | URLs of outgoing or incoming requests | Configure URL scrubbing for `/api/marketplace/*` and `state=` before enabling it. |
| Browser history and developer tools | The redirect URL and API request URLs | Cannot be controlled by the server. The 15-minute TTL bounds the risk. |
| Running uvicorn some other way (gunicorn workers, `--log-config`, a custom access logger) | Depends on the logger names used | Keep the `uvicorn.access` logger, or attach `RedactStateFilter` to the logger that writes access lines. |

In every case the exposed value expires after 15 minutes and, with approval disabled, only allows reading `roles` and `orders`. Moving `state` from the URL path into a `POST` body would remove it from all URL-based logs; that is a frontend and API change for a later ticket.

### Reachability

`/marketplace/signup` must be reachable without a username and password, as Google's guidance requires, and over public HTTPS because the request originates in the user's browser.

## Deployment on AWS EKS

The service runs as one pod behind an internet-facing Application Load Balancer, built from the `Dockerfile` and `k8s.yaml` that sit next to `main.py`.

### What the manifests create

- **Namespace** `marketplace`.
- **ConfigMap** `marketplace-config`: the four settings from the Configuration section.
- **Deployment** `marketplace-api`: one replica, port 8080, the key secret mounted read-only at `/var/secrets/gcp/key.json`, readiness and liveness probes on `/healthz`.
- **Service** `marketplace-api`: `ClusterIP`, port 80 to 8080.
- **Ingress** `marketplace-api`: class `alb`, internet-facing, HTTPS on 443 with an ACM certificate, HTTP redirected to HTTPS, health check on `/healthz`.

The container starts uvicorn with `--proxy-headers` so URLs behind the load balancer honour `X-Forwarded-*`, and runs as a non-root user (UID 10001).

### Steps

1. Make sure the cluster has the AWS Load Balancer Controller, and that an ACM certificate exists for your API domain in the cluster's region.
2. In GCP, create a JSON key for the `thales-test` service account and save it as `key.json`.
3. Create an ECR repository, then build and push the image.
4. Edit `k8s.yaml`: the image URL, the four ConfigMap values, the certificate ARN and the Ingress host.
5. Create the namespace and the key Secret, then apply the manifest.
6. Read the load balancer hostname from the Ingress and point your API domain at it in Route 53.
7. In Producer Portal, under Frontend integration, set the Sign up URL to `https://<api-domain>/marketplace/signup`.
8. Deploy the React page at the path used in `FRONTEND_URL` and set its `API` constant to the API domain.

```bash
aws ecr create-repository --repository-name marketplace-api --region REGION
aws ecr get-login-password --region REGION | docker login --username AWS \
  --password-stdin ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com
docker build -t marketplace-api .
docker tag marketplace-api:latest ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/marketplace-api:latest
docker push ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/marketplace-api:latest

kubectl create namespace marketplace
kubectl create secret generic gcp-sa-key -n marketplace --from-file=key.json=./key.json
kubectl apply -f k8s.yaml
kubectl get ingress -n marketplace
```

The Deployment is fixed at one replica. Sign-up sessions now live in PostgreSQL, so scaling out becomes possible once a database is provisioned.

> **Not yet deployable with the database code.** The deployment files have not been changed in this milestone. Before the next AWS deployment: the `Dockerfile` copies only `main.py` and must also copy `config.py`, `db.py`, `models.py`, `signup_sessions.py`, `alembic.ini` and `migrations/`; the Deployment needs `DATABASE_URL` from a Kubernetes Secret; a PostgreSQL instance (e.g. RDS) must exist; and `alembic upgrade head` must run before the new version starts (e.g. as a Kubernetes Job).

## Testing and troubleshooting

### Automated tests

The tests in `tests/` need no network access or Google credentials. They sign Marketplace-style JWTs with a throwaway local key, so the real verifier is exercised.

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Database tests use `TEST_DATABASE_URL`, or `DATABASE_URL` with `_test` added to the database name. They refuse to run against a database whose name does not end in `_test`, create it if missing, apply the migrations, and empty every table after each test. If PostgreSQL is not running, those tests are **skipped** with the reason shown; the rest still run.

- `test_approval.py`: the approve route returns `403` for every request (valid, expired or unknown `state`; with or without credentials or an allowed `Origin`), leaves the session usable, never touches the database and never calls Google.
- `test_signup_and_session.py`: sign-up redirects with only `state`, stores only its hash (never the raw `state` or the JWT), rejects bad tokens (`401`) and missing fields (`422`); session lookup returns only `roles` and `orders`, returns `404 Session expired` for unknown or expired states, and does not consume `state`.
- `test_models.py`: UUID keys, unique constraints, allowed values, foreign-key behaviour on delete, and that no column can hold a password, token or raw `state`.
- `test_migrations.py`: one migration head, the database is at head, migrations match `models.py` exactly, and downgrade to empty then upgrade again works.
- `test_log_redaction.py`: unit tests for `redact_state`, and a test that starts the app under uvicorn with its default logging config and checks the access log never contains `state`.

`requirements-dev.txt` is not installed in the container image.

### Manual checks

Two curl calls confirm the service and the form parsing work before you involve Marketplace.

```bash
curl https://api.example.com/healthz
curl -i -X POST https://api.example.com/marketplace/signup \
  -d "x-gcp-marketplace-token=garbage"
kubectl logs -n marketplace deploy/marketplace-api
```

The first should return `{"ok":true}`. The second should return `401 Invalid token`, which proves the route, the form field and the verifier are wired up. Then run a real purchase flow from the Marketplace preview and watch the browser land on the React page with `?state=...`.

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `401 Invalid token` on a real preview click | `aud` does not match `MARKETPLACE_AUDIENCE` | Decode the token without verifying it (for example on jwt.io), read `aud`, and set `MARKETPLACE_AUDIENCE` to match |
| `401 Invalid token` with a connection or timeout message | The pod cannot download Google's certificates | Allow outbound HTTPS to `googleapis.com` from the pod |
| `405` or a blank page at the Sign up URL | Sign up URL points at the React server | Point it at the API: `/marketplace/signup` |
| `422` on `/marketplace/signup` | The form field is missing, for example the request was sent as JSON | Send `x-gcp-marketplace-token` as form data |
| Redirect lands on `app.example.com` | `FRONTEND_URL` still has its default | Update the ConfigMap, then restart the Deployment |
| Browser reports a CORS error from React | `FRONTEND_ORIGIN` differs from the React origin | Match scheme, host and port exactly, with no trailing slash |
| `404 Session expired` | Over 15 minutes old, or never existed | Start the sign-up again from Marketplace |
| `500` with `DATABASE_URL is not set` | No database configured | Set `DATABASE_URL` (locally: copy `.env.example` to `.env`) |
| `500` with a connection error | PostgreSQL not running or wrong credentials | `docker compose ps`; check `DATABASE_URL` matches `POSTGRES_*` in `.env` |
| `relation "marketplace_signup_sessions" does not exist` | Migrations not applied | `alembic upgrade head` |
| `403` on approve | Expected: approval is disabled until authenticated authorization exists | None; do not work around it |
| `[REDACTED]` in access log paths | Expected: `state` is removed from uvicorn's logs | Correlate requests by time and client address instead |

## Known limitations and hardening checklist

The service is fit for a preview test, not for production: approval is disabled until authentication exists, the deployment files do not include the database yet, and nothing consumes Marketplace events.

### Known limitations

- **Deployment not updated for the database.** See the note under Deployment on AWS EKS.
- **Expired sign-up sessions are kept.** Nothing deletes rows past `expires_at`; they are ignored by lookups but accumulate.
- **No users or organisations are created yet.** The tables exist for the authentication milestone.
- **Approval disabled.** No route approves Procurement accounts; customers cannot complete sign-up until authenticated approval is built.
- **Blocking approve call.** When re-enabled, `_approve_procurement_account` uses the synchronous `AuthorizedSession`; calling it from an `async def` handler would block other requests on that worker for up to the 15-second timeout.
- **No account linking.** Nothing records which of your customers owns the procurement account ID.
- **`state` in URL paths.** Logs outside the application can still record it (see [Remaining log exposure](#remaining-log-exposure-outside-the-application)).
- **No login handler.** The Login URL, and the SSO `POST` that carries the same JWT, are not implemented. `verify_marketplace_jwt` can be reused for the SSO case.
- **No event handling.** Nothing reads the Pub/Sub topic that carries subscription and entitlement events.
- **Certificate failures look like bad tokens.** A failed certificate download returns `401`.
- **Unverified API call.** The approve path and body come from memory and need checking against Google's guide.

### Hardening checklist

- [x] Reject approval based on possession of `state` alone (approve route returns `403`)
- [x] Redact `state` from uvicorn's access and error logs
- [ ] Re-enable approval only for an authenticated user authorized for the account
- [x] Move sign-up sessions to PostgreSQL, storing only a hash of `state`
- [ ] Update the Dockerfile and Kubernetes manifests for the database, run migrations on deploy, then raise the replica count
- [ ] Delete expired sign-up sessions on a schedule
- [ ] Make the approve call non-blocking (a plain `def` handler or an async HTTP client)
- [ ] Require the `account_admin` role in the backend before approving
- [ ] Configure ALB, WAF and frontend-host logging so `state` is not retained (see Remaining log exposure)
- [ ] Store the procurement account ID, `user_identity` and order IDs against the new customer record at registration
- [ ] Confirm the approve request against the Procurement API reference
- [ ] Replace the service account key with workload identity federation
- [ ] Create a separate production service account, Pub/Sub topic and subscription, apart from `thales-test`
- [ ] Implement the Login URL and SSO verification
- [ ] Consume Pub/Sub entitlement events
- [ ] Add rate limiting
