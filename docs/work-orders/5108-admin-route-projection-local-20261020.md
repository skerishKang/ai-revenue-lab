# LOCAL work order — #5108 model-policy propagation from existing admin

STATUS=IMPLEMENTED / IMPLEMENTED=YES
BASE_MAIN=8f47a771e191b99d8c92bdd34e06904caf8f7f65
ISSUE=#5108
Suggested lane: LOCAL C (admin model projection); keep product UI work separate from LOCAL A and LOCAL B.

## Reuse / scope
- Latest main already has PR #5132 `/admin` hub, #5123 server-attested admin roles, and `apps/padiem-chat/static/admin-models.js` with Preview/Apply UI. Preserve all three; do not reimplement an admin portal, admin accounts, or a second route-policy store.
- Trace the existing authorized route Preview→Apply→Audit/Rollback contract to each of Chat/Claw/B66 model-selection/read endpoints. Classify each read path PRESENT / GAP / NOT_VERIFIED.
- Implement only a **proven missing source-level projection/refresh or honest error/status display** in the current admin/product model interfaces. Preserve product-tier limits from the current approved server policy, and keep actual model/provider choice as runtime configuration rather than hardcoded test/UI model names.
- Add focused contract tests for applied revision visibility and fail-closed unauthorized/failed/stale reads. Existing admin role boundaries and B66 customer-data isolation must remain intact.

## Exclusions / conflict prevention
- No direct production model/Secret/Worker/DB changes, provider registration, auto-router activation, policy redefinition, or new B14 backend. Live admin migration/role grant/deploy evidence remains in the existing #5108 acceptance path.
- Do not modify BYOK-direct source owned by #5121 / open PR #5167, connector/PC/OAuth or COM2 CI workflow; coordinate if model UI and open BYOK PR touch identical files.
- Do not alter B66 quote candidate/approval (#3186, COM2 LOCAL B), common conversation UI (#4488), i18n (#4807 LOCAL A), or notification (#5170).
- If propagation is already source-complete, report NO_CHANGE with concrete path/tests instead of inventing code. Focused tests + existing mandatory GitHub CI only; one coherent push.

LOCAL deliverable: verified minimal missing change or explicit NO_CHANGE mapping, exact HEAD and test result; CENTRAL handles review/merge/deploy. Draft/work order is not implementation.

## LOCAL result (2026-10-20) — IMPLEMENTED

Reused unchanged: PR #5132 `/admin` hub, PR #5123 server-attested roles, the existing
`/api/admin/models/{me,snapshot,change-preview,change-apply,rollback-preview,audit,routes,route-preview,route-apply,route-rollback-preview}`
contract, the central per-product/per-grade route ledger (migration 050) and the shared
product-tier declaration. No new admin system, store, account or policy was added.

### Read-path classification (source level)

| Product | Read path | Before | After |
| --- | --- | --- | --- |
| Chat | `chat_routes` → `chat_request_tier_context` → `resolve_chat_tier_route` | PRESENT | PRESENT (no change) |
| Claw | `GET /api/claw/verified-model-choices` | GAP | PRESENT |
| Claw | `POST /api/claw/general` free-lane model choice | GAP | PRESENT |
| B66 | `GET /api/b66/quote/models` grade rows | GAP | PRESENT |
| B66 | `POST /api/b66/quote/interpret`, B66 AI chat, B66 AI conversation | GAP | PRESENT |
| Admin | `GET /api/admin/models/routes` + `/admin-models` placement panel | GAP (fixed "not wired" label) | PRESENT |

### Confirmed gaps and the minimal fix

1. **Claw model-selection screen ignored the applied route.** The picker hardcoded the
   static free model pair and offered the whole B14 catalog for paid grades, so an
   applied `claw/<grade>` route never appeared. It now offers the resolved server route
   (a stored central row is authoritative; the static contract is the fallback) and
   reports `route_source`. A disabled central row fails closed with `tier_unavailable`
   instead of silently reverting to the old lane. No model name is hardcoded any more.
2. **Claw free-lane dispatch could bypass the applied route.** The hardcoded free pair
   stayed selectable after an administrator replaced it; the free lane now accepts only
   the resolved route candidates (identical to the static pair when no row exists).
3. **B66 dropped a grade whose central-route model was outside the product-local
   per-grade grant list.** The grade vanished from the picker with no error and the
   request was later refused with `model_tier_forbidden`. The grade's centrally assigned
   model is now the selectable model of that grade; the product grant list still narrows
   the free-choice models and the global model OFF list still wins. Grade separation
   (a free member never reaches a paid grade) is unchanged.
4. **The administrator console kept a fixed "not wired" label** for the central policy,
   Chat and Claw even when the route ledger was connected. The placement panel now
   projects the real per-product/grade assignment of the selected model, and an explicit
   product-policy block stays visible.

### Tests

- New: `apps/padiem-chat/tests/test_5108_admin_route_projection.py` (10 cases). 7 of them
  fail when the product-side fix is reverted (mutation proof), so they are load-bearing.
- Repaired a stale acceptance mock: `test_4428_central_model_control_browser.py` was
  already red on `main` because the console calls `/api/admin/models/routes` and the
  mock answered only `me`/`snapshot`/`preview`; the nav-link count was also stale after
  PR #5132. It is green again and now also asserts the projected placement.
- Full `apps/padiem-chat` suite: 6881 passed, 17 failed — every failure also fails on
  the pristine `main` tree in this environment (Windows subprocess import path, touch
  target sizes, locale copy) and is unrelated to this change.

### Not covered here

Live migration 050/052, the role grant, Worker/Pages deployment and the real browser
E2E stay in the CENTRAL acceptance path. `LIVE_VERIFIED=NO`.

## LOCAL C addendum (2026-10-20) — two remaining gaps closed

The parallel LOCAL implementation above landed on this same Draft branch and covers the
Claw free lane, the B66 grade rows and the admin placement panel. Two gaps were still
open in that result and are closed here, on top of it, without touching its behaviour.

1. **The applied revision was not visible in the product read path.** The chooser
   reported `route_source` but not *which* applied ledger revision governs the grade,
   so an operator could not tell an applied decision from the static declaration
   without opening the admin ledger. `central_model_route_runtime` now resolves the
   grade route and the applied revision in one ledger read, and the product model
   read path reports `route_revision`. It is the revision of the stored row that
   governs that product/grade, and `0` when no stored row governs it, so an
   unrelated ledger revision is never read as an applied decision.
2. **A paid grade could still bypass an applied route.** The chooser offers only the
   routed models once a stored row governs a paid grade, but an explicit member pick
   outside the routed candidates was still dispatched. The paid lane now refuses that
   pick with `403 model_not_available_for_tier`, so the offered list and the model
   that actually runs cannot diverge. Without a stored row the Plus explicit-choice
   feature keeps its existing behaviour.

### Addendum tests

- New: `apps/padiem-chat/tests/test_5108_admin_route_revision_visibility.py` (4 cases):
  applied revision visibility, no revision without an applied row, paid-lane
  bypass refused, paid-lane explicit choice unchanged without an applied row.
- Mutation proof: disabling the two fixes fails exactly
  `test_product_model_list_states_the_applied_ledger_revision` and
  `test_paid_lane_explicit_choice_cannot_replace_the_applied_route`.
- Focused runs (new file + the admin/model/Claw/B66 route suites) pass. The full
  `apps/padiem-chat` suite shows the same 17 environment failures with and without
  this addendum (Windows subprocess import path, touch target sizes, locale copy,
  browser lifecycle contract), so this addendum adds no regression.


