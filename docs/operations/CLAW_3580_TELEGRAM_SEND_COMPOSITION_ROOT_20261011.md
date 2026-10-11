# #3580 — Telegram SEND trusted port composition root (2026-10-11)

## Scope of this implementation slice

Two existing, previously tested components had no place that assembled them:

1. `kagent/telegram_document_transport.py` — `StdlibTelegramDocumentSendPort`, the concrete Bot API
   `sendDocument` multipart transport over pinned TLS (`api.telegram.org`, no redirect, no retry,
   bounded response, no token in any error).
2. `kagent/telegram_artifact_delivery.py` — `TelegramArtifactDeliveryAdapter`, the connector-owned
   `ArtifactDeliveryAdapterPort` implementation that re-resolves the trusted channel, resolves the
   token/chat id inside the trusted binding, verifies run/workspace scoped canonical material,
   consumes the existing approval verdict and emits the existing `ArtifactDeliveryReceipt`.

Before this change the only callers of the real transport were its own hermetic tests, and
`PRODUCTION_TELEGRAM_SEND_ACTIVATED` read `False`. No host wired a `document_send` port into the
adapter.

New `kagent/telegram_document_send_composition.py` is the single composition root, mirroring the
Drive slice in `CLAW_3580_DRIVE_WRITE_COMPOSITION_ROOT_20261011.md` and the existing
`e2b_live_composition.py` precedent:

- binds the canonical `StdlibTelegramDocumentSendPort` to the existing adapter through
  `delivery_adapter(...)`; a look-alike transport is refused;
- the token, chat id, endpoint and destination are never parameters — they stay inside the
  existing trusted binding and the source-owned transport;
- construction performs no provider request and resolves no token;
- `safe_dict()` projects the provider host and class name, never a token, chat id or artifact byte;
- `blocked_reasons` names the authority gaps that remain closed.

## Evidence (hermetic: patched HTTPS connection, deterministic fakes)

- `python -m unittest tests.test_telegram_document_send_composition_3580` → **8 PASS**.
- Focused regression re-run with the neighbouring suites (`test_telegram_artifact_delivery`,
  `test_telegram_document_transport`, `test_telegram_contracts`, `test_telegram_bot_runtime`,
  `test_artifact_delivery_execution_receipt`, `test_artifact_delivery_intent`) → see PR.
- Covered: composition root wired while `armed` stays `False`; zero provider requests and zero
  token resolutions at construction (a raising `HTTPSConnection` ctor proves it); one physical
  `POST /bot<token>/sendDocument` carrying the canonical artifact bytes and the resolved provider
  chat id drives the existing adapter to a SUCCEEDED receipt with exactly one external side effect;
  look-alike transports refused; projection leaks no token/chat id/bytes; parameter surface pinned.

## Not implemented or activated

```text
TELEGRAM_DOCUMENT_SEND_COMPOSITION_ROOT_WIRED=True
PRODUCTION_TELEGRAM_SEND_ACTIVATED=False        # no production host composes it yet
TELEGRAM_SEND_GRANT_AUTHORIZED=False            # #2010 keeps SEND unauthorized
LIVE_TELEGRAM_SEND_CANARY=False
PRODUCTION_ACTIVATION=BLOCKED
NEW_TELEGRAM_AUTHORITY=False
NEW_SECRET_STORE=False
```

- No bot-token store, connector identity, channel authority or approval authority is created here.
- No Worker/chat host injection, no Production rollout, no live Telegram call, no customer file.
- The model still never receives a token or a destination; nothing here changes that boundary.

## Next acceptance

1. Drive implementation of `ArtifactDeliveryAdapterPort` so a Drive hand-off produces the existing
   `ArtifactDeliveryReceipt` (Telegram already has one; Drive does not) — separate PR.
2. After an explicit owner-authorized Telegram SEND grant, a bounded live canary recorded in #3936.
