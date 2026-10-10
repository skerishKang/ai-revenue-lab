# Hark #3580: browser candidate selection and canonical Engine decision handoff

Date: 2026-10-10. This implementation is an **owner-facing, fail-closed UI/API slice**, not proof of the full production Hark Office E2E. Do not enable it on Production until the real trusted source is supplied.

## Implemented

1. Existing B62 Claw 'Connect this computer' panel now contains a local quote candidate chooser. Users click '견적서 후보 조회'; the browser derives the run_id from the existing canonical connected local-handoff view model; it never accepts free-form local paths or claims a working device without that projection.
2. New owner-cookie-authenticated GET /api/claw/office/candidates?run_id=... accepts only a run id and calls an explicitly injected trusted `claw_office_chooser_source.candidates(owner_id,run_id)`. With no source (default Worker), it responds 503. It discloses only validated filename, type, size and opaque SHA-256 candidate_ref, up to 40; strips path/content/owner/credentials/evidence. Every response sets no-store.
3. New owner-cookie-authenticated POST /api/claw/office/candidates/select accepts EXACTLY run_id and candidate_ref. All caller-supplied path, workspace, decision, approval evidence or identity fields are refused. The trusted injected `source.select` must verify the owner/run/candidate and have already persisted a canonical P01 Engine approval pause; the route will only project its `awaiting_approval` outcome with an exact Engine run ID, never 'approved', 'execution_started' or a file READ grant.
4. The chooser's explicit Approve/Deny buttons submit **only `{run_id: engine_run_id, decision}`** via the existing B62 `/api/claw/approvals/decision` first-party authenticated Engine continuation. It does not build VerifiedApprovalDecision, ToolAuthorizationContext, DeviceCommandEnvelope or any broker credential. An approve response only confirms Engine continuation; the UI does **not** assert PDF generation, Drive upload or a completed Local Runner result. A failed or unconfigured source is shown as unavailable, not success.
5. Existing KAgent `P01ApprovedSelectedRootQuoteDiscovery` (PR #4189) and `TrustedP01OfficeFilePlanBridge` (PR #4175) remain unchanged, as do existing source-file READ authorization and Windows Excel renderers. The new B62 source is a typed host injection seam, currently not configured in the production Worker.

## Verification

Owner-bound ASGI tests verify missing auth/source, foreign owner, malformed trusted results, omission of private paths/content, selection cannot promote browser fields into P01 authority, and correct engine-run-only approval projection. JavaScript tests validate candidate response bounds, UI click → prepare → canonical Engine decision request, and disconnected local run network refusal. No real operator file or paid model calls in tests.

## Remaining to actually complete requested E2E

**1. Trusted backend source:** A new product P01 Office tool flow must create a real owner-approved metadata-only LIST and later an exact per-file READ task through the already existing Engine-owned canonical approval pause/decision protocol. It must store the candidate set and bind run, owner, workspace, device, selected root, command and exact request fingerprint (one-shot, durable, TTL), and relay only approved evidence by authenticated device-bound transport. Current #3140 acceptance loopback is explicitly not a production source.
**2. Resident live composition:** The new owner-approved source must actually inject `office_p01_plan_source` into Windows Resident build_resident_host and connect the already implemented selection READ → supervised Excel XLSX/PDF or separate legacy XLS/PDF → post-ACK Broker source+PDF staging. Conversions of original .xls must have their own truthful kind and lineage.
**3. User result:** Broker owner-only reconciliation → separately consented Google Drive WRITE and D1 indexing → canonical PDF preview/download and status in Hark. Existing Engine continuation alone does not prove Resident execution or user file delivery.

Until these are deployed and exact-head verified with real owner approval, this UI is present but presents a truthful 503 unavailable status. No Production deploy, Secrets mutation, Drive upload or model call performed. Keep #3580/#3933/#3936 OPEN.