# AI Operating Model

## 1. Objective

The project uses different AI capability tiers for different economic roles. The purpose is not to force every task through a free model. The purpose is to reserve expensive reasoning for high-leverage decisions while using abundant free inference for repeatable production.

## 2. Role separation

### Strategic controller

Responsibilities:

- clarify product intent;
- maintain the project thesis;
- design system architecture;
- write canonical project documents;
- decompose work into small issues;
- define acceptance criteria and prohibited scope;
- inspect diffs and evidence;
- decide whether work is accepted, revised, or rejected;
- create and manage GitHub issues and pull requests when connector support permits.

This role should use the strongest available reasoning and review capability because design errors can multiply across all later free-model work.

### Free implementation worker

Default candidate: HY3 through an available free provider.

Responsibilities:

- implement narrowly defined issues;
- write tests specified by the issue contract;
- perform repetitive refactoring;
- generate fixtures and structured data;
- produce implementation evidence;
- revise work after review.

The worker must not independently redefine product scope, architecture, security policy, or acceptance criteria.

### Free runtime producer

Responsibilities:

- collect and classify source material;
- translate, summarize, and structure information;
- generate content variants;
- personalize presentation;
- analyze feedback;
- produce subsequent editions;
- perform routine cross-checking and quality gates.

Runtime production should use replaceable free or low-cost models whenever their measured quality is sufficient.

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

> Strong reasoning designs and controls the factory. Abundant free models operate the factory.

This does not weaken the project's thesis. It reflects normal industrial organization: scarce expertise designs systems; abundant production capacity performs repeatable work.

## 4. Development workflow

```text
User defines business direction and approves major decisions
        ↓
Strategic controller writes architecture, issue contract, and acceptance criteria
        ↓
Free model implements on a dedicated branch
        ↓
Free model reports changed files, tests, outputs, and remaining risks
        ↓
Strategic controller inspects the exact diff and evidence
        ↓
Revise, reject, or open/approve a pull request
        ↓
Merge only after acceptance criteria are demonstrated
```

## 5. Issue contract requirements

Every implementation issue assigned to a free model should include:

- business purpose;
- exact in-scope files or modules;
- explicit out-of-scope areas;
- required behavior;
- failure behavior;
- acceptance tests;
- required evidence;
- security and privacy constraints;
- completion report format.

Large issues should be divided before implementation.

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

## 7. Model abstraction

Product code must not hard-code HY3 or any other provider throughout the application.

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

The configured provider and model should be replaceable through environment or deployment configuration.

Example:

```env
AI_PROVIDER=nous
AI_MODEL=tencent/hy3:free
```

A provider adapter may later route the same task to another free model without changing application-level business logic.

## 8. Model quality policy

Free does not mean unmeasured. Each model/provider combination should be evaluated for:

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

A model may be suitable for extraction but unsuitable for final prose, or suitable for drafting but unsuitable for verification.

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

## 11. Initial decision

- Repository documentation, architecture, issue design, and final review: strategic controller.
- Default implementation worker: HY3 free, while quality remains acceptable.
- Free fallbacks: additional measured models such as StepFun or Gemma.
- Runtime production: free-model-first with provider abstraction.
- Strong paid models: exceptional use, recorded and justified.
