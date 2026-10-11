# Hark WEB-FIRST P01 WRITE owner decision — separate durable authority

**2026-10-11 KST. Source-only intermediate milestone for #3933 / #3928.**

## Why a separate decision record is mandatory

The original READ confirmation from #4279 and the source edit reservation
from #4289 are **not consent to WRITE**. A distinct Engine/Core
`workspace.xlsx.quote.revise_workcopy` pause must be shown to the
authenticated owner, who must explicitly approve or deny the exact
school/supply edit plan, original SHA, private workcopy and run.

## Source implemented here

- New additive **B62 D1 migration 033**, `claw_web_xlsx_quote_write_decisions`:
  unique selection/pause/continuation, immutable owner/workspace/run,
  source document + SHA, workcopy document, edit SHA, explicit approve/deny
  and one-shot dispatching/confirmed/denied state. This record is distinct
  from the existing original-read decision D1 and the edit *request* D1 (032).
- A private `D1WebQuoteWriteOwnerDecisionStore` compares all edit receipt
  fields before INSERT, binds Core pause/continuation to a single owner
  decision, refuses duplicate dispatch and retains **unknown** outcomes
  in dispatching state (no auto replay). Source revision storage is
  unchanged and original bytes remain untouched.
- Independent Engine `D1WebQuoteOwnerWriteApprovalGrant` reads the trusted
  B62 database directly. It verifies Core `ApprovalPause` +
  `VerifiedApprovalDecision` + invocation SHA, original READ-approved
  live source/run/workcopy via previously reviewed D1 resolver, exact
  selection/edit SHA and separately reserved WRITE decision row including
  pause, continuation, outcome, first-party owner decision/evidence IDs.
  It does not grant write on a browser flag, prior READ consent, an edit
  request alone, or a forged/mismatching D1 row. Denied and approved
  decisions are both checked against the actual Core pause.
- App factory constructs private B62 owner-WRITE ledger only when the
  real workspace D1 storage is present. It **does not** turn on the
  `web_xlsx_quote_write_enabled` flag or install a public WRITE action.

## Not yet connected (do not declare E2E success)

- Actual Core WRITE pause issuance and **signed-in browser approve/deny
  endpoints**, durable Engine WRITE continuation store, Worker Service
  Binding adapter, and first-party composition of the new verifier are
  **still missing**. The source Engine code defaults to no WRITE grant.
- This migration is not applied to Production. No Production flags,
  secrets, customer data, arbitrary Drive/Windows access or real file
  processing were changed.
- A faithful Excel-to-PDF renderer for supported quote XLSX, two
  owner-only artifact cards, and authenticated deployed full-flow
  verification remain unfinished. Keep #3933/#3928/#3936 OPEN.

## Evidence

`apps/padiem-ai-engine/tests/test_3933_web_quote_owner_write_grant.py`
tests actual Core pause/digest, two outcomes and tampered B62 receipt
scope. `apps/padiem-chat/tests/test_3933_web_quote_write_owner_decision.py`
tests independent owner ledger, one-shot reservation, rejects unknown
Engine results and mutated edit/file/owner identifiers.
