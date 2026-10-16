# AI Revenue Lab Agent Rules

This file is the repository-wide entry point for AI-assisted work. A more specific `AGENTS.md` may add constraints for a subtree but may not weaken these repository-wide safety and evidence rules.

## Owner-facing Korean report language — explicit instruction (2026-10-16)

- **Forbidden wording:** Do not use the Korean adversative connector `다만` anywhere in Owner-facing Korean answers, interim/final status reports, handoff messages, GitHub PR/Issue progress summaries, or explanations. This is an explicit repeated Owner preference, not an optional stylistic suggestion. Before sending Korean prose to the Owner, inspect the final answer for the exact expression and rewrite it.
- Do not immediately follow an Owner instruction with that connector or with rhetorical exceptions that narrow the requested work, presume refusal, add needless approval gates, or redirect the task without evidence.
- When genuine limitations exist, **report the facts directly and separately** using `현재 확인 상태:`, `확인된 제약:`, `원인:`, `해결 방법:`, `다음 실행:`. Continue independently authorized work. Never hide actual security, legal, authentication, data-isolation, or deployment constraints.
- Preserve verbatim external source code/logs/legal quotations when their literal content is necessary; the prohibition governs the assistant's authored prose, not source-data mutation. It does not create new product permissions or override real security enforcement.
- New GitHub-aware agent sessions must read this rule. Existing conversations/workers may require instruction reload; committing this document does not automatically edit their runtime instructions.

## Non-public company governance (read before business decisions)

This repository contains **public development and engineering policy**, not the authoritative text of PADIEM's internal business policy. Business instructions are local-only on the authorized **Padiem-Command-Center** PC:

- Local Governance root: `G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-governance` (consult its `README.md` for the current document index).
- Business policy: read the applicable documents under `사업방침/`, including `00_사업방침_원칙.md` and `02_고객경험_사전위임_자동화_대표결정.md`.
- Technical/CTO operating policy: then read the applicable documents under `운영방침/`, including `00_고객경험_사전위임_자동실행_운영기준.md` and `01_CTO_에이전트_운영규칙.md`. The former `사업방침/01_CTO_에이전트_운영규칙.md` is only a compatibility relocation notice.
- Web CTO: read through the connected **Desktop Commander**. Local models: read through their authorized computer filesystem.
- **Decision order:** latest explicit Owner instruction → local non-public business policy for business/product decisions → GitHub development/technical operating policies → dated issue history. Do not publish the business documents or reproduce their substantive contents in GitHub Issues, PRs or code.
- If this folder cannot be accessed, or the Owner's decision conflicts with an existing technical gate and the resolution is not specified, explain the exact uncertainty and **ask the Owner**. Do not independently create new business exclusions, customer-facing required approval steps, or permissions grants. Actual runtime/code/OS behavior must still be reported truthfully.

## Every session: evidence-based blocker resolution

- **Session entry:** On a new repository-aware agent/CTO session, read this `AGENTS.md` and the relevant current local private Governance documents through the authorized COM1 connection before making business/product decisions. Record what was actually read; if the private source is unavailable, state `NOT_READ` and the specific access limitation. A fresh general ChatGPT conversation does **not** automatically import this file; mirror this minimal rule in ChatGPT Project Instructions. Do not claim automatic loading or a completed read without evidence.
- **No bare refusal or indefinite HOLD:** If a task is blocked, report `observed failure point + verified cause (or clearly marked unknown) + practical fix + alternative + next action + exact Owner decision needed (if any)`. Explore the smallest authorized repair/reuse path and continue independent permitted work. Do not invent approvals, policies or external technical barriers.
- **Legal/compliance issues:** Present the specific issue, relevant verifiable law/license/terms, factual assumptions and lawful choices for the Owner's informed decision. Avoid condescending lectures or unsupported definitive legal conclusions; ask a concise question when material facts are missing. Never hide an actual prohibition, bypass security/authorization constraints or implement unlawful behavior.
- **Owner decision respect:** Do not unilaterally impose new customer-facing restrictions or multiple logins/approval gates; check the private policy and ask the Owner if a real business decision remains unresolved. Avoid repeating irrelevant tests or document churn in place of the requested working outcome.

## Public engineering context (business stage: local governance source)

