# padiem-embedded-runtime (IP-SIDECAR S6 approval presentation)

Shared, browser-safe embedded shell boundary for host products. S2 delivered
the package-level runtime contract plus one repository-local reference host;
S3 added the reusable host-context bridge, public bootstrap/session
projection, version-compatibility and integration diagnostics, and host-safe
fail-over; S4 added public-safe evidence/citation presentation primitives;
S5 added browser-safe attachment input presentation (bounded selection
metadata, deterministic upload-lifecycle states, opaque server-issued
`att_*` ref display tokens); S6 adds display-only approval/action-confirmation
presentation (bounded proposal projections, staged confirmation intents,
host-driven approval states, opaque upstream reference tokens). No Engine
transport, no provider calls, no browser network fetch, no File/Blob byte
reads, no ref minting, no approval verification or authority minting, no
action execution, no secrets, no product semantics.

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
    attachment_input.py      # S5 bounded selection/lifecycle/opaque att_* ref presentation
    approval_presentation.py # S6 display-only proposal/intent/state/reference projection
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
- `ATTACHMENT_INPUT_TRUSTED_BY_DEFAULT=NO` — selection fields are
  allowlisted (`name`/`media_type`/`byte_size`); path/URL/markup/secret-shaped
  values fail the item; local paths and storage locators can never pass.
- `FILE_BLOB_BYTE_READ=NO · DOM_INPUT_OWNERSHIP=NO` — the sidecar projects
  host-supplied bounded metadata only; it never reads bytes or owns a picker.
- `ATTACHMENT_REF_MINTING=NO` — `att_*` refs are grammar-validated display
  tokens issued by the Engine attachment authority; URL/path-shaped refs are
  rejected without retaining the raw value.
- `SHARED_BOUNDS_ARE_HINTS_NOT_AUTHORITY=YES` — jpeg/png/webp and the 4 MiB
  image bound surface as validation hints; product acceptance policy stays
  with product adapters, byte/media authority stays with Engine.
- `LIFECYCLE_PRESENTATION_NEVER_BREAKS_HOST=YES` — malformed lifecycle input
  degrades to a safe `idle`/`INVALID_HOST_INPUT` view, never an exception.
- `APPROVAL_AUTHORITY_MINTING=NO` · `APPROVAL_TOKEN_MINTING=NO` — the sidecar
  projects upstream approval proposals/states for display only; requirement
  evaluation, decision verification, expiry/scope enforcement, and
  authority/evidence issuance belong to Core/Engine/P01.
- `DIRECT_ACTION_EXECUTION=NO` — confirmation intents (`approve`/`reject`/
  `confirm`/`cancel`) are staged for host handoff; staging performs no
  execution, transport, or handoff itself.
- `APPROVAL_PROPOSAL_FIELDS_ALLOWLISTED=YES` — only bounded
  `proposal_id`/`tool_id`/`requirement`/`summary` pass; raw Tool
  args/results, diffs, URLs, paths, markup, and secret-shaped values fail the
  item; presentation is order-preserving, deduplicated, capped, and never
  raises.
- `APPROVAL_STATE_HOST_DRIVEN=YES` — only allowlisted states/reason codes
  display; the sidecar never owns a clock or decides expiry; malformed state
  degrades to `unavailable`/`INVALID_HOST_INPUT`.
- `UPSTREAM_REFERENCE_DISPLAY_ONLY=YES` — identifier-shaped public refs
  render as opaque non-executable tokens; URL-shaped refs are rejected
  without retaining the raw value.

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
