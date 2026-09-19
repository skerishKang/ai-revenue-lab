# P01 Engine Caller Registration Runbook v1

Refs: #1914 (B54 P01 port + CLI run flow), PR #1919 (Slice 2 wiring), #2375/#2402
(production authority), #2439 (duplicate-caller 401 investigation), #2484
(canonical smoke authority), #2520 / PR #2521 (dedicated overlay-only caller id)

## Authority and scope

This runbook fixes the owner/CENTRAL-performed procedure that must complete
**before the first live `kagent p01-run` execution on the current architecture**.
It registers the B54/P01 Claw caller as a **dedicated overlay-only Engine
caller**.

```text
STATUS = OWNER_PROCEDURE_NOT_YET_RUN
CALLER_ID = b54-p01-overlay-20260914-a1        # dedicated overlay-only Claw caller
OVERLAY_SECRET = PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY (padiem-ai-engine)
CHAT_BINDING = P01_ENGINE_CALLER_ID (padiem-chat, plain_text)
BASE_V1 = PADIEM_ENGINE_CALLER_REGISTRY_V1 (opaque, NOT mutated by this runbook)
BASE_REWRITE_REQUIRED = NO
FIRST_LIVE_RUN = BLOCKED_BY_THIS_RUNBOOK
PRODUCTION_MUTATION = REQUIRES_SEPARATE_OWNER_AUTHORIZATION (this document performs none)
```

No secret **value** appears in this document. Every credential is generated and
held by the owner or lives in the GitHub Actions secret
`B62_P01_ENGINE_CREDENTIAL`. Never paste a credential value into issues, PRs,
chat, or CI logs.

## Current authority model (dedicated overlay-only caller)

```text
Engine Overlay CALLER_ID            = b54-p01-overlay-20260914-a1
Chat P01_ENGINE_CALLER_ID value     = b54-p01-overlay-20260914-a1
authority_diagnostic EXPECTED_OVERLAY_CALLER_ID = b54-p01-overlay-20260914-a1
auth_boundary_diagnostic P01_CHAT_CALLER_ID     = b54-p01-overlay-20260914-a1
credential_equivalence CALLER_ID                = b54-p01-overlay-20260914-a1
production smoke CALLER_ID / PADIEM_ENGINE_SMOKE_CALLER_ID = b54-p01-overlay-20260914-a1
```

`.github/tests/test_b54_p01_overlay_caller_id_parity.py` pins this single
canonical contract: all of the authorities above must carry exactly this one
value (no alias, no dual-id acceptance, no fallback, no shadowing).

Rules that the current architecture depends on:

- The Claw/P01 caller lives in the **overlay** (`..._V1_OVERLAY`), never in the
  opaque base V1. The overlay is one additive single-caller authority owned by
  the rotation gate.
- The old Claw caller is **not** provisioned into base V1 anymore, and base V1
  content is never read, rewritten, or required by the overlay path
  (`BASE_V1_MUTATION=0`).
- The dedicated overlay caller id must stay distinct from every base V1 caller
  id. If base and overlay ever carry the same caller id, the Engine fails closed
  for everyone with `duplicate_service_caller`.

## How Engine caller authentication works (verified source facts)

- Enforcement point: `apps/padiem-ai-engine/worker.py` calls
  `app.identity_enforcement.authenticate_request()` for every non-health route.
  Health (`/internal/v1/health`) is unauthenticated.
- The caller presents two headers: `x-padiem-engine-caller` (caller id) and
  `x-padiem-engine-credential` (high-entropy credential). The Python client
  (`apps/padiem-ai-engine/clients/python/padiem_ai_engine_client`) sets both.
- Server-side authority is the opaque base V1 registry
  (`PADIEM_ENGINE_CALLER_REGISTRY_V1`) plus the optional additive single-caller
  overlay (`PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY`). Malformed/blank payloads
  fail closed; there is never a fallback to the legacy one-caller trio while
  the base V1 is present.
- Overlay semantics: when the request caller id equals the overlay caller id the
  Engine authenticates directly against the overlay caller. Configuring the
  overlay while base V1 is absent fails closed, and an overlay caller id
  duplicating a base caller id fails closed with `duplicate_service_caller`.
- Identifier grammar (caller id, app id): `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`.
- Credential: 32 to 512 bytes (UTF-8). Stored/compared only as SHA-256 digest,
  constant-time.
- Registry limits: 1 to 64 callers, 1 to 32 `allowed_app_ids` per caller (no
  duplicates), duplicate `caller_id` fails closed, serialized payload must not
  exceed 524288 bytes.
- App authorization is checked only after the credential verifies. The B54
  product app id is `b54-padiem-claw` (constant `P01_APP_ID` in
  `apps/korean-ai-code-agent/src/kagent/p01_adapter.py`).

