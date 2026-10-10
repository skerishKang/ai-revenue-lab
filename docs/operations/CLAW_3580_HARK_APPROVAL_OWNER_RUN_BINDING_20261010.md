# Hark #3580 — Fix original Hark run approval and durable P01 readback

Date: 2026-10-10. This is a real B62 product authorization/UI correctness repair, not a claim of full broker-to-resident file execution.

## Observed bug

The Hark Office chooser introduced in PR #4193 stored an Engine-internal `engine_run_id` from selection, then sent it as `run_id` to `POST /api/claw/approvals/decision`. The existing B62 first-party approval route expects the **original Hark/Claw run id**, since it loads the owner-and-workspace-scoped `claw_approval_handoff` row by `(user_id, run_id, workspace_id)`. It obtains `p01_run_id`, pause ID and continuation from this durable row. Sending the internal Engine id instead causes a false missing/foreign pause or fails the response correlation.

## Implemented

1. The chooser still verifies the Engine pause metadata from its trusted selection source, but now POSTs **only original run ID + approve/deny** to the canonical B62 first-party endpoint; response correlation also checks the original Hark run. It never sends Engine-internal run ID or pause/continuation/approval authority to that endpoint.
2. Before the chooser selection route returns an approval-required state, the B62 server independently calls its pre-existing `history_store.load_claw_approval_handoff(user_id=owner_id, run_id=run_id, workspace_id=server_derived_workspace)`. The source's pending claim must correlate exactly with the durable handoff's `p01_run_id`, and stored pause/ref/trusted resume snapshot must be present. Foreign owner, wrong workspace, missing, expired, consumed or incompatible handoffs fail closed. This eliminates source-claim-only fake approval prompts.
3. Existing `claw_approval_decision` retains Engine-exclusive decision verification and consumes the durable continuation once. No new approval issuer, no local READ grant and no broker mutation.
4. UI result check still requires canonical exact original run terminal Broker ACK. The existing PDF preview remains owner-bound.

## Verification

Python tests include 51 PASS (B62 owner decision plus Office chooser), JS 3 PASS (real click chain with **different Engine and Hark IDs**, ensures original Hark ID is the sole decision argument), `git diff --check` clean. Additional negative tests: source claims waiting without durable handoff; foreign Engine ID in durable history; absent handoff store.

## Remaining actual customer E2E

Trusted Office chooser candidate/Engine pause producer and canonical broker command enrollment need real owner/device/root/command linkage; the approved Engine decision and local device permission must be delivered once through authenticated Broker to the shipped Resident's currently unconfigured `office_p01_plan_source`. Resident must produce XLSX/PDF and stage chunks after exact ACK. Operational enablement and Drive WRITE consent are separate. Keep #3580/#3933/#3936 OPEN; #3140 loopback test evidence never authorizes user files.
