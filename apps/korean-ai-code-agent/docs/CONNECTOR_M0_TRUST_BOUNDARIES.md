# B54 Connector M0 Trusted Boundaries v1

Status: repository-side contract complete  
Parent: #1632  
Implementation issue: #1658

## Authority split

```text
Control Plane / trusted connector authority
  = identity, entitlement, account binding, OAuth/token custody, refresh/revocation

P01
  = Tool / Skill / Approval / Evidence authority

B54
  = connector product adapter, bounded event/read/write projections, physical transport seam
```

B54 never owns or projects raw access tokens, refresh tokens, OAuth client secrets,
API keys or cookies.

## Binding

`ConnectorBindingProjection` is the only account/workspace identity shape that B54
needs. It contains opaque trusted references plus granted scope/capability metadata
and issuance/expiry/revocation state.

A binding is usable only when:

- state is active;
- current time is not before issuance;
- current time is before optional expiry.

Revoked or expired bindings fail closed.

## Health

`ConnectorHealthProjection` carries a trusted observation timestamp and explicit
freshness TTL. A stale observation never counts as healthy even when its last state
was `healthy`.

A healthy connector therefore means:

```text
health.state == healthy
AND health observation is fresh
AND exact binding is still usable
```

## Inbound events

`ConnectorInboundEvent` separates provider verification from untrusted body data.

Acceptance requires:

- exact connector/binding/workspace refs;
- replay disposition = new;
- when signatures are required: verified signature + bounded signature age;
- body remains explicitly untrusted.

`InMemoryEventReplayGuard` exists only as a deterministic repository fake. Production
replay state must live in trusted durable infrastructure.

The event body is bounded and redacted before safe projection. No event body grants
tool or write authority by itself.

## External writes

`ConnectorWriteIntent` binds a material write to:

- exact connector and binding;
- exact actor;
- exact tool;
- exact target;
- SHA-256 payload fingerprint rather than model text;
- idempotency key;
- P01 approval ref;
- P01 evidence ref;
- optional expected resource/version ref.

`InMemoryWriteIdempotencyRegistry` distinguishes:

```text
new key
same-key same-intent replay
same-key different-intent conflict
```

A write is not considered successful because a model said it succeeded. External
success is represented only by `ConnectorWriteReceipt`, which carries a trusted
receipt ref, provider operation ref, target, commit timestamp, evidence ref and
optional returned version/rate-limit state.

## Rate limits and provider errors

`ConnectorRateLimitProjection` represents bounded remaining/limit/retry/reset state.
`ConnectorProviderError` normalizes provider failures without exposing raw provider
payloads or credential-bearing error text.

## Trusted MCP transport

`TrustedMcpTransport` is the B54 MCP adapter seam. It receives:

```text
ConnectorConnection(binding_ref, actor_ref, connector_id)
+ reviewed ConnectorCatalogueEntry
+ TrustedMcpAuthority
```

It sends the trusted authority only:

- opaque binding ref;
- opaque actor ref;
- connector id;
- pinned HTTPS endpoint from the reviewed catalogue;
- bounded tool name/arguments;
- timeout.

The trusted authority resolves and refreshes credentials outside B54.

M0 intentionally rejects:

- unknown connector ids;
- connectors configured for a non-MCP transport;
- MCP entries without a pinned HTTPS host;
- malformed/duplicate/oversized live tool lists;
- invalid trusted call envelopes.

Model-facing MCP results pass through the existing bounded + secret-redacted
connector result envelope.

## Production boundary

```text
TRUSTED_CONNECTOR_BINDING_REQUIRED = YES
RAW_CONNECTOR_SECRET_IN_B54 = NO
HEALTH_FRESHNESS = YES
STALE_HEALTH_COUNTS_HEALTHY = NO
WEBHOOK_SIGNATURE_BOUNDARY = YES
WEBHOOK_REPLAY_BOUNDARY = YES
INBOUND_BODY_TRUSTED = NO
WRITE_IDEMPOTENCY = YES
P01_APPROVAL_REF_REQUIRED_FOR_WRITE = YES
TRUSTED_WRITE_RECEIPT = YES
MODEL_TEXT_COUNTS_AS_EXTERNAL_WRITE_SUCCESS = NO
RATE_LIMIT_PROJECTION = YES
TRUSTED_MCP_TRANSPORT = YES
REAL_TRUSTED_MCP_AUTHORITY_CONFIGURED = NO
FAKE_CONNECTOR_COUNTS_AS_LIVE = NO
REAL_EXTERNAL_CALL = NO
PRODUCTION_MUTATION = NO
```

Child connector issues should extend these contracts rather than introducing a
second OAuth, connector, replay, idempotency or MCP framework.
