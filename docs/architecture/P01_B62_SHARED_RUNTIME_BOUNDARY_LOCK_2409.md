# P01 / B62-Shared Runtime Boundary Lock (#2409 Wave 0)

```text
DOC_STATUS = ARCHITECTURE_BOUNDARY_LOCK
ISSUE = #2409
CENTRAL_AUTHORITY_COMMENT = 5671625914
WAVE_0 = APPROVED
BASE_SHA = 510e5b73d782e7084eb9377243a28eeeb99cff37
LAST_VERIFIED = 2026-09-15
SOURCE_MUTATION = DOCS_ONLY
RUNTIME_DIFF = 0
PRODUCTION_MUTATION = 0
```

This document locks the boundary rulings CENTRAL accepted for #2409 so later
waves implement against a fixed authority instead of re-auditing. It changes
no runtime source, no workflow, and no Cloudflare configuration. It complements
`docs/architecture/B62_P01_B14_CONTROL_PLANE_OWNERSHIP_REVIEW_20260831.md`
(a dated product-authority snapshot) and
`docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`
(canonical capability ownership).

## Accepted boundary ruling

```text
CONTRACT      = platform-independent P01 wire contract, caller identity
                data model, credential-shape policy, fail-closed policy
                -> IP-CORE   (packages/padiem-ai-core)

ENFORCEMENT   = concrete trusted caller enforcement, caller registry,
                Service Binding transport normalization
                -> IP-ENGINE (apps/padiem-ai-engine)

COMPOSITION   = product binding names, Worker composition adapter
                -> B62       (apps/padiem-chat)

DEPLOY_OPS    = Cloudflare Worker secret/version/deployment/rollback machinery
                -> REPOSITORY OPERATIONS LAYER (.github), NOT IP-CONTROL

NEW_PYTHON_PACKAGE_FOR_DEPLOYMENT_RUNTIME = NO
```

Cross-cutting rule: promotion is decided by responsibility shape
(platform-independent contract vs concrete enforcement vs product composition
vs operational machinery), never by historical lane number.

### 1. Contract belongs to IP-CORE

Platform-independent, stdlib-only semantics with no Cloudflare API, wrangler,
or Workers-runtime dependency:

- the P01 invocation/wire contract envelope (`app_id` + caller identity +
  credential presentation toward the Engine);
- the caller identity data model (bounded identifier grammar, digest-compare
  credential model, never plaintext credential storage);
- credential-shape policy (byte bounds, identifier bounds, cardinality caps);
- the fail-closed policy (missing/malformed authority rejects; no silent
  fallback, no shadowing, no id remapping).

Core may define these shapes; it must not gain secret mutation, registry
operation, or transport implementation.

### 2. Enforcement belongs to IP-ENGINE

Concrete runtime authority at the Engine wire boundary:

- header/env enforcement (`identity_enforcement.py`);
- the versioned caller registry and its additive overlay plus bounded
  retirement policy (`PADIEM_ENGINE_CALLER_REGISTRY_V1`,
  `PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY`, retired-caller deny);
- Service Binding transport normalization (`cloudflare_transport.py`);
- the legacy one-caller trio, authoritative only while the V1 registry is
  genuinely absent.

Registry payloads and credentials are deployment secrets owned by the Engine
deployment boundary. They are not Core content and not Control Plane content.

### 3. Composition belongs to B62 (apps/padiem-chat)

- the concrete binding names `P01_ENGINE_SERVICE`, `P01_ENGINE_CALLER_ID`,
  `P01_ENGINE_CREDENTIAL` are product-deployment names;
- `worker_config.py` binding validation and `claw_p01_composition.py` are the
  product composition adapter: they compose an Engine client from trusted
  Worker bindings and fail closed to `None`;
- product admission/abuse quota remains B62-owned.

Wave 1 may lift the generic shape/fail-closed policy into Core, but the
binding names and composition wiring stay in the product.

