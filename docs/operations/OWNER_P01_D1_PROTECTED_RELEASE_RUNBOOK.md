# Owner P01 D1 — Protected Worker Connection & Rollback Runbook

- Status: **SOURCE-READY OPERATING PROCEDURE — NOT EXECUTED IN PRODUCTION**
- Issue: [#3782](https://github.com/skerishKang/ai-revenue-lab/issues/3782)
- Execution surface: existing GitHub Actions / Cloudflare API; workflow `.github/workflows/b54-owner-d1-controlled-connection.yml`
- Engineering authorities: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`, `AI_DEVELOPMENT_OPERATING_POLICY.md`, `b62_binding_state_guard.py` and canonical `cloudflare_served_version_cli.py`
- No new Cloudflare database, generic deployer, browser-control model, Broker or Resident is introduced.

## Exactly what this procedure changes

One existing Cloudflare Worker **binding configuration**, not the Worker source, is eligible per transaction. The binding `BROWSER_CONTROL_OWNER_P01_D1` connects the already-provisioned `padiem-browser-owner-p01` database to one Worker. All original bindings are inherited from the EXACT currently served immutable version. Expected counts at the audited prestate: Engine 18→19, B54 Chat 27→28. Counts/identities are verified fresh before any write, never assumed from a historical screenshot.

**Ordering:** Engine `padiem-ai-engine` first. Only after it is proven in Production may Chat `padiem-chat` be processed. A single dispatch must never change both Workers or call a Browser Use action. #3783 Browser Use remains Draft, with Product P01/Broker/Resident G1–G3 independently gated.

Cloudflare references: [Worker PATCH settings](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/subresources/script_and_version_settings/methods/edit/), [Worker versions/deployments](https://developers.cloudflare.com/workers/versions-and-deployments/), [rollback](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/).

## Preconditions (fail closed)

1. Owner has explicitly authorized this **named Production connection**. Merger approval of a source PR alone is **NOT** Production write authorization. Workflow uses the protected GitHub `production` environment.
2. The complete current GitHub `main` SHA is recorded; dispatch `target_sha` must equal exact current main at start and at the final prewrite check.
3. Verify the Cloudflare account hosting both exact Workers. Confirm **three distinct** Owner, Chat and Engine D1 resource UUIDs. No new D1 create or schema write.
4. Resolve actual 100%-serving version through the shared canonical deployments API resolver, not Wrangler raw-list ordering. Require the **latest uploaded version to equal that served version** (Cloudflare settings PATCH may refuse divergence, e.g. error 10214). Reject traffic splits, unknown versions, unfamiliar binding types, drifted original D1/service/P01 caller credential, or owner binding already present.
5. Verify Engine-first ordering (Engine transaction requires Chat owner binding absent; Chat transaction requires Engine owner binding already correctly installed), and check no concurrent Worker release is underway. There is a residual external concurrent-mutation race because the Cloudflare endpoint is not known to provide an atomic compare-and-swap; a separate manual operational release freeze remains necessary.

## Apply — one Worker per dispatch

Start only with the exact, owner-confirmed `workflow_dispatch`:

| Input | Engine example | Chat follow-up |
|---|---|---|
| `mode` | `apply` | `apply` |
| `worker` | `engine` | `chat` |
| `target_sha` | **Current main SHA**, exact | **Current main SHA**, re-read |
| `expected_active_version` | Fresh Engine 100%-served version | Fresh Chat 100%-served version |
| `anchor_run_id` | Empty | Empty |
| `confirmation` | `CONNECT_OWNER_P01_D1_FROM_EXACT_MAIN` | Same |

The job runs through a strict sequence:

1. Verify SHA/account/approval and obtain GET-only `/deployments`, immutable `/versions/{id}`, `/settings`, latest versions and three D1 inventories. Check peer Worker's served version.
2. Create **in runner memory only** a multipart JSON PATCH candidate whose old entries each have `{"type":"inherit","name":"...","version_id":"<exact-old-version>"}`, followed by one `{"type":"d1","name":"BROWSER_CONTROL_OWNER_P01_D1","database_id":"<actual-owner-DB-UUID>"}`. Preserve writable `workers/message`/`workers/tag` annotations. Do not use `latest`, `old_name`, or raw Worker mock `wrangler.toml`.
3. Capture a **new** non-secret pre-mutation rollback anchor, distinct from #3856's prior GET-only preflight artifact. It contains original served version ID, source main SHA, Worker and peer identifiers, immutable metadata digests and binding counts; no token, DB UUID, secret name/value or raw settings payload. Upload as `owner-d1-rollback-anchor-<apply-run-id>` with `if-no-files-found:error` **before any mutation**. An upload failure means **no PATCH**.
4. Re-read active AND latest Worker version and exact main immediately before mutation, aborting if any changed.
5. Serialize the JSON file **directly** as `{"bindings":[...],"annotations":{...}}`. The multipart field is named `settings`, so the file must **not** contain another top-level `{"settings":...}` wrapper. Validate the on-disk structure before uploading the rollback anchor.
6. Send one official `PATCH /settings` with multipart `settings=@candidate.json;type=application/json`. Mark attempt before the command. After HTTP 200 and `success:true`, compare **the actual API response's binding list** with the original version: require all old authorities intact and exactly one Owner D1 addition. A 200 response with no Owner D1 is a failed mutation. No retries.
7. Re-resolve the 100%-served version and GET its immutable detail and settings. Require a distinct new served version with exactly one Owner D1 addition, all old bindings/Secret identities, exact code etag/Assets/compatibility/runtime metadata parity and writable annotation parity. Check existing Chat health when Chat is changed. Do not enable Browser Use in the same dispatch.
8. Only a complete post-served proof permits `OWNER_D1_ONE_WORKER_CONNECTED=VERIFIED`. A successful PATCH HTTP response alone does not.

## First live trial finding (2026-10-09)

- Initial Engine apply run [#37902435504](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37902435504) returned HTTP 200 but created a 100%-served version with **no Owner D1 binding**. The candidate file had an extra outer `settings` object. This defect was in the CENTRAL-authored release procedure, not caused by the unrelated OAuth read-only source changes.
- Original Engine version `79311785-1351-49e1-ac89-f069cdcfab0b` was restored and proved 100%-served by the owner-approved rollback run [#37903374269](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37903374269). Original 18 bindings, script metadata and runtime were restored; Chat was unchanged.
- The API-generated version changed both script `etag` and `last_deployed_from` (Wrangler → API), while handlers and runtime matched. Cloudflare documents etag as hashed script content, so **code equivalence has NOT been proven**. Keep the existing exact script-resource integrity guard until independent per-version content proof or an approved equally strong replacement is available. Do not declare a second live apply ready solely because the payload JSON tests pass.
- A new live Engine apply requires **separate owner approval**, exact current version checks, a new prewrite rollback anchor and resolution of the code-integrity evidence issue.

## Actual 1,804-module source equivalence, 2026-10-09 (READ ONLY)

The failed first Engine settings PATCH created version `7bb1efa1-1252-4a18-9aba-9dc03a0d909f` from original version `79311785-1351-49e1-ac89-f069cdcfab0b`. Their ordinary Version Detail `resources.script.etag` values differed, as did `last_deployed_from` (`wrangler` → `api`).

Cloudflare's **documented, version-specific** beta GET API `GET /accounts/{account_id}/workers/workers/{worker_id}/versions/{version_id}?include=modules` returns the complete `modules` list and each module's `content_base64`. Authorized read-only requests for BOTH historical versions returned:

- `BEFORE_MODULE_COUNT=1804` and `AFTER_MODULE_COUNT=1804`.
- Each contained 1 JavaScript module, 1,580 Python modules, 177 octet-stream modules, 46 plain-text modules; 22,500,883 total decoded module bytes each.
- Sorted manifest of **(module name, content type, decoded byte SHA-256, decoded byte length)** was exactly identical between versions. Manifest SHA-256 for both: `f9543d2c913673a4c00ad6e3031eb24bdb63350f7bdc510faa37cf0601bef774`. No source bytes, credentials, raw database identifiers, or API tokens were printed or persisted.
- Conclusion: **the entire version-specific code/module content was identical**, despite the changed Worker script `etag` and upload provenance metadata. This was a valid settings-only source-preserving version transition, and the old check produced a false negative about *code* change while still correctly rejecting the missing Owner D1 binding.

### Updated automatic post-release guard

The controlled release job now fetches both the immutable **pre- and post-Worker versions with `?include=modules`** using GET. The verifier binds both module responses to their expected exact original and actually 100%-served new version IDs, requires every module's name/type/decoded byte length/SHA-256 to match, checks for missing/duplicate modules and invalid base64, and fails closed on any module or unrelated Worker resource drift.

When and **only when** all module bytes match, the verifier permits the two Cloudflare-generated `resources.script` metadata fields `etag` and `last_deployed_from` to differ. Every other script field (handlers, named handlers and all future metadata keys), runtime setting, Asset configuration and every old binding must still match exactly. The Owner D1 addition is still required, and the existing strict `assert_owner_version_integrity` function remains unchanged. No mutable `GET /scripts/{name}/content` is substituted for exact-version proof. The code-module response files stay in runner temp and must never be uploaded as artifacts or logged.

This historical read-only comparison proves the previous incident's script equivalence. It **does not** claim an additional Owner D1 connection; any new live release still requires separate owner authorization and a fresh prewrite rollback anchor.

Cloudflare source: https://developers.cloudflare.com/api/typescript/resources/workers/subresources/beta/subresources/workers/subresources/versions/methods/get/

## Explicit anchored rollback — separate owner decision/dispatch

After any ambiguous or failed apply, inspect live versions and intended transaction first. The workflow **intentionally does not auto-rollback** a version that could belong to a concurrent publisher. Select the exact affected Worker and apply run's externally stored anchor, verify the expected currently serving version, and authorize a **new, single-use** rollback dispatch:

| Input | Required value |
|---|---|
| `mode` | `rollback` |
| `worker` | Same affected Worker |
| `target_sha` | Exact current main |
| `expected_active_version` | Newly observed **current** served version (not a guess) |
| `anchor_run_id` | GitHub Actions run ID from the original apply, whose anchor artifact exists |
| `confirmation` | `ROLLBACK_OWNER_P01_D1_TO_ANCHORED_VERSION` |

The rollback job downloads the **original prewrite anchor** from that run; it does not trust an operator-supplied rollback target. It verifies Worker identity, original immutable script/runtime hashes, binding-name/type hash and old version ID against Cloudflare GET /versions. Then it rechecks active version equality and makes **one** explicit `POST /deployments` to the anchored old version at 100%. It polls canonical served version and checks Chat health. Never invoke an implicit `previous` rollback, guess a version, or retry an ambiguous POST.

**Limitation:** Worker rollback does not restore D1 data. If the original D1 resource is deleted, Worker rollback may fail. On uncertain or competing edits, stop and escalate before mutation.

## Result/stop vocabulary

```
SOURCE_ONLY_PR_MERGE=NOT_A_PRODUCTION_WRITE
PREWRITE_ANCHOR_UPLOAD=HARD_PRECONDITION
PATCH_CALL_LIMIT_PER_APPLY=1
ROLLBACK_CALL_LIMIT_PER_DISPATCH=1
ENGINE_BEFORE_CHAT=MANDATORY
EXACT_OLD_BINDINGS_PRESERVED=MANDATORY
CODE_ASSETS_RUNTIME_EQUALITY=MANDATORY
GITHUB_PRODUCTION_ENVIRONMENT=REQUIRED
AMBIGUOUS_POST_PATCH=HOLD_NO_RETRY
BROWSER_USE_ACTIVATION=SEPARATELY_GATED
```

This runbook documents a **guarded, currently unexecuted** live procedure; its first live run is itself a Production mutation and must not be called a proven integration until the post-served readback and original Product smoke genuinely pass.