### Overlay payload format (what the rotation gate PUTs)

```json
{
  "version": 1,
  "caller": {
    "caller_id": "b54-p01-overlay-20260914-a1",
    "credential": "<raw B62_P01_ENGINE_CREDENTIAL, unhashed>",
    "allowed_app_ids": ["b54-padiem-claw"]
  }
}
```

The Engine hashes the credential internally (`caller_secret_digest`). Do not
hand-craft this payload for production: the rotation gate builds it and enforces
the 32..512-byte credential gate and the overlay-only PUT target.

### Which endpoint may be used for the B54 smoke

The public ingress worker serves ONLY `/internal/v1/execute` and ignores
caller-supplied Engine credential headers (it mints its own identity). The B54
smoke needs `/internal/v1/orchestrate` with the caller's own
`b54-p01-overlay-20260914-a1` headers, so `P01_ENGINE_BASE_URL` must point
directly at the `padiem-ai-engine` worker (custom domain/route owned by the
owner) or at a local `pywrangler dev` instance — never at the ingress URL.

## Cutover contract (ORDER IS MANDATORY — DO NOT REORDER)

```text
1. Engine Overlay          -> NEW caller id (b54-p01-overlay-20260914-a1)
2. exact served-version authority readback (deployments API -> versions/{active})
3. Engine-side mutation-free smoke using the NEW caller id
4. only if step 3 PASSES: Chat P01_ENGINE_CALLER_ID -> NEW caller id
5. Chat config verify
6. Phase-A only under a SEPARATE CENTRAL authorization
```

The Engine-side new identity must be **proven by smoke before the Chat change
lands**. Steps 1 and 4 are separate live operations, so a short fail-closed
window exists between them: after step 1 and before step 4, Chat still presents
the old id and those requests fail closed with `service_authentication_failed`
— never a silent fallback, alias, or dual-id acceptance. Running step 4 first is
a configuration error with the same fail-closed refusal.

## Version freeze and rollback contract

There is **no caller-id-specific automatic Engine rollback writer**. The
`rollback-production-engine` job in
`.github/workflows/b54-engine-production-deploy-gate.yml` restores the
**previous** Worker version via `wrangler rollback`, which is not an exact
version target. A version freeze during cutover is therefore mandatory:

```text
CUTOVER_ENGINE_VERSION_FREEZE=YES
PREMUTATION_SERVED_VERSION_ID = <record the active served version before step 1>
during cutover:
  ENGINE_DEPLOY=0
  OTHER_ENGINE_SECRET_VERSION_MUTATION=0
  OTHER_ENGINE_CONFIG_VERSION_MUTATION=0
```

Failure handling:

```text
1. Engine rollback FIRST (previous served version)
2. verify the active served authority is restored to the pre-cutover state
   (served-version readback == PREMUTATION_SERVED_VERSION_ID)
3. only then Chat snapshot rollback (b62 rollback_config with the recorded
   rollback_version_id and the pre-mutation settings snapshot)
ROLLBACK_ORDER=ENGINE_FIRST_THEN_CHAT
```

If an intermediate Engine version drift is observed during cutover: **STOP**. Do
not perform a blind previous-version rollback — the previous version may no
longer be the pre-cutover authority. Escalate for an exact-version decision
first.

## Procedure A — align the overlay caller (owner/CENTRAL only)

### A1. Read-only authority classification (no mutation)

Run the read-only authority gate
(`.github/workflows/b54-engine-caller-authority-readonly-gate.yml`) or the
rotation gate's `classify` subcommand against the served version detail. Expect
the base V1 and the overlay to already be `secret_text` on the served version,
and record `LEGACY_PRE_STATE` and `PREMUTATION_SERVED_VERSION_ID`.

### A2. Credential authority

The credential is the GitHub Actions secret `B62_P01_ENGINE_CREDENTIAL` — the
same secret the B62 Chat worker presents. It never passes through
`workflow_dispatch` inputs and never appears in logs or evidence.

### A3. Apply the overlay caller id / credential (PRODUCTION MUTATION — owner/CENTRAL authorized)

Dispatch `.github/workflows/b54-engine-caller-registry-overlay-rotation-gate.yml`
from exact `main` with its confirmation phrase. The gate:

- PUTs ONLY `PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY` (base V1 and the legacy
  trio are never mutated; a runtime-inert legacy trio is captured and proven
  preserved),
- builds the canonical single-caller overlay above,
- proves pre/post readback on the actually served version, never the mutable
  settings plane.

### A4. Served-version readback (step 2 of the cutover contract)

`resolve-active` + `versions/{active}` detail readback, then the served-version
guard with `--expect-overlay`. Record the new active version id.