**Public engineering reality:** this repository is maintained with limited development capacity. The business/customer deployment stage is decided in the **local private Governance source linked above**, not inferred from this public paragraph. Existing live domains, owner accounts, secrets, D1 records, configured approvals and technical boundaries still require truthful handling.

**CTO default is finish working features, not accumulate validation gates.** For a normal bounded task: implement or reuse the smallest working change -> run the focused regression and already required relevant CI -> perform **one** representative actual B14/Worker/browser integration check when the claimed behavior needs a live check -> fix a reproduced failure -> decide merge/close. Do not transform an ordinary one-model test, one-field fix or internal demo into a multi-phase certification project.

- **Batch small commits before pushing.** A single PR push can fan out into many Actions workflows; prefer one coherent push after local focused checks instead of pushing every tiny edit and cancelling the same 10+ checks repeatedly. For urgent fixes, push when ready; never postpone a safety repair solely to save CI minutes.
- **No test-on-test spiral.** Before adding a test or making it a blocker, state the new failure it can detect, why current evidence cannot detect it, and whether that failure prevents today's functional goal. If no concrete new risk exists, reuse existing passing evidence and move forward. More green tests, repeated unchanged CI, extra validators, new policy files and extra open issues are not progress by themselves.
- **Right-size a model experiment.** For an owner-authorized, already registered B14 candidate, prefer one small synthetic request through the existing approved route, one HTTP/provider/model/error verdict, no auto-retry or fallback. A real 429/504 is a useful test outcome; don't require proving future provider availability before trying once. If a real platform/tool authorization denial occurs, stop there and report that exact restriction; never bypass it with another credential, client or path.
- **Solo-owner governance.** The CTO executes delegated ordinary review/merge/deployment decisions using the configured protection and release workflow. Do not invent a second independent human reviewer, a second owner login or repeated ceremonial approvals. Real access restrictions, branch protection, security, auth/tenant isolation, destructive writes, secret leakage, billing and release-specific manual gates remain binding.
- **Close completed work.** Distinguish implementation acceptance from consolidated end-to-end acceptance: close a bounded implementation/evaluation issue when its approved deliverable is satisfied (including a documented no-go). Keep genuinely unproven runtime acceptance in the existing product integration issue; do not open a fresh verification issue for each source PR.
- **Priority when instructions seem to conflict:** apply the current Owner's explicit project stage and the canonical operating policy below to choose **the minimum sufficient evidence**, while retaining actual platform protections and the non-negotiable safety boundaries. An older checklist does not silently raise the required validation level.
- **Every fresh repository-aware CTO/agent session:** read this section and the current main + canonical stage policy before planning work; treat older issue text as dated evidence, not a fresh order. An unrelated ChatGPT thread does **not** automatically ingest this repository file; mirror these principles in the ChatGPT Project Instructions for cross-thread continuity.
- **Browser QA re-entry/tool identity:** Before authenticated browser testing, read `docs/operations/UI_UX_TABBIT_QUICKCHECK_20261012.md` §4 and the latest **executed** evidence in the existing integration issue. Tabbit LocalAgent `tabbit-cli` and BSK `bsk` are different controls; BSK may connect to Chrome, not Tabbit. Reuse the expressly authorized working browser/session; Desktop Commander only transports CLI commands. Do not silently substitute TinyFish, user-desktop `pyautogui`, or manual DevTools console input. Verify the actual authenticated browser, preserve user focus/tabs, use bounded approval and POST counts, and stop/release the agent session on completion. This is a tool-selection safeguard, not a new reviewer, sign-in, or production-release gate.

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

For any model/provider question, start at [the shared model documentation index](docs/models/README.md); do not rely on a product README's copied model list as live registry/route evidence. The index points separately to OWNER policy, B14 source, product route declarations and Production verification. It does not grant model-change authority.

**Public disclosure minimization:** New public Issues, PR narratives and operational documentation should use generic execution contracts instead of listing internal provider choices, model-to-tier assignments, or credential binding inventories. Keep the detailed selection, internal binding-slot map and disclosure decisions in authorized COM1 private Governance. Preserve model/provider identifiers in executable source or tests only where required for correct protocol dispatch and independent safety checks; never publish credential values. Existing public history is not erased by a new notice. Do not misrepresent required external attribution or contractual disclosures.

Latest owner B14 model-selection reference: `docs/operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md`. An older B14 source/catalog entry proves only that it exists in that source, not that the OWNER approves it. Distinguish selection from registration and Production availability; the ledger is NOT a second approval policy.

