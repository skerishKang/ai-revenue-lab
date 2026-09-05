# P01 Engine Caller Registration Runbook v1

Refs: #1914 (B54 P01 port + CLI run flow), PR #1919 (Slice 2 wiring)

## Authority and scope

This runbook fixes the owner-performed procedure that must complete **before the
first live `kagent p01-run` execution**. It registers the B54 caller
(`b54-kagent`) in the Engine's production caller authority.

```text
STATUS = OWNER_PROCEDURE_NOT_YET_RUN
REGISTRY_ENTRY_b54-kagent = NOT_REGISTERED
LOCAL_ENV_ON_OWNER_PC = NOT_SET
FIRST_LIVE_RUN = BLOCKED_BY_THIS_RUNBOOK
PRODUCTION_MUTATION = REQUIRES_SEPARATE_OWNER_AUTHORIZATION (this document performs none)
```

No secret **value** appears in this document. Every credential is generated and
held by the owner. Never paste a credential value into issues, PRs, chat, or
CI logs.

## How Engine caller authentication works (verified source facts)

- Enforcement point: `apps/padiem-ai-engine/worker.py` calls
  `app.identity_enforcement.authenticate_request()` for every non-health route.
  Health (`/internal/v1/health`) is unauthenticated.
- The caller presents two headers: `x-padiem-engine-caller` (caller id) and
  `x-padiem-engine-credential` (high-entropy credential). The Python client
  (`apps/padiem-ai-engine/clients/python/padiem_ai_engine_client`) sets both.
- Server-side authority is one of two **mutually exclusive** configurations on
  the `padiem-ai-engine` worker environment:
  1. `PADIEM_ENGINE_CALLER_REGISTRY_V1` (preferred, multi-caller): when present
     it is the ONLY caller authority. Malformed/blank payloads fail closed;
     there is never a fallback to the legacy trio.
  2. Legacy one-caller trio (authoritative only while the V1 variable is
     genuinely absent): `PADIEM_ENGINE_CALLER_ID`, `PADIEM_ENGINE_CALLER_SECRET`,
     `PADIEM_ENGINE_ALLOWED_APPS` (comma-separated app ids).
- Identifier grammar (caller id, app id): `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`.
- Credential: 32 to 512 bytes (UTF-8). Stored/compared only as SHA-256 digest,
  constant-time.
- Registry limits: 1 to 64 callers, 1 to 32 `allowed_app_ids` per caller (no
  duplicates), duplicate `caller_id` fails closed, serialized payload must not
  exceed 524288 bytes.
- App authorization is checked only after the credential verifies. The B54
  product app id is `b54-padiem-claw` (constant `P01_APP_ID` in
  `apps/korean-ai-code-agent/src/kagent/p01_adapter.py`).

### V1 registry payload format

```json
{
  "version": 1,
  "callers": [
    {
      "caller_id": "<existing-ingress-owned-caller-id>",
      "credential": "<existing-plaintext-secret-from-owner-vault>",
      "allowed_app_ids": ["<each-app-currently-allowed-by-the-legacy-trio>"]
    },
    {
      "caller_id": "b54-kagent",
      "credential": "<owner-generated-32-to-512-byte-secret>",
      "allowed_app_ids": ["b54-padiem-claw"]
    }
  ]
}
```

CRITICAL: enabling V1 instantly retires the legacy trio. The payload above
MUST include a faithful entry for the existing ingress-owned caller, or live
ingress traffic fails closed with `unknown_service_caller` /
`service_authentication_failed`.

### Which endpoint may be used for the B54 smoke

The public ingress worker serves ONLY `/internal/v1/execute` and ignores
caller-supplied Engine credential headers (it mints its own identity). The B54
smoke needs `/internal/v1/orchestrate` with the caller's own
`b54-kagent` headers, so `P01_ENGINE_BASE_URL` must point directly at the
`padiem-ai-engine` worker (custom domain/route owned by the owner) or at a
local `pywrangler dev` instance — never at the ingress URL.

