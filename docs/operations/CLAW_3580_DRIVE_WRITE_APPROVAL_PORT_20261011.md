# #3580 — Drive WRITE approval port over the existing canonical P01 machinery (2026-10-11)

## What was missing

`GoogleDriveArtifactUploadAdapter` refuses to create a Drive file until its injected
`DriveWriteApprovalPort` returns `True` for the **exact** write intent. No host implementation of
that port existed anywhere in the repository — only test fakes — so the Drive WRITE path could not
be composed even with a grant, and the Drive host boundary (PR #4331) always reported
"no trusted Drive approval port was supplied".

## Investigation result (work A)

- The repository has **one** canonical approval machinery: `padiem_ai_core.agent_approval`
  (`ApprovalPause`, `VerifiedApprovalDecision`, `ApprovalOutcome`, `ContinuationStatus`,
  `resolve_approval_pause`, `tool_invocation_digest`) plus `padiem_ai_core.tool_runtime.ToolInvocation`.
- The closest precedent is `browser_control_lease_authority.BrowserControlAuthorityEvidence`, which
  is explicitly *"a browser-control-specific validator/projection over the existing P01 evidence
  envelope — it is not an approval authority"*. The same shape is reused here for Drive.
- The Engine's only existing WRITE approval grant (`web_xlsx_quote_write_tool_binding`,
  `tool_execution_service._web_quote_write_approval_grant`) is Hark-quote/P01-specific and belongs
  to #3933. It was **not touched**.
- Conclusion: reuse is possible **without a new approval schema or authority**.

## This slice

New `kagent/google_drive_write_approval.py`:

- `drive_write_approval_arguments(...)` / `drive_write_tool_invocation(...)` /
  `drive_write_approval_fingerprint(...)` — the canonical Drive-write argument map
  (`DRIVE_WRITE_APPROVAL_ARGUMENT_FIELDS`), built only from refs the adapter already validated
  (connector/binding/actor/tool/workspace/run/artifact id/SHA/folder/payload fingerprint/capability),
  never from model text, a browser body or a local path. The digest **reuses**
  `tool_invocation_digest`, so there is no second hash authority.
- `DriveWriteApprovalEvidence` — a Drive-specific validator/projection over the canonical
  `ApprovalPause` + `VerifiedApprovalDecision`, with structural checks (pause tool must be the
  canonical Drive upload tool, decision must belong to the pause, decision evidence ref must match,
  evidence must not outlive the pause).
- `AuthorizedDriveWriteApprovalPort` — the `DriveWriteApprovalPort` implementation. Refusal order:
  1. intent must be a Google Drive **create** intent (`google-drive`, canonical tool, no
     `expected_version_ref`) — a READ or overwrite intent is refused **before** any evidence lookup;
  2. trusted evidence must exist for the exact invocation digest;
  3. decision must be `APPROVED`, pause tool/run/digest must match, and the pause scope must carry
     `drive.files.create`;
  4. `resolve_approval_pause` must return `RESUMABLE` (denied/expired refused);
  5. the decision id is consumed **once** (`InMemoryDriveWriteApprovalConsumption`) — a second
     upload can never reuse the same approval.
- `UnconfiguredDriveWriteApprovalEvidencePort` — refuses when no trusted evidence source is wired.
  No new durable store (`NEW_DURABLE_STORE=False`); cross-worker replay protection belongs to the
  separately authorized platform store.
- Any exception inside the port returns `False`; approval material and provider text never surface.

**READ approval is not WRITE approval** (`READ_APPROVAL_IS_NOT_WRITE_APPROVAL=True`): a READ pause has
a different tool id and no `drive.files.create` in scope, and both cases are refused by test.

## Connection to the Drive host boundary

`app/claw_drive_upload_host_composition.py` gained:

- `build_canonical_drive_write_approval_port(...)` — the one canonical approval port a host may inject.
- `approval_evidence` / `approval_clock` inputs on `build_claw_drive_upload_host_state(...)`: when the
  host supplies only the canonical P01 evidence source, the boundary wraps it in
  `AuthorizedDriveWriteApprovalPort`. The existing `approval` input still works, so no prior caller
  breaks.

## Evidence (hermetic)

- New kagent suite `test_google_drive_write_approval_3580` → **16 PASS**.
- kagent focused regression (Drive approval/upload/composition/folder-proof/transport, full chain,
  browser-control lease authority) → **103 PASS**.
- chat `test_3580_claw_drive_upload_host_composition` → **14 passed**, including a **full canonical
  stack upload**: composed real multipart port + `AuthorizedDriveFolderProofPort`-shaped proof +
  canonical approval port built from a P01 evidence double drives the existing adapter to a DURABLE
  artifact with exactly one provider POST and exactly one evidence lookup.
- Covered: approved-exact authorizes exactly once; denied refused; READ approval refused; expired
  pause/evidence refused; foreign run / wrong fingerprint / wrong pause refused; foreign connector and
  version-pinned intent refused before any evidence lookup; evidence-source exception fails closed;
  projection carries no approval material.

## Not implemented or activated

```text
DRIVE_WRITE_APPROVAL_PORT_IMPLEMENTED=YES     # over existing canonical P01 machinery
NEW_APPROVAL_AUTHORITY=NO
NEW_APPROVAL_SCHEMA=NO
NEW_DURABLE_STORE=NO
PRODUCTION_APPROVAL_PORT_COMPOSED=NO          # no host wires a live P01 evidence source yet
DRIVE_WRITE_GRANT_AUTHORIZED=NO               # #2010 READ-only
REAL_DRIVE_UPLOAD=NOT_PROVEN
PRODUCTION_ACTIVATION=BLOCKED
PRODUCTION_MUTATION=0
```

The Engine Hark-quote WRITE approval tool, Calendar #2952, Browser Control #3782, B14 routing, B66
and Windows Resident were **not** modified.
