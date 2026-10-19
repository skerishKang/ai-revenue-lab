# B66 member inquiries and operator notifications (2026-10-12)

## Boundaries

- **Explicit submission only.** A normal AI chat request is never copied to an operator.
- Member: login required; header `문의하기` form; category, subject and 5–3000 character body.
- Rate cap: 3 submissions per signed-in user per hour (D1-based).
- D1 retains the full inquiry; authenticated Google owner admin can review and mark resolved at `/admin-inquiries.html`.
- Telegram, Discord, and email receive only a notification with inquiry ID and category, not full inquiry text or user email. The owner sees the complete inquiry only in the admin panel.
- Alert dispatch uses existing `B66SignupNotifier` configured channel destinations. Per-channel D1 receipt rows permit retry without replaying successful destinations.
- Admin can retry failed/missing inquiry alerts; configured channels are independent of the Hermes process.
- **No requirement to change Hermes tokens or restart Hermes** for B66. Existing Hermes host `168.138.200.12` checked active under `hermes-gateway.service`, Restart=always, Linger=yes.

## Required release order

1. Review/merge exact-head CI and the Pages bridge routes, after passing targeted tests.
2. Apply migration `apps/padiem-chat/migrations/038_b66_member_inquiries.sql` to the exact intended Charliekant PADIEM_CHAT_DB D1, then verify table schema; do not execute it in the separate Padiem account D1.
3. Deploy `padiem-chat` Worker and `quick-quote-kr` Pages project, verifying `POST /api/padiem/b66/inquiries` yields 401 anonymously, accepts one authenticated test inquiry, and the administrator can view it.
4. Set Worker secrets for existing notification channels: `B66_ALERT_TELEGRAM_BOT_TOKEN`, `B66_ALERT_TELEGRAM_CHAT_ID`, `B66_ALERT_DISCORD_WEBHOOK_URL`, and optionally `B66_ALERT_RESEND_API_KEY`, `B66_ALERT_EMAIL_FROM`, `B66_ALERT_EMAIL_TO`. These currently have **not** been added or verified in production. Oracle Hermes `DISCORD_BOT_TOKEN` is **not** a Discord webhook URL.
5. Verify that only the explicitly submitted test inquiry causes operator alerts, and verify pending signup alerts separately in `/admin-notices.html`.
6. Verify alerts per channel and record receipts; test Google-admin access restriction and no leakage of the inquiry text in webhook payloads.

## Security / rollback

- Frontend sends no bot credential; all destinations come from Worker bindings.
- New endpoints require signed user session; admin endpoints additionally require existing verified Google administrator identity.
- The API returns 503 before migration, leaving old B66 features operational. Deploy frontend after DB schema in place.
- New schema is additive. Rollback should disable inquiry UI and routes without deleting D1 inquiry data.
- Avoid writing/reading credentials via ChatGPT output, GitHub commits, logs, shell history, or chat.
- No domain/DNS changes required to add Telegram/Discord webhook destinations. Resend sending domain DNS is separate.

## Targeted local verification

- `test_b66_member_inquiries.py`
- `test_b66_admin_membership.py`
- `node --check` for Pages routing and UI scripts
