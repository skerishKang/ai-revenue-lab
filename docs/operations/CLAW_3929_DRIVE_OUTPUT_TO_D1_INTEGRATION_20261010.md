# #3929 / #3580 — trusted Drive durable output → owner D1 index

**2026-10-10 KST · source integration, no Production Drive activation**

## What is now composed in source

`apps/padiem-chat/app/claw_durable_drive_output_pipeline.py` is the B54
trusted server compositor between the **existing #3580**
`GoogleDriveArtifactUploadAdapter.create_output` and the **already deployed
D1 026 / #4127** `D1HistoryStore.register_owner_conversation_artifact` port.

`create_app(..., claw_drive_artifact_uploader=<existing-CP-approved-adapter>)`
installs a `app.state.claw_durable_drive_output_pipeline` internal-only
object. **Default (no injected adapter) is None**, so the presence of a D1
binding, auth cookie, arbitrary user JSON or model output does not grant
Drive WRITE or activate a provider.

The compositor:
1. Resolves current owner+conversation from server-authenticated, previously
   saved identity; checks **completed canonical run** and CP workspace BEFORE
   any provider attempt.
2. Calls the **real existing Drive upload adapter exactly once**. This adapter,
   *not this compositor*, checks bound consent, valid CP WRITE scopes,
   parent folder proof, immutable original file bytes and SHA, safe upload
   idempotency and provider metadata receipt. It returns a DURABLE canonical
   artifact only on provider-confirmed success.
3. Revalidates the canonical returned provider receipt against the exact
   `artifact_id + SHA + run + workspace + binding + idempotency key + folder`.
   A Google Workspace PDF export that is only REGISTERED but not DURABLE
   is expressly **not** accepted as a successful Drive artifact.
4. Rechecks the current owner/run after the provider operation. Calls the
   existing D1 trusted registration port only for an actual DURABLE
   XLSX/PDF whose original run is completed in this owner/thread/workspace.
5. Returns a sanitized artifact-id/SHA record, **not** Drive file URL,
   provider ID, a new READ token, or PDF/XLSX content.

No parallel output retries: Drive upload may succeed just before an owner
revocation or D1 outage; if registration then fails, the result is **unknown /
not indexed**, never a false PASS. The provider may still contain an uploaded
orphan. A separate audited reconciliation operator, not an automatic
re-upload, is the only safe recovery strategy.

## Actual focused evidence

The new `test_3929_claw_drive_output_registration.py` exercises:
- ACTUAL `GoogleDriveArtifactUploadAdapter` implementation, fake separately
  approved Drive provider and folder proofs, SHA/size-verified binary payload;
- Real SQLite running migrations 001/009/014/015/**026**; canonical completed
  Claw run → provider receipt → D1 durable registry → **existing logged-in
  Starlette GET** with matching artifact ID+SHA and no provider ID disclosure;
- An actual synthetic `openpyxl` XLSX and synthetic PDF, registered as
  independent immutable artifacts and resolved separately by type;
- Wrong owner/conversation/workspace, incomplete run before provider;
- Missing WRITE approval before upload; and uncertain post-upload D1
  refusal with **zero auto retries**;
- `create_app` default unconfigured versus explicitly trusted adapter
  injection; no new public write API.

The Drive provider is fake in this test: **no real Google WRITE** occurs.
No actual Office PDF conversion is claimed by these upload tests; the
separate #3933 real Windows Excel local canary remains the Office evidence.

## Still blocked — DO NOT CLOSE #3929/#3580/#3933/#3936

- The production Worker root does **not** inject a genuine owner-authorized
  Google Drive uploader/grant. Drive WRITE was never authorized here and
  remains unavailable until explicit user consent and CP-controlled binding.
- No existing Claw P01/Office task *currently invokes* this internal
  compositor after its real output: task/plan execution, approved file
  editing, byte download and visible Claw file card remain separate work.
  Do not infer functional Drive/Office operations from source-only host
  injection.
- Real cross-session file selection and independently authorized
  Drive material **READ**, PDF preview/download, later XLSX revision, and
  Hark eight-scene end-to-end validation are still outstanding.
- Production D1 026 has already been approved/applied/read back **EXACT**.
  Do **not** rerun it. No new schema, Worker deployment, secrets or model
  change in this PR.

```text
D1_026_PRODUCTION=EXACT_PREVIOUSLY_VERIFIED
PROVIDER_APPROVAL_REUSED=YES_BY_CONTRACT
TRUSTED_UPLOAD_TO_D1_HOST_SEAM=CONNECTED_IN_SOURCE
FAKE_PROVIDER_BINARY_RECEIPT_TO_REAL_SQLITE_D1=PASS
XLSX_AND_PDF_DISTINCT_ARTIFACTS=PASS_OFFLINE
CROSS_OWNER_FOLLOWUP=DENY_OFFLINE
PRODUCTION_REAL_PROVIDER_ADAPTER=NOT_INJECTED
PRODUCTION_DRIVE_WRITE=0
PRODUCTION_DEPLOY=0
HARK_USER_UI_E2E=NOT_VERIFIED
```
