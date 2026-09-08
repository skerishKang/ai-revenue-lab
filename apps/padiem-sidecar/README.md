# B53 Padiem Sidecar — Product Source Root

Canonical B53 product source root established by #2180 (S4). This tree owns
B53 commercial/product adapter and reference-host semantics **only**.

## Ownership boundary

- All reusable runtime primitives (bootstrap, host context, bridge,
  diagnostics, lifecycle, evidence/citation, attachment, approval,
  streaming/error/retry presentation, Engine port) are **imported** from
  IP-SIDECAR at `packages/padiem-embedded-runtime/` (`padiem_embedded_runtime`).
  Nothing is copied or reimplemented here.
- B53 owns: the product config envelope (`SidecarProductConfig`), the
  delegating `ProductAdapter`, the deterministic fixture-driven
  `reference_host` journey, and handoff-only fake/stub ports.
- Engine and Control Plane remain fake/stub ports in this slice:
  `DeterministicFakeEnginePort` (IP-SIDECAR) and
  `StubControlPlaneContextPort` (B53-owned stub). No real Engine transport,
  no real Control Plane call, no tenant authority, no provider/model routing,
  no action/retry/upload execution, no approval-authority minting.

## Layout

```text
apps/padiem-sidecar/
  README.md
  app/
    __init__.py
    product_adapter.py      # B53 product config + delegating adapter
    reference_host.py       # deterministic conformance journey
  fixtures/
    local_conformance.json  # normal + malformed inputs per proof surface
  tests/
    __init__.py
    test_product_adapter_conformance.py  # delegation/ownership proof tests
    test_reference_host_journey.py       # journey + fail-safe tests
```

## Running the focused tests

From the repository root (Python 3.11+, stdlib only):

```text
python -m unittest discover -s apps/padiem-sidecar/tests -t apps/padiem-sidecar
```

or, with pytest available:

```text
python -m pytest apps/padiem-sidecar/tests -q
```

The tests import `padiem_embedded_runtime` from
`packages/padiem-embedded-runtime/` via sys.path bootstrap in each test
module; no installation step is required.
