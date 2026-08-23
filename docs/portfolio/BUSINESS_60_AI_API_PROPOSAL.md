# Business 60 · AI API — Proposed Portfolio Identity

- Authority issue: #650
- Number authority: `proposed-number`
- Stable slug: `ai-api`
- English display name: `AI API`
- Korean display name: `AI API 탐색 허브`
- Lifecycle: `concept`
- Portfolio state: `planned`
- Proposed workspace: `apps/ai-api/` — **not created by this proposal**
- Future hostname candidates: `api.limone.dev`, `api.padiem.net`
- Current public surface: none

## Product promise

AI API is a current, source-forward discovery product for finding AI API access paths that are free, discounted, credited, unusually cheap, or temporarily promoted.

The practical information layer answers:

- what model/provider is available;
- what the current benefit is;
- whether the benefit applies to API, CLI, agent, playground, or another access type;
- who is eligible;
- when the offer expires;
- whether a card or application is required;
- how difficult setup is;
- which official source supports the claim;
- when that source was last verified.

The public entry experience is intentionally cinematic. The current visual direction treats API access as an abstract connection between a human and AI capabilities rather than presenting a generic card directory as the first impression.

## Cinematic frontdoor direction

Current exploratory narrative:

```text
spatial / planetary environment
→ lone female protagonist
→ floating API state appears
→ protagonist activates the connection
→ electric / neural / vascular-like light propagates through the body
→ vision/interface activation
→ gesture-like spatial manipulation of AI surfaces
→ voice/intention becomes generated code
→ transition into the practical discovery and deal layer
```

Existing LoveTree visual assets may be reused where appropriate. No current local proof-of-concept is owner-approved final UI merely because it exists.

## Information product scope

B60 owns the discovery/verification layer for:

- recurring free tiers;
- free models;
- new-user credits;
- free trials;
- launch promotions;
- limited-time discounts;
- startup credits;
- student credits;
- event/referral promotions when relevant;
- provider/model/capability metadata needed to understand an offer;
- official source and verification history;
- offer start/end time and expiry state;
- geography and eligibility constraints;
- card-required and new-user-only conditions;
- access type such as web/API/CLI/IDE/agent/cloud console;
- setup difficulty and concise usage guidance;
- future save/watch/expiry-alert features.

## Boundary with Business 14

Business 14 · Korean AI Platform is the execution platform.

```text
B60 AI API
  discover · verify · compare · explain access
             ↓ optional future handoff
B14 Korean AI Platform
  execute · route · meter · observe model calls
```

B60 does not initially own:

- provider execution adapters;
- OpenAI-compatible model execution endpoints;
- multi-provider routing and fallback;
- platform credit resale;
- metered customer billing;
- persistent customer provider-key storage;
- Business 14 runtime/account authority.

A future integration may allow a B60 offer/model page to open the corresponding B14 execution flow, but the products remain separately numbered and separately governed.

## Credential boundary

Initial B60 work must not persist user passwords or provider login credentials.

Persistent API-key storage is also out of scope until a separately reviewed encrypted-vault design exists. If introduced later, plaintext secrets must never be stored in Neon, logs, analytics, browser persistence, or repository files.

## Initial data target

The first featured-offer candidate is a Vercel/fx/GLM-5.2 promotion discussed during product discovery.

Before public publication, the exact offer must be freshly re-verified from the strongest available official source. The system must preserve source confidence and must not convert a social/community report into a verified official claim without evidence.

## Initial phase authority

```text
UI      = IN_PROGRESS
UX      = BLOCKED_BY_UI
BACKEND = FROZEN
```

This reflects exploratory cinematic prototypes only. It does not imply accepted UI, product UX, database schema, authentication, deployment, or Production readiness.

## Registration-only non-goals

Issue #650 and its registration PR do not create or authorize:

- `apps/ai-api/` runtime implementation;
- Neon tables or migrations;
- production offer crawlers;
- provider credentials;
- API-key vaults;
- Cloudflare deployment;
- DNS/domain changes;
- a public API resale service;
- owner UI approval.
