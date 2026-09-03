# B54 Telegram Connector Safety v1

Status: repository-side preparation  
Parent: #1640  
Implementation: #1674  
Telegram verification date: 2026-09-03

## Provider truth

Padiem Claw uses the official Telegram Bot API only.

Current provider facts used by this contract:

- Bot API calls are authenticated with the bot token; the token belongs in trusted secret authority, never B54 task/model state.
- inbound updates use either `getUpdates` or webhook mode; they are mutually exclusive.
- `Update.update_id` is the provider update identifier used for dedupe/order recovery.
- `setWebhook(secret_token=...)` causes Telegram to send the exact secret in `X-Telegram-Bot-Api-Secret-Token`.
- this header proof is shared-secret equality at trusted ingress, **not** an HMAC signature.
- Telegram retries webhook delivery when the endpoint does not accept the delivery.
- cloud Bot API provider limits are broader than the Padiem product limits; B54 intentionally uses a 10 MiB file quarantine cap.
- callback query `data` is client-originated and limited to a small payload; it is not approval authority.

## Identity and chat scope

`TelegramBotScope` binds:

```text
trusted connector binding
Padiem workspace
bot identity
Telegram bot user identity
explicit paired chats
explicit allowed senders per chat
```

A Telegram chat/user id is evidence, not sufficient Padiem authorization by itself.

Private chats require exactly one paired sender. Groups, supergroups and channels may be connected only through an explicit paired-chat policy. Privileged inbound intake is a separate flag and is **not** reused as outbound-send authority.

## Ingress modes

`TelegramIngressConfig` supports exactly one mode:

```text
WEBHOOK
GET_UPDATES
```

Webhook mode requires an opaque `webhook_secret_binding_ref`. The raw secret is resolved and compared by trusted ingress outside B54.

`TelegramWebhookProof` records only:

```text
proof_ref
secret_binding_ref
secret_header_verified
verified_at
```

`TelegramInboundUpdate.accepted_by()` requires the proof's secret binding to match the exact ingress configuration. A proof from another webhook secret cannot be replayed across bindings.

For polling mode, any webhook proof causes fail-closed rejection.

## Update replay and untrusted content

Inbound acceptance requires:

```text
replay = NEW
update_type explicitly allowlisted
exact binding/workspace/bot/chat/sender scope
correct ingress proof for webhook mode
```

Message text, captions, callback data and file metadata remain untrusted external data. They never become P01/tool authority.

Production must back update-id dedupe with durable storage; the repository contract does not claim an in-memory test guard is sufficient for multi-worker Production use.

## File safety

The repository safety cap is:

```text
MAX_TELEGRAM_FILE_BYTES = 10 MiB
```

This is a Padiem product bound, not a Telegram provider limit claim.

A file becomes model-usable only after:

```text
quarantine_state = accepted
sha256 = exact digest
quarantine_evidence_ref = trusted evidence
```

Raw file bytes are not automatically inserted into model context.

## Callback approval

Telegram callback data carries only an opaque short challenge reference.

Forbidden pattern:

```text
approve=true&task=123&amount=...
```

Required pattern:

```text
<opaque challenge ref>
```

`TelegramCallbackChallenge` binds the server-owned meaning to:

- exact connector binding/workspace/bot/chat;
- exact sender;
- exact P01 approval + evidence refs;
- approve or reject decision;
- issue/expiry times;
- single-use consumption state.

Challenge lifetime is capped at one hour. Production consumption must be durable and atomic so two callbacks cannot consume one approval challenge concurrently.

## Outbound capabilities

Semantic capabilities are independent of provider method naming:

```text
telegram.send_message
telegram.send_document
telegram.edit_message
telegram.answer_callback
```

`TelegramOutboundMaterial` fingerprints the exact approved target and content identity. A material change invalidates the prior P01 approval.

Outbound authorization checks a paired chat and exact actor independently of the `privileged_intake_allowed` inbound flag.

The shared `ConnectorWriteIntent` must match:

```text
connector_id = telegram
binding_ref = exact binding
tool_name = exact semantic capability
target_ref = exact Telegram target
payload_fingerprint = material fingerprint
expected_version_ref = telegram-material:<fingerprint>
approval_ref = exact P01 approval
evidence_ref = exact P01 evidence
actor_ref = exact paired actor
```

## Receipts

Provider success must be represented through trusted `ConnectorWriteReceipt` correlation. Generated model text does not count as message delivery evidence.

Message/document/edit actions require returned message identity. Callback-answer receipt uses explicit callback success instead.

## Explicit non-authority

```text
OFFICIAL_BOT_API = YES
PERSONAL_MTPROTO_SESSION = NO
WEBHOOK_SECRET_HEADER = YES
WEBHOOK_SECRET_IS_HMAC = NO
WEBHOOK_AND_GETUPDATES_SIMULTANEOUS = NO
UPDATE_ID_DEDUP = REQUIRED
CALLBACK_DATA_IS_APPROVAL_AUTHORITY = NO
RAW_BOT_TOKEN_IN_B54 = NO
RAW_WEBHOOK_SECRET_IN_B54 = NO
AUTONOMOUS_SPAM = NO
REAL_TELEGRAM_BOT_CONFIGURED = NO
REAL_TELEGRAM_SEND_CONFIGURED = NO
PRODUCTION_MUTATION = NO
```

## Live gate still required

Repository-side contracts do not configure a bot or authorize a real send. #1640/#1569 remain responsible for:

1. trusted bot-token binding;
2. exact bot identity probe;
3. webhook or polling mode selection;
4. webhook secret setup and readback-safe proof where webhook is selected;
5. durable update-id dedupe;
6. paired-chat onboarding;
7. bounded file quarantine canary;
8. callback challenge durability/single-use proof;
9. separately approved outbound send/edit/document/callback canaries;
10. delivery/result receipt evidence;
11. rollback/revocation verification.
