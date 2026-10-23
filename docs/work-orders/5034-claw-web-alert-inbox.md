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

## BLOCKED — the browser client (RESOLVED 2026-10-23)

The browser half was blocked on an owner decision about the service-worker
allowance in the browser-persistence privacy gate. **That decision was given on
2026-10-23: the service worker Web Push requires is allowed.** The gate was not
weakened; it gained one narrow, reviewed allowance.

### The allowance, exactly

`.github/scripts/b62_browser_persistence_audit.py` still forbids
`localStorage`, `sessionStorage`, `indexedDB`, `document.cookie`, `cookieStore`,
`CacheStorage` and `navigator.serviceWorker` everywhere. The one addition is:

| Constraint | Value |
| --- | --- |
| One client file | `apps/padiem-chat/static/claw-push.js` |
| One declared path | `const PADIEM_PUSH_SW_PATH = "/push-sw.js";` (exactly once) |
| Closed call shapes | `register(PADIEM_PUSH_SW_PATH)`, `ready`, `getRegistration()` |
| Service worker | `apps/padiem-chat/static/push-sw.js` (scanned like any other file) |

Any other file, any second declaration, or any other `navigator.serviceWorker`
call shape still fails the gate. The service worker itself stores nothing: no
cache, no browser storage, no cookie, and no fetch handler that could persist a
response.

### What the browser half now does

| Piece | Role |
| --- | --- |
| `static/claw-push.js` | permission request on user gesture, subscribe/unsubscribe, server register/unregister, sign-out cleanup, the inbox toggle |
| `static/push-sw.js` | background `push` receipt, `notificationclick` focus-or-open, `pushsubscriptionchange` local cleanup |
| `static/index.html` | the toggle in the existing inbox header (`#clawPushSetting`) |
| `static/app.js` | sign-out drops this device's subscription |

A denied permission, an unsupported browser and a deployment with no VAPID
authority are three different reported states. In all three the existing web
inbox keeps working unchanged.

## Server delivery — now connected

| Piece | Role |
| --- | --- |
| `app/claw_web_push_sender.py` | RFC 8291 `aes128gcm` payload encryption and RFC 8292 VAPID over Workers `crypto.subtle` |
| `app/claw_automation_push_notification.py` | the terminal-run to device notification seam |
| `app/claw_automation_background_execution.py` | calls the seam after the existing Task/Alert projection |
| `app/app_factory.py` | builds the VAPID authority and sender from Worker bindings |
| `.github/scripts/b62_d1_migration_065_schema.py` | the 065 deploy-gate preflight |

### Why WebCrypto and not `pywebpush`

The Chat Worker is a Pyodide build whose committed lock carries no
`cryptography` wheel, so `pywebpush`/`py-vapid` cannot be imported there.
Workers do expose `crypto.subtle`, and this repository already uses it through
Pyodide FFI in `app/connector_worker_webcrypto_verify.py`. The sender follows
that same reviewed pattern.

The encryption is verified against an **independent decryptor** written from RFC
8291 §3.3-§3.5 in `tests/test_5034_web_push_sender.py`, not against itself.

### Delivery invariants

- `INBOX_IS_SOURCE_OF_TRUTH` — the Task/Alert record is written first; the push
  is strictly additional.
- `NO_JOB_RERUN` — a push failure never re-executes the automation.
- `DEDUP_BY_RUN` — the existing projection's own `created` answer gates the
  notification, so a re-projected run cannot notify twice.
- `MINIMAL_LOCK_SCREEN` — a short status plus the inbox link. No document
  content, no ERP data, no secret, no run output.
- `GONE_SUBSCRIPTION_IS_REMOVED` — a 404/410 from the push service drops the row.
- `PUSH_NEVER_RAISES` — every failure is a reported outcome, never a crash in
  the automation lane.

## Still required before this is live

1. **VAPID key pair** — `PADIEM_PUSH_VAPID_PRIVATE_KEY`,
   `PADIEM_PUSH_VAPID_PUBLIC_KEY` and `PADIEM_PUSH_VAPID_SUBJECT` must be set as
   Worker secrets. Until then the capability route reports `enabled=false` and
   no toggle is offered. No key is created by this change.
   **Status 2026-10-23:** the three secrets were set from COMP1 at 07:55 KST and
   approved by the Owner afterwards ([#5034 comment](https://github.com/skerishKang/ai-revenue-lab/issues/5034#issuecomment-6354398761));
   the reviewed baseline was aligned by #5609. The capability route is therefore
   enabled in production. Names only; values are never recorded.
2. **D1 migration 065** — the additive table must be applied through the
   protected deploy gate. The preflight now refuses a deploy whose 065 schema is
   not `EXACT`.
   **Status 2026-10-23:** the 065 subscription table exists in production (read-only
   row count 0 at 09:1x KST). An `EXACT` verdict from the gate preflight is not
   recorded for run 39878432983 (that job ran in a separate mode); treat the
   schema as applied but not gate-attested.
3. **Real device reception** — browser background delivery is a separate fact
   from web-inbox persistence and is not verified by this source change.
   **Status 2026-10-23:** still not verified; subscriptions were 0 at the time of
   the Owner decision. Actual push delivery is a separate verification task.
4. **Chat Worker deployment** — not performed by this change.
   **Status 2026-10-23:** `main` `701fbdd` (includes #5600 and #5602) was deployed
   through the protected gate, run 39878432983 (success); served version per the
   operator report `3f2e022b-7fb1-4aa4-b6b5-67c45f79d40a`.