### 4. Deployment machinery belongs to the repository operations layer

Worker secret put/replace, version activation, binding preservation/readback,
deployment and rollback verification are operational machinery, currently
implemented as repository operations:

- `.github/workflows/b54-engine-*` (caller registry provision/rotation,
  credential equivalence, production deploy/smoke gates);
- `.github/workflows/b62-*` (live config activation, production code deploy
  gate, binding state guard, cloudflare deploy gates);
- `.github/scripts/b62_cloudflare_*.py`, `b62_binding_state_guard.py`,
  `b62_served_version_secret_guard.py`, `b62_claw_live_config_activation.py`,
  `b54_engine_*.py`.

Ruling: this machinery must NOT be promoted into `padiem-control-plane` merely
because it is cross-product. The preferred long-term shape is parameterized
shared helpers under `.github` with product/Engine-specific thin wrappers
(a Wave 4 candidate). No new Python package is authorized for a deployment
runtime at this stage.

## Wave 0 classification snapshot

Current paths at BASE_SHA, classified per the #2409 taxonomy. This is a
documentation snapshot, not an implementation order.

| Current path | Responsibility | Classification | Target owner |
|---|---|---|---|
| `apps/padiem-chat/app/worker_config.py` | P01 binding validation + fail-closed shape policy | SPLIT | IP-CORE (shape/policy) + B62 (names) |
| `apps/padiem-chat/app/claw_p01_composition.py` | Worker composition adapter | KEEP | B62 |
| `apps/padiem-chat/app/dispatch_quota.py`, `usage_gate.py` | product admission quota | DO_NOT_MOVE_YET | B62 |
| `apps/padiem-chat/app/control_plane_identity*.py` | CP identity bridge (runtime-active) | DO_NOT_MOVE_YET | B62 consuming IP-CONTROL |
| `apps/padiem-ai-engine/app/service_identity.py` | caller identity records + authentication primitives | SPLIT | IP-CORE (data model) + IP-ENGINE (enforcement) |
| `apps/padiem-ai-engine/app/identity_enforcement.py` | caller registry enforcement | DO_NOT_MOVE_YET | IP-ENGINE |
| `apps/padiem-ai-engine/app/cloudflare_transport.py` | Service Binding transport normalization | KEEP | IP-ENGINE |
| `apps/padiem-ai-engine/clients/python/**` | product-facing Engine client | KEEP | IP-ENGINE (client surface) |
| `.github/workflows/b54-engine-*`, `b62-*deploy/activation/gate*` | secret/version/deploy/rollback machinery | KEEP (repo-ops) | `.github` operations layer |
| `.github/scripts/b62_cloudflare_*.py`, `b62_binding_state_guard.py`, `b62_served_version_secret_guard.py`, `b62_claw_live_config_activation.py` | deploy verification helpers | KEEP (repo-ops), RENAME direction | `.github` operations layer |
| `packages/padiem-control-plane/**` | canonical identity/entitlement/usage/audit contracts | KEEP | IP-CONTROL (explicitly NOT deploy machinery) |

## DO_NOT_MOVE_YET (incident-near / runtime-active)

While the current P0 recovery loop is active, these paths are frozen for
incident analysis and runtime stability:

```text
apps/padiem-chat/app/worker_config.py            (P01 binding composition)
apps/padiem-chat/app/claw_p01_composition.py     (P0 recovery surface)
apps/padiem-chat/app/dispatch_quota.py           (#2509/#2531 quota gate cycle)
apps/padiem-chat/app/usage_gate.py               (quota gate cycle)
apps/padiem-chat/app/control_plane_identity*.py  (runtime-active identity bridge)
apps/padiem-ai-engine/app/identity_enforcement.py(caller registry, #2525 retirement)
apps/padiem-ai-engine/app/service_identity.py    (caller registry, runtime-active)
```

Wave 1 extraction may proceed only for platform-independent shapes that do not
touch these live enforcement/quota/registry behaviors, and only after CENTRAL
confirms the P0 runtime path is stable.

