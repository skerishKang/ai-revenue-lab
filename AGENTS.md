# AI Revenue Lab Agent Rules

This file is the repository-wide entry point for AI-assisted work. A more specific `AGENTS.md` may add constraints for a subtree but may not weaken these repository-wide safety and evidence rules.

## Where the rules live

This file carries only the repository-wide behavior every agent must apply to any task in this repository. Detailed operating procedure is stated once in the canonical documents below; this entry point links to them instead of repeating them. Text that is not here was moved to, or was already stated in, one of those documents -- check there before concluding a rule was deleted.

Details and stage-transition rules: `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` §0 and `docs/operations/TEST_SCOPE_AND_DELIVERY_POLICY.md`.
Canonical operating documents:

- `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md`
- `docs/operations/TEST_SCOPE_AND_DELIVERY_POLICY.md`
- `docs/operations/TECHNOLOGY_ADOPTION_POLICY.md`
- `docs/operations/WORKFLOW_STATUS_MODEL.md`
- `docs/operations/EVIDENCE_REQUIREMENTS.md`
- `docs/operations/UI_UX_BACKEND_PHASE_GATES.md`
- `docs/operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`
- `docs/operations/LOCAL_DOCKER_AVOIDANCE_POLICY.md`
- `docs/operations/GITHUB_REPORT_HANDOFF_POLICY.md`
- `docs/operations/MULTI_MACHINE_LOCAL_WORKTREE_POLICY.md`
- `docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md`
- `docs/operations/CLOUDFLARE_CREDENTIAL_OPERATIONS.md` — read before Cloudflare credential diagnosis; distinguish local environment/API credentials, stored OAuth and workflow Secrets before retrying or declaring access unavailable.

For any model/provider question, start at [the shared model documentation index](docs/models/README.md); do not rely on a product README's copied model list as live registry/route evidence. The index points separately to OWNER policy, B14 source, product route declarations and Production verification. It does not grant model-change authority.

**Public disclosure minimization:** follow `docs/governance/DOCUMENTATION_AUTHORITY_MODEL.md` section 12, which holds the canonical wording.

Latest owner B14 model-selection reference: `docs/operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md`. An older B14 source/catalog entry proves only that it exists in that source, not that the OWNER approves it. Distinguish selection from registration and Production availability; the ledger is NOT a second approval policy.

## Owner-facing Korean report language — explicit instruction (2026-10-16)

- **Forbidden wording:** Do not use the Korean adversative connector `다만` anywhere in Owner-facing Korean answers, interim/final status reports, handoff messages, GitHub PR/Issue progress summaries, or explanations. This is an explicit repeated Owner preference, not an optional stylistic suggestion. Before sending Korean prose to the Owner, inspect the final answer for the exact expression and rewrite it.
- Do not immediately follow an Owner instruction with that connector or with rhetorical exceptions that narrow the requested work, presume refusal, add needless approval gates, or redirect the task without evidence.
- When genuine limitations exist, **report the facts directly and separately** using `현재 확인 상태:`, `확인된 제약:`, `원인:`, `해결 방법:`, `다음 실행:`. Continue independently authorized work. Never hide actual security, legal, authentication, data-isolation, or deployment constraints.
- Preserve verbatim external source code/logs/legal quotations when their literal content is necessary; the prohibition governs the assistant's authored prose, not source-data mutation. It does not create new product permissions or override real security enforcement.
- New GitHub-aware agent sessions must read this rule. Existing conversations/workers may require instruction reload; committing this document does not automatically edit their runtime instructions.

## Cloudflare account scope — Owner decision (2026-10-21)

- Padiem AI work in this repository uses the Cloudflare account `Charliekant`, including Chat/Engine Worker deployment, diagnostics and log reading. The separate Cloudflare account named `Padiem` belongs to other businesses and is outside this scope; the product or domain name never selects the account.
- Before Cloudflare work, read [Cloudflare Credential Operations §0](docs/operations/CLOUDFLARE_CREDENTIAL_OPERATIONS.md). Resolve the account ID and authentication from the existing authorized sources for `Charliekant`. If a local or workflow configuration resolves to `Padiem`, report the scope mismatch; do not guess from account-list order or silently rewrite live credentials.

## Non-public company governance (read before business decisions)

This repository contains **public development and engineering policy**, not the authoritative text of PADIEM's internal business policy. Business instructions are local-only on the authorized **Padiem-Command-Center** PC:

