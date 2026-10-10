# B66 CGI independent QA: current proof and next safe operator gate (2026-10-11)

## Scope: Kim Beom-shin CGI 1–3 item quotation MVP only

The user-facing acceptance is **CGI password account -> ten Guided questions ->
actual D1 save -> sign out -> independent browser sign in -> resume ->
QuoteCore totals -> approved CGI browser PDF -> scoped synthetic cleanup**.
The existing CGI alpha account has an unfinished D1 Guided row that is **PRESENT**.
No command is authorized to overwrite or delete it.

## Already executed

- Live CGI ten-question browser/QuoteCore/browser PDF (isolated Guided persistence):
  Actions **38070751613** SUCCESS. Does not establish real D1 writes.
- Live real D1 row preserved, independent same-owner browsers and resume:
  Actions **38070864691** SUCCESS. Does not establish a new complete quote cycle.
- Complete-text Gemini CGI real-model PDF: Actions **38069160662** SUCCESS.
- Missing unit price -> Gemini follow-up -> PDF: Actions **38069493985** SUCCESS.
- Live original-PDF fixed-area raster measurement: Actions **38071689775** SUCCESS;
  unmasked MAE 0.074/255, |delta| > 16 only 0.021%; CGI export is raster image
  PDF, original is text/vector PDF, not byte- or structure-identical.
- Newly added synthetic two-account ten-step real SQL test:
  `apps/padiem-chat/tests/test_b66_guided_independent_qa_e2e.py`.
  Ten authenticated PUTs, independent same-owner GET each step, foreign account
  isolation, actual QuoteCore totals KRW 22,000, exact scoped DELETE, zero rows
  after cleanup. Uses **local SQLite with the actual D1 migration SQL and
  B66 Starlette HTTP routes**; never claims Production D1.

## Why a second production password signup alone is NOT sufficient

- `POST /api/padiem/auth/password/register` can register a distinct account.
- The company profile has a separately owner-scoped authenticated PUT route.
- The **approved Saved Quote Skill** has no public write/assignment route:
  `b66_quote_skill_provisioning.py` needs a trusted operator grant and
  server-resolved canonical target. An unapproved user cannot inherit the
  existing CGI owner's quotation skill.
- `quote-browser-pdf.js` pins the CGI certified preview and PDF to an exact
  `CGI_SKILL_ID` and approved base SHA. A newly assigned generic E2E Skill
  is **not** equivalent to CGI; an independent account with an arbitrary
  saved-skill row ID does not prove the CGI original PDF flow.
- The existing protected GitHub Production environment exposes only the CGI
  alpha login for this smoke; no second CGI credential pair was available at
  the time of this investigation.
- There is an existing guarded test-skill provisioning workflow
  `.github/workflows/b62-b66-e2e-skill-provision-gate.yml`, but it creates
  **a synthetic generic Skill**, not automatically a second CGI certified
  fixed-ID assignment.

## Required safe, end-to-end staging authority

Preferred: an **isolated B66 QA staging environment with its own D1 binding**,
separate from all CGI alpha/customer rows, and test-only password credentials.
The test environment must resolve its own user/workspace and provision an
operator-approved CGI Skill and CompanyProfile using an approved, public source
artifact. To preserve the currently hard-pinned CGI Skill ID without changing
Production code or duplicating a global row ID, use **a separate D1 database**
where this same key can be scoped to QA without conflicting with the live row.

This requires:
1. Authorized staging Worker/Pages URL and QA-only D1 binding, verified as
   **distinct from Production**. Never repoint Production or alter its D1.
2. One QA username/password stored in an authorized secret manager with no
   plaintext logs, plus synthetic CompanyProfile (never a real customer's).
3. Server-side trusted operator grant to assign the existing **approved CGI
   template contract** to the QA user; keep the approved Skill ID, asset digest,
   fingerprint and source rights verifiable. Do not simply forge the grant or
   copy private customer source data into QA.
4. An exact-main protected one-shot browser workflow with preflight:
   D1 QA scoped slot EMPTY, approved CGI Skill+Profile READY, full ten-step
   browser writes enabled only for QA URL, midpoint separate login/resume,
   QuoteCore/PDF validation, and exact synthetic-marker cleanup readback.
   On failure, preserve evidence; never delete a row not proven synthetic.
5. Actual owner consent before modifying Production Secrets, Production Worker
   bindings, or using customer-owned CGI row; **none done by this task**.

Alternative if a verified existing independent CGI QA account already has
the correct approved Skill, profile and EMPTY D1 row: use it; no new staging
binding or new account required.

## Decision gate

`LOCAL_10_STEP_REAL_SQL=PASS` is NOT `PRODUCTION_CGI_END_TO_END=PASS`.
Do not close #4229 until one uninterrupted signed QA session actually saves
to the isolated D1 and another independently authenticated session resumes it
and produces the genuine CGI browser PDF. Keep #4117/#3839 native Sol multipage
work out of this 1–3 item MVP acceptance.
