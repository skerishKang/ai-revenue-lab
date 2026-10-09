# AI Operating Model

```text
DOC_STATUS = CANONICAL_ROLES_GUIDE
MODEL_SELECTION_AUTHORITY = docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md
IMPLEMENTATION_POLICY = docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md
LAST_RECONCILED = 2026-10-09
```

**Scope:** This document describes responsibilities, workflow economics and independent review. It is **not** a model catalog, an authority to select a default/fallback, or an instruction to choose free models. For model/provider registration, owner-approved exclusions, per-execution user choice and Production gates follow the [canonical Owner model policy](../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md) and [model authority index](../models/README.md). Actual executable models and Production readiness must be verified separately.

## Owner communication rule

Respond to the Owner's explicit technical/product question. Do not add unsolicited security/privacy lectures, self-justifying caveats, or unrelated warnings. Report a dependency only when it is evidenced and affects the requested task. Follow the repository-wide answer/report focus rule in AGENTS.md;

## 1. Objective

The project separates strategic decisions, bounded implementation, independent verification and repeatable runtime work. Cost and model strength may inform an **Owner-authorized** execution plan, but never implicitly select a model, activate a route or force free-first execution. Availability and quality require evidence for the actual task and provider.

## 2. Role separation

### Strategic controller

Responsibilities:

- clarify product intent;
- maintain the project thesis;
- design system architecture;
- write canonical project documents;
- perform or commission a bounded internal/OSS/commercial technology landscape scan before substantial commodity implementation;
- prefer buy/adopt/adapt/sidecar integration over custom build when it is faster and meets the product boundary;
- decompose work into bounded parent-owned slices without routine issue sprawl;
- define acceptance criteria and prohibited scope;
- inspect diffs and evidence;
- decide whether work is accepted, revised, or rejected;
- create and manage GitHub issues and pull requests when connector support permits.

This role should use suitable, explicitly authorized reasoning and independent review capability, because design errors can multiply across later implementation work.

### Implementation worker

The owner or authorized operating environment supplies the permitted implementation model. No hard-coded HY3, free-tier worker default, automatic fallback or model-ranking authority is implied.

Responsibilities:

- implement narrowly defined issues;
- write tests specified by the issue contract;
- perform repetitive refactoring;
- generate fixtures and structured data;
- produce implementation evidence;
- revise work after review.

The worker must not independently redefine product scope, architecture, security policy, or acceptance criteria.

### Runtime producer

Responsibilities:

- collect and classify source material;
- translate, summarize, and structure information;
- generate content variants;
- personalize presentation;
- analyze feedback;
- produce subsequent editions;
- perform routine cross-checking and quality gates.

Runtime production may use cost-efficient replaceable models **when the Owner has approved the relevant model/route and the observed task quality is sufficient**. No pricing filter, provider fallback or automatic model selection is authorized by this roles guide.

### Exceptional expert model

Paid or strongest models may be used for:

- foundational architecture decisions;
- unresolved implementation failures;
- security-sensitive review;
- difficult debugging;
- benchmark calibration;
- release audits;
- rare high-risk content decisions.

Their use must be recorded rather than hidden.

## 3. Core rule

> Keep product and model authority separate from interchangeable execution capacity; use evidence to choose the necessary validation effort.

Engineering work may use different capability tiers only within the Owner's explicit route/model decisions. It must not turn a historical free-model cost hypothesis into today's runtime selection policy.

## 4. Development workflow

For substantial new capabilities, architecture begins with technology intake rather than immediate coding.

```text
User defines capability
        ↓
Strategic controller audits internal + OSS + commercial options
        ↓
Buy / adopt / adapt / sidecar decision
        ↓
Only if needed: custom implementation contract
```

Then the delivery workflow continues:

```text
User defines business direction and approves major decisions
        ↓
Strategic controller writes architecture, issue contract, and acceptance criteria
        ↓
Authorized implementation worker implements on a dedicated branch
        ↓
Focused implementation checks / DEV_FAST_GATE
        ↓
Implementation actor is released to the next authorized task
        ↓
Independent Windows / Ubuntu / browser validators run in parallel as required
        ↓
Validator owns reproduction and may repair attributable failures
        ↓
Strategic controller inspects the exact diff and final validation evidence
        ↓
Revise, reject, or open/approve a pull request
        ↓
Merge only after acceptance criteria and required FULL_VALIDATION are demonstrated
```