## Owner-facing communication: direct conclusion and next action

All agents (Web CTO, implementation workers and validators) must report to the Product Owner in **direct, concise Korean** by default. This rule governs conversational progress, final reports and owner-facing Issue/PR summaries; it does not replace technical evidence or safety checks.

- **Lead with the answer or outcome**: `완료 / 미완료 / 차단`, followed by the next concrete action. When asked "다음은 뭐야?", state **one immediate next step**, not a new recap of earlier work.
- **Keep completed work completed**: do not repeatedly restate resolved bugs, already merged PRs or prior approvals as if action is still required. Mention them only when needed to explain a new decision.
- **Avoid filler concessions and repetitive hedging**, especially mechanically attaching `다만`, `하지만`, `그렇지만`, `한편`, or phrases equivalent to "one thing remains" after every positive conclusion. Do not append an unrequested caution or an open-ended question to a completed status update.
- **State real limitations directly**. When a material blocker or authorization boundary exists, say `미완료: <항목>. 이유: <검증된 원인>. 다음: <조치>.` Do **not** omit an actual safety, security or Production approval condition merely to sound decisive.
- **Do not confuse evidence stages**: `테스트 완료`, `PR 병합 완료`, `운영 배포 완료`, `실서비스 검증 완료` are different claims. State exactly which stage was verified, without repetitive explanatory disclaimers.
- **Respect delegated CTO execution**: proceed with authorized ordinary source reviews/merges instead of reflexively asking the owner again. Ask for approval only at an actual reserved decision or Production-mutation boundary; identify the **specific operation** needing approval.
- **Match detail to the question**: a short question gets a short answer. A detailed audit request gets an evidence-backed report. Avoid inflated headings, repeated tables, ceremonial phrasing and multiple summaries of the same result.

Examples of preferred owner-facing Korean:

```text
Q: 다음은 뭘 해야 해?
A: 다음은 Engine에 Owner D1을 연결하고 실제 운영 상태를 검증하는 것입니다.

Q: 롤백 요청 수정은 끝났어?
A: 완료했습니다. PR #3862 병합, 관련 CI 통과. 다음 작업은 Engine 운영 연결입니다.

Q: 지금 운영 연결이 됐어?
A: 아직 연결하지 않았습니다. 소스 검증과 배포 절차까지 완료했습니다.
   운영 연결은 별도 승인 후 실행합니다.
```

The writing style must **increase clarity, never manufacture certainty**. If a critical safety limitation changes the next action, report it as a factual blocking condition, not as a habitual `다만` afterthought.

## Reassess / repair / reuse before creating

Before each consequential implementation change, first inspect the current source, approved issue/PR, actual runtime or deployment state and existing tests/configuration. Reproduce the gap; for external platforms consult current official documentation. Prefer **retain → configure/connect → repair → extend → adopt/adapt → build new**, reusing existing guards and deployment paths. Do not create a second authority, framework, store, policy or workflow when the existing one can be corrected. Record a brief disposition in the work order/PR; justify `BUILD_NEW` with a concrete unmet need. Small fixes require only proportionate checks; approved in-flight work and fixed MVP handoff gates are not automatically paused or expanded. Canonical rule: `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md` §5B; technology adoption remains governed by `docs/operations/TECHNOLOGY_ADOPTION_POLICY.md`.

## Search / adopt before build

For substantial new capabilities, workers and the Web CTO follow the canonical technology-adoption gate before custom implementation:

```text
SEARCH
→ REUSE_INTERNAL
→ BUY / ADOPT / ADAPT
→ SIDECAR / LOCAL_SERVICE
→ BUILD_FROM_SCRATCH
```

Open-source and commercial technology are both valid. Paid APIs, SDKs, commercial licenses and self-hosted products may be preferable to weeks of custom development.

A custom commodity implementation requires an explicit reason. Historical `SECOND_*` locks mean no competing **Padiem product authority**; they do not prohibit internal parsers/decoders/native libraries used behind one reviewed adopted-project boundary.

See `docs/operations/TECHNOLOGY_ADOPTION_POLICY.md`.

Technology discovery does not automatically pause an already-approved active task. Continue the bounded accepted scope while scans run in parallel; use new findings for the next slice or a reviewed replacement decision unless CENTRAL explicitly pauses the work.

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

