# WO-10 PR-C (D28): Engine Gmail OAuth port + D1 connector grant activation

## Status: FAIL-CLOSED (Production not yet activated)

Production remains fail-closed until the activation gate below is satisfied.
No real user data is read in this PR. The owner-only test mailbox grant
insertion into D1 is a **separate dispatch** after this PR merges.

## Components

### 1. `app/gmail_port_httpx.py` — HttpxGmailReadPort
- Fetch-based `GmailReadPort` over `httpx.AsyncClient`. The Engine runs as a
  Python Worker (Pyodide) where `urllib.request` is unavailable, so every
  outbound HTTP call is async through `httpx`.
- OAuth token refresh is implemented here (~60 lines). The three OAuth
  credentials are injected as constructor arguments:
  - `client_id` ← `ENGINE_GOOGLE_OAUTH_CLIENT_ID` Worker secret
  - `client_secret` ← `ENGINE_GOOGLE_OAUTH_CLIENT_SECRET` Worker secret
  - `refresh_token` ← `ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN` Worker secret
- Token refresh POSTs to `https://oauth2.googleapis.com/token`
  (`grant_type=refresh_token`), caches the access token for
  `expires_in - 60s`, and re-refreshes on 401 (exactly one retry).
- Scope gate: `required_scopes ⊆ {gmail.readonly}`. Host gate: only
  `gmail.googleapis.com`. Byte bound enforced by streaming read.
- Exceptions carry no token/secret/binding_ref material.

### 2. `migrations/0003_engine_connector_grants.sql` + `app/connector_grants_d1.py`
- D1 table `padiem_engine_connector_grants` stores **grant references only**:
  app_id, canonical_agent_id, connector_id, binding_ref, actor_ref,
  granted_scopes_json, active, created_at, updated_at.
- `CloudflareD1ConnectorGrantStore.load_gmail_grants()` returns
  `dict[app_id, GmailGrant]`. On any parse/binding error it raises
  `ServiceContractError("connector_grants_unavailable", 503)` — fail-closed.
- **No credential material is stored in D1.**

### 3. `app/connector_bindings.py` + `worker_identity.py`
- `GMAIL_PORT_BOUND_IN_PRODUCTION` flag removed. The resolver is now built
  from env-derived secrets + D1 grant references.
- `_tool_binding_resolver_for_env(env)`:
  - `_gmail_port_for_env(env)`: builds `HttpxGmailReadPort` only when all
    three Worker secrets are present, else `None`.
  - `_gmail_grants_for_env(env)`: loads grants from the
    `ENGINE_CONNECTOR_GRANTS` D1 binding, else `{}`.
  - Returns `None` (fail-closed) if either piece is missing.
- `_engine_services_for_env` is now `async` (the D1 grant load is async).

### 4. `wrangler.toml` + `.github/workflows/b54-engine-d1-provision-gate.yml`
- D1 binding `ENGINE_CONNECTOR_GRANTS` points at the same provisioned
  `padiem-engine` database (`6b77ad02-bc27-488f-bb97-6325f6750cba`).
- Provision gate applies migration 0003 and asserts the new table exists.

## Activation gate (BLOCKER_G1_OWNER_OAUTH_CLIENT = OPEN)

1. `0003` migration provisioned (D1 provision gate).
2. Three Worker secrets put (`ENGINE_GOOGLE_OAUTH_CLIENT_ID`,
   `ENGINE_GOOGLE_OAUTH_CLIENT_SECRET`,
   `ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN`) — values never in source.
3. Owner-only test mailbox grant: 1 row inserted into
   `padiem_engine_connector_grants` via `scripts/` (separate dispatch).
4. A11 smoke: grant-less app → 403 `tool_agent_not_bound`; owner app → real
   Gmail API call (1 `search_messages`) → 200 + projection verified.
5. Manifest state flip is a **separate PR** after the above.

## Secrets (names only)

| Name | Source | Stored? |
|---|---|---|
| `ENGINE_GOOGLE_OAUTH_CLIENT_ID` | Worker secret | No |
| `ENGINE_GOOGLE_OAUTH_CLIENT_SECRET` | Worker secret | No |
| `ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN` | Worker secret | No |

## Test coverage

- `tests/test_gmail_port_httpx.py` (12 tests, `httpx.MockTransport`):
  token refresh/caching, expiry re-refresh, 401 retry, scope/host gates,
  byte bound, 5xx mapping, secret-free error strings, authorization header.
- `tests/test_connector_grants_d1.py` (6 tests): hit/miss, inactive rows,
  malformed JSON → 503, binding exception → 503, None binding rejection.
- `tests/test_d1_binding_config.py` (4 tests): 3 D1 bindings, same DB,
  ENGINE_CONNECTOR_GRANTS binding, entrypoint/app surface untouched.