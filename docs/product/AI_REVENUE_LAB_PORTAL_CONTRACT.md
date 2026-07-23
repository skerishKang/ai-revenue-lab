# AI Revenue Lab Portal Product Contract

- Status: Draft for acceptance under Issue #83
- Depends on: `ADR-0003-shared-portal-isolated-products.md`
- Product workspace when implemented: `apps/portal/`

## 1. Product objective

AI Revenue Lab Portal is the single user-facing entry point for the AI Revenue Lab portfolio.

It allows one person to authenticate once, understand which AI-native services exist, see which services they may use, and enter each Business without confusing the portfolio account with product-local authorization or product-private data.

The first portal MVP is a service launcher and account boundary. It is not a cross-product personal-data dashboard.

## 2. Primary users

### 2.1 Portfolio user

A person with a verified shared identity who may have access to zero, one, or several Businesses.

### 2.2 Invited product participant

A portfolio user who has been admitted by a specific Business through that Business's invitation, membership, or operator-controlled process.

### 2.3 Product operator

A person with a product-local operational role. Operator status is never inferred from general portal membership.

### 2.4 Portfolio administrator

A restricted operator who maintains the service catalog, portal notices, and access integration. Infrastructure access may additionally require Cloudflare Access. This role does not automatically grant access to private records in every Business.

## 3. Core user promise

The portal must make four facts clear:

1. the user has one AI Revenue Lab account;
2. each Business is a distinct service;
3. access to one service does not imply access to every service;
4. each service protects and manages its own private records.

## 4. MVP information architecture

The route names below are the product contract. Exact framework implementation is deferred to the portal implementation issue.

### Public or pre-authentication

- `/` — portfolio introduction or authenticated launcher redirect;
- `/login` — Google and controlled email/password sign-in;
- `/privacy` — portfolio identity and product-data boundary;
- `/terms` — portfolio terms when approved;
- `/help` — account and service-entry help.

### Authenticated

- `/services` — service catalog and launcher;
- `/services/{business-slug}` — service detail and access state;
- `/account` — shared identity, linked sign-in methods, and account actions;
- `/access-requests` — optional view of requested or pending product access;
- `/logout` — explicit sign-out action.

The portal may use `/` as the authenticated service catalog after login. The implementation must preserve a stable direct URL for the service catalog.

## 5. Service catalog

Each service card displays only registry-approved, non-secret metadata:

- Business number when verified;
- Korean and English display name;
- short product purpose;
- lifecycle status;
- access state for the current user;
- service availability;
- launch or request-access action;
- privacy or data-scope summary;
- optional last-used timestamp stored at portal level.

The portal must not display product-private titles, notes, drafts, travel plans, stories, video records, or generated content unless a later cross-product data contract and explicit consent are approved.

## 6. Service lifecycle states

Registry lifecycle state and user access state are separate.

### 6.1 Registry lifecycle state

- `concept` — recorded idea without an implementation workspace;
- `research` — product research or contract work;
- `incubation` — isolated MVP work;
- `private_preview` — hosted synthetic or invited preview;
- `pilot` — controlled real-user pilot;
- `active` — generally available to its authorized audience;
- `paused` — temporarily not accepting use;
- `archived` — retained for evidence but not launched.

### 6.2 User access state

- `available` — user is authorized and may launch;
- `request_access` — user may submit an access request;
- `pending` — request or invitation acceptance is pending;
- `invite_required` — Business requires an invitation outside the portal;
- `not_authorized` — authenticated but not admitted;
- `coming_soon` — product is not available to users;
- `maintenance` — temporarily unavailable;
- `suspended` — product-local access was revoked or suspended.

A service card must not transform `authenticated` into `available` without product-owned authorization evidence.

## 7. Launch flow

### 7.1 Authorized service

1. user signs in through shared Firebase Auth;
2. portal maps the verified external subject to `portal_user_id`;
3. portal resolves service metadata and current access state;
4. user selects Launch;
5. the product receives or obtains a Firebase ID token through an approved browser flow;
6. the product backend verifies the token server-side;
7. the product maps identity to its own product user and roles;
8. the product authorizes or denies the requested resource;
9. product UI provides a visible return-to-portal action.

### 7.2 Unauthorized service

The product and portal both fail closed. The user sees a plain explanation and the allowed next action, such as request access, use an invitation, or return to the catalog.

### 7.3 Security constraints

- never place ID tokens in URLs;
- never trust a client-provided Firebase UID;
- never pass product roles in unsigned query parameters;
- never use the portal card state as the product backend's final authorization check;
- never expose service secrets in the catalog.

