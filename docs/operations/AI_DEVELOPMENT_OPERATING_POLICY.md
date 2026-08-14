# AI Development Operating Policy

- Status: canonical repository operating policy
- Scope: repository-wide implementation, validation, review, merge, and Production verification
- Authority: Issue #148
- Deployment authority: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

## 1. Purpose

AI Revenue Lab separates product authority, implementation, independent validation, and final technical review so that completion claims are tied to reproducible exact-revision evidence rather than worker self-report.

The policy is designed for rapid AI-assisted product development. It does not require a fixed UI → UX → backend sequence. The Web CTO chooses the smallest bounded evidence slice that can answer the current product question.

## 2. Required roles

1. **User / Product Owner** — product goal, priority, material product/UX/business decisions, and owner-only merge or Production authority when required by the work contract.
2. **Web CTO** — exact work contract, architecture/safety boundary, acceptance criteria, remote audit, independent final review.
3. **Web Developer** — authorized implementation, implementation tests/self-checks, Draft PR, CI response, implementation report.
4. **Local Validator** — independent exact-head execution in a real browser/OS/hardware/local-service environment when the work contract requires it.

A person or model may perform several non-independent stages. However:

```text
ONE_ACTOR_MAY_PERFORM_MULTIPLE_NON_INDEPENDENT_STAGES,
BUT IMPLEMENTATION AND INDEPENDENT LOCAL VALIDATION
MUST NOT BE CLAIMED BY THE SAME ACTOR FOR THE SAME REVISION.
```

When the implementer also runs local/browser checks because no independent validator is available, those checks are implementation self-checks or non-independent verification. They may be useful evidence but do not satisfy an explicitly required independent validation gate.

## 3. Product-evidence model

Product work is organized around the evidence goal, not a mandatory ceremony. A work contract may use one or more of these stages:

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

These stages are not required to occur in order for every Business.

The contract must identify what is needed now:

- visual desirability/UI;
- end-to-end UX;
- deterministic simulation;
- service-led operation;
- local runtime;
- live backend/API/provider slice;
- authentication/persistence;
- commercial/reliability hardening.

Backend work is not frozen by default. Build the smallest observable, reversible runtime slice when it is necessary to prove the primary product journey. Conversely, do not add backend, accounts, providers, or persistence when a static/deterministic/service-led slice answers the current question faster and more truthfully.

UI, UX, backend/runtime, deployment, market-reference, investor-demo, commercial, and owner-visual verdicts remain separate evidence dimensions.

## 4. Default responsibility flow

```text
User request / portfolio authority
→ Web CTO work contract
→ Web Developer implementation
→ implementation self-check and configured CI
→ independent validation when required
→ Web CTO final review
→ owner decision when the contract reserves one
→ merge
→ configured Production deployment and acceptance when authorized
```

This is a responsibility and evidence flow, not a mandatory product-stage ordering rule.

A step may be marked `NOT_REQUIRED` only when the work contract or final review records the reason. Do not silently skip a required gate.

## 5. Work identity before implementation

Record:

- repository and default branch;
- current exact base SHA;
- branch name;
- Issue/work-order authority;
- selected product-evidence stage;
- allowed paths;
- forbidden paths;
- explicit non-goals;
- required automated checks;
- independent validation requirement;
- owner-only decision requirement, if any;
- deployment lane/risk level, if applicable;
- acceptance criteria.

“Latest main” alone is not revision identity.

## 6. Web CTO responsibilities

The Web CTO:

- reads current remote state rather than trusting previous reports;
- fixes the exact work contract and smallest useful scope;
- defines data/security/deployment/non-goal boundaries;
- separates evidence dimensions and approval authorities;
- inspects the actual diff and current exact head;
- checks CI and validation sufficiency;
- rejects stale-head evidence unless applicability is explicitly justified;
- assigns the final technical/review status.

Only the Web CTO assigns:

```text
READY
CONDITIONALLY_READY
NOT_READY
```

These statuses do not manufacture owner visual approval, commercial approval, merge authority, or Production authority that the work contract reserves separately.

## 7. Web Developer responsibilities

The Web Developer:

- starts from the authorized exact base or reports drift before proceeding;
- changes only authorized paths;
- implements product behavior, tests, and documentation in scope;
- creates/updates a Draft PR;
- records exact base/head, changed files, diff, commands, exit statuses, pass/fail/skip counts, CI, and limitations;
- distinguishes implementation self-check from independent validation;
- never self-assigns final CTO status.