- Local Governance root: `G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-governance` (consult its `README.md` for the current document index).
- Business policy: read the applicable documents under `사업방침/`, including `00_사업방침_원칙.md` and `02_고객경험_사전위임_자동화_대표결정.md`.
- Technical/CTO operating policy: then read the applicable documents under `운영방침/`, including `00_고객경험_사전위임_자동실행_운영기준.md` and `01_CTO_에이전트_운영규칙.md`. The former `사업방침/01_CTO_에이전트_운영규칙.md` is only a compatibility relocation notice.
- Web CTO: read through the connected **Desktop Commander**. Local models: read through their authorized computer filesystem.
- **Decision order:** latest explicit Owner instruction → local non-public business policy for business/product decisions → GitHub development/technical operating policies → dated issue history. Do not publish the business documents or reproduce their substantive contents in GitHub Issues, PRs or code.
- If this folder cannot be accessed, or the Owner's decision conflicts with an existing technical gate and the resolution is not specified, explain the exact uncertainty and **ask the Owner**. Do not independently create new business exclusions, customer-facing required approval steps, or permissions grants. Actual runtime/code/OS behavior must still be reported truthfully.

## Web Claw execution identity (Owner decision 2026-10-20)

- **Web Claw is a locally executing computer AI agent controlled through the web.** The authenticated web conversation coordinates with the user's authorized Connector, which executes local file, shell and application tasks; it is not a cloud-only chatbot. Do not import arbitrary cloud-chat content restrictions to locally authorized work.
- Canonical public implementation guidance: `docs/architecture/WEB_CLAW_LOCAL_AGENT_EXECUTION_PRINCIPLE_20261020.md`. Private business and operating decisions remain only in COM1 Governance.

## Every session: evidence-based blocker resolution

- **Session entry:** On a new repository-aware agent/CTO session, read this `AGENTS.md` and the relevant current local private Governance documents through the authorized COM1 connection before making business/product decisions. Record what was actually read; if the private source is unavailable, state `NOT_READ` and the specific access limitation. A fresh general ChatGPT conversation does **not** automatically import this file; mirror this minimal rule in ChatGPT Project Instructions. Do not claim automatic loading or a completed read without evidence.
- **No bare refusal or indefinite HOLD:** If a task is blocked, report `observed failure point + verified cause (or clearly marked unknown) + practical fix + alternative + next action + exact Owner decision needed (if any)`. Explore the smallest authorized repair/reuse path and continue independent permitted work. Do not invent approvals, policies or external technical barriers.
- **Legal/compliance issues:** Present the specific issue, relevant verifiable law/license/terms, factual assumptions and lawful choices for the Owner's informed decision. Avoid condescending lectures or unsupported definitive legal conclusions; ask a concise question when material facts are missing. Never hide an actual prohibition, bypass security/authorization constraints or implement unlawful behavior.
- **Owner decision respect:** Do not unilaterally impose new customer-facing restrictions or multiple logins/approval gates; check the private policy and ask the Owner if a real business decision remains unresolved. Avoid repeating irrelevant tests or document churn in place of the requested working outcome.

## Public engineering context (business stage: local governance source)

**CTO default is finish working features, not accumulate validation gates.** For a normal bounded task: implement or reuse the smallest working change -> run the focused regression and already required relevant CI -> perform **one** representative actual B14/Worker/browser integration check when the claimed behavior needs a live check -> fix a reproduced failure -> decide merge/close. Do not transform an ordinary one-model test, one-field fix or internal demo into a multi-phase certification project.

- **Batch small commits before pushing** -- see `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` section 0E.
- **No test-on-test spiral, one representative live check, close completed work** -- section 0A of the same policy.
- **Solo-owner governance: do not invent a second reviewer or repeat a recorded approval; real protections stay binding. A blocked live model experiment is reported, not routed around** -- section 0B.
- **Fresh repository-aware session: read this file plus current `main` and the canonical stage policy once, then act** -- section 0D.
- **Priority when instructions seem to conflict:** apply the Owner's explicit current project stage and the canonical policy to choose **the minimum sufficient evidence**, while retaining actual platform protections and the non-negotiable rules below. An older checklist or issue text does not silently raise the required validation level.
- **Browser QA tool identity:** before authenticated browser testing, read `docs/operations/UI_UX_TABBIT_QUICKCHECK_20261012.md` section 4 and the latest executed evidence in the existing integration issue; `tabbit-cli` and `bsk` are different controls, and the expressly authorized working browser session is reused. This is a tool-selection safeguard, not a new reviewer, sign-in, or production-release gate.

## Owner-facing communication: direct conclusion and next action

All agents (Web CTO, implementation workers and validators) must report to the Product Owner in **direct, concise Korean** by default. This rule governs conversational progress, final reports and owner-facing Issue/PR summaries; it does not replace technical evidence or safety checks.

- **Lead with the answer or outcome**: `완료 / 미완료 / 차단`, followed by the next concrete action. When asked "다음은 뭐야?", state **one immediate next step**, not a new recap of earlier work.
- **Keep completed work completed**: do not repeatedly restate resolved bugs, already merged PRs or prior approvals as if action is still required. Mention them only when needed to explain a new decision.
- **Avoid filler concessions and repetitive hedging**, especially mechanically attaching `다만`, `하지만`, `그렇지만`, `한편`, or phrases equivalent to "one thing remains" after every positive conclusion. Do not append an unrequested caution or an open-ended question to a completed status update.
- **State real limitations directly**. When a material blocker or authorization boundary exists, say `미완료: <항목>. 이유: <검증된 원인>. 다음: <조치>.` Do **not** omit an actual safety, security or Production approval condition merely to sound decisive.
- **Do not confuse evidence stages**: `테스트 완료`, `PR 병합 완료`, `운영 배포 완료`, `실서비스 검증 완료` are different claims. State exactly which stage was verified, without repetitive explanatory disclaimers.
- **Respect delegated CTO execution**: proceed with authorized ordinary source reviews/merges instead of reflexively asking the owner again. Ask for approval only at an actual reserved decision or Production-mutation boundary; identify the **specific operation** needing approval.
- **Match detail to the question**: a short question gets a short answer. A detailed audit request gets an evidence-backed report. Avoid inflated headings, repeated tables, ceremonial phrasing and multiple summaries of the same result.

[Owner communication examples](docs/agents/OWNER_COMMUNICATION_EXAMPLES.md).

The writing style must **increase clarity, never manufacture certainty**. If a critical safety limitation changes the next action, report it as a factual blocking condition, not as a habitual `다만` afterthought.

## Reassess / repair / reuse before creating

Before each consequential implementation change, first inspect the current source, approved issue/PR, actual runtime or deployment state and existing tests/configuration. Reproduce the gap; for external platforms consult current official documentation. Prefer **retain → configure/connect → repair → extend → adopt/adapt → build new**, reusing existing guards and deployment paths. Do not create a second authority, framework, store, policy or workflow when the existing one can be corrected. Record a brief disposition in the work order/PR; justify `BUILD_NEW` with a concrete unmet need. Small fixes require only proportionate checks; approved in-flight work and fixed MVP handoff gates are not automatically paused or expanded. Canonical rule: `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` §5B; technology adoption remains governed by `docs/operations/TECHNOLOGY_ADOPTION_POLICY.md`.

## Search / adopt before build

For substantial capabilities, follow the canonical technology-adoption gate before custom implementation: SEARCH → REUSE_INTERNAL → BUY / ADOPT / ADAPT → SIDECAR / LOCAL_SERVICE → BUILD_FROM_SCRATCH. Open-source and commercial options are valid; custom commodity implementation requires a reason. Historical `SECOND_*` locks concern competing product authority. Continue approved work while discovery proceeds. See the [full guidance](docs/agents/TECHNOLOGY_ADOPTION_GUIDANCE.md) and `docs/operations/TECHNOLOGY_ADOPTION_POLICY.md`.

## Roles

1. **User / Product Owner** — product goals, priorities, material UX/business decisions, merge/Production authority when the work contract requires owner authorization.
2. **Web CTO** — work contract, architecture/safety boundary, acceptance criteria, current-remote audit, independent final review.
3. **Implementation Worker (local model)** — implementation on the authorized branch, focused implementation tests, Draft PR, `DEV_FAST_GATE`, and implementation report. After the fast gate passes, the worker is released to the next authorized issue instead of waiting synchronously for the full Windows/Ubuntu/browser matrix.
4. **Local Validator(s)** — asynchronous exact-head execution in the required real environments when independent local/browser/OS/hardware validation is required. Windows, Ubuntu and browser/full-regression validation may be owned by different validator actors in parallel.

One actor may perform multiple **non-independent** stages. The same actor must not claim both implementation and **independent Local Validation** for the same revision.

```text
ONE_ACTOR_MAY_PERFORM_MULTIPLE_NON_INDEPENDENT_STAGES
BUT_IMPLEMENTATION_AND_INDEPENDENT_LOCAL_VALIDATION
MUST_NOT_BE_CLAIMED_BY_THE_SAME_ACTOR_FOR_THE_SAME_REVISION
```

When independent validation is actually required, what the validator records and how that record must be discoverable from the PR is defined in `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` section 10 and `docs/operations/templates/LOCAL_VALIDATION_REPORT.md`.

## Fast development gate and parallel validation

Development progress and merge readiness are separate gates.

```text
DEV_FAST_GATE=PASS
→ DEV_ACTOR_RELEASED=YES
→ implementation actor may move to the next authorized issue

VALIDATOR_WINDOWS=PENDING|PASS|FAIL|FIXING
VALIDATOR_UBUNTU=PENDING|PASS|FAIL|FIXING
VALIDATOR_BROWSER=PENDING|PASS|FAIL|NOT_REQUIRED
→ validators run asynchronously and may work in parallel

FULL_VALIDATION=PASS
→ required before merge when configured/relevant
```

A failing asynchronous validator blocks merge of the affected revision, not unrelated development progress. Per-slice proof selection and the repair/implementation-actor consequence: `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` sections 2, 8 and 10.

## Product-evidence stages are flexible

AI Revenue Lab does **not** require every Business to follow a mandatory UI → UX → backend ceremony.

A work contract selects the smallest evidence stage needed; the [stage list](docs/agents/EVIDENCE_AND_DELIVERY_FLOWS.md) gives examples.

The same stage list and the rule that verdicts of different kinds remain separate are canonical in `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` section 3 and `docs/operations/UI_UX_BACKEND_PHASE_GATES.md`.

## MVP delivery closure

A customer handoff or pilot deadline is an operating constraint, not an invitation to keep expanding validation indefinitely.

The evidenced handoff-blocker set, validation budget, fixed handoff gate, final smoke budget and terminal rule are canonical in `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` section 3A.

See the [MVP closeout flow](docs/agents/EVIDENCE_AND_DELIVERY_FLOWS.md): confirmed blocker through customer handoff.

## Finish-first execution mode

For Padiem platform work, completion throughput takes priority over maximizing concurrent feature starts.

Canonical current authority: `#3523`.

```text
DEVELOPMENT_MODE=FINISH_FIRST
ACTIVE_PRIMARY_IMPLEMENTATION_AXES=1
MAX_SUPPORTING_BLOCKER_LANES=2
BACKGROUND_LANES=READ_ONLY_OR_VALIDATION
UNRELATED_NEW_FEATURE_IMPLEMENTATION=FROZEN
```

The canonical machine-readable blocks for this mode, including the product-boundary vocabulary, are `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` sections 3B and 3B-1; the issue-classification vocabulary is `docs/operations/WORKFLOW_STATUS_MODEL.md`.

Parallel work is allowed only when it helps finish the same primary axis: blocker removal, exact-head validation, CI diagnosis, forensic investigation, or directly required platform integration. A free implementation worker must not select an unrelated issue merely to stay busy.

The fast-development rule means "do not wait on unrelated validation"; it does **not** mean "start an unrelated feature after every fast-gate pass."

## Default responsibility flow

The responsibility and evidence sequence runs from the work contract and implementation through validation, CTO review, applicable owner decision, merge, and authorized deployment; see the [full flow](docs/agents/EVIDENCE_AND_DELIVERY_FLOWS.md). This is not a mandatory product-stage sequence. A stage may be `NOT_REQUIRED` only with a recorded reason.

## Repository-wide test-scope rule

`docs/operations/TEST_SCOPE_AND_DELIVERY_POLICY.md` applies to **every** Business/app/package and to Engine/Core/Control Plane/Chat/Claw/Desktop work.

로컬 테스트가 실패하면 결함 단정 전에 먼저 `scripts/dev/check_venv_freshness.py`를 실행해 낡은 venv 설치본을 배제한다.

Default for a bounded bug fix:

```text
REPORT_MODE=COMPACT
focused load-bearing regression
+ relevant configured CI
+ Production smoke only when applicable
```