## Procedure A — register `b54-kagent` (owner only)

### A1. Inventory the current engine caller configuration

From `apps/padiem-ai-engine/`:

```text
npx wrangler secret list          # expect the legacy trio names, if present
```

Record (names only, never values): the current caller id, and the exact
`PADIEM_ENGINE_ALLOWED_APPS` list. The ingress worker's non-secret var shows
the ingress-owned caller id; the engine-side trio must match it.

### A2. Generate the B54 credential (owner machine, high entropy)

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

64 URL-safe characters (well inside 32-512 bytes). Store the value ONLY in the
owner's secret store (e.g. Windows Credential Manager / password vault). It is
never committed, never pasted into an issue.

### A3. Assemble the V1 payload

Build the JSON from the "V1 registry payload format" section with:
- entry 1: the existing ingress-owned caller (same id, same plaintext secret
  from the owner vault, same allowed apps as the current trio), and
- entry 2: `b54-kagent` with the A2 credential and
  `allowed_app_ids: ["b54-padiem-claw"]`.

### A4. Validate offline before touching production (no mutation)

Run the Engine's own parser locally against the payload file. This only proves
the payload parses; it changes nothing:

```powershell
# from apps/padiem-ai-engine, with its deps importable
python -c "import sys; sys.path.insert(0,'.'); from app.identity_enforcement import parse_caller_registry_v1; parse_caller_registry_v1(open('registry-payload.json', encoding='utf-8').read()); print('PARSE_OK')"
```

Delete the payload file securely after use (it contains plaintext credentials).

### A5. Apply on the engine worker (PRODUCTION MUTATION - owner-authorized)

```powershell
# from apps/padiem-ai-engine/
npx wrangler secret put PADIEM_ENGINE_CALLER_REGISTRY_V1
# paste the validated JSON payload when prompted
```

Rollback = `npx wrangler secret delete PADIEM_ENGINE_CALLER_REGISTRY_V1`
(restores the legacy trio authority, provided the trio secrets are still set).

### A6. If the legacy plaintext secret is not recoverable

The legacy caller credential has a real zero-downtime rotation seam. Note it
lives in the **ingress worker (JavaScript)**, not the Python engine code -
`rg PADIEM_ENGINE_CALLER_SECRET_NEXT apps/padiem-ai-engine` finds it. Source
of truth (as of this commit):

- `apps/padiem-ai-engine/ingress/worker.mjs:22` - `PADIEM_ENGINE_CALLER_SECRET_NEXT` env constant
- `apps/padiem-ai-engine/ingress/worker.mjs:193-211` - seam behavior: NEXT is
  presented first when set; CURRENT is presented at most once, only as a retry
- `apps/padiem-ai-engine/ingress/worker.mjs:5-8` - hard attempt ceiling:
  initial attempt + exactly one retry (`MAX_ENGINE_ATTEMPTS = 2`), never looped
- `apps/padiem-ai-engine/ingress/worker.mjs:116-125` - the retry fires ONLY on
  the precise non-executing auth-failure signal (status 401 with
  `error.code === "service_authentication_failed"`); 403/413/429/5xx, timeouts,
  and malformed/oversized bodies never trigger a retry
- `apps/padiem-ai-engine/ingress/test/worker.test.mjs:588-652` - tests pinning
  the seam

The seam is ingress-client-side only: the engine still trusts exactly one
credential per caller at any moment; the ingress absorbs the transition by
trying both of its own secrets. Steps (do NOT reorder; the window between
steps 2 and 3 is the only migration state):

1. Generate a new secret S2 for the legacy caller.
2. On the ingress worker: `npx wrangler secret put PADIEM_ENGINE_CALLER_SECRET_NEXT`
   (value S2). Until step 3 lands, every request pays one extra Engine
   round-trip (NEXT attempt -> 401 -> CURRENT retry).