## 8. Local Validator responsibilities

When independent Local Validation is required, the validator:

- checks out or otherwise executes the exact remote PR head;
- records expected and actual tested SHA;
- records OS/runtime/browser/hardware/local-service environment;
- records repository cleanliness and whether source was modified;
- runs required user journeys, tests, browser checks, provider/local-runtime checks, or hardware/OS-specific checks;
- records commands, exits, relevant logs, screenshots/artifacts, console/page/network failures, and reproduction evidence.

If the validator changes product source, that creates a new implementation revision. The modified run cannot be labelled independent validation of that new revision.

## 9. CI and automated checks

CI is required when configured and relevant to the scope, but CI is not universal completion evidence.

- Never claim a nonexistent CI run passed.
- A static/lint test does not prove browser UX.
- A browser test does not prove Production revision identity.
- A mocked provider test does not prove a live provider contract.
- A successful URL/HTTP 200 does not prove the reviewed SHA is deployed.

Missing coverage must be stated and supplemented by the evidence required by the work contract.

## 10. Revision invalidation

Evidence belongs to the exact revision it tested. A new commit invalidates prior-head evidence for changed behavior unless the Web CTO explicitly documents why an item remains applicable.

Before merge, re-read:

- current `main`;
- PR exact head;
- changed files/diff;
- CI/checks;
- comments/review threads;
- exact-head validation evidence.

Use expected-head merge protection where available.

## 11. Scope and safety rules

- No direct `main` mutation for ordinary feature work.
- No unrelated dirty-file inclusion.
- No out-of-scope file changes without contract update.
- No acceptance/test/assertion/safety weakening merely to obtain a pass.
- No hidden failure, skip, warning, or untested state.
- No secrets, credentials, personal data, or private evidence in source/logs/PRs/screenshots/reports.
- No hidden source edits by a validator.
- No wrong-project deployment/Preview as acceptance evidence.
- No unverified claim that a live site represents a reviewed revision.

## 12. UI and owner visual decisions

The Web CTO may independently reject objective visual defects such as:

- clipping/overflow;
- unreadable contrast;
- broken hierarchy;
- nonfunctional controls;
- inconsistent responsive behavior;
- console/page/runtime errors;
- obvious product-contract mismatch.

When a work contract explicitly reserves aesthetic/taste approval to the owner, a model/CTO must not convert its own judgment into `OWNER_UI_APPROVED`.

When the owner delegates design selection to the CTO, the CTO may choose a direction, but the decision must be recorded explicitly as a CTO-delegated product decision rather than rewriting historical owner-approval evidence.

## 13. Backend and service-led evidence

Select an explicit backend mode when relevant:

```text
NO_BACKEND
DETERMINISTIC_SIMULATION
SERVICE_LED
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
PILOT_RUNTIME
COMMERCIAL_HARDENING
```

Use real backend capability early when it is necessary to prove product value. Keep it bounded to the primary evidence journey and concrete data/security/cost risk.

Authentication is not mandatory for every MVP; authorization is mandatory whenever private records can be read or mutated.

Service-led MVPs are legitimate when the manual operator boundary is disclosed and measured.

## 14. Merge and Production

Deployment behavior is governed by `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`.

For Git-connected projects, an explicitly authorized merge to the configured Production branch is the deployment action. Do not create an alternate manual/Preview/staging deployment merely because a Git-triggered deployment is inconvenient.

Before merge, require the evidence and authority defined by the work contract. After merge, Production-capable work is complete only after the configured Production surface is verified against the resulting main/release revision and the relevant primary journey.

## 15. Prohibited interpretation of historical phase records

Historical `UI_ONLY`, UI→UX→backend, approval, Preview, or backend-frozen records remain truthful evidence of the policy that applied to those revisions. They do not override this current repository-wide policy for new work.

## 16. Templates and supporting documents

- Workflow states: `WORKFLOW_STATUS_MODEL.md`
- Evidence: `EVIDENCE_REQUIREMENTS.md`
- Product evidence / phase separation: `UI_UX_BACKEND_PHASE_GATES.md`
- CTO work order: `templates/CTO_WORK_ORDER.md`
- Developer report: `templates/WEB_DEVELOPER_REPORT.md`
- Local Validation report: `templates/LOCAL_VALIDATION_REPORT.md`
- CTO final review: `templates/CTO_FINAL_REVIEW.md`
