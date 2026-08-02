# Business 14 / 54 Product Consolidation

- Decision date: 2026-08-02
- Owner decision: approved for portfolio reconciliation and bounded implementation
- Business 14 authority: Issue #371
- Business 54 authority: Issues #372 and #373
- Superseded Router work: Issues #314, #316 and closed-unmerged PR #318

## 1. Decision

The former **Business 54 · AI Model Router** is removed as an independent public Business.

Its useful capabilities are absorbed into **Business 14 · Korean AI Platform** as an internal service named `Router Core`.

The Business 54 number is reassigned to **Korean AI Code Agent / 한국형 AI 코드 에이전트**, a personal-first coding-agent application that consumes Business 14.

```text
Business 14 · Korean AI Platform
= Korean-first OpenRouter-class model platform

Business 14 Router Core
= internal model/provider selection, constraint and fallback engine

Business 54 · Korean AI Code Agent
= personal Cursor/OpenCode-class coding-agent application
```

## 2. Public product count

This consolidation creates two public products, not three.

### Public product A — Business 14

Business 14 provides:

- one Korean-first model platform;
- OpenAI-compatible API access;
- external, domestic and local/self-hosted model catalog;
- BYOK and later platform-key/credit choices;
- Provider adapters and health;
- usage and KRW-oriented cost visibility;
- manual model choice;
- internal Router Core;
- Personal, Team, Enterprise and Government editions.

### Internal module — Router Core

Router Core provides:

- task and capability classification;
- hard privacy, region, tool and parameter constraints;
- quality, cost, latency and throughput preferences;
- local-first and BYOK preferences;
- provider health and eligibility;
- ordered provider and model fallback;
- `no-safe-route` and user/human handoff;
- route reason codes and evidence.

Router Core has no independent account, billing, brand, Business number or deployment identity.

### Public product B — Business 54

Business 54 provides:

- Korean task entry;
- repository context and search;
- Plan / Build / Review modes;
- bounded edits and permissions;
- command and test evidence;
- failure correction and retry;
- diff review;
- accept, reject and revision decisions;
- Business 14 route selection and usage visibility.

Business 54 does not duplicate Provider registry, BYOK, billing or model routing infrastructure.

## 3. Market sequence

Both products begin with personal users.

```text
Personal
→ Team
→ Enterprise
→ Government
```

The initial audience is individual Korean developers, freelancers, solo founders, students, researchers and advanced local-model users.

Enterprise and Government editions extend a product already proven in daily personal use. They must not dominate the initial information architecture.

## 4. Existing implementation evidence

### Business 14

`apps/korean-ai-platform/**` already contains:

- Korean-first language policy;
- model catalog Demo;
- request-scoped BYOK gateway;
- multi-Provider registry;
- deterministic model-to-Provider routing;
- Provider key isolation;
- session workspace;
- dedicated Cloudflare Worker runtime surface;
- network-free upstream tests.

The existing deterministic route is the base for Router Core, not a discarded experiment.

### Former Business 54 Router

PR #318 contains only an unmerged static reference under:

```text
reference/business-54-ai-model-router-v1/**
```

It contains no live Provider gateway, backend, credentials, billing, benchmark or model execution. It is closed unmerged and remains historical reference only.

### New Business 54 Code Agent

Draft PR #374 implements a deterministic competitive demo under:

```text
reference/business-54-korean-ai-code-agent-v1/**
```

It demonstrates a complete Korean request → plan → route → edit preview → test failure → correction → pass → diff → user decision journey without live model or repository mutation.

## 5. Portfolio Console identity

The Portfolio Console identity sources must display:

```text
Business 14
slug: korean-ai-platform
Korean: 한국형 AI 모델 플랫폼
state: running

Business 54
slug: korean-ai-code-agent
English: Korean AI Code Agent
Korean: 한국형 AI 코드 에이전트
state: review
workspace: reference/business-54-korean-ai-code-agent-v1/
```

No current Portfolio Console surface should display Business 54 as `AI Model Router` after this reconciliation is merged and deployed.

## 6. Implementation ownership

### Web model default

Use a capable Web model for:

- product framing;
- current reference research;
- UI and interaction design;
- frontend implementation;
- ordinary repository work;
- GitHub issues, branches and Draft PR orchestration;
- exact-head Web CTO source review.

### Local worker boundary

Use Local only when the work materially requires:

- fresh detached-worktree independent validation;
- real localhost browser execution;
- OS-specific installation or shell behavior;
- long or hardware-dependent test suites;
- real local-model and device integration;
- screenshots and geometry evidence from the exact head.

A Local worker must not treat its own implementation self-check as independent validation. UI redesign remains Web-owned unless the Web reviewer returns a concrete defect and a bounded correction request.

## 7. Historical continuity

Do not delete historical issues, comments or branches merely because the strategy changed.

Use these records as product-decision evidence:

- #314 and #316: closed `not_planned`;
- PR #318: closed unmerged;
- #371: Business 14 consolidation authority;
- #372: Business 54 Code Agent product authority;
- #373: first coded-demo execution contract;
- PR #374: first Web implementation.

## 8. Non-actions

This consolidation does not authorize:

- merging Draft PRs;
- Production deployment;
- real Provider resale claims;
- storing credentials;
- prepaid credits or payment processing;
- real autonomous repository or terminal mutation;
- automatic push, merge or deployment;
- enterprise or government readiness claims.

## 9. Current state

```text
BUSINESS_14_PUBLIC_MODEL_PLATFORM
ROUTER_CORE_INTERNAL
BUSINESS_54_PERSONAL_CODE_AGENT
PERSONAL_FIRST
WEB_IMPLEMENTATION_DEFAULT
LOCAL_INDEPENDENT_VALIDATION_ONLY
MERGE_AND_PRODUCTION_NOT_AUTHORIZED
```