3. Apply A5 with the registry payload carrying the legacy entry's credential as S2.
   The ingress first attempt now succeeds and the retry path goes unused.
4. After a clean soak, converge the ingress on S2 as CURRENT:
   `npx wrangler secret put PADIEM_ENGINE_CALLER_SECRET` (value S2), then
   `npx wrangler secret delete PADIEM_ENGINE_CALLER_SECRET_NEXT`.
   Never delete the ingress CURRENT before step 3 has landed - every ingress
   request would then fail with `service_authentication_failed`.

## Procedure B — configure the owner PC (values live only in the PC)

Three user-level environment variables (set once, in a NEW shell afterwards):

```powershell
[Environment]::SetEnvironmentVariable('P01_ENGINE_BASE_URL',  '<engine-worker-https-url>', 'User')
[Environment]::SetEnvironmentVariable('P01_ENGINE_CALLER_ID', 'b54-kagent', 'User')
[Environment]::SetEnvironmentVariable('P01_ENGINE_CREDENTIAL', '<A2-credential>', 'User')
```

Value requirements enforced by
`apps/korean-ai-code-agent/src/kagent/p01_run_flow.py` (Slice 2, PR #1919):

| Variable | Requirement |
| --- | --- |
| `P01_ENGINE_BASE_URL` | absolute http(s) URL, no credentials/query/fragment; trailing `/` allowed; `http://` is for loopback dev instances only |
| `P01_ENGINE_CALLER_ID` | short identifier without spaces; must equal the registry entry (`b54-kagent`) |
| `P01_ENGINE_CREDENTIAL` | 32-512 bytes, exactly the A2 value |

All three must be present together: none set → `p01_engine_not_configured`;
partially set → `p01_engine_misconfigured`. The `p01-run` flow never falls
back to the B14 demo path.

## Procedure C — smoke and verification

1. Unauthenticated health (proves the base URL reaches the engine worker):
   `curl.exe -sS <P01_ENGINE_BASE_URL>/internal/v1/health`
2. Live run:
   ```powershell
   kagent . p01-run "저장소 README 요약해줘"
   ```
   Success = exit code 0 and a `[P01 ORCHESTRATION]` block with
   `status=completed`. Authentication problems surface as
   `KAGENT_P01: p01_engine_request_failed` (the Engine-side code is not echoed
   to avoid leaking internals; check engine logs for the exact code).
3. Negative check (optional): temporarily set a wrong credential → must still
   fail closed (`p01_engine_request_failed`), never fall back to demo.

## Failure report format (issue #1914 comment)

Report FACTS AND CODES ONLY — never header values, credentials, or full URLs
with query strings:

```text
STEP = A|B|C
EXIT_CODE = <int>
KAGENT_P01_CODE = one of:
  p01_engine_not_configured | p01_engine_misconfigured | p01_engine_url_invalid |
  p01_engine_unreachable | p01_engine_request_failed | p01_app_id_mismatch |
  p01_authority_field_unsupported | p01_authority_pinning |
  p01_result_correlation_mismatch | p01_run_id_invalid
ENGINE_SIDE_CODE (from engine logs) = one of:
  unknown_service_caller | service_authentication_failed |
  service_app_not_authorized | invalid_caller_registry |
  service_identity_unavailable | service_identity_misconfigured
TIMESTAMP_UTC = <iso8601>
```

Interpretation quick table:

```text
unknown_service_caller          -> b54-kagent missing from the V1 payload
service_authentication_failed   -> credential mismatch (A2 value vs registry entry)
service_app_not_authorized      -> allowed_app_ids lacks b54-padiem-claw
invalid_caller_registry         -> malformed V1 JSON (size/version/keys/duplicates)
p01_engine_unreachable          -> base URL wrong/worker not deployed/firewalled
p01_engine_misconfigured        -> local env partial or value shape invalid
```