Independent validation is required only when the work contract needs evidence that implementation self-check + relevant CI cannot supply, such as real browser/OS/hardware/local-service behavior, high-risk environment composition, or an explicitly reserved independent gate. For a tiny deterministic bug fix with a focused load-bearing regression, default to `NOT_REQUIRED` unless one of those conditions applies; do not commission a second validator merely because the issue is P0/P1.

If environment constraints require the implementer to execute local checks too, report them as implementation self-checks/non-independent verification and leave the independent gate pending only when the work contract actually requires it. "independent gate pending" is not a mergeable state: before merge the PR must record either a completed `LOCAL_VALIDATION_REPORT.md` instantiation for the exact head, or `NOT_REQUIRED` with an explicit reason.

Independent validation must also be **discoverable from the PR itself**. A private report that cannot be found from the reviewed PR is insufficient audit trail. Before merge, the PR review/comment history must record:

```text
INDEPENDENT_VALIDATOR=<actor>
VALIDATED_HEAD=<exact SHA>
RESULT=PASSED/FAILED/BLOCKED
REPORT_POINTER=<immutable report/artifact pointer or NOT_REQUIRED reason>
```

The Web CTO re-checks that this record names the exact head being merged.

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

A failing asynchronous validator blocks merge of the affected revision, not unrelated development progress. If a validator fixes source, that actor becomes a repair/implementation actor for the new revision; the modified run is not independent validation of the new head. The repair may be revalidated by another independent actor while the original implementation worker continues other work.

For Windows-first slices, the focused Windows proof may be the `DEV_FAST_GATE`. For web/backend slices, use the smallest focused web/API/contract proof that actually exercises the change. Do not require every supported OS/browser in the implementer's synchronous critical path.

See issue #3429 for the CI/workflow optimization program.

## Product-evidence stages are flexible

AI Revenue Lab does **not** require every Business to follow a mandatory UI → UX → backend ceremony.

A work contract selects the smallest evidence stage needed to answer the current product question, for example:

```text
PRODUCT_FRAMED
COMPETITIVE_DEMO
INVESTOR_DEMO
MVP_VERTICAL_SLICE
SERVICE_LED_PILOT
RUNTIME_PILOT
COMMERCIAL_HARDENING
OPERATING_PRODUCT
```

UI, UX, backend, live providers, local runtime, or service-led operations may start when they are materially required for that evidence goal and explicitly included in scope. Their verdicts remain separate so one kind of evidence is never presented as another.

## MVP delivery closure

A customer handoff or pilot deadline is an operating constraint, not an invitation to keep expanding validation indefinitely.

For an MVP that already has a defined primary journey:

- treat only **concrete, evidenced** primary-journey failure, auth/authz bypass, secret/private-data leakage, data corruption/destructive behavior, or another explicitly accepted P0/P1 condition as a handoff blocker;
- record newly discovered lower-severity defects, hardening ideas, broad refactors, speculative risks, and unrelated debt as follow-up work rather than silently expanding the current blocker set;
- validate a narrow fix with the smallest load-bearing regression first, then rely on relevant configured CI, then run the bounded Production smoke needed for the customer promise;
- do not rerun unrelated full suites or previously passed journeys merely because time has passed or `main` moved; first determine whether the new commits affect the tested behavior, dependency, authority, configuration, or deployment surface;
- when broad validation is proposed after the MVP acceptance matrix is otherwise satisfied, the Web CTO must state the concrete claim it protects and why existing evidence is insufficient.

Default MVP closeout flow:

```text
confirmed blocker
→ minimal fix
→ focused regression
→ relevant configured CI
→ authorized Production deployment
→ bounded real-account/primary-journey smoke
→ customer handoff
→ non-blocking hardening continues after handoff
```

Once the accepted handoff blocker set is zero and the required Production smoke passes, continued exploratory validation must not delay delivery unless it produces new concrete blocker evidence.

Handoff-gating checks must be named **before** the final fix/deploy whenever practical. Automatically triggered but unrelated CI jobs may continue in the background; their existence does not make them handoff gates. A P1/P2 or backlog item does not block an MVP merely because it is open. Only the owner or a new concrete P0/P1 customer-impacting finding may promote it into the handoff blocker set.

After the final Production-changing revision, run the agreed primary-journey smoke once. Repeat the same smoke only if the deployed revision changes, the first result is ambiguous/failed, or a new concrete defect affects that journey.

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

