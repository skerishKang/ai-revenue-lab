# ADR-0003: Use One Shared Portal and Identity Layer While Keeping Products Isolated

- Status: Decided
- Date: 2026-07-23
- Issue: #83
- Extends: `ADR-0002-product-workspaces.md`

## 1. Context

AI Revenue Lab is no longer only a repository that happens to contain several experiments. The intended user experience is one portfolio product through which a person can discover and enter multiple AI-native services.

The repository already has two relevant decisions:

1. every revenue experiment lives in an independent workspace under `apps/`;
2. the Firebase project `ai-revenue-lab-identity` is the shared identity provider for the portfolio.

Those decisions do not yet define a portal, a service launcher, a common account boundary, product entry behavior, or the relationship between shared authentication and product-local authorization.

Without a portfolio decision, each Business can independently create a top-level brand, login flow, account screen, navigation shell, user key, and authorization model. That would make later integration expensive and could incorrectly couple private product data.

## 2. Decision

AI Revenue Lab will operate as one user-facing **AI Revenue Lab Portal** with multiple independently implemented and deployed products.

The architecture is:

```text
Firebase Auth: ai-revenue-lab-identity
                 │
                 ▼
        AI Revenue Lab Portal
   account · service catalog · launcher
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
 Business 1  Business 2  Business N
 app/runtime app/runtime app/runtime
 DB + roles  DB + roles  DB + roles
```

The portal is a product, not a shared database and not a monolithic replacement for the Business applications.

A future portal implementation belongs in:

```text
apps/portal/
```

Reusable runtime code may later belong in `platform/`, but only after implemented products demonstrate the same behavior and a separate extraction decision is accepted.

## 3. Identity and authorization boundaries

### 3.1 Shared authentication

Firebase Auth project `ai-revenue-lab-identity` is the portfolio identity provider.

Firebase answers only:

> Which external identity authenticated this request?

Backends must verify Firebase ID tokens server-side. Client-supplied user IDs, emails, roles, or Business numbers are not trusted authorization evidence.

### 3.2 Stable portal identity

The portal must map an external identity to an internal stable `portal_user_id`.

The mapping key is conceptually:

```text
(identity_provider, provider_subject) -> portal_user_id
```

For Firebase, `provider_subject` is the verified token subject. Firebase UID must not become the primary key for every product table.

### 3.3 Product-local authorization

Each Business owns:

- whether the portal user is admitted;
- the product-local user or participant identifier;
- roles such as participant, traveler, reader, operator, editor, or administrator;
- tenant or workspace membership;
- access to product records;
- suspension, revocation, and deletion state.

An authenticated portal account does not automatically receive access to every Business.

Conceptually:

```text
portal_user_id -> product_user_id -> product roles and records
```

This mapping is stored and enforced by the product, not inferred from the existence of a Firebase account.

### 3.4 Administrator boundary

End-user Firebase authentication and infrastructure/operator protection are separate concerns.

Cloudflare Access may protect administrative or staging surfaces. A Firebase account alone must never confer administrator rights.

## 4. Product isolation

Each Business remains responsible for its own:

- workspace under `apps/<product>/`;
- application runtime and release lifecycle;
- database and migrations;
- authorization tables and internal identities;
- secrets and provider credentials;
- private product data;
- backup, restore, deletion, and retention procedures;
- product tests and deployment gates;
- cost, usage, engagement, and revenue evidence.

The default production pattern may use separate Modal applications and separate Neon databases or projects, but the registry records the actual choice for each Business.

No Business may query another Business database directly.

Cross-product data use requires a separate, explicit consent and data-contract decision. A common account is not common data ownership.

## 5. Portal responsibilities

The portal owns:

- portfolio branding and top-level navigation;
- shared sign-in, sign-out, and account entry;
- the Business catalog and service launcher;
- service availability and access-state presentation;
- links to product, support, privacy, and account-management surfaces;
- a stable return-to-portal affordance;
- portfolio-level notices that do not expose product-private content;
- future portfolio subscription or billing entry points, when separately authorized.