### A5. Engine-side mutation-free smoke (step 3 of the cutover contract)

Run `.github/workflows/b54-engine-production-smoke-only-gate.yml` with the exact
`expected_served_version`. A9/A10/A11/A12 read the caller id from
`CALLER_ID` / `PADIEM_ENGINE_SMOKE_CALLER_ID` in the workflow environment, so the
smoke scripts themselves need no caller-id change. Do NOT proceed to Procedure B
unless this smoke PASSES.

## Procedure B — Chat binding and owner PC

### B1. Chat caller binding (step 4 of the cutover contract)

`.github/workflows/b62-claw-live-config-activation-gate.yml` sets the plain_text
binding `P01_ENGINE_CALLER_ID` to `b54-p01-overlay-20260914-a1`. It changes ONLY
that binding; every unrelated/secret binding is inherited, and the pre-mutation
settings snapshot is recorded for bounded rollback.

### B2. Chat config verify (step 5 of the cutover contract)

Re-read the served Chat configuration and confirm the caller binding equals the
canonical id. Caller-id drift is refused/re-classified as `P01_CALLER_SET` by
the existing gate semantics (no silent alias).

### B3. Owner PC values (values live only in the PC)

Three user-level environment variables (set once, in a NEW shell afterwards):

```powershell
[Environment]::SetEnvironmentVariable('P01_ENGINE_BASE_URL',  '<engine-worker-https-url>', 'User')
[Environment]::SetEnvironmentVariable('P01_ENGINE_CALLER_ID', 'b54-p01-overlay-20260914-a1', 'User')
[Environment]::SetEnvironmentVariable('P01_ENGINE_CREDENTIAL', '<the B62 credential>', 'User')
```

| Variable | Requirement |
| --- | --- |
| `P01_ENGINE_BASE_URL` | absolute http(s) URL, no credentials/query/fragment; trailing `/` allowed; `http://` is for loopback dev instances only |
| `P01_ENGINE_CALLER_ID` | short identifier without spaces; must equal the overlay caller (`b54-p01-overlay-20260914-a1`) |
| `P01_ENGINE_CREDENTIAL` | 32-512 bytes, exactly the `B62_P01_ENGINE_CREDENTIAL` value |

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
4. Phase-A runs only under a separate CENTRAL authorization (step 6).

## Historical (SUPERSEDED) — legacy shared-caller base V1 registration

Everything in this section describes the **previous** architecture. It is kept
for history and must not be re-executed for the Claw caller.

- The old Claw caller was registered as a second entry in the opaque base V1
  payload (`PADIEM_ENGINE_CALLER_REGISTRY_V1`) under the shared caller id
  `b54-kagent`, next to the ingress-owned caller.
- That shared id was also placed in the additive overlay, which is exactly what
  produced the #2439 `duplicate_service_caller` 401-for-everyone collision: the
  base already contained `b54-kagent`, so the overlay duplicated it.
- The legacy base entry may still be physically present in base V1. It is not
  read or required by the current overlay path, and it must not be rewritten by
  this runbook. The legacy
  `.github/workflows/b54-engine-caller-registry-v1-provision-gate.yml` path has
  had its Claw-provisioning policy permanently retired (#2523) and fails closed
  (`WORKFLOW_APPLY_FOR_CLAW=FAIL_CLOSED`). It **must not** be dispatched for Claw.
- The only path that may change base V1 is the separately-authorized
  `b54-kagent` removal gate (#2519) — never this cutover.

- Historical evidence naming is preserved on purpose: the Engine
  `authority_diagnostic` field `BASE_CONTAINS_B54_KAGENT` still answers "does the
  opaque base still carry the old shared caller?" against the legacy id, while
  `EXPECTED_OVERLAY_CALLER_ID` tracks the current dedicated overlay caller.

## Failure report format

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
  unknown_service_caller | service_authentication_failed | duplicate_service_caller |
  service_app_not_authorized | invalid_caller_registry |
  service_identity_unavailable | service_identity_misconfigured
TIMESTAMP_UTC = <iso8601>
```

Interpretation quick table:

```text
unknown_service_caller          -> the canonical overlay caller id is missing
                                   from the served overlay authority
service_authentication_failed   -> credential mismatch (B62 value vs registry entry)
duplicate_service_caller        -> the overlay caller id duplicates a base V1 caller
                                   id (fails closed for every caller; do not paper
                                   over it with an alias or dual-id acceptance)
service_app_not_authorized      -> allowed_app_ids lacks b54-padiem-claw
invalid_caller_registry         -> malformed registry JSON (size/version/keys/duplicates)
p01_engine_unreachable          -> base URL wrong/worker not deployed/firewalled
p01_engine_misconfigured        -> local env partial or value shape invalid
```
