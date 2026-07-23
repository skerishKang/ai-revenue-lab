# Portal–Product Integration Contract

- Status: Draft for acceptance under Issue #83
- Applies to: `apps/portal/` and every Business integrated with AI Revenue Lab Portal
- Depends on:
  - `ADR-0003-shared-portal-isolated-products.md`
  - `AI_REVENUE_LAB_PORTAL_CONTRACT.md`
  - `BUSINESS_REGISTRY.md`

## 1. Purpose

This contract defines the minimum technical, identity, authorization, navigation, privacy, and operational behavior required when an independent Business is launched from AI Revenue Lab Portal.

It does not create shared product code. A Business may satisfy the contract with its own framework and implementation as long as its observable behavior and security boundaries match.

## 2. Integration layers

Portal integration has four distinct layers.

### Layer A — registry

Static, non-secret metadata that lets the portal describe and launch the Business.

### Layer B — authentication

Shared Firebase identity verification.

### Layer C — product authorization

Product-owned membership, role, and record access.

### Layer D — presentation

A restrained global portal shell plus the Business's local product shell.

A Business is not integrated merely because it has a service card or uses Firebase.

## 3. Required registry metadata

Every integrated Business must have an approved registry entry containing:

```text
business_number          verified integer or null while unresolved
slug                     stable lowercase slug
display_name_ko          Korean display name
display_name_en          English display name
workspace                repository-relative apps path
lifecycle                approved lifecycle vocabulary
short_description_ko     portal-safe summary
short_description_en     portal-safe summary
launch_url               approved HTTPS URL or null
support_url               approved URL or null
privacy_url               product privacy URL or null
authentication_mode      shared_firebase | legacy_invite | hybrid
authorization_owner      product-local owner statement
runtime_class            safe non-secret description
database_class           safe non-secret description
portal_integration       none | catalog_only | auth_connected | fully_integrated
```

The registry must not contain secrets, credentials, private infrastructure URLs, user IDs, or role assignments.

## 4. Identity contract

### 4.1 Token source

The product accepts identity only from a verified Firebase ID token issued for the approved `ai-revenue-lab-identity` project, or from a separately documented legacy access mechanism during migration.

### 4.2 Server-side verification

The product backend must verify at least:

- signature;
- issuer;
- audience/project;
- expiration;
- token subject;
- revocation where the selected Firebase verification mode supports it and the product risk requires it.

The browser must not be trusted to assert these values.

### 4.3 Identity mapping

The product maps the verified identity to a product-local identity.

Recommended conceptual key:

```text
identity_provider = "firebase"
provider_subject = verified token sub
```

The mapping table may also retain a `portal_user_id` when the portal exposes a secure mapping mechanism approved in the portal implementation issue.

The product's domain records continue to reference `product_user_id`, participant ID, traveler ID, reader ID, or another product-owned identifier.

### 4.4 No email-only authorization

Email address alone is not a stable authorization key. Domain checks or allowlists may contribute to a controlled invitation policy but do not replace verified subject mapping and product membership.

## 5. Authorization contract

After successful authentication, the product performs its own authorization.

Minimum decision sequence:

```text
verified identity
  -> product identity mapping exists?
  -> product account active?
  -> required membership exists?
  -> required role exists?
  -> requested record belongs to permitted scope?
  -> allow or deny
```

Required denial cases include:

- valid Firebase user with no product mapping;
- mapped user with inactive or deleted product account;
- user with the wrong role;
- user attempting another participant's or tenant's record;
- portal catalog incorrectly showing an available state;
- expired, malformed, wrong-project, or absent token.

The product backend is the final authority even when the portal has already displayed an access state.

## 6. Launch and session contract

### 6.1 Launch URL

The portal launches an approved HTTPS product URL from the registry.

Allowed launch context in the URL is limited to non-sensitive navigation state, for example:

```text
?from=portal
?locale=ko
```

Prohibited URL values include:

- Firebase ID token;
- refresh token;
- session cookie;
- product role;
- participant identifier;
- invitation token;
- private record identifier not otherwise safe to expose.

### 6.2 Session handling

A product may use:

- direct bearer-token requests;
- a server-issued product session after verifying Firebase;
- a documented hybrid during legacy migration.

When a product creates its own cookie session, it must:

- use secure, httponly cookies in production;
- use an explicit SameSite policy;
- bind the session to the product-local identity;
- re-check active/deleted/suspended status where required;
- support revocation;
- protect state-changing cookie-authenticated requests against CSRF.

Products must not rely on a broad shared cookie scoped to all Business subdomains unless a later security decision explicitly approves it.

### 6.3 Sign-out

The global account action signs out of the shared identity session. Product-local sessions must define how they are invalidated or rendered unusable after global sign-out.

A product may additionally provide local sign-out, but the distinction must be clear.

## 7. Global shell contract

Every integrated user-facing Business must expose:

- a visible `AI Revenue Lab` identifier or portal mark;
- a return-to-portal or service-switcher action;
- account access when authenticated;
- sign-out access or a route back to the portal account menu;
- product name as a second-level identity;
- product-local navigation separate from global navigation.

The global shell may be implemented by the product itself until shared code extraction is approved.

### 7.1 Visual hierarchy

Required hierarchy:

```text
AI Revenue Lab                 global portfolio identity
Product Name                   current Business identity
Product navigation             local workflow
Page title and content         current task
```

Prohibited presentation:

- product name presented as the only top-level organization when integrated;
- permanent empty portal sidebars inside every product;
- a global shell that forces all products into one generic dashboard style;
- product-local controls mixed indistinguishably with global account controls.

