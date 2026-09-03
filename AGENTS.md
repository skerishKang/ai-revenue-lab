# AI Revenue Lab Agent Rules

This file is the repository-wide entry point for AI-assisted work. A more specific `AGENTS.md` may add constraints for a subtree but may not weaken these repository-wide safety and evidence rules.

Canonical operating documents:

- `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md`
- `docs/operations/WORKFLOW_STATUS_MODEL.md`
- `docs/operations/EVIDENCE_REQUIREMENTS.md`
- `docs/operations/UI_UX_BACKEND_PHASE_GATES.md`
- `docs/operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`
- `docs/governance/B05_DANJION_BOUNDARY.md` — B05 is lineage-only; product work routes to DanjiOn.

## Roles

1. **User / Product Owner** — product goals, priorities, material UX/business decisions, merge/Production authority when the work contract requires owner authorization.
2. **Web CTO** — work contract, architecture/safety boundary, acceptance criteria, current-remote audit, independent final review.
3. **Web Developer** — implementation on the authorized branch, implementation tests, Draft PR, CI response, implementation report.
4. **Local Validator** — exact-head execution in the required real environment when independent local/browser/OS/hardware validation is required.

One actor may perform multiple **non-independent** stages. The same actor must not claim both implementation and **independent Local Validation** for the same revision.

```text
ONE_ACTOR_MAY_PERFORM_MULTIPLE_NON_INDEPENDENT_STAGES
BUT_IMPLEMENTATION_AND_INDEPENDENT_LOCAL_VALIDATION
MUST_NOT_BE_CLAIMED_BY_THE_SAME_ACTOR_FOR_THE_SAME_REVISION
```

If environment constraints require the implementer to execute local checks too, report them as implementation self-checks/non-independent verification and leave the independent gate pending when the work contract requires it.

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

## Default responsibility flow

```text
User request / portfolio authority
→ Web CTO exact work contract
→ Web Developer implementation
→ implementation self-check + configured CI
→ independent validation when required
→ Web CTO final review
→ owner decision when materially required
→ merge
→ configured Production deployment and acceptance when authorized
```

This is a responsibility/evidence flow, not a mandatory product-stage sequence. A stage may be `NOT_REQUIRED` only with a recorded reason.

## Non-negotiable rules

- Re-read current remote state immediately before mutation, review, and merge.
- Record repository, exact base SHA, branch, allowed paths, forbidden paths, non-goals, and acceptance criteria before implementation.
- Do not directly modify `main` for ordinary development.
- Do not include unrelated dirty files or out-of-scope files.
- Do not weaken tests, assertions, safety checks, or acceptance criteria merely to obtain a pass.
- Never report failed, skipped, unavailable, or unexecuted checks as passing.
- Keep secrets, credentials, personal data, and private evidence out of source, logs, PRs, screenshots, and reports.
- CI proves only what it actually executes; CI alone is not universal completion evidence.
- Evidence belongs to the exact SHA it tested.
- A validator who modifies product source has created a new implementation revision; that run is not independent validation of the new revision.
- Wrong-project Preview or deployment output is defect evidence, not product acceptance evidence.
- `READY`, `CONDITIONALLY_READY`, and `NOT_READY` are Web CTO technical/review verdicts, not automatic merge commands.
- Final owner visual approval must never be inferred from a model/worker approval when the work contract explicitly reserves visual taste to the owner.
- Deployment follows `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`; no alternate Preview/manual deployment path is implied by these rules.
- For any B05 request, read `docs/governance/B05_DANJION_BOUNDARY.md` first. Do not create or modify a standalone B05 product surface; route product work to `skerishKang/02-danji-on` unless the user explicitly requests historical/portfolio metadata maintenance only.

## Required templates

- Work contract: `docs/operations/templates/CTO_WORK_ORDER.md`
- Implementation report: `docs/operations/templates/WEB_DEVELOPER_REPORT.md`
- Independent/local validation report: `docs/operations/templates/LOCAL_VALIDATION_REPORT.md`
- Final review: `docs/operations/templates/CTO_FINAL_REVIEW.md`