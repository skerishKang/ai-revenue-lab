# tests/e2e — Web ↔ Control Plane ↔ Desktop non-model E2E (LOCAL3, #3098)

This directory is LOCAL3-owned integration/E2E harness territory for issue
**#3098** (branch `test/3098-web-desktop-nonmodel-e2e`). It composes the REAL
product modules from three areas and proves the boundary contracts between
them — it does not replace any of them and it does not create a new execution
authority:

```text
PAIRING_AUTHORITY      = packages/padiem-control-plane (InMemoryBrokerPairingAuthority)
APPROVAL_AUTHORITY     = canonical P01 ApprovalPause/VerifiedApprovalDecision objects
PERMISSION_AUTHORITY   = existing kagent Local Agent permission contracts (#1635)
PHYSICAL_EXECUTION     = existing kagent Windows runtimes (process + file)
WEB_PRESENTATION       = existing padiem-chat Claw routes / app factory
```

## What is proven

```text
Web user/session → canonical account/workspace → device visibility
→ paired/online device → bounded work ticket → Local Agent admission
→ local deterministic action → bounded execution result
→ result/artifact metadata → same Web conversation projection
```

with the fail-closed matrix:

```text
HAPPY_PATH=PASS              (cross-platform receipt mode + real-Windows mode)
OFFLINE_DEVICE=FAIL_CLOSED   REVOKED_DEVICE=FAIL_CLOSED
WRONG_ACCOUNT=FAIL_CLOSED    WRONG_WORKSPACE=FAIL_CLOSED
EXPIRED_TICKET=FAIL_CLOSED   REPLAYED_COMMAND=FAIL_CLOSED
CAPABILITY_ESCALATION=FAIL_CLOSED
MODEL_CALLS=0                (the happy path runs with all sockets blocked)
RAW_SECRET_PROJECTION=0      (injected secret never reaches any projection)
CANCEL=PASS / TIMEOUT=PASS   (real Windows runtime, Job Object tree kill)
```

The successor model is intentionally absent (`MODEL_SELECTION=NO`): no model,
provider or b14 client is constructed anywhere on this path, and the
`no_network` fixture fails the loop the moment any socket is opened.

## Fixture rule

The desktop legs only ever touch the pytest `tmp_path` fixture directory
(`fixture-root/sample.txt`). No real user file, personal path, network service
or production resource is read or mutated. All transports are in-process
handler-backed ports; no public inbound port exists.

## Run

```bash
# from apps/padiem-chat (the venv carries the three file-dependencies)
uv sync --locked --extra dev
uv run --locked python -m pytest ../../tests/e2e -q
```

CI runs the same suite on Ubuntu and Windows via
`.github/workflows/web-desktop-nonmodel-e2e.yml`. Windows-only cases
(real subprocess read, file-capability separation, timeout/cancel) skip on
other platforms.

## Known boundary finding (reported, not fixed here)

The broker work-ticket material is process-execute-shaped (`argv`,
`cwd_relative`, …) and `BoundLocalAgentRuntimeAssembly.execute` accepts only
`LocalCommandRequest`. A ticket literally carrying
`capability=filesystem.read` therefore cannot be expressed yet;
`WindowsSelectedRootFileRuntime` (the #1635 file capability) is enforced locally
with its own P01 file grant but is not reachable through a broker ticket. That
is a shared-contract/implementation extension owned outside LOCAL3 (control
plane material schema + desktop assembly), so this harness drives the canonical
process-execute ticket for the composed loop and proves the
`filesystem.read != filesystem.write` separation on the local runtime leg.
