# #5034 — Common user notification integration and Web Push handoff

STATUS: DRAFT_SCOPE_ONLY / IMPLEMENTED=NO
SOURCE_ISSUE: https://github.com/skerishKang/ai-revenue-lab/issues/5034
RELATED_EXTERNAL_DELIVERY: https://github.com/skerishKang/ai-revenue-lab/issues/4389
BASE_MAIN_AT_CREATION: cb5e3b7546ec3395d6dad54d67a2c64b003ae6c4

## Verified existing functions — reuse, do not recreate

- B66 member signup / support inquiry administrator notifications, D1 admin inbox, and Telegram/Discord/Resend senders already exist (#4387 / #4389).
- Claw workspace/owner-scoped task and web alert persistence and UI already exist (#2058 / #2328 / #2341).
- Keep administrator notifications in existing admin pages. Keep user job notifications in user-facing product surfaces; they are distinct recipients, rights, and navigation targets.
- #4389 owns external Telegram / Discord / email notification adapters and live delivery. Do not reproduce them here.

## Implementation scope — missing integrations only

A. Establish actual missing cross-product event links for Chat, Claw, and B66 completed/failed user jobs into the **existing** user web alert inbox, preserving product-specific results and current deployed surfaces. Start with one confirmed missing path, not three speculative copies.

B. Reuse existing run/event idempotency authority: one user alert per real event, no duplicate when retried; alert failures never re-execute an underlying job.

C. Preserve original owner/workspace/product/recipient server-derived identity, authorize the inbox read and the *target* link separately. A B66 operator/admin recipient is not automatically the customer's recipient; avoid leaking customer quotes or operator alerts.

D. Extend the existing user-facing notification path with opt-in, origin-scoped Web Push for supported browsers/devices, using current service-worker/configuration conventions if present. Browser background delivery is distinct from web inbox persistence; verify actual device reception separately. Unsupported or denied push keeps the web inbox.

## LOCAL execution sequence

1. Inspect current main, AGENTS.md and relevant governance; inventory existing B66 admin notifier/admin inbox and Claw user task/alert store/UI plus Chat notifications.
2. Record implemented vs missing **by product and recipient**. If every user web-inbox flow is already implemented, do not rebuild; move to genuinely missing Web Push connection.
3. Implement the smallest non-overlapping missing vertical slice in this PR, with focused identity, deduplication, navigation and failure tests.
4. Test and run mandatory CI; report exactly implemented, merged, deployed, and real Web Push delivery separately.

## Explicit exclusions

- No second notification inbox, new alert database, duplicate admin panel, replacement of B66's existing notifier, or new scheduler.
- No connector development: PC/Drive/mobile connection, file transfer, broker/tool dispatch or external SaaS link.
- No Telegram/Discord/email senders here (#4389 owns them).
- No secret or production push key creation, deployment, or actual outbound delivery without a relevant separately authorized implementation.
- No new customer-facing approval rule, account/role regime, or business policy.

This file is an implementation handoff only; no functional code has been implemented by this draft.