Do not turn every available/automatically-triggered test into a required gate. Do not wait for unrelated observational CI. Do not commission independent validation merely because an issue is P0/P1. Whole-product/repository testing requires an actual whole-surface blast radius or explicit gate.

## Non-negotiable rules

- Re-read current remote state immediately before mutation, review, and merge.
- Treat local clones and worktrees as machine-local working copies; the freshly fetched remote head is the only cross-machine source of truth. Follow `docs/operations/MULTI_MACHINE_LOCAL_WORKTREE_POLICY.md`.
- Record repository, exact base SHA, branch, allowed paths, forbidden paths, non-goals, and acceptance criteria before implementation.
- Do not directly modify `main` for ordinary development.
- Do not include unrelated dirty files or out-of-scope files.
- Do not weaken tests, assertions, safety checks, or acceptance criteria merely to obtain a pass.
- Never report failed, skipped, unavailable, or unexecuted checks as passing.
- Keep secrets, credentials, personal data, and private evidence out of source, logs, PRs, screenshots, and reports.
- CI proves only what it actually executes; CI alone is not universal completion evidence.
- A red external security/compliance signal is not cancelled by unrelated green CI. Before merge it must be resolved, or carry an explicit authorized disposition/waiver with reason and exact affected revision.
- Evidence belongs to the exact SHA it tested.
- A validator who modifies product source has created a new implementation revision; that run is not independent validation of the new revision.
- When a runtime-data validation bug is found at one trust boundary, trace the same field/contract through downstream parser/builder/projector/serializer/export/write boundaries. Explicit `null`, `undefined`, and a missing required property are distinct states unless the canonical contract explicitly says otherwise.
- For fail-open or bypass-prone fixes, add a load-bearing regression and use mutation/differential proof when practical so the test is shown to fail when the defect is restored.
- Wrong-project Preview or deployment output is defect evidence, not product acceptance evidence.
- `READY`, `CONDITIONALLY_READY`, and `NOT_READY` are Web CTO technical/review verdicts, not automatic merge commands.
- Before merge, the Web CTO posts an auditable `CTO_FINAL_REVIEW` record containing the exact head SHA and the **applicable** checklist results. Tiny bounded fixes may use the compact checklist; do not populate irrelevant template sections merely for ceremony.
- Owner-delegated merges must be single-purpose, head-SHA-pinned, and condition-checked at execution time (re-read remote state; required CI/gate results still valid).
- Final owner visual approval must never be inferred from a model/worker approval when the work contract explicitly reserves visual taste to the owner.
- **Model/provider decisions are owner-only.** If work encounters model selection, replacement, benchmarking, fallback ordering, provider routing, model-specific credential/binding, or activation/deployment decisions, stop model work and ask the Product Owner. Do not search, compare, live-test, rank, modify, merge, or deploy model/provider choices without fresh explicit owner instruction for that scope. Follow `MODEL_CHANGE_OWNER_APPROVAL_POLICY.md`.
- Deployment follows `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`; no alternate Preview/manual deployment path is implied by these rules.
- Local Docker Desktop / local Docker daemon is not a default development or deployment path. Do not start or require it unless established remote build/deploy paths have been checked and the Product Owner explicitly approves a task-specific exception. Follow `LOCAL_DOCKER_AVOIDANCE_POLICY.md`.
- On Windows, do not run `git worktree remove --force` while the worktree contains a junction/symlink/reparse point into a shared dependency directory (for example another checkout's `node_modules`). Remove the link itself with a link-safe operation first, verify the target directory is intact, then remove the worktree.

## GitHub report handoff

Reporting depth is proportional to task risk.

For bounded bug fixes/tiny glue with directly reviewable diff + focused tests/CI, default to:

```text
REPORT_MODE=COMPACT
```

The compact Issue/PR comment is the complete report in COMPACT mode. LONG mode, the report repository and path, the disabled Google Drive/rclone path, secret safety and report-write failure handling are canonical in `docs/operations/GITHUB_REPORT_HANDOFF_POLICY.md`.

## Required templates

- Work contract: `docs/operations/templates/CTO_WORK_ORDER.md`
- Implementation report: `docs/operations/templates/WEB_DEVELOPER_REPORT.md`
- Independent/local validation report: `docs/operations/templates/LOCAL_VALIDATION_REPORT.md`
- Final review: `docs/operations/templates/CTO_FINAL_REVIEW.md`
