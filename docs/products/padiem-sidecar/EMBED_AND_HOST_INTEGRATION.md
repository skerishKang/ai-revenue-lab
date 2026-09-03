# Padiem Sidecar Embed and Host Integration

## Integration objective

Install Padiem Sidecar into an existing host without making Sidecar the host's application authority.

## Supported presentation direction

V1 reference:

```text
Desktop: right-side drawer/panel
Mobile: bottom sheet/full-height drawer
```

Future presentation may include inline blocks or native app shells if they preserve the same trust and adapter boundaries.

## Bootstrap contract

Illustrative direction only:

```html
<script
  src="https://cdn.padiem.ai/sidecar.js"
  data-sidecar="<public-sidecar-id>"
  data-position="right">
</script>
```

The public identifier is not a credential. The browser must never receive Engine machine credentials or Provider secrets.

## Origin registration

Each Sidecar configuration should eventually bind to an explicit host-origin policy.

```text
tenant
sidecar id
allowed host origins
adapter id/version
environment
configuration version
```

Unexpected origin => fail closed / Sidecar disabled.

## Host context bridge

The host may project bounded context such as:

```text
page URL / route
page title
selected item/document/product reference
visible bounded excerpt
trusted signed-in user/session reference where server-authorized
product-specific context envelope from adapter
```

Rules:

- raw DOM is untrusted;
- only minimum context required for the task should cross the boundary;
- sensitive/private fields require explicit server-side scope;
- no hidden host credentials/tokens in the AI context;
- context size is bounded;
- product adapter determines domain interpretation.

## Host action bridge

Host mutations are not arbitrary JavaScript callbacks.

Define stable capability IDs such as:

```text
commerce.cart.add
support.ticket.create
booking.request.create
lovebud.memory.draft
```

Each action contract defines:

- capability id;
- input schema;
- tenant/site scope;
- user/session requirement;
- approval requirement;
- idempotency/replay contract;
- bounded result schema;
- timeout/failure behavior.

The AI/model may propose an action but cannot invent a new capability ID or widen its scope.

## Host-safe failure

Sidecar must degrade independently:

```text
bootstrap failure -> host still works
AI unavailable -> host still works
Engine/Core/B14 unavailable -> host still works
panel JS error -> host core journey still works
Sidecar disabled -> host has no dependency on Sidecar for primary navigation/content
```

## Content Security Policy / embedding

Implementation must document required CSP/connect-src/script-src/frame-src behavior before external customer rollout. Do not require customers to broadly weaken CSP.

## Installation lifecycle

```text
REGISTER
→ CONFIGURE
→ PREVIEW
→ INSTALL_IN_DEV/PREVIEW
→ VERIFY_HOST_AND_CONTEXT
→ APPROVE
→ PRODUCTION_ENABLE
→ MONITOR
→ UPGRADE / ROLLBACK / DISABLE
```

No production enablement occurs merely because a script tag is installed.

## Compatibility

Maintain a compatibility matrix for:

```text
Sidecar runtime version
bootstrap version
adapter version
host integration version
supported browser/runtime range
configuration schema version
```

Breaking compatibility requires an explicit migration path.

## First-party versus external integration

First-party Padiem Businesses may use repository/Service Binding integrations unavailable to external customers. External customers must use the public/customer-safe integration contract; internal credentials and private service identities are never copied to customer browsers.

Refs #1722 #1723