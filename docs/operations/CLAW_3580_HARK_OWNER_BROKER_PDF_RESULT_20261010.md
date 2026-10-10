# Hark #3580 — Owner-scoped Broker PDF result display

Date: 2026-10-10. This closes the user-visible result leg for a completed canonical Broker Office run, without declaring the still-missing live P01 selected-file READ approval complete.

## Trusted control flow

1. Hark Office UI already performs selected-candidate lookup and submits the owner's separate decision via the canonical Engine continuation API. On Engine approve response it presents a **manual** '실행 결과 확인' action: never states the Resident has executed merely because Engine returned successfully.
2. The result action asks the existing owner-authenticated `/api/claw/runs/{run_id}/local-result` endpoint to reconcile the original browser-bound run with its canonical terminal Broker command. Only a completed and appended projection for that exact run reveals a link for PDF preview. No browser-supplied command, workspace, document path, authorization token, or Drive intent.
3. The link calls new owner-authenticated GET `/api/claw/office/runs/{run_id}/pdf`. It delegates **exclusively** to existing `LocalRunnerResultSource.read_staged_office_output(owner_id, run_ref, kind='pdf')`. That pre-existing host method checks owner-run history, owner conversation, workspace, successful exact Broker command and ACK, correlation fields, and reconstructs private PDF chunks with full-file hash, PDF header/tail, size/metadata integrity.
4. HTTP response is bounded verified PDF with inline disposition, no-store/private cache, same-origin CORP, nosniff, sandbox CSP and no user-supplied path in filenames. Missing, foreign, stale, absent, invalid or broken stages return bounded status with no private error or file bytes. There is no public method for arbitrary Office binary retrieval and no Drive WRITE action.

## Verification

Owner/missing/foreign/unconfigured/invalid response cases and full exact PDF projection tested with ASGI. Browser test covers candidate selection → canonical Engine owner approval → manual completed Broker status check → correct owner-only PDF preview URL. Python focused 14 PASS; Node 3 PASS. No Production deploy, Secrets changes, source-file modification, Drive uploads or paid model calls.

## Remaining strict operational blocker

The actual P01 Engine still needs a real Office LIST/READ approval pause producer and a device-bound authenticated verified-grant transfer to the Windows Resident. `office_p01_plan_source` is not currently composed in shipped Resident `main()`. The #3140 loopback authority is non-production and MUST NOT be used. This PR only adds final status/preview when the pre-existing trusted source actually has bytes. Keep #3580, #3933, #3936 OPEN.