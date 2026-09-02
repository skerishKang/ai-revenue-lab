# Padiem Claw Release & Rollback Policy

A release is promoted only from a reviewed exact Git revision with reproducible tests and explicit authority boundaries.

## Gates

1. fresh `main` and dependency contract audit
2. branch scope inspection
3. compile/static validation
4. B54 contract/regression tests
5. P01 conformance for cross-layer adapters
6. secret/static-origin audit where applicable
7. preview/staging smoke before production
8. release evidence with exact SHA

## Change classes

- docs-only: no production mutation
- product-local compatible: B54 tests + regression
- P01/B14 integration: cross-layer conformance mandatory
- sandbox/provider: threat model + isolation test + rollback proof
- deployment/config: environment preflight + postdeploy smoke

## Rollback

Rollback restores a previously accepted immutable release artifact/config pair. Do not improvise by editing production live. After rollback verify health, identity/entitlement, safe execution boundary and sandbox cleanup.

Use semver when external consumers exist. Contract-breaking public changes require migration notes. HTML/product copy does not redefine runtime contracts.
