# #3580 — Telegram artifact delivery consumer route + receipt store (2026-10-11)

## What was missing

The connector-owned delivery adapter (#3666) and its host injection boundary (#4333/#4342) had **no
consumer**: nothing selected an artifact, asked for a SEND approval, called the adapter or recorded
what happened. Nothing durable recorded that an artifact had already been delivered either, so a
repeated request could have delivered the same file twice.

## This slice

### 1. Owner-scoped receipt store — `app/claw_artifact_delivery_receipt_store.py`

Migration `036_claw_artifact_delivery_receipts.sql` (additive, under the existing Claw history D1
owner) plus `D1ArtifactDeliveryReceiptStore` and an `InMemoryArtifactDeliveryReceiptStore`.

- **The reservation is the duplicate guard.** One row per (owner, conversation, workspace, artifact,
  artifact digest); a fresh reservation id decides `new` vs `existing`.
- The D1 reservation is `INSERT OR IGNORE ... SELECT` restricted by BOTH the owner's conversation and
  the **completed** owner run, so a caller-chosen run or a foreign conversation cannot create a row.
- **One attempt per artifact.** A recorded attempt is never re-sent; a delivery whose provider
  outcome is unknown needs a separately authorized reconciler, not a browser retry
  (`RESERVATION_RELEASE_SUPPORTED = False`).
- Not an approval authority, a connector authority or a second artifact authority.
- `receipt_public_projection()` carries no raw trusted-channel reference and no provider error text.

### 2. Consumer route — `app/claw_telegram_delivery_routes.py`

`POST /api/claw/conversations/{conversation_id}/artifacts/{artifact_id}/telegram`

1. the signed-in owner and the canonical workspace are proved server-side;
2. only an already-completed, owner-scoped artifact of the existing D1 conversation index can be
   selected (a foreign owner, a foreign workspace or an unregistered artifact is a 404);
3. the artifact digest and media type are checked against the index row;
4. the delivery request is built by the **host** from the current trusted channel context plus an
   approval handle taken from the existing approval authority — the route never mints one, and the
   destination is never a request value;
5. the existing adapter performs at most one provider call;
6. the canonical receipt is recorded through the store;
7. one attempt per artifact: a second request returns the recorded receipt and never sends again;
8. the response states the actual terminal status — `succeeded` → 200 `delivered: true`; `refused` →
   403 `delivery_refused`; failure → 502 `delivery_not_completed`. If the adapter raises before
   producing a receipt, a truthful `FAILED_TERMINAL` receipt is recorded (the exception *class name*
   is the only thing that reaches it — never the message) and success is never claimed.

**No trusted seam → 403 and no provider path at all.** With no injected adapter, receipt store or
host request builder the route answers `403 delivery_unavailable` before the adapter is reached.

### 3. Host request builder — `claw_telegram_delivery_host_composition.build_claw_telegram_delivery_request`

Reuses `resolve_trusted_channel_reference` → `bind_delivery_intent` →
`declare_delivery_execution_request`, with a deterministic attempt/intent identity so a retry maps to
the same logical attempt.

### 4. Wiring

`create_app(claw_artifact_delivery_receipt_store=..., claw_telegram_delivery_request_builder=...)`
→ `app.state`; `worker.py` builds the D1 receipt store from the existing history binding and leaves
the request builder `None` (no host approval source exists), so the route refuses with 403.

## Evidence (real SQLite migrations 026 + 036, real D1 bindings, real Starlette + session auth)

- New suite `test_3580_claw_telegram_delivery_consumer` → **17 passed**.
- Focused chat regression (consumer, Telegram host boundary, `test_claw_telegram`, D1 artifact index,
  Drive read delivery, deploy config, CI scope contract) → **115 passed**.
- Covered: unauthenticated 401; invalid ids 400; **no trusted seam → 403 with zero adapter calls**;
  foreign owner / wrong workspace / unregistered artifact 404 with zero adapter calls; missing SEND
  approval → 403 with zero adapter calls; successful delivery records a receipt and a second request
  returns `already_delivered` with **one** adapter call total; failed and refused deliveries report
  the truth and are never retried; an adapter exception records a terminal failure without a false
  success and without leaking the exception message; an in-flight reservation → 409 with zero adapter
  calls; the D1 reservation cannot be created for a non-completed run; the receipt projection hides
  the channel reference; the route module contains no `send_document` / `bot_token` /
  `api.telegram.org` / `provider_chat_id`.

## Not implemented or activated

```text
CONSUMER_ROUTE_IMPLEMENTED=YES
NEW_WRITE_SEND_AUTHORITY=NO
DESTINATION_FROM_REQUEST=NO
APPROVAL_MINTED_BY_ROUTE=NO
MIGRATION_036_APPLIED=NO                  # owner-run gate; adding the SQL changes nothing
PRODUCTION_TELEGRAM_DELIVERY_INJECTED=NO  # no adapter / builder composed yet
TELEGRAM_SEND_GRANT_AUTHORIZED=NO         # #2010 READ-only
REAL_TELEGRAM_DELIVERY=NOT_PROVEN
PRODUCTION_ACTIVATION=BLOCKED
PRODUCTION_MUTATION=0
```

## Still open in #3580

1. A host approval provider so `claw_telegram_delivery_request_builder` can be composed (needs the
   CP SEND grant plus the existing approval authority).
2. An owner-run migration-036 apply gate.
3. Real operational verification in #3936.

Hark #3933, the Engine execution boundary, Calendar #2952, Browser Control #3782, B14 routing, B66
and Windows Resident were **not** modified.