### 7.2 Mobile

At 390px width:

- return to portal remains available;
- product navigation remains usable;
- fixed navigation does not cover product actions;
- global and local labels remain distinguishable;
- no horizontal overflow is introduced by the shell.

## 8. Language contract

- Korean is the initial default portal language;
- English is the complete secondary language for portal-generated and product-application-generated labels;
- the launch flow may pass a non-sensitive locale preference;
- products remain authoritative for their own user-created content language;
- a language switch must preserve the corresponding product path where practical and safe.

## 9. Access-state exchange

The portal must represent product access honestly.

### Phase 1: registry or operator-controlled state

The first portal MVP may use a portal-owned allowlist or registry-backed state for a controlled pilot. It must label the state as portal knowledge and the product must still re-authorize on launch.

### Phase 2: product access-status interface

A later integration may expose a minimal authenticated endpoint, conceptually:

```text
GET /portal-integration/access-status
```

A successful response may contain only:

```json
{
  "service": "personal-edition",
  "access": "available",
  "roles": ["participant"],
  "reason_code": "active_membership"
}
```

This shape is illustrative until an implementation issue approves a versioned API schema.

The response must not include private content, raw database IDs unnecessary to the portal, credentials, or unrestricted administrator claims.

## 10. Product privacy contract

The product must publish or document:

- categories of private data it owns;
- whether portal identity is linked;
- product-specific deletion and export behavior;
- retention limits or current limitations;
- whether AI providers receive content;
- where product authorization is stored;
- whether the service is synthetic, preview, pilot, or active.

The portal may link to this information but does not replace it with one generic statement.

## 11. Deletion and unlinking contract

Each integrated Business must distinguish:

- revoke access;
- unlink external identity;
- soft-delete product account;
- delete or anonymize product records;
- retain evidence required by a documented policy;
- delete the shared portal account.

A portal deletion request must produce an explicit product result:

```text
completed
not_found
retained_with_reason
blocked_requires_operator
failed_retryable
```

The product must not claim completion when only the portal mapping was removed but private product records remain outside the approved retention contract.

## 12. Failure behavior

### Portal unavailable

Products may remain directly reachable if their approved access model permits it. They must not depend on a live portal page for every authorization decision.

### Firebase unavailable

New authentication fails closed. Existing product sessions follow their documented lifetime and risk policy.

### Product unavailable

The portal displays maintenance or unavailable state without exposing internal errors.

### Access-state disagreement

The product denial wins. The user receives a non-sensitive reason and a route back to the portal or access-request process.

## 13. Observability and audit

Portal and product audit events may correlate through opaque identifiers but must not copy private content.

Minimum safe event categories:

- authentication success/failure category;
- portal service launch;
- product identity mapping created/revoked;
- product authorization allow/deny reason code;
- global sign-out;
- access request submitted/resolved;
- deletion request state.

Do not log:

- ID tokens;
- refresh tokens;
- invitation tokens;
- passwords or API keys;
- full private notes or generated artifacts;
- unrestricted database connection strings.

## 14. Integration test contract

Every product integration issue must prove:

### Authentication

- valid token success;
- missing token denial;
- expired token denial;
- malformed token denial;
- wrong-project token denial;
- client-supplied UID ignored.

### Authorization

- authenticated but unregistered user denied;
- inactive/deleted/suspended product user denied;
- correct role allowed;
- wrong role denied;
- cross-user or cross-tenant record denied.

### Navigation

- portal launch URL contains no token;
- return-to-portal action works;
- product-local navigation remains intact;
- Korean and English shell labels render;
- mobile shell does not obscure content.

### Privacy and operations

- no secret in logs or generated static artifacts;
- private pages use restrictive cache/noindex behavior;
- product unavailability fails safely;
- sign-out or revocation invalidates access according to the documented session model;
- current product suites remain green.

## 15. Business 1 migration contract

The Personal Edition integration issue must explicitly inventory:

- current participant one-time tokens;
- current participant sessions;
- current admin-secret access;
- participant active/deleted status checks;
- invitation eligibility;
- publication review roles;
- existing revocation behavior.

It must then define a reversible migration that does not:

- grant access to every Firebase account;
- make Firebase UID the participant primary key;
- remove current invitations before mapped access is verified;
- grant administrator rights from a Firebase claim without product-owned approval;
- strand existing participants without an operator recovery path.

## 16. Onboarding checklist

Before a Business is marked `fully_integrated`:

- [ ] verified registry entry exists;
- [ ] launch URL and environment are approved;
- [ ] shared token verification is implemented server-side;
- [ ] product-local identity mapping exists;
- [ ] authenticated-but-unauthorized denial is tested;
- [ ] product roles remain local;
- [ ] global and local shells are distinguishable;
- [ ] return-to-portal and sign-out behavior are tested;
- [ ] no token appears in URLs;
- [ ] private data remains in the product boundary;
- [ ] deletion, suspension, and unlink behavior are documented;
- [ ] language and mobile requirements pass;
- [ ] deployment, secret, backup, and restore responsibilities are recorded;
- [ ] product-specific test suite passes without weakened assertions.

## 17. Shared-code rule

Products may initially duplicate a small verified token adapter or shell pattern.

Move code into `platform/` only after:

1. at least two products implement the same behavior;
2. both have working integration tests;
3. the interface is stable enough to reduce rather than increase coupling;
4. a separate ADR approves extraction and release ownership.

A common portal product under `apps/portal/` does not by itself justify a general shared framework.
