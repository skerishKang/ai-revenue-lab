# Hark P01 Office file-plan evidence → Resident (2026-10-10, #3580)

## Implemented

The Resident's **existing** `build_resident_host` now accepts the explicitly injected, trusted, operator-owned `office_p01_plan_source`. This is NOT an environment flag, HTTP/browser endpoint or public tool, and **the shipped `main()` does not provide one**. A different Office supplier combined with it is rejected.

The new `TrustedP01OfficeFilePlanBridge` binds a plan from the injected trusted P01 host to the exact canonical **successfully ACKed** Broker command: binding, command, tool-request, run, request, revision, sequence, full command fingerprint and device. The plan includes the already-verified canonical **`LocalFileRequest(READ)` and `WindowsFileAuthorityEvidence`**. It must refer to the identical approved XLSX path within the selected root; it cannot originate from LLM text, generic command output, browser payload, directory scanning, an arbitrary absolute path or another user's command.

There is **no new permission/approval authority**. The bridge passes the exact canonical evidence to the existing `P01LocalPermissionWindowsFileAuthorizationPort`, which independently checks: request SHA-256, device/root, recomputed local policy, `ApprovalPause` exact `ToolInvocation`, user-approved `VerifiedApprovalDecision`, approval expiry and single-use decision/fingerprint. The real `WindowsSelectedRootFileRuntime` then independently checks selected-root file confinement, symlink/reparse escapes, READ-only path, file size and intact bytes before a supervised Excel/PDF renderer runs. The downstream post-ACK XLSX/PDF Broker staging remains exactly as in merged PR #4171 and earlier; no duplicate producer is added.

The bridge is a bounded 32-pending evidence cache in a **single trusted host process**, not a durable P01 authority or a grant issuer; consumption is one-shot and duplicate commands are rejected. Failure, absence or wrong-command evidence prevents file read/export and any Broker bytes, preserving the already-ACKed command's terminal truth.

## What was verified

- On a connected Windows PC, built a temporary synthetic XLSX in a NEW selected-root temp directory and used the **real `WindowsSelectedRootFileRuntime` and `P01LocalPermissionWindowsFileAuthorizationPort`** with canonical, synthetic test `ApprovalPause`, `VerifiedApprovalDecision` and local `LocalPermissionRequest`; exact authorized bytes were read, transformed with fake renderer, sent via fake Broker transport only after the genuine test command ACK. No user's real files or Drive access were touched.
- Denied/absent/mismatched-run/mismatched-command/expired/wrong-scope P01 evidence all blocked; no Excel render, no XLSX/PDF transmission, no canonical command re-execution.
- Actual `build_resident_host(..., office_p01_plan_source=...)` composed the real Windows file runtime with P01 authorization and reused the same one-shot bridge for request selection and evidence lookup. The test closes its temporary durable SQLite handle before cleanup.
- Existing Windows selected-root file tests, supervised Excel producer and Resident post-ACK regression were run focused; no broad duplicate CI test suite was added.
- Excel COM itself was exercised with synthetic files in prior merged #4171 and worked; **this change does not run a live user-approved P01 Office task**.

## Remaining operational gates

1. The live P01 supervisor **must actually provide** the `TrustedP01OfficePlanSource.approved_plan` for a legitimate, currently verified user authorization, not a synthetic test record. No such production provider was installed or enabled in `main()` by this PR. This is a deliberately explicit trusted-host integration boundary, not automatic permission on every resident command.
2. The separate Broker binary transfer gate `LOCAL_AGENT_OFFICE_CHUNK_TRANSFER_ENABLED` remains OFF until operator rollout and authenticated end-to-end proof.
3. Supervised Excel COM orphan cleanup on forced timeout and interactive Office license/session still need operational proof before unattended activation.
4. Separately approved Drive READ/WRITE and durable two-file reconciliation with D1 + Claw file-card/PDF preview/download still need live proof.

**No Production deploy, new Windows server, Secrets mutation, OAuth READ/WRITE, customer file mutation or paid AI calls.** Keep #3580/#3933/#3936/#3928 OPEN.
