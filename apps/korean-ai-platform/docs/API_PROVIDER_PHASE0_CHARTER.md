# Business 14 API Provider Phase 0 Charter

Status: **Canonical product-direction proposal**  
Decision date: **2026-07-24**  
Tracking issue: **#114**

## 1. Original business hypothesis

Business 14 began as one revenue experiment derived from a simple question:

> Can an AI business earn money by supplying model access and inference, rather than only by building one end-user AI application?

The initial product category is a **Korean AI API provider**.

Business 14 should give Korean developers and organizations one Korean-first point of access to multiple external, domestic, and later self-hosted/open models. It should make model discovery, API integration, usage visibility, Korean won cost interpretation, support, and operational controls easier than contracting with and integrating every provider independently.

The provider business may later operate in several modes:

1. **Gateway/aggregation** — route requests to external model providers through one interface.
2. **BYOK management** — let customers connect their own provider credentials while Business 14 supplies management and observability.
3. **Business 14 credit** — sell metered access through a unified credit and billing layer where legally and commercially supported.
4. **Self-hosted inference** — serve selected open models on controlled GPU capacity.
5. **Dedicated enterprise access** — provide isolated endpoints, domestic processing options, integration, and support.

Phase 0 does not prove that every mode is feasible. It makes the business proposition visible enough to evaluate.

## 2. Canonical product definition

> Business 14 is a Korean-first AI API provider that exposes external, domestic, and self-hosted models through unified access, then helps customers compare, test, integrate, route, and account for model usage.

Plain-language product promise:

> 여러 AI 모델을 각각 가입하고 연동하지 않아도, 하나의 한국형 API와 관리 화면에서 모델을 선택·시험하고 사용량과 원화 비용을 확인할 수 있습니다.

## 3. Primary customer

Phase 0 is business-to-developer and business-to-business first.

Primary users:

- Korean developers and small engineering teams;
- startups adding AI features without maintaining many provider integrations;
- SMEs that need Korean documentation, support, and understandable cost controls;
- organizations comparing overseas, domestic, and self-hosted processing;
- teams that may later require a dedicated endpoint or private deployment.

The default Phase 0 user is not a consumer asking the platform to write a document, build a website, or complete a coding task. Those may become downstream applications using the API.

## 4. What the Phase 0 Demo must communicate

A first-time reviewer should understand within two to three minutes that Business 14 sells and manages **AI API access**.

The clickable deterministic Demo must include:

### Model catalog

- provider and model;
- external, domestic, or self-hosted classification;
- representative input/output pricing expressed in a KRW-oriented way;
- processing region;
- capability tags;
- honest Demo availability labels.

### Unified API access

- one Business 14 API-key concept;
- Demo key create/revoke interaction;
- clear separation among Business 14 credit, BYOK, and self-hosted access.

### API Playground

- model or routing-policy selection;
- prompt input;
- deterministic sample output;
- estimated tokens, KRW cost, latency, provider, and processing region;
- explicit statement that the response and measurements are simulated.

### Integration examples

- `curl`;
- Python;
- JavaScript;
- an OpenAI-compatible request form where appropriate.

Examples must use non-secret placeholders only.

### Usage and credit

- Demo credit balance;
- current-period request and spend summary;
- provider/model breakdown;
- representative failure-rate information;
- clear separation between synthetic figures and real billing.

### Routing preview

- lowest estimated cost;
- fastest expected response;
- Korean-language priority;
- domestic/self-hosted processing priority;
- direct model selection.

Routing may be deterministic in Phase 0 and must not imply real optimization or failover.

## 5. Phase 0 revenue hypotheses

The Demo should make the following possible revenue paths understandable without claiming that any revenue, resale contract, or customer exists:

1. usage margin or service fee on metered API access;
2. monthly software fee for unified usage, routing, quotas, logs, and team controls;
3. BYOK management fee;
4. self-hosted open-model inference fee;
5. dedicated enterprise endpoint, deployment, and support fee.

The CTO review after the Demo must choose which path should be tested first. Phase 0 must not silently assume that provider resale is legally or commercially available.

## 6. Truthfulness boundary

The first Demo may use synthetic fixtures and require zero network access.

It must not claim:

- live provider execution;
- a real Business 14 API key;
- production billing or payment;
- current provider resale agreements;
- a secured GPU allocation;
- deployed self-hosted inference;
- real customer usage;
- actual revenue;
- production routing, failover, latency, availability, or pricing guarantees.

All model prices, credits, requests, responses, latency, availability, and routing decisions must be visibly labeled as Demo data when simulated.

No API key, bearer token, customer identifier, payment detail, or private provider error may enter source code, fixtures, HTML, screenshots, logs, or committed documents.

## 7. Explicit Phase 0 non-goals

The following are deferred:

- worker → validator → human approval workflow;
- general user task templates for website, document, research, data, marketing, or coding work;
- Git or GitHub execution;
- real authentication and tenant authorization;
- production quotas, rate limits, invoices, or tax documents;
- live payment;
- PostgreSQL production deployment;
- GPU procurement;
- provider-specific legal or commercial commitments.

These may be valid later work. They are not the first proof required for the original business hypothesis.

## 8. Relationship to PR #79 and PR #112

### PR #79 — governed execution console

PR #79 is preserved as a Draft experiment in enterprise governance and operator controls. Its cost, token, processing-region, policy, evidence, BYOK-state, and approval concepts may later contribute to provider operations.

It is not the Phase 0 product core and must not be marked Ready, merged, or expanded before the API-provider Demo review.

### PR #112 — user workspace

PR #112 is preserved as a validated clickable application-layer experiment stacked on PR #79. Its six general work templates demonstrate a possible service built on top of AI models, not the original API-provider business itself.

It must remain Draft, stacked, unmerged, and unexpanded before the API-provider Demo review.

Neither PR is rejected. Their product role and sequencing are deferred.

## 9. Implementation isolation

The Phase 0 implementation must:

- branch from the latest accepted `main`;
- use an independent branch such as `feat/business-14-api-provider-demo`;
- remain within `apps/korean-ai-platform/**` unless scope expansion is separately approved;
- avoid stacking on PR #79 or PR #112;
- use synthetic data and work without external network access;
- selectively reuse code only where it supports the provider information architecture;
- avoid importing the governed-execution workflow as the default user experience.

## 10. Acceptance gate

Phase 0 is ready for CTO product review when:

- the home page clearly presents unified AI API supply rather than AI task completion;
- model catalog, Playground, examples, usage/credit, and routing preview are clickable;
- Business 14 credit, BYOK, external provider, and self-hosted concepts are distinguishable;
- all simulated claims are labeled;
- desktop and 390px mobile paths have no blocking layout or navigation defect;
- browser console errors and failed local assets are zero in the validated path;
- no secret, real customer, payment, contract, GPU, or revenue claim is committed;
- PR #79 and PR #112 remain Draft and unmerged.

## 11. Post-Demo decisions

The next CTO review must decide:

1. Is the API-provider proposition understandable without explanation?
2. Which first commercial wedge is most plausible: gateway/BYOK, unified credit, or self-hosted inference?
3. What legal, supplier, GPU, billing, and unit-economics research is required before live implementation?
4. Which parts of PR #79 belong in provider governance and operations?
5. Should PR #112 become a separate downstream application, a customer console, or an archived experiment?

Until that review, the Phase 0 charter governs Business 14 sequencing.
