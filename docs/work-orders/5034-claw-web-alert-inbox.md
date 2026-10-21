# #5034 — Common user notification integration and Web Push

STATUS: IMPLEMENTED_SOURCE / DEPLOYED=NO / LIVE_VERIFIED=NO
SOURCE_ISSUE: https://github.com/skerishKang/ai-revenue-lab/issues/5034
RELATED_EXTERNAL_DELIVERY: https://github.com/skerishKang/ai-revenue-lab/issues/4389

## Inventory — implemented vs missing, by product and recipient

The user-facing inbox and the admin/operator notifications are **different
recipients** and stay different. The admin path was already complete and is
untouched; the user path was complete for the one real asynchronous user job.

| Product | Recipient | Event | Existing implementation | State |
| --- | --- | --- | --- | --- |
| Claw (B54) | **user** | scheduled automation run reaches a terminal state | `claw_automation_task_alert_bridge` → `claw_automation_projection_bridge` → `D1ClawTaskAlertStore` (existing `claw_task_alert`) | **already implemented** |
| Claw (B54) | user | a user-initiated composer turn | synchronous, the user is present in the surface | **no event to notify** — not a gap |
| Chat (B62) | user | a chat turn | synchronous, the user is present in the surface | **no event to notify** — not a gap |
| B66 | **admin/operator** | member signup / support inquiry | `b66_signup_notifications` + the D1 admin inbox + the Telegram/Discord/Resend senders (#4387/#4389) | **already implemented** |
| B66 | user | a quote/PDF request | synchronous, the user is present in the surface | **no event to notify** — not a gap |

**Conclusion:** every user web-inbox flow that has a real event is already
implemented, and the two other products have no asynchronous user job to
notify about. Re-implementing them would be the "three speculative copies" the
work order forbids. The genuinely missing piece was therefore the **Web Push
connection** on the existing user inbox, which this PR implements.

## Implemented in this PR — Web Push opt-in on the existing user inbox

Nothing here is a second inbox, a second notification authority, a new login
or a new event scheme. The inbox stays exactly where it was:
`D1ClawTaskAlertStore` + `/api/claw/inbox/{tasks,alerts}`.

| Piece | Role |
| --- | --- |
| `apps/padiem-chat/app/claw_push_subscriptions.py` | the device-subscription store, the register/unregister routes, the capability route, and the delivery seam |
| `apps/padiem-chat/migrations/065_claw_push_subscriptions.sql` | additive device-endpoint registry (no notification record) |
| `apps/padiem-chat/app/app_factory.py` | the three routes and the store wiring, over the existing `PADIEM_CHAT_DB` |

### Reused, never recreated

- the signed-in owner authority (`_require_owner`) and the server-owned
  workspace authority (`_resolve_memory_workspace`) — the browser names
  neither;
- the existing `PADIEM_CHAT_DB` binding and the existing `claw_task_alert`
  inbox authority for the records themselves;
- the existing alert/task records: this slice never writes, edits, completes
  or re-opens one.

### Pinned contracts

- `NO_SECOND_INBOX` — no notification record is stored in the push table, and
  the inbox read surface is untouched.
- `INBOX_STATE_NEVER_CHANGED_BY_PUSH` — a push failure, a missing push
  authority or a denied permission never changes the status of the underlying
  task or alert, and never re-executes the job that produced it.
- `WEB_INBOX_SURVIVES_PUSH_DENIAL` — the web inbox works unchanged when push
  is unsupported, denied or unconfigured.
- `SERVER_DERIVED_OWNER` — workspace and member come from the session only; a
  body that names an account or a workspace is refused.
- `NO_ENDPOINT_IN_RESPONSE` / `NO_ENDPOINT_IN_LOG` — the browser never
  receives an endpoint, a key or a secret back, and the endpoint is never
  logged.
- `PUSH_AUTHORITY_OPTIONAL` — with no push authority configured the seam
  reports `not_configured` instead of pretending a device was reached.
- one device endpoint is one row per account: a retried subscribe updates the
  existing row instead of creating a duplicate.
- another account's subscription is the same bounded `404` as a missing one.

### Delivery states (web inbox vs browser delivery are separate facts)

`delivered` / `failed` / `not_configured` / `no_subscription`. The inbox record
is the source of truth; the push result never rewrites it.

## Explicit exclusions (unchanged)

- No second notification inbox, new alert database, duplicate admin panel,
  replacement of B66's existing notifier, or new scheduler.
- No connector development: PC/Drive/mobile connection, file transfer,
  broker/tool dispatch or external SaaS link.
- No Telegram/Discord/email senders here (#4389 owns them).
- No secret or production push key creation, deployment, or actual outbound
  delivery without a relevant separately authorized implementation.
- No new customer-facing approval rule, account/role regime, or business
  policy.

## BLOCKED — the browser client (an owner decision, not a coding gap)

The **browser** half of Web Push cannot be implemented in this product's static
JavaScript under the current privacy gate.

`apps/padiem-chat/static/*` is scanned by `.github/scripts/b62_browser_persistence_audit.py`,
which **forbids** `navigator.serviceWorker` (together with `localStorage`,
`sessionStorage`, `indexedDB`, `document.cookie`, `cookieStore` and
`CacheStorage`). The only allowance the gate knows is one reviewed
`sessionStorage` key for the Android handoff inside `app.js`; there is no
allowance for a service worker.

Web Push has no alternative: `PushManager.subscribe()` requires a registered
service worker to receive the push. So a Web Push client and the existing
browser-persistence privacy gate are in direct conflict.

The gate is an owner-set protection ("all user state stays server-side, never
in the browser"), and weakening it to ship a push client is a product/privacy
decision that this change does not take. The guard was left exactly as it is.

**What is needed to unblock it:** an owner decision to allow a reviewed
service-worker allowance (the same shape as the Android handoff allowance:
one file, one reviewed key, one exact call shape) or a different delivery
mechanism. Until then the server-side contract below is complete and tested,
and the browser half stays unimplemented.

**What is still missing after that decision:** the browser opt-in/opt-out
module, the receiving service worker, and the wiring of the delivery seam
into the existing terminal-run event path.

0. **The browser client** — blocked above; needs the owner decision on a
   service-worker allowance.
1. **Push authority configuration** — a VAPID key pair and a push binding on
   the B62 Worker are required before any browser can subscribe. Until then
   the capability endpoint reports `enabled=false` and the browser is not
   offered a toggle that could never deliver. No push key is created here.
2. **D1 migration 065** — the additive device-endpoint table is **not applied**
   in Production. It needs the protected migration gate procedure.
3. **Real device reception** — browser background delivery is a separate fact
   from web-inbox persistence and is not verified by this source change.
4. **Chat Worker deployment** — not performed by this change.
