# Hark WEB-FIRST — guarded Cloudflare binding readiness

**2026-10-11 KST. Production release NOT executed; XLSX WRITE/PDF OFF.**

## Observed production authority (read-only, exact version exports)

- Account: verified existing Cloudflare `padiem-chat` + `padiem-ai-engine` account.
- B62 `padiem-chat` version `1c7563f5-f15b-45f2-8bd2-0a60ff706e27`:
  **29 existing named bindings**, including `PADIEM_CHAT_DB` D1
  `702bb62b-36f5-41a0-973f-c4f663ee01e6`, R2
  `PADIEM_WORKSPACE_FILES`, `P01_ENGINE_SERVICE` and existing
  authentication/secret-store bindings. Read only; no binding values/secret
  material copied into the source repository.
- Engine version `121e9ca1-0538-40d7-9547-948c0db752e3`:
  **18 existing bindings**, including `ENGINE_CONTINUATION`
  D1 `6b77ad02-bc27-488f-bb97-6325f6750cba`.
- After explicit additive SQL migration on 2026-10-11:
  B62 tables `029`–`034` and Engine `0009`–`0010` exist.
  The newly created selection/WRITE decision and Engine READ/WRITE tables
  sampled empty; customer rows untouched by these CREATE-only SQL files.
- Deployed B62 was still older than merged Hark #4298/#4301. Existing
  deployed Engine lacks `WEB_XLSX_PRIVATE_B62_D1`; deployed B62 lacks
  `BROWSER`. **No customer XLSX modification or Production PDF proof.**

## Source change and deliberate activation separation

- Engine `wrangler.toml` now declares **one new** trusted private B62 D1
  identifier `WEB_XLSX_PRIVATE_B62_D1`, tied to the exact observed
  `PADIEM_CHAT_DB` UUID (above). This alone grants no Core approval.
  Cloudflare D1 bindings are not platform-enforced read-only capabilities:
  security relies on Engine using the D1 scope resolver's SELECTs,
  first-party owner grants and independent Core user confirmation.
- B62 `wrangler.toml` now declares `[browser] binding = "BROWSER"`
  for opt-in standard-quote-summary PDF Quick Actions. Compatibility date
  already meets Cloudflare's `2026-03-24` requirement. Binding presence
  is **not** a PDF-render operation; entitlement/billing remains unverified.
- All Hark READ/WRITE/PDF flags remain absent or OFF by default; this
  change does not trigger PDF rendering, enable customer writes, set
  secrets, migrate rows or deploy any Worker.

## Critical blocker: current source Wrangler files are NOT complete Prod manifests

The currently deployed B62 has **29** existing bindings and Engine has
**18**, including operator-managed secrets, D1, R2 and service bindings.
The repository's minimal B62 `wrangler.toml` does NOT enumerate them.
Running `wrangler deploy`, `pywrangler deploy`, or replacing live
Worker bindings directly from that incomplete file can DROP production
auth, R2 and P01 connectors. **Do not do that.**

`apps/padiem-chat/scripts/hark_cloudflare_release_guard.py`
compares the two actual deployed version JSON manifests to the
**candidate production Worker version manifests** using only safe
binding metadata. For each service it requires:
- No existing binding name disappeared or changed Cloudflare type;
- No existing resource identity (D1 UUID, Service target and environment,
  R2 bucket, etc.) was silently rebound;
- New B62 `BROWSER` is type `browser`;
- New Engine `WEB_XLSX_PRIVATE_B62_D1` is type `d1` **and points to
  exactly the deployed B62 `PADIEM_CHAT_DB`**;
- The source has the approved compatibility date and no default-on
  Hark permission flags.

The script **does not deploy** and never has/prints secret values. A
manifest name/type match does not independently prove the same secret
VALUE is retained; first-party auth and Service Binding runtime smoke
must still pass. Without actual candidate Worker version manifests it
returns `PRODUCTION_DEPLOYMENT=BLOCKED` (exit 2), not "ready".

Example (from `apps/padiem-chat`, read-only version exports):

```powershell
python scripts/hark_cloudflare_release_guard.py `
  --chat-toml ./wrangler.toml `
  --engine-toml ../padiem-ai-engine/wrangler.toml `
  --live-b62-version <live-B62-versions-view.json> `
  --live-engine-version <live-Engine-versions-view.json> `
  --candidate-b62-version <candidate-B62-versions-view.json> `
  --candidate-engine-version <candidate-Engine-versions-view.json>
```

**Production run order** (subject to approved deployment policy):
1. Obtain exact-head verified code+CI and immutable existing production
   version IDs, full nonsecret binding inventory, and separate secrets
   presence (not secret values). Confirm managed production deployment
   path for these Workers; do not bypass repo deploy policy with a manual
   Wrangler upload. Confirm Browser Run entitlement and usage budget
   before ANY billable render.
2. Prepare candidate version configuration preserving all existing
   resources; compare actual candidate version JSON against the exact
   deployed baseline. A source TOML alone is NOT a candidate version.
3. With ALL new feature flags OFF, perform only the production deployment
   already permitted by the product's Git/Worker pipeline. Read back
   deployed version ID and full binding name/type/resource identity set.
4. Verify root/static/anonymous-auth/logged-in READ-only responses, D1
   schema readback and unchanged existing critical API behavior.
5. Independently prove owner READ P01, separate WRITE P01 and private
   R2 revision exact-head flows with synthetic authorized accounts.
   Then activate narrow WRITE flags in an approved canary if proof is
   complete. Record no-retry and rollback path.
6. Only then opt-in `PADIEM_WEB_XLSX_QUOTE_PDF_ENABLED=true` after
   validating `BROWSER.quickAction("pdf")` on a synthetic quote and
   checking response MIME, bytes, costs and owner-only download.
7. Do signed-in Hark #3936 all-scenes E2E, PDF visual template acceptance,
   then conversation artifact cards/follow-up. Keep #3928/#3933 OPEN
   until independently verified.

No production release, flag activation, paid Browser Run call, customer
file processing or secret mutation was authorized or executed by this
config-source PR.