## 8. Shared account surface

The account screen may show:

- display name and verified email from the identity provider;
- enabled sign-in methods;
- portal language preference;
- account creation and recent sign-in metadata where safely available;
- service memberships at a summary level;
- sign-out;
- account deletion request entry;
- links to product-specific export or deletion controls.

The portal account screen must not provide direct editing of product roles or private product content.

## 9. Navigation contract

### 9.1 Global portal shell

Integrated products expose a restrained global layer containing:

- AI Revenue Lab identity;
- service switcher or return-to-portal action;
- account access;
- sign-out access;
- portfolio privacy/help links where appropriate.

### 9.2 Product-local shell

Below or within the global layer, each Business retains:

- its product name;
- local navigation;
- local terminology;
- local role and workflow controls;
- its own visual identity within portfolio accessibility standards.

The global layer must not consume the primary content area or make every Business look identical.

## 10. Business 1 initial integration

Personal Edition is the first integration target because it established the shared Firebase and production infrastructure pattern.

The integration must preserve these current controls until migration is explicitly accepted:

- private invitation or one-time token eligibility;
- participant status checks;
- administrator access restrictions;
- publication review boundary;
- session revocation after participant deletion.

The target user experience is:

```text
shared Firebase authentication
        +
Personal Edition invitation/membership authorization
        =
Personal Edition access
```

A Firebase account without a Personal Edition membership receives no participant or administrator access.

## 11. Privacy and data boundaries

### Portal may store

- portal internal user identifier;
- external identity mapping;
- locale and accessibility preferences;
- service catalog metadata;
- product membership summary or opaque status where approved;
- last-used service identifier and timestamp;
- access request state;
- audit events for login and service launch.

### Portal must not store by default

- Personal Edition source material or editions;
- Living Travel letters or traveler answers;
- Living Fiction canon or personal branches;
- Living Learning responses or learning records;
- World Feed private preferences or generated briefs;
- Personal Video Archive notes, ratings, tags, or viewing records;
- Korean AI Platform execution payloads or API keys.

## 12. Deletion and revocation

Portal account deletion is a coordinated process, not an uncontrolled database cascade.

The portal must:

1. verify the requester;
2. identify product memberships without reading private product content;
3. create deletion or unlink requests per integrated Business;
4. allow each Business to execute its own retention and deletion contract;
5. record completion or a legally/operationally justified retention state;
6. revoke portal authentication and sessions at the correct point;
7. avoid claiming complete deletion until product confirmations exist.

Product-local suspension may remove access to one service without deleting the portal account.

## 13. Accessibility and language

- Korean is the initial default language;
- English is a complete secondary interface for portal-generated labels;
- product names and user-created content may remain in their original language;
- keyboard navigation, visible focus, semantic headings, and reduced-motion behavior are required;
- service status may not rely on color alone;
- the portal and integrated global shell must work at 390px mobile width and standard desktop widths.

## 14. Operational requirements

The portal implementation must eventually provide:

- fail-closed production configuration;
- server-side Firebase token verification;
- no secrets in client HTML, logs, or repository artifacts;
- restrictive cache behavior for account and membership surfaces;
- noindex for private pages;
- CSRF protection for state-changing server actions where cookies are used;
- rate limits for login-adjacent and access-request actions;
- structured audit events without private product content;
- health and deployment evidence;
- deterministic local tests using fake identity verification.

## 15. Non-goals for the first portal MVP

The first portal MVP does not include:

- one shared database for all Businesses;
- a cross-product search of private records;
- a universal product administrator role;
- payment or subscription implementation;
- automatic enrollment in every service;
- social profiles or public sharing;
- product-private notifications aggregated without consent;
- shared AI provider credentials;
- migration of all Businesses in one release;
- replacement of product-local UI or navigation.

## 16. Acceptance criteria for a future implementation issue

- shared Google and controlled email/password authentication works;
- unauthenticated users cannot access account or service membership data;
- verified identity maps to a stable internal portal user;
- service catalog is rendered from a checked-in or database-backed registry contract;
- at least Business 1 demonstrates authenticated-but-unauthorized denial;
- authorized Business 1 users can launch without tokens in URLs;
- global and local navigation are visually distinct;
- sign-out and return-to-portal behavior work;
- no product-private data is copied into the portal;
- deletion and revocation states are represented honestly;
- mobile, accessibility, privacy headers, secret handling, and audit tests pass.