## Historical lane aliases and naming direction

```text
P01  -> legacy shared-platform identifier; current = IP-CORE / IP-ENGINE split
B54  -> Padiem Claw product lane; also the historical prefix of Engine
        deployment gates (b54-engine-*)
B62  -> Padiem Chat product lane; also the historical prefix of chat/product
        deploy gates and scripts (b62-*)
B14  -> Korean AI Platform (provider/model execution authority)
```

Historical issue numbers, commit messages, workflow names and script prefixes
remain valid aliases and are never rewritten. Migration direction for NEW
artifacts only:

```text
preferred naming families:
padiem-claw-*
padiem-ai-engine-*
padiem-ai-core-*
padiem-control-plane-*
padiem-production-*
```

No mass rename without a migration plan. Existing `b54-engine-*` / `b62-*`
workflows keep running under their historical names until an approved Wave 4
rename with CI-trigger verification. Wave 0 performs no renames.

## wrangler.toml vs live binding authority (ownership note)

Recorded discrepancy — documentation only, no config mutation:

- `apps/padiem-chat/wrangler.toml` is a mock/preview baseline. It declares
  `ASSETS`, `B14_SERVICE` and mock-mode vars only.
- The live `padiem-chat` Worker carries bindings and vars that do not exist in
  that file, including `P01_ENGINE_SERVICE` (service), `P01_ENGINE_CALLER_ID`
  (var), `P01_ENGINE_CREDENTIAL` (secret), `PADIEM_CHAT_DB` (D1),
  `PADIEM_WORKSPACE_FILES` (R2), `IDENTITY_AUTHORITY_SERVICE` (service), and
  production runtime/quota values.
- Authority rule: for the deployed Workers, the live Cloudflare Worker
  configuration is the binding authority. The repository operations layer
  reads the live settings dump as its only input and preserves unchanged
  bindings by reference (`b62_claw_live_config_activation.py`), with
  structure drift blocked by `b62_binding_state_guard.py` and served-version
  secret typing enforced by `b62_served_version_secret_guard.py`.
- Consequence: `wrangler.toml` must never be treated as proof of live binding
  state, in either direction (absence in the file does not mean absence
  live; presence does not mean deployed).
- Disposition: reconciling `wrangler.toml` with live configuration is a later
  repository-operations decision requiring explicit authorization. Wave 0
  changes no Cloudflare configuration.

## Ordered waves (as approved)

```text
Wave 0  documentation/boundary lock only            <- this change
Wave 1  extract reusable contracts, no behavior change
Wave 2  move generic primitives with compatibility wrappers
Wave 3  thin padiem-chat adapters
Wave 4  workflow/name cleanup + parameterized repo-ops helpers
Wave 5  historical B62 alias deprecation
```

Each implementation wave requires independent CENTRAL approval, must be
independently revertible, must not mix behavior change with path moves, and
must be covered by exact-head CI.

## Wave 0 non-goals (enforced)

```text
RUNTIME_SOURCE_MOVE      = NO
PYTHON_RUNTIME_REFACTOR  = NO
WORKFLOW_RENAME          = NO
CLOUDFLARE_CONFIG_CHANGE = NO
CALLER_REGISTRY_MUTATION = NO
QUOTA_MUTATION           = NO
SECRET/VERSION_MUTATION  = NO
PRODUCTION_MUTATION      = 0
```

## Governing references

- Issue #2409, CENTRAL authority comment `5671625914`
- `docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`
- `docs/architecture/B62_P01_B14_CONTROL_PLANE_OWNERSHIP_REVIEW_20260831.md`
- `docs/governance/LEGACY_AI_TERMINOLOGY_MAP.md`
- `docs/internal-platform/{core,engine,control-plane}/README.md`
- `docs/operations/P01_ENGINE_CALLER_REGISTRATION_RUNBOOK_v1.md`