## 5. Issue contract requirements

Every implementation issue assigned to a worker should include:

- business purpose;
- exact in-scope files or modules;
- explicit out-of-scope areas;
- required behavior;
- failure behavior;
- acceptance tests;
- required evidence;
- security and privacy constraints;
- completion report format.

Large issues should be bounded before implementation, but routine child-issue proliferation is not required. Prefer one major parent per worker/track unless an independent authority boundary justifies another issue.

## 6. Evidence required from an implementation worker

A completion claim should include at minimum:

- branch name;
- base commit SHA;
- exact changed files;
- summary of each change;
- full test commands;
- test results and exit codes;
- lint or type-check results where applicable;
- current `git status --short`;
- known limitations;
- confirmation that prohibited files and scope were not changed.

Claims without evidence are not completion.

Implementation completion and merge readiness are deliberately separate. A worker may report `DEV_FAST_GATE=PASS` and `DEV_ACTOR_RELEASED=YES` while `FULL_VALIDATION=PENDING`; that is valid progress, not a merge claim.

## 7. Model abstraction

Product code must not hard-code HY3 or any other provider throughout the application. Executable identities, permitted routes, per-execution user choice and model selection are owned by B14, Control Plane and the [Owner policy](../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md), not this document.

The minimum abstraction should support task-oriented operations such as:

```text
generate
extract
classify
translate
verify
personalize
summarize_feedback
```

The configured provider/model should be replaceable through the authorized B14/Control Plane registration and configuration boundaries. **Replaceability does not authorize automatic routing, fallback, switching, onboarding or deployment.** A historical configuration example is not an executable model or deployment instruction.

## 8. Model quality policy

Cheap, expensive, or free does not mean proven. When the Owner authorizes a model evaluation (and only then), relevant model/provider combinations can be evaluated for:

- availability;
- latency;
- output-schema compliance;
- hallucination rate;
- multilingual quality;
- source faithfulness;
- long-context handling;
- coding reliability;
- cost and quota;
- provider stability.

A model may be suitable for extraction but unsuitable for final prose, or suitable for drafting but unsuitable for verification. Such evaluations are neither an automatic MVP prerequisite nor delegated authority to register, pick or activate models.

## 9. Runtime verification principle

Verification should rely on evidence independence, not merely model agreement.

Ten models reading the same unsupported source do not create ten independent confirmations. A stronger workflow is:

- extract a claim from one source;
- find independent official or primary sources;
- compare dates, entities, and status;
- record whether confirmation is single-source, multi-source, conflicting, or superseded;
- update the content when the source state changes.

## 10. Economic accounting

Every material AI task should be attributable to one of the following:

- free inference;
- paid API inference;
- paid consumer-tool review;
- local compute;
- human work.

The project should be able to state not only revenue but also how much free AI production, paid AI, infrastructure, and human time created that revenue.

## 11. Historical staffing hypothesis and current authority

Earlier versions listed HY3 as a default free implementation worker, StepFun/Gemma as free fallbacks and free-model-first production. **Those were historical cost/staffing hypotheses, not current approved model routes or fallback/default policies.** Preserve them in Git history; do not treat them as active instructions.

Current operational interpretation:

- Strategic controller: architecture, scope, independent review and scoped GitHub execution authority, without model selection authority.
- Implementation worker: model chosen by the Owner or already-authorized tooling; follows a bounded task and exact-head evidence gate.
- Runtime producer: uses only registered, permitted and execution-ready model routes as defined by B14 and the Owner policy; per-execution user selection is allowed where the product contract provides it.
- Review/Production: exact source/CI, released configuration, real model/provider and user-visible E2E are distinct gates; additional live calls and Production mutations remain separately authorized.

The current primary Padiem finish-first work order lives in [#3523](https://github.com/skerishKang/ai-revenue-lab/issues/3523), not in a duplicated date-specific model list here.
