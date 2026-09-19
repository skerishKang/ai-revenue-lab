# P01 Engine Gmail READ activation — Control Plane access-lease architecture

## Status

```text
SOURCE_CONVERGENCE=#2657 / PR #2699
PRODUCTION_DEPLOY=NOT_AUTHORIZED_BY_THIS_DOCUMENT
LIVE_GMAIL_READ=NOT_YET_PROVEN
GMAIL_WRITE=0
GMAIL_SEND=0
```

Google Drive #2644 is the accepted precedent. Long-lived Google refresh
credentials remain owned by Control Plane. The canonical Engine Gmail path
must receive only a short-lived `gmail.readonly` access lease over the private
`CONTROL_PLANE_GOOGLE_OAUTH` Service Binding.

## Canonical authority path

```text
server-derived Gmail grant
→ binding_ref + actor_ref
→ Engine CONTROL_PLANE_GOOGLE_OAUTH private RPC
→ connector=gmail
→ short-lived gmail.readonly access lease
→ bounded Gmail provider GET
```

The browser, model/task payload and product consumer never receive or choose
the provider credential, binding reference or OAuth scope.

## Components

### 1. Control Plane access-lease authority

`packages/padiem-control-plane/google_oauth_access_lease.py` owns the
long-lived credential boundary. It accepts only reviewed connector/scope
pairs, unseals the refresh credential inside Control Plane, refreshes the
provider token there, and returns a bounded private access lease.

Reviewed Gmail scope:

```text
connector_id=gmail
scope=https://www.googleapis.com/auth/gmail.readonly
```

### 2. Engine access-lease client

`app/google_oauth_access_lease.py` validates the private RPC result and
accepts only the explicit reviewed connector map for Gmail and Google Drive.
The lease schema rejects extra fields such as refresh credentials.

### 3. Canonical Gmail provider port

`app/gmail_port_cp_lease.py` implements the trusted `GmailReadPort` using
the short-lived lease.

Properties:

- exact Gmail readonly scope only;
- exact `gmail.googleapis.com` HTTPS host;
- bounded GET response;
- no redirects;
- no refresh-token field;
- no access-token cache;
- provider HTTP 401 permits one fresh CP lease and one retry only;
- no Gmail write/draft/send capability.

The older `app/gmail_port_httpx.py` direct-refresh implementation may remain
as legacy/test source, but it is not the canonical Production Worker
composition and must never become a silent fallback.

### 4. Worker composition

`worker_identity._gmail_port_for_env()` uses
`CONTROL_PLANE_GOOGLE_OAUTH`. It does not read
`ENGINE_GOOGLE_OAUTH_CLIENT_ID`,
`ENGINE_GOOGLE_OAUTH_CLIENT_SECRET` or
`ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN` for canonical Gmail execution.

`ENGINE_CONNECTOR_GRANTS` remains the D1 authority for server-side Gmail
grant references. D1 contains no provider credential material.

### 5. Worker-native external transport

`app/cloudflare_external_transport.py` provides a Gmail-specific Worker
transport restricted to `gmail.googleapis.com`. The Worker Fetch boundary
normalizes response encoding metadata using the same reviewed transport
mechanism proven by Drive.

## Source acceptance

Before merge:

```text
EXACT_HEAD_ENGINE_CI=PASS
P01_DEPLOYMENT_BOUNDARY=PASS
OPERATIONS_POLICY_GUARD=PASS
DRIVE_REGRESSION=PASS
RAW_REFRESH_TOKEN_TO_ENGINE_CANONICAL_PATH=NO
ENGINE_GMAIL_DIRECT_REFRESH_PRODUCTION_FALLBACK=NO
```

## Production sequencing

Source merge does **not** authorize Production mutation.

After merge, CENTRAL must fresh-read exact `main` and then use separately
authorized gates in this order:

1. deploy the exact-main Engine source;
2. prove the served version and health;
3. run provider-free ToolRuntime/registry evidence where applicable;
4. verify the canonical Gmail D1 grant and Control Plane credential binding
   without exposing binding/token values;
5. issue a separate single-use live Gmail READ canary authority;
6. execute at most one bounded provider READ according to that authority;
7. only after PASS may Gmail Production READ acceptance be claimed.

## Hard locks

```text
LONG_LIVED_REFRESH_TOKEN_OWNER=CONTROL_PLANE
RAW_REFRESH_TOKEN_TO_ENGINE=NO_CANONICAL_PATH
RAW_REFRESH_TOKEN_TO_BROWSER_MODEL_TASK=NO
CALLER_MINTED_BINDING_REF=NO
CALLER_MINTED_SCOPE=NO
GMAIL_SCOPE=gmail.readonly_ONLY
GMAIL_WRITE=0
GMAIL_CREATE_DRAFT=0
GMAIL_SEND=0
PUBLIC_OAUTH_ROUTE_CHANGE=NO
NEW_OAUTH_STACK=NO
SCHEMA_MIGRATION=NO_FOR_2657
PRODUCTION_MUTATION_REQUIRES_SEPARATE_AUTHORITY=YES
```

## Historical note

The original D28 activation design used three Engine-owned Google OAuth secret
values and refreshed tokens inside `HttpxGmailReadPort`. That architecture is
historical compatibility evidence only and is superseded for canonical
Production Gmail by #2657. Do not provision those legacy Engine secret values
as a way to activate the current Gmail path.
