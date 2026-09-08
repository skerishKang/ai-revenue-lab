# padiem-embedded-runtime (IP-SIDECAR S2 minimal contract)

Shared, browser-safe embedded shell boundary for host products. S2 scope is
the package-level runtime contract plus one repository-local reference host.
No Engine transport, no provider calls, no secrets, no product semantics.

## Layout

```text
packages/padiem-embedded-runtime/
  padiem_embedded_runtime/   # importable contract modules (stdlib only)
    bootstrap.py             # browser-safe bootstrap/config contract
    lifecycle.py             # closed -> opening -> open -> closing -> closed + disabled
    host_context.py          # untrusted host-context envelope (never authority)
    events.py                # public-safe event projection primitives
    engine_port.py           # abstract Engine port + deterministic fake (tests/demo only)
  reference_host/            # repository-local demo host (fixture-driven, no I/O)
  fixtures/                  # deterministic demo fixture (JSON)
  tests/                     # focused unittest contract tests (stdlib only)
```

## Security invariants (enforced by tests)

- `BROWSER_VISIBLE_SECRET=NO` — secret-like bootstrap values fail closed.
- `HOST_CONTEXT_TRUSTED_BY_DEFAULT=NO` — envelope always `untrusted`.
- `HOST_CONTEXT_AS_SYSTEM_AUTHORITY=NO` — reserved authority keys dropped.
- `CROSS_TENANT_STATE=NO` — per-instance state only, no module globals.
- `RAW_TOOL_ARGS_OR_RESULTS_EXPOSED=NO`, `HIDDEN_REASONING_EXPOSED=NO`,
  `RAW_TERMINAL_OUTPUT_EXPOSED=NO` — event allowlist + shape guards.
- `FAIL_SAFE_DISABLE=YES` — failures land in `disabled`; host-safe results
  keep the host primary journey unbroken.

## Run tests

```text
cd packages/padiem-embedded-runtime
python -m unittest discover -s tests -t .
```

No third-party dependencies. `pytest` also collects the suite.

## Boundary

Authority: `docs/internal-platform/sidecar/README.md`.
Ownership chain: Host/Product Adapter -> IP-SIDECAR -> IP-ENGINE ->
IP-CORE -> B14 -> Provider/model. Control Plane remains the canonical
identity/tenant/entitlement/usage/billing/audit authority.

Refs #1739.
