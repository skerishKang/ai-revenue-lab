# LOCAL work order — #4807 Chat/Claw locale expansion

STATUS=SCOPE_ONLY / IMPLEMENTED=NO
BASE_MAIN=8f47a771e191b99d8c92bdd34e06904caf8f7f65
ISSUE=#4807
Suggested lane: LOCAL A (Chat/Claw shared UI); coordinate with #4488 owner before shared file edits.

## Reuse / scope
- Inspect latest main and existing #2489/#1729 locale/URL contracts first. Existing `apps/padiem-chat/static/locale.js` has ko/en; add zh-CN/ja via the same translation dictionary/selector, preserving ko default, existing ko/en and URL-selected language.
- Start with a bounded Chat/Claw shared shell and representative core screen. Classify B66/other site adoption as REUSE_READY / GAP; do not refactor B66 quotation screens or introduce a second i18n framework.
- Translate UI labels and accessibility/placeholder strings. Missing keys fall back to Korean with a report. Do not change assistant response/document language, login, model, API, account, billing, or customer terms.
- Implement separate F(ko feature) / T(changed translation keys) / V(affected responsive layout, mocked) checks per `docs/operations/PADIEM_I18N_THREE_TRACK_VALIDATION_20261015.md`, reusing existing tests rather than multiplying full E2E by four languages.

## Exclusions / conflict prevention
- No Connector, PC/Drive/OAuth, Android installer (#5185), B14/BYOK (#5167), or notification event/inbox/Web Push (#5170) code.
- Do not edit #4488-owned shared conversation/UI files, `reference/business-66-padiem-quote-v1/easy-mode.js` or `index.html`, or #5170 notification UI without coordinating ownership.
- Existing security CI remains required. Only focused locale and changed geometry tests; one coherent push after focused local checks.
- If the first inspected screen is already complete, mark RETAIN/NO_CHANGE and choose the next demonstrably missing i18n surface in this same issue. Do not generate a duplicate subsystem.

LOCAL deliverable: real minimal feature diff + focused test evidence + exact HEAD; CENTRAL handles review/merge/deploy. Draft/work order is not implementation.
