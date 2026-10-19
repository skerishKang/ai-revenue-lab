# Hark #3580 — First-party Engine verified Office READ receipt boundary

Date: 2026-10-11 (KST). This is an incremental implementation of the previously absent **trusted Engine approval evidence handoff**. It does **not** assert the full owner→Broker→Resident E2E is active.

## Existing problem

The Engine already issues an `ApprovalPause` for a registered Office tool and verifies the first-party signed-in decision, but the immutable `VerifiedApprovalDecision` is process-local during `resume_payload`. There is no private, persisted handoff of that actual approved READ evidence to the product/Broker/Resident lane. Existing #3140 loopback test authority must never substitute for it.

Earlier #4202 added an internal `OrchestrationRequest.trusted_agent_bridge_run_id` but the real Engine orchestration service had no trusted internal entry to populate it. The default random `bridge_run_*` caused the canonical Windows file READ validator to reject the pause's run ID.

## Implemented in Engine

1. The server-only Python keyword `OrchestrationEngineService.orchestrate_payload(payload, trusted_office_run_id=...)` permits *only* the registered `hark-office-local-p01` application with exactly one LIST or READ tool and arguments containing the **identical** trusted run ID. It injects the existing Core internal run identity. Public JSON rejects attempted `trusted_office_run_id`; no HTTP route or browser access to this keyword was created. Server caller must independently authenticate the Broker owner/workspace/device/root and command before calling it.
2. `ApprovedOfficeReadReceipt` binds the exact immutable `ApprovalPause` and **actual Engine-first-party-verified** `VerifiedApprovalDecision`, canonical consumed continuation reference, and the exact registered READ ToolInvocation SHA-256 and arguments (device, run, root, selected basename, request fingerprint). It rejects denied/expired/foreign/tampered READs, mismatched run, non-READ tool or malformed source. No workbook content is held.
3. On a successful Engine USER_CONFIRMATION resume, only *after* the continuation is atomically consumed and the ToolRuntime returns COMPLETED, an **optional, server-injected** `ApprovedOfficeReadReceiptSink.record_verified_office_read(receipt)` is called. It is never fed the raw browser user submission. LIST/deny/error paths do not emit READ receipts; a replay of the consumed continuation cannot emit again.
4. If an injected sink fails or does not acknowledge durable persistence with literal `True`, Engine responds 503, does not assert local file access and does not retry the consumed decision. This deliberately sacrifices liveness on ambiguous storage failures rather than double-issuing local file read evidence; the user must begin a fresh operation. A future fully durable deployment should co-locate persistence and continuation commit transactionally.
5. The production Engine composition does **not** inject an Office sink. Default behavior remains unchanged, OFF with no private approval export or local file permission. The receipt is NOT a `WindowsFileAuthorityEvidence` grant and does not authorize device operations.

## Verification

Python tests cover real Engine registered Office READ first-party approve/consume → private receipt exactly once; default random run remains; injected trusted run correlation; unauthenticated request-field injection 400; mismatched trusted run 409; LIST and deny do not emit read receipt; sink refusal returns 503 and cannot be replayed; immutable receipt rejects filename/run/fingerprint/permission-scope changes. Core/Engine focused 21 PASS. No Production deploy, secrets or user file read, no Cloud Drive WRITE, no paid model call.

## Remaining for actual Hark Office E2E

B62 must provide a real trusted Office chooser source, backed by the canonical Broker selected-root candidate metadata and an authenticated owner/workspace/device/run binding, and call the **private** Engine Office orchestration entry. The Engine private receipt sink must be implemented as durable per-owner/per-Broker-command, one-shot TTL storage over authenticated service bindings, and paired with a device-owned `LocalPermissionRequest`. Only then may the *already existing* Windows `P01LocalPermissionWindowsFileAuthorizationPort` and `TrustedP01OfficeFilePlanBridge` consume canonical evidence via `office_p01_plan_source` on the shipped Resident. The canonical file read + supervised XLSX/PDF + Broker post-ACK upload + Hark PDF preview must then be proven on a user-approved local file. Production enablement and Google Drive WRITE require separate consent.

Keep issues #3580, #3933, #3936 OPEN until real proof. No test-harness approval is production consent.
