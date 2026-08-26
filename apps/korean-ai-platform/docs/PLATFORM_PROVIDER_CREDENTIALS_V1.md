# Business 14 Platform Provider Credentials V1

## Decision

Business 14 is the Padiem-wide model-access authority. Provider credentials owned by Padiem/owner are held by Business 14 only. Other Padiem products consume Business 14 rather than receiving upstream Provider keys directly.

This preserves the product decision in #371 and Router Core contract in #377:

```text
Padiem products / external clients
        ↓
Business 14 API or internal Service Binding
        ↓
Business 14 Router Core
        ↓
Provider adapters
        ↓
Provider-owned model APIs
```

Business 14 supports both:

```text
model = b14/auto
model = <explicit B14 catalog model id>
```

Manual model selection must remain available. `b14/auto` is an additional routing mode, not the only route.

## Credential classes

Business 14 must distinguish three credential classes.

### 1. Platform-owned upstream Provider credentials

Examples include owner-supplied API credentials for providers already used elsewhere by the owner.

Rules:

- never commit a Provider key to Git;
- never place a Provider key in catalog/registry JSON;
- never log, return, reflect or persist raw Provider keys;
- production Provider credentials are deployment-owned secrets bound only to Business 14 runtime;
- each Provider receives only its own credential;
- Provider adapters use fixed/server-configured upstream origins; user-supplied arbitrary upstream URLs are prohibited;
- redirects remain disabled and response/error material remains bounded;
- secret values are owner/local input only and are not pasted into GitHub issues, PRs or ChatGPT.

The repository may contain only non-secret binding names, for example:

```text
provider_id = groq
credential_binding = B14_PROVIDER_GROQ_API_KEY
```

It must never contain the corresponding secret value.

### 2. Request-scoped customer BYOK

Existing request-scoped BYOK compatibility remains separate from platform-owned supply.

Rules:

- request-scoped only for V1;
- do not persist customer Provider credentials;
- one Provider credential is never reused for another Provider;
- missing credential prevents that route rather than widening to an unrelated credential source;
- future persistent encrypted customer-key vault is a separate product/security decision.

### 3. Business 14 client credentials

Business 14 client authentication is distinct from upstream Provider credentials.

Target shape:

```text
B14 client key -> Business 14 -> Provider credential
```

A B14 client must never receive the upstream Provider credential.

For first-party Workers in the same Cloudflare account, prefer an internal Service Binding when available instead of distributing a B14 client secret.

For external apps/SDKs or environments where Service Binding is unavailable, Business 14 should issue a revocable client credential with scoped model/policy permissions. Plaintext client credentials must not be stored in application databases after issuance; persistent verification should use a one-way verifier/digest design. Exact durable-store implementation requires a separate storage/auth slice if no suitable existing store already exists.

## Provider registry V1

Evolve the current Provider registry so a route can declare its credential source without embedding a key.

Conceptual shape:

```json
{
  "provider_id": "provider-a",
  "credential_source": "platform_secret",
  "credential_binding": "B14_PROVIDER_A_API_KEY",
  "base_url": "https://api.provider.example.com",
  "models": [
    {
      "model_id": "provider-a/model-x",
      "upstream_model": "model-x",
      "enabled": true,
      "capabilities": ["chat"]
    }
  ]
}
```

Allowed credential sources in V1:

```text
platform_secret
request_byok
none
```

`none` is for trusted/local routes that genuinely require no credential.

A route configured as `platform_secret` must fail closed if the expected deployment secret is unavailable. It must not silently fall back to request BYOK or another Provider secret unless the routing policy explicitly selects a different eligible route.

## Manual and automatic routing

The client-facing model contract remains:

```text
manual: model=<catalog-model-id>
auto:   model=b14/auto
```

Manual pinned requests must not silently substitute another model unless an explicit existing fallback contract allows it. Automatic routing may choose among eligible routes according to Router Core hard constraints and bounded fallback policy.

Provider credentials are an eligibility condition, not a browser-visible routing control.

## Padiem Chat relationship

Padiem Chat remains a first-party B14 consumer:

```text
B62 Padiem Chat
   ↓ B14_SERVICE Service Binding
B14
   ↓
Provider/model
```

Padiem Chat must not receive or store Groq/OpenRouter/Cerebras/etc. Provider keys.

## Owner-supplied Provider intake

The owner may reuse Provider credentials currently configured in another local client, but intake is manual and secret-safe:

1. inventory Provider IDs, model IDs, API base origins and credential type without printing secret values;
2. add only non-secret Provider/model metadata and binding names to B14 source;
3. owner/local registers the actual Provider secret in the production B14 secret boundary;
4. run one bounded live smoke per newly enabled Provider/model family;
5. record only success/failure, selected Provider/model, capability evidence and bounded operational metadata;
6. never record the secret value.

Do not integrate with or depend on the other local client itself. Business 14 reuses the owner's Provider accounts/credentials, not that client's runtime.

## Security invariants

```text
PROVIDER_SECRET_IN_GIT = NO
PROVIDER_SECRET_IN_REGISTRY_JSON = NO
PROVIDER_SECRET_IN_LOGS = NO
PROVIDER_SECRET_IN_RESPONSE = NO
ARBITRARY_UPSTREAM_URL = NO
CROSS_PROVIDER_KEY_REUSE = NO
B14_CLIENT_RECEIVES_PROVIDER_KEY = NO
FIRST_PARTY_SERVICE_BINDING_PREFERRED = YES
MANUAL_MODEL_SELECTION = PRESERVED
B14_AUTO = PRESERVED
```

## Implementation order

1. add a generic server-owned credential-resolution contract to B14 Provider routes;
2. preserve existing OpenRouter server key as the first backward-compatible platform-secret route;
3. add network-free tests for secret isolation, missing-secret fail-closed, manual route and auto route;
4. inventory the owner's currently used Provider/model set without exposing keys;
5. add approved Provider adapters/configuration one Provider at a time;
6. owner/local installs the real production secrets and runs bounded live smoke;
7. separately implement/scaffold external B14 client-key issuance/auth if the current runtime has no safe persistent client-key store.

## Non-goals of this document

- no Provider secret values;
- no Cloudflare mutation;
- no GitHub Actions secret carrying upstream Provider keys;
- no persistent customer BYOK vault;
- no billing/resale claim;
- no forced Padiem Chat model picker change;
- no removal of `b14/auto`;
- no removal of manual model selection.
