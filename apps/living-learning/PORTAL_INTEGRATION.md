# Living Learning — Portal Production Integration Contract

This document defines how Living Learning connects to the AI Revenue Lab portal
in production. It is a **contract only**: no real account email, URL, secret, or
token is recorded here, and nothing in this repository performs a live Firebase,
Neon, Modal, or Cloudflare call. Local runs are network-free (SQLite + mock
provider + fake identity verifier).

## Target architecture

```text
GitHub
  -> Cloudflare Pages: Portal UI and Living Learning frontend

Browser
  -> Firebase Auth (shared identity project)
  -> Firebase ID token
  -> Modal FastAPI (Living Learning backend, scale-to-zero)
  -> Neon PostgreSQL (Living Learning-dedicated database)
```

## Component roles

### GitHub

- Source of truth for all Living Learning code and migrations.
- Pull-request gate: changes merge only through reviewed PRs.
- **CI status:** GitHub-hosted CI (Actions) is currently **unavailable** because
  of account billing/spending constraints. Until it is restored, merge evidence
  uses an explicit **manual CI waiver** plus directly executed local acceptance
  suites. The absence of hosted CI must **never** be described as green or
  passed; every report states that evidence is worker-local.
- Deploys the static frontend to Cloudflare Pages.
- Deploys the FastAPI backend to Modal.
- Holds environment-scoped secrets (injected into Modal/Cloudflare, never committed).

A GitHub Actions gate remains a planned future item, but it is **not** an
active gate today and must not be represented as one.

### Cloudflare

- Serves the Portal UI and the Living Learning frontend (static assets).
- Provides the product entry route into Living Learning.
- Holds **no** database credentials.
- Performs **no** direct AI generation — generation happens only in the backend.

### Firebase

- Provides **shared identity only**, under the identity project
  `ai-revenue-lab-identity`.
- Issues ID tokens that the backend verifies.
- Stores **no** learning records.
- Grants **no** automatic Business membership — a Firebase login never, by
  itself, creates a learner, operator, or reviewer in Living Learning.

### Modal

- Runs the FastAPI app as an ASGI service.
- Verifies Firebase ID tokens (via the `IdentityVerifier` protocol).
- Enforces product authorization (external identity + membership + role +
  ownership).
- Performs lesson generation and deterministic validation.
- Scales to zero when idle.

### Neon

- Living Learning-dedicated PostgreSQL database.
- **No** direct browser access — only the backend connects.
- Separates a migration-owner role (runs migrations) from a least-privilege
  runtime role (serves requests).
- Uses a pooled runtime connection URL.
- Schema changes happen only through explicit, additive migrations.

## Identity and authorization model

Authentication (Firebase) and authorization (Living Learning) are strictly
separated. Access requires **all** of:

1. A verified Firebase identity (`IdentityVerifier.verify_bearer_token`).
2. An active `external_identities` row (`UNIQUE(provider, issuer, subject)`).
3. An active `product_memberships` row with the correct role
   (`learner` / `operator` / `reviewer`).
4. Resource ownership (a learner only reaches their own lessons).

The Firebase `subject` is **never** used as a learner id. The learner id comes
from the product membership. Operator role is **never** auto-granted from email,
domain, or Firebase custom claims — a membership row must exist.

### Local / test verifiers

- `FakeIdentityVerifier` — maps known tokens to principals; rejects unknown
  tokens; an empty instance rejects everything (fail-closed).
- `RejectingIdentityVerifier` — rejects every token; the safe default until a
  verifier is configured.

The real Firebase verifier sits behind the same `IdentityVerifier` protocol and
is wired only in production.

## API boundary (`/api/v1`)

- Bearer token required on all non-health endpoints.
- Verifier injected via dependency (`get_identity_verifier`).
- Generic `401 unauthorized` / `403 forbidden` / `404 not_found` — no reason,
  subject, or token detail leaks.
- Product-local membership required; learner ownership enforced; operator role
  gated.
- Request size bounded at the Pydantic schema layer (field length/list limits).
- Pydantic request/response schemas; no raw arbitrary JSON pass-through; no raw
  HTML returned (the AI never generates HTML — structured data is validated, then
  the application renders).
- No raw token, subject, or private text is logged.
- Private responses carry `Cache-Control: no-store` and `X-Robots-Tag:
  noindex, nofollow`.
- CORS uses an exact-origin allowlist; wildcard origin with credentials is never
  configured (`allow_credentials=False`, bearer tokens only).

### Health contract

`/health` and `/api/v1/health` return, without secrets:

```json
{
  "status": "ok",
  "database_backend": "sqlite",
  "identity_provider": "fake",
  "ai_provider": "mock",
  "ai_model": "runtime-model-name",
  "portal_contract_version": "v1"
}
```

Never exposed: database path/URL, Firebase project secret, bearer token, API
key, internal exception text, raw provider error.

## Generation safety contracts (enforced before persistence)

- **AST allowlist**: generated Python is validated against a strict allowlist;
  `Call` is restricted to `print()`. Imports, attribute access, lambdas,
  subscripts, dunder names, and dangerous builtins are rejected.
- **Answer grounding**: a review answer must be justified by taught material
  (section prose, code examples, expected output, term definitions) — never by
  the question/answer/rationale itself.
- **Atomic idempotency**: operations are guarded by a DB-unique operation key
  with a CAS lifecycle (`pending` / `completed` / `failed_retryable` /
  `failed_terminal`); exactly one owner under concurrency; failed claims are
  recoverable.
- **Single transaction**: the second-lesson persist (lesson, exercises, feedback
  application, mastery, adaptation decisions, generation-run finalize, claim
  completion) is one atomic transaction.
- **Provider accounting**: every provider call (including failures and repair
  calls) is recorded per attempt group; token totals are NULL when not reported;
  no credential or raw private input is stored.
- **Pending review default**: generated lessons are `pending_review`; there is no
  automatic publication. Operator approve/reject is an explicit manual action.

## Remaining production work (out of scope here)

- Neon PostgreSQL parity (sqlite3-shaped wrapper over psycopg, pooled runtime
  URL, separate migration-owner role, advisory-lock migrations).
- Live Firebase ID-token verification (real `IdentityVerifier` implementation).
- Modal deployment (ASGI wiring, scale-to-zero, secret-driven config).
- Cloudflare-connected frontend (Portal + Living Learning UI).
- Portal service catalog registration.
- GitHub Actions deployment gate.
- Production smoke test.
