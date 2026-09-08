# Padiem Sidecar Product Requirements

## V1 outcome

A host website/app can install a branded contextual AI panel that answers from approved context/evidence, preserves the host product boundary, and uses the shared Padiem platform for execution.

## Functional requirements

### Host integration

- support a right-side drawer/panel as the first reference presentation;
- allow inline/mobile-native adapters later without changing core contracts;
- bootstrap from a public non-secret Sidecar/tenant reference;
- load configuration only from trusted server authority;
- expose explicit ready/error/disabled states;
- never block the host's primary page when Sidecar is unavailable.

### Context

- accept only allowlisted current-page/context fields;
- distinguish browser/DOM text from trusted server-side product state;
- attach source/locator metadata when available;
- prevent arbitrary page text from becoming system/policy authority;
- support product adapters for domain-specific context.

### Conversation and execution

- streaming answer presentation;
- bounded retry/cancel states;
- grounded Evidence/citation presentation;
- summary/translation/rewrite modes;
- current-information/research capability only through shared Core/Engine contracts;
- no direct Provider API calls from browser or B53 product code.

### Files and richer input

- file/image UI primitives may be added after trusted upload/storage contracts exist;
- file type/size and tenant boundaries must be explicit;
- uploads never imply automatic tool/action permission.

### Memory/continuity

- continuity is optional and tenant/policy-controlled;
- shared Memory/RAG semantics remain Core authority;
- tenant/account identity remains Control Plane authority;
- no anonymous cross-session memory without an explicit product contract.

### Host actions/tools

- actions require allowlisted capability IDs;
- caller/client may request an action but cannot self-authorize it;
- material writes require trusted approval/policy as defined by the owning runtime;
- every action is correlated to tenant, Sidecar, user/session and host adapter;
- host action failure must be bounded and must not corrupt host state.

## Admin/onboarding requirements

A customer/operator must be able to define or inspect:

- tenant/organization;
- host origin(s);
- Sidecar identity;
- branding/theme/language;
- enabled capabilities;
- data/context scopes;
- adapter/version;
- allowed actions/tools;
- environment (dev/preview/production);
- current runtime version/health;
- install instructions;
- disable/rollback state.

## Non-functional requirements

### Security

- no Provider or Engine machine secret in browser;
- cross-tenant data access prohibited;
- strict origin/host policy;
- bounded inputs/outputs;
- CSP/embedding compatibility documented;
- fail closed when configuration or trust authority is missing.

### Reliability

- Sidecar failure does not break host navigation/forms/content;
- disable/kill switch exists per tenant/site/environment;
- version rollback is possible;
- streaming interruption yields clear retry/reconnect UX;
- duplicate action execution is prevented where material writes exist.

### Performance

- bootstrap payload kept bounded;
- panel assets cacheable/versioned;
- lazy-load where possible so host first content remains primary;
- AI latency exposed as progress rather than freezing host UI.

### Accessibility

- keyboard-operable open/close/composer/actions;
- visible focus;
- screen-reader labels;
- mobile/touch-safe controls;
- reduced-motion support;
- host page remains accessible when panel is closed or unavailable.

## V1 non-goals

- general autonomous browser control;
- arbitrary host JavaScript execution;
- unrestricted DOM scraping;
- customer-controlled Provider credentials in browser;
- replacing B62/Padiem Chat;
- replacing B54/Padiem Claw;
- building duplicate Core/Engine/B14 runtimes;
- final billing/pricing implementation.

## Acceptance direction

```text
HOST_PRESERVING = YES
CONTEXT_CONTRACT_BOUNDED = YES
STREAMING_UI = REQUIRED
EVIDENCE_UI = REQUIRED
DIRECT_PROVIDER_BROWSER_CALL = NO
GENERIC_AI_RUNTIME_DUPLICATION = NO
HOST_ACTION_ALLOWLIST = REQUIRED
TENANT_ISOLATION = REQUIRED
DISABLE_ROLLBACK = REQUIRED
```

Refs #1722 #1723