Parallel work is allowed only when it helps finish the same primary axis: blocker removal, exact-head validation, CI diagnosis, forensic investigation, or directly required platform integration. A free implementation worker must not select an unrelated issue merely to stay busy.

For the current Padiem cycle, the primary axis is:

```text
Padiem Platform
-> canonical identity/account/workspace
-> required entitlement/admission
-> Padiem AI Engine
-> Padiem Core / B14
-> B54 Padiem Claw
-> user-visible result
```

Architecture is decided top-down, but implementation proceeds from the **lowest missing dependency upward** until the user-visible vertical slice is complete.

A discovered issue must be classified before implementation:

```text
PRIMARY_BLOCKER
PRIMARY_NONBLOCKING_FOLLOWUP
UNRELATED_BACKLOG
```

Only `PRIMARY_BLOCKER` may preempt the primary lane.

Source-complete or merged-main is not terminal completion for a Finish-first axis. The applicable terminal definition includes Production activation, end-to-end reference-product proof, a user-visible result, rollback readiness, and zero primary blockers.

Product boundaries remain strict. B66 Padiem Quote, B67 Padiem Legal, B62 Padiem Chat, and B54 Padiem Claw are independent products that may reuse Padiem Platform authorities. Shared Platform usage does not authorize moving product-local work into another product's lane.

```text
B66_IS_ENGINE=NO
B66_IS_CLAW=NO
B66_PRODUCT_INDEPENDENT=YES
```

The fast-development rule means “do not wait on unrelated validation”; it does **not** mean “start an unrelated feature after every fast-gate pass.” Validators may run in parallel while the implementation actor continues the same primary axis.

## Default responsibility flow

```text
User request / portfolio authority
→ Web CTO exact work contract
→ Implementation Worker (local model) implementation
→ focused self-check + DEV_FAST_GATE
→ DEV_ACTOR_RELEASED; implementation may continue elsewhere
→ asynchronous Windows / Ubuntu / browser validators when required
→ FULL_VALIDATION on the final exact head
→ Web CTO final review
→ owner decision when materially required
→ merge
→ configured Production deployment and acceptance when authorized
```

This is a responsibility/evidence flow, not a mandatory product-stage sequence. A stage may be `NOT_REQUIRED` only with a recorded reason.

## Repository-wide test-scope rule

`docs/operations/TEST_SCOPE_AND_DELIVERY_POLICY.md` applies to **every** Business/app/package and to Engine/Core/Control Plane/Chat/Claw/Desktop work.

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
- Follow §11A Test execution economy in `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md`: batch logical edits, scale validation to changed impact, and do not repeat broad suites solely because unrelated main drift occurred.

## GitHub report handoff

Reporting depth is proportional to task risk.

For bounded bug fixes/tiny glue with directly reviewable diff + focused tests/CI, default to:

```text
REPORT_MODE=COMPACT
```

The compact Issue/PR comment is the complete report. Do **not** create a separate workdiary report merely because the task is Padiem/CLAW.

Use:

```text
REPORT_MODE=LONG
REPORT_REPO=skerishKang/workdiary
REPORT_PATH=padiem-reports/YYYY-MM-DD/<CLAW>/<task>.md
REPORT_COMMIT=<immutable workdiary commit SHA>
```

only for materially complex/high-risk work, large evidence packages, independent local/browser/hardware validation, migrations/destructive/auth-secret boundary work, incident investigations, or when CENTRAL explicitly requests it.

Google Drive/rclone reporting is disabled. Do not retry quota failures or perform Drive delete/trash cleanup. Prefer GitHub Actions artifacts for screenshots, Playwright traces and large logs. Never put password/secret/token/cookie/private-key/database-credential values into reports, comments or artifacts.

A LONG-mode report-write failure blocks only work that actually requires LONG mode; it must not manufacture a blocker for a COMPACT-eligible tiny fix.

Follow `docs/operations/GITHUB_REPORT_HANDOFF_POLICY.md`.

## Required templates

- Work contract: `docs/operations/templates/CTO_WORK_ORDER.md`
- Implementation report: `docs/operations/templates/WEB_DEVELOPER_REPORT.md`
- Independent/local validation report: `docs/operations/templates/LOCAL_VALIDATION_REPORT.md`
- Final review: `docs/operations/templates/CTO_FINAL_REVIEW.md`