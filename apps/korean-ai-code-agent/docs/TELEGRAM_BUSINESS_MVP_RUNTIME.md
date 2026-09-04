# Padiem Claw Telegram Business MVP Runtime

This slice adds a repository-side physical runtime source for the first business-usable Telegram surface.

## Supported source path

```text
Official Telegram Bot API
  -> getUpdates (bounded text messages)
  -> trusted provider chat/sender binding resolution
  -> existing TelegramBotScope paired-chat authorization
  -> canonical TelegramInboundUpdate (untrusted input)

Approved Padiem result
  -> existing Telegram outbound material + approval + ConnectorWriteIntent preflight
  -> exact text SHA-256 recheck
  -> trusted provider chat-id resolution
  -> sendMessage
  -> bounded provider message receipt
```

## Security boundary

- Official Bot API only; no MTProto personal-account scraping.
- Telegram chat/user identity is not Padiem authority.
- Unpaired chats are ignored for privileged intake.
- Raw bot token is resolved only inside the trusted runtime boundary and is never returned in safe projections.
- `sendMessage` requires the existing Telegram outbound preflight and exact approved text hash.
- TLS uses the default OS/Python trust store and exact `api.telegram.org:443`.
- Redirects, non-JSON responses and oversized responses fail closed.
- Replay disposition uses the existing connector replay guard.

## MVP scope

This source intentionally supports natural-language text intake and `sendMessage` result presentation first.
Files, callback approval UX, document sends and webhook deployment remain separate slices even though their canonical contracts already exist.

## Live gate

Repository source does **not** mean a real bot is configured.

```text
OFFICIAL_TELEGRAM_BOT_API_RUNTIME_SOURCE = YES
REAL_TELEGRAM_BOT_TOKEN_CONFIGURED = NO
LIVE_TELEGRAM_BOT_VERIFIED = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```

To become live, a trusted secret/binding authority must provision an actual Bot API token and exact paired chat/user mapping, then run a real inbound/outbound canary without exposing the token.

Refs #1640 #1632
