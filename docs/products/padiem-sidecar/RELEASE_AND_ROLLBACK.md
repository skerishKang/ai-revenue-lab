# Padiem Sidecar Release and Rollback

## Release unit

Treat a production integration as a tuple, not one generic deployment:

```text
Sidecar runtime version
+ tenant/site configuration version
+ product/customer adapter version
+ host integration version
```

A generic runtime release is not proof that every tenant integration is safe.

## Promotion sequence

```text
SOURCE/CONFIG REVIEW
→ DEV/LOCAL CONTRACT TESTS
→ PREVIEW HOST
→ INTEGRATION QA
→ EXACT VERSION RECORD
→ PRODUCTION APPROVAL
→ BOUNDED ENABLE
→ HEALTH + FUNCTIONAL VERIFICATION
→ ACCEPT OR ROLLBACK
```

## Required pre-release evidence

- exact source/runtime version;
- exact adapter version;
- tenant/config version;
- changed capability/data/action scopes;
- host-origin policy;
- relevant automated tests;
- browser/device integration QA;
- rollback anchor;
- known limitations;
- approval authority.

## Release classes

### Generic runtime release

Changes reusable Sidecar panel/bootstrap/runtime primitives. Requires cross-consumer regression against supported adapters.

### Adapter release

Changes domain/customer semantics. Requires exact host/product QA; should not require modifying the generic runtime unless a shared gap is proven.

### Configuration release

Changes tenant/site branding, capabilities, origins, data scopes or allowed actions. Material scope widening receives the same scrutiny as source changes.

### Emergency disable

Turns off a tenant/capability/runtime path without waiting for a normal feature release.

## Rollback priority

Prefer the smallest rollback that restores safety:

1. disable newly enabled capability;
2. roll back tenant/config version;
3. roll back adapter version;
4. roll back generic Sidecar runtime;
5. global Sidecar disable only when necessary.

Host product rollback is not the default recovery for a Sidecar-only defect.

## Fail-closed activation

If configuration, service identity, adapter compatibility or trusted policy cannot be proven, Sidecar remains disabled/unavailable rather than guessing a fallback authority.

## No hidden fallback

Do not silently bypass Engine/Core/B14 by calling a Provider directly when shared platform execution fails.

## Data/action rollback

A software rollback cannot automatically undo a completed material host action. Action contracts must therefore use approvals, idempotency and explicit compensating-action policy where applicable.

## Production verification

After activation verify at minimum:

```text
HOST_PRIMARY_JOURNEY = UNAFFECTED
SIDECAR_BOOTSTRAP = PASS
TENANT/ORIGIN_BINDING = PASS
CONTEXT_PROJECTION = PASS
ENGINE/CORE EXECUTION = PASS
EVIDENCE UI = PASS where applicable
ACTION BOUNDARY = PASS where enabled
SECRET EXPOSURE = 0
CROSS_TENANT LEAKAGE = 0
```

## Rollback evidence

Record what was reverted, exact version/config restored, verification result and unresolved incident follow-up.

## Git-connected deployment caution

A repository merge may trigger existing automatic deployments. Before enabling a real B53 production target, define path-scoped deployment boundaries so unrelated monorepo merges do not unnecessarily redeploy Sidecar.

## S0 boundary

No deployment identity, CDN, DNS or Production target is created by this document.

Refs #1722 #1723