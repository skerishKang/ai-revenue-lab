# LOCAL work order — #5108 model-policy propagation from existing admin

STATUS=SCOPE_ONLY / IMPLEMENTED=NO
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