The portal does not own:

- product records;
- product-specific roles;
- product workflow state;
- private content aggregation by default;
- automatic access grants;
- a shared superuser role across all products.

## 6. Global shell and product shell

Every integrated product presents two levels of identity.

### Global level

- AI Revenue Lab brand;
- service switcher or return-to-portal action;
- account and sign-out access;
- portfolio-level accessibility and privacy links.

### Product level

- Business display name;
- product-local navigation;
- product workflow and terminology;
- product-local role and access state.

A product must not visually imply that it is the whole portfolio. The global shell must remain restrained so that each Business can preserve its own product character.

## 7. Deployment and hostname model

The portal and Businesses may use separate hostnames and deployments.

The canonical registry records, without secrets:

- portal and product slug;
- public or staging hostname;
- runtime provider;
- database class;
- authentication mode;
- authorization owner;
- lifecycle status.

No token, credential, database URL, service-account JSON, or private deployment secret belongs in the registry.

ID tokens must not be placed in query strings or launcher URLs.

## 8. Business numbering

`docs/portfolio/BUSINESS_REGISTRY.md` is the sole canonical number-to-product registry after this ADR is merged.

Only evidenced mappings may be marked verified. Missing or conflicting numbers remain reserved or unresolved; names must not be invented to make the table look complete.

At this decision point, the verified mappings are:

- Business 1 — Personal Edition;
- Business 2 — Living Travel;
- Business 3 — Living Fiction;
- Business 4 — Living Learning;
- Business 13 — Personal Video Archive;
- Business 14 — Korean AI Platform.

World Feed has a repository workspace but conflicting historic numbering and therefore requires an explicit reconciliation decision.

## 9. Business 1 transition

Personal Edition currently supports private invitation/token access and an administrator secret flow.

Portal integration must not silently delete or bypass those controls.

A separate implementation issue must define and test one of these transitions:

1. preserve invitation eligibility while Firebase supplies authentication;
2. migrate existing invitations to product-local memberships mapped from portal identities;
3. operate a reversible dual-access period with explicit revocation behavior.

Until that migration is accepted, the existing flow remains authoritative.

## 10. Phased implementation

### Phase A — documentation

- approve this ADR;
- approve the portal product contract;
- establish the Business Registry;
- approve the product integration contract;
- update repository navigation documents.

### Phase B — portal MVP

- create `apps/portal/` through a separate issue;
- implement shared login and service launcher;
- use synthetic or allowlisted access states;
- do not aggregate private product data.

### Phase C — first product integration

- integrate Business 1;
- verify identity mapping and authorization denial;
- preserve or migrate invitation access reversibly;
- add global shell and return-to-portal behavior.

### Phase D — repeatable onboarding

- onboard later Businesses one at a time;
- prove the integration contract in at least two products;
- only then consider extracting shared code into `platform/`.

## 11. Relationship to ADR-0002

ADR-0002 remains valid.

Independent workspaces prevent a portfolio portal from becoming one tightly coupled application. This ADR adds a user-facing composition layer and shared identity boundary; it does not merge product code, databases, or release schedules.

The combined rule is:

> One portfolio experience, one shared identity provider, independently authorized and independently operated products.

## 12. Consequences

### Positive

- users receive one coherent portfolio entry point;
- products stop inventing incompatible top-level login and account experiences;
- authentication can be reused without sharing private product data;
- each Business can still be deployed, paused, audited, or retired independently;
- Business onboarding becomes an explicit contract rather than ad hoc UI work.

### Costs

- portal identity mapping and product membership must be designed and tested;
- account deletion requires coordination across independent products;
- visual work needs both global and product-local shells;
- deployment and access state must be maintained in a canonical registry;
- existing products require deliberate migration rather than automatic SSO assumptions.

## 13. Non-goals of this decision

This ADR does not:

- implement the portal;
- choose a payment provider;
- create a shared product database;
- authorize cross-product personalization;
- authorize public signup for every Business;
- create a common administrator role;
- move product code into `platform/`;
- change any current product route or workflow by itself.
