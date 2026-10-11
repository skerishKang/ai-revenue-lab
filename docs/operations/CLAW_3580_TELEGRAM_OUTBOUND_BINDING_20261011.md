# #3580 — Telegram outbound trusted binding (2026-10-11)

## What was missing

`TelegramArtifactDeliveryAdapter` resolves the bot token and the destination chat id **inside** the
adapter through an injected `TelegramTrustedBindingPort` (`resolve_bot_token` / `provider_chat_id`).
The only implementation in the repository was the inbound-only `StaticTelegramTrustedAuthority`
(the chat app's webhook authority), which exposes neither method. **No outbound binding existed**, so
the Telegram SEND path could not be composed even with a grant.

## This slice

New `kagent/telegram_outbound_binding.py` — `TrustedTelegramOutboundBinding`, a scope-bound adapter
over two injected trusted ports:

- `TelegramBotTokenSecretPort.resolve_bot_token(binding_ref, bot_ref)` — in production the **existing**
  server-side secret/binding lookup the chat app already uses; not a new store.
- `TelegramProviderChatIdPort.resolve_provider_chat_id(binding_ref, bot_ref, chat_ref)` — the
  **reverse lookup of the same pairing authority** that produced the `TelegramBotScope` (the pairing
  identity map the inbound route already uses), so an outbound destination can never disagree with
  the paired chat.

Boundaries, all fail-closed:

- `binding_ref`/`bot_ref` must be the scope's own — a foreign bot or binding is refused;
- `chat_ref` must already be paired in the scope, so a caller cannot invent or redirect a destination;
- the token must satisfy the existing `kagent.telegram_bot_runtime` token contract and the chat id
  the existing exact-integer contract (negative group/channel ids stay valid) — both **reused**, not
  re-implemented;
- unconfigured ports refuse; a source failure refuses without forwarding its message;
- no token or chat id reaches a projection, an exception message or a log line; the token is **not
  cached**, so revocation takes effect immediately.

`CONSTRUCTION_PROVIDER_CALLS = 0`: construction performs no I/O, and nothing here sends anything —
the adapter performs the single `sendDocument` after channel re-resolution, scoped canonical material
verification and the existing approval verdict. #2010 keeps Telegram SEND unauthorized.

## Connection to the Telegram host boundary

`app/claw_telegram_delivery_host_composition.py` gained:

- `build_canonical_telegram_outbound_binding(...)` — the one canonical outbound binding a host may inject.
- `outbound_secrets` + `outbound_chat_ids` inputs on `build_claw_telegram_delivery_host_state(...)`:
  when the host supplies only the trusted secret and pairing sources, the boundary wraps them in
  `TrustedTelegramOutboundBinding`. **Both sources are required together** — a token without a paired
  destination (or the reverse) cannot deliver anything, and the boundary refuses to pretend otherwise.
  The existing `trusted_binding` input still works, so no prior caller breaks.

## Evidence (hermetic)

- New kagent suite `test_telegram_outbound_binding_3580` → **12 PASS**.
- kagent focused regression (outbound binding, adapter, transport, composition, bot runtime,
  contracts, full chain) → **117 PASS**.
- chat `test_3580_claw_telegram_delivery_host_composition` → **15 passed** (was 11);
  `test_claw_telegram` + deploy-config → **73 passed**.
- Covered: the real binding drives the existing adapter to a `SUCCEEDED` receipt with exactly one
  provider side effect and the resolved token/chat id; a **revoked binding refuses before the token is
  ever resolved**; foreign binding/bot/unpaired chat refused with zero source calls; token and chat-id
  contracts enforced (short token, bool/str chat id refused, negative group id accepted); source
  failure leaks nothing; projection carries no token/chat id/binding/workspace/chat ref.

## Not implemented or activated

```text
TELEGRAM_OUTBOUND_BINDING_IMPLEMENTED=YES
NEW_SECRET_STORE=NO
NEW_CONNECTOR_IDENTITY_AUTHORITY=NO
TOKEN_CACHED=NO
PRODUCTION_OUTBOUND_BINDING_COMPOSED=NO   # no host wires a live secret/pairing source yet
TELEGRAM_SEND_GRANT_AUTHORIZED=NO         # #2010 READ-only
REAL_TELEGRAM_DELIVERY=NOT_PROVEN
PRODUCTION_ACTIVATION=BLOCKED
PRODUCTION_MUTATION=0
```

Hark #3933, the Engine execution boundary, Calendar #2952, Browser Control #3782, B14 routing, B66
and Windows Resident were **not** modified.
