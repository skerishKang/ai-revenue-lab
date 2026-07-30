# Business 14 Decision Log

This document records product-direction decisions for Business 14 so later implementation does not overwrite the original business hypothesis through accumulated feature work.

## 2026-07-22 — Original opportunity identified

Business 14 emerged during a broader discussion about whether AI could generate revenue through multiple independent business experiments.

The specific opportunity was an **AI API provider** for the Korean market:

- overseas AI provider and inference businesses were becoming visible;
- a comparable Korean-first offering was not obvious;
- developers and organizations might prefer one Korean entry point for several models;
- revenue might come from API usage, management software, support, and later directly hosted inference;
- government-supported or otherwise secured GPU capacity was considered as a possible future path for hosting open models.

The initial question was commercial and infrastructural:

> Can Business 14 sell access to AI models and inference to Korean developers and organizations?

It was not initially defined as a consumer AI workspace or a coding approval console.

## 2026-07-23 — Governed-execution implementation created

Issue #80 and Draft PR #79 implemented a substantial governed-execution Demo with:

- worker and validator separation;
- human approval, rework, and rejection;
- changed-file and test evidence;
- cost and token display;
- domestic/overseas processing labels;
- path policies and approval gates;
- product-local SQLite persistence;
- nonpersistent raw BYOK handling.

This work is technically useful and may support a future enterprise provider-operations layer. However, its default product story became "AI work execution and approval" rather than "unified AI API supply."

Decision: preserve PR #79 as a Draft experiment. Do not treat it as the canonical Phase 0 product.

## 2026-07-24 — User-workspace implementation validated

Issue #105 and stacked Draft PR #112 separated a general user workspace from the operator console.

The implemented clickable Demo includes:

- a natural-language task entry;
- six application templates;
- recent-task presentation;
- result-first task detail;
- technical evidence behind disclosure;
- an operator console under `/admin`.

Local final validation reported:

- system Microsoft Edge used for browser validation;
- FastAPI server and `/health` started successfully with Demo SQLite persistence;
- desktop 1440 × 1100 flow passed;
- mobile 390 × 844 flow passed;
- no horizontal overflow;
- zero browser console errors;
- zero failed local asset requests;
- 240 tests passed with one normal-suite warning and warning-strict suite passed;
- clean working tree and unchanged head `255e327b8ac6289b1f7d2f8bf01ef16e114f1944`;
- PR body updated only; no code commit, push, rebase, or merge.

This validates the quality and truthfulness of the clickable user-workspace experiment. It does not validate the original API-provider business hypothesis.

Decision: preserve PR #112 as a Draft, stacked application-layer experiment. Do not retarget, merge, or expand it before the Phase 0 API-provider review.

## 2026-07-24 — Product direction reset

The CTO review found that later ideas had accumulated around Business 14 and obscured the initial commercial thesis.

Canonical order is reset to:

1. define and demonstrate the Korean AI API provider proposition;
2. review business legibility and first commercial wedge;
3. decide whether gateway/BYOK, unified credit, or self-hosted inference should be tested first;
4. only then decide how the governed-execution console and general user workspace fit.

Issue #114 is the canonical Phase 0 implementation issue.

The required Phase 0 Demo is intentionally narrow:

- model catalog;
- unified API-key concept;
- API Playground;
- integration examples;
- Demo usage and KRW cost visibility;
- routing-policy preview;
- clear separation among external, domestic, self-hosted, BYOK, and Business 14 credit modes.

The first Demo may be fully deterministic and network-free. It must make the business being sold understandable without claiming live providers, billing, GPU capacity, customers, or revenue.

## Current sequencing decision

### Active priority

- Issue #114 — Business 14 Phase 0: Korean AI API Provider concept demo.

### Preserved but blocked from expansion

- Issue #80 / Draft PR #79 — governed-execution and enterprise-operations experiment.
- Issue #105 / Draft PR #112 — general user-workspace/application-layer experiment.

### Prohibited until Phase 0 review

- marking PR #79 or PR #112 Ready;
- merging either PR;
- retargeting PR #112 to `main`;
- adding real providers, authentication, billing, or production infrastructure to those PRs;
- expanding general task templates as the Business 14 product core;
- treating worker/validator/human approval as the original Business 14 definition.

## Reuse policy

Existing work is not discarded.

Potential later reuse from PR #79:

- provider/model usage accounting;
- cost and token evidence;
- processing-region labels;
- BYOK registration state;
- policy and approval controls;
- operator and audit views.

Potential later reuse from PR #112:

- user/operator shell separation;
- progressive disclosure;
- responsive navigation;
- accessible cards and state presentation.

Reuse must be selective and subordinate to the API-provider information architecture. Existing commits must not be copied wholesale into Phase 0 merely to preserve sunk work.

## Review standard

A later implementation report is insufficient by itself. The CTO review must independently verify:

- branch and base relationship;
- actual changed files and scope;
- product story on first load;
- Demo truthfulness;
- browser behavior at desktop and 390px;
- test and console evidence;
- absence of secrets and unsupported commercial claims;
- continued Draft/unmerged state of PR #79 and PR #112.

## 2026-07-25 — Product-wide Korean default confirmed

Decision: Korean (`ko-KR`) is the canonical product language and the default UI language for all Business 14 phases and surfaces.

This applies to:

- Phase 0 API Provider Demo;
- Phase 1 BYOK Gateway;
- Phase 2 multi-provider routing;
- model catalog and Playground;
- User Workspace;
- Operator Console;
- onboarding, settings, help, validation, errors, privacy, security, cost, and billing guidance;
- future Business 14 product extensions.

Operational rules:

- first visit defaults to Korean;
- missing or invalid locale state falls back to Korean;
- English may be provided only as an explicit secondary locale;
- new product work and documentation are completed in Korean first;
- untranslated English-locale strings fall back to Korean;
- full Korean/English parity is not a default implementation or merge requirement;
- standard API fields, source code, commands, and Provider/model proper names may remain in English, while user-facing explanations and default navigation remain Korean.

This is a Korea-market product decision, not a temporary single-user convenience.

Canonical policy document:

`docs/BUSINESS14_LANGUAGE_POLICY.md`
