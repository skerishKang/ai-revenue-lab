# padiem-embedded-runtime (IP-SIDECAR S4 evidence/citation presentation)

Shared, browser-safe embedded shell boundary for host products. S2 delivered
the package-level runtime contract plus one repository-local reference host;
S3 added the reusable host-context bridge, public bootstrap/session
projection, version-compatibility and integration diagnostics, and host-safe
fail-over; S4 adds public-safe evidence/citation presentation primitives
(bounded normalization, deterministic order/dedup/reference labels, host-safe
empty/degraded states). No Engine transport, no provider calls, no browser
network fetch, no secrets, no product semantics.

## Layout

```text
packages/padiem-embedded-runtime/
  padiem_embedded_runtime/   # importable contract modules (stdlib only)
    bootstrap.py             # browser-safe bootstrap/config contract
    lifecycle.py             # closed -> opening -> open -> closing -> closed + disabled
    host_context.py          # untrusted host-context envelope (never authority)
    events.py                # public-safe event projection primitives
    engine_port.py           # abstract Engine port + deterministic fake (tests/demo only)
    compatibility.py         # S3 runtime/host contract version check (no raise)
    diagnostics.py           # S3 public-safe status/reason-code diagnostics
    bridge.py                # S3 untrusted-context -> projection + fail-safe pipeline
    evidence.py              # S4 public-safe evidence/citation presentation (bounded, deterministic)
  reference_host/            # repository-local demo host (fixture-driven, no I/O)
  fixtures/                  # deterministic demo fixtures (JSON)
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
- `DIAGNOSTICS_PUBLIC_SAFE=YES` — diagnostics expose only allowlisted
  status/reason codes; raw exceptions, credentials, and Engine/provider
  material never reach the projected view.
- `VERSION_CHECK_NEVER_RAISES=YES` — malformed/missing host versions yield a
  deterministic unsupported verdict instead of an exception.
- `BRIDGE_NEVER_BREAKS_HOST=YES` — every invalid/incompatible intake returns
  a host-safe outcome (degraded or disabled), never an error to the host.
- `REAL_ENGINE_TRANSPORT=NO` — `EnginePort` stays abstract/fake-only in S3.
- `EVIDENCE_INPUT_TRUSTED_BY_DEFAULT=NO` — citation fields are allowlisted;
  unknown fields and non-public-looking values fail the item.
- `CITATION_PRESENTATION_DETERMINISTIC=YES` — stable order, dedup on
  `(source_id, locator)`, and `[1]..[n]` labels; repeat runs are identical.
- `CITATION_DEGRADED_NEVER_RAISES=YES` — malformed/oversize input yields an
  `empty`/`degraded` host-safe presentation, never an exception to the host.
- `HTML_OR_NETWORK_EXECUTION=NO` — no HTML rendering, no URL fetch, no
  arbitrary link execution; markup-shaped values are rejected.

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
