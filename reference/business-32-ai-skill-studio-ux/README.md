# Business 32 · AI Skill Studio / AI 업무 실습실 — Phase 2 UX

Phase 2 deterministic synthetic frontend UX for Issue #349.

## Status

```text
BUSINESS_32_PHASE_2_UX_IMPLEMENTED
UX_REVIEW_READY
NOT_INDEPENDENTLY_VALIDATED
BROWSER_VERIFICATION_DEFERRED
BACKEND_FROZEN
PR_OPEN_DRAFT_UNMERGED
DO_NOT_MERGE
```

## Authority

- Product decision: #246
- Phase 1 UI contract: #248
- Phase 1 UI PR: #251 (OPEN / Draft / unmerged)
- Approved UI exact head: `8d2a6aef2d7a0bd8519b203691db95a7d216ddac`
- Phase 2 UX contract: #349

## Product result

`VERIFIED ORGANIZATIONAL AI SKILL`

The user selects one bounded synthetic purchase task, confirms scope and required
inputs, executes five guided steps, compares source evidence, discovers missing and
conflicting evidence, stops/supplements/resumes, produces a recommendation-memo
draft, requests human review, applies corrections, re-runs the corrected procedure,
retains unresolved exceptions, receives human final approval, and saves a reusable
organizational skill card with version, owner, and next-review date.

No live execution, upload, model call, storage, account, API, database, analytics,
billing, enterprise integration, or Cloudflare mutation.

## Synthetic fixture

```text
Organization: Nori Works — fictional
Task: 세 개의 합성 공급업체 견적서를 비교해 구매 추천 메모 작성
Reviewer: 합성 운영 책임자 (fictional operations lead)
Real execution: 없음
```

All organization, people, suppliers, quotations, prices, contracts, and review
records are synthetic. `data/fixture.json` is the canonical fixture;
`scripts/fixture.js` is its embedded deterministic mirror.

## State model

16 domain states + 8 general states = 24 states:

```text
domain:    initial, task-selected, input-incomplete, ready, running, step-complete,
           missing-evidence, conflicting-evidence, stopped, draft-result,
           review-requested, correction-required, revised, approval-pending,
           approved, skill-saved
general:   loading, empty, validation-error, system-error, retry, cancelled,
           resume, completed
```

The deterministic state machine is `scripts/machine.js` (`B32Machine`), a pure
reducer. Every state has a deterministic test path in `tests/`.

## Synthetic roles and reviewer handoff

```text
operator  — 업무 실행자
reviewer  — 합성 운영 책임자 · 사람 검토자
```

The machine context carries `activeRole` and `roleHistory`. Handoff is an explicit
UI action, never a button attribute:

```text
검토자에게 인계   — operator → reviewer
실행자에게 반환   — reviewer → operator
```

`approve-review`, `reject-review`, and `approve` require `activeRole === reviewer`
at the state-machine level; an operator attempting them transitions to
`validation-error` with:

```text
업무 실행자는 자신의 결과를 검토하거나 승인할 수 없습니다.
합성 운영 책임자에게 인계하십시오.
```

Execution actions are operator-only and blocked for the reviewer role:

```text
select-task, check-inputs, supplement, begin-run, complete-step, next-step,
request-supplement, resolve-conflict, stop-run, resume-run, resume-confirm,
request-review, apply-correction, re-run, save-skill, complete
```

A reviewer attempting any of them transitions to `validation-error` with:

```text
검토자는 업무 실행·수정·저장을 대신할 수 없습니다. 실행자에게 반환하십시오.
```

`approved → save-skill` requires `activeRole === operator`, human approval, and
an unsaved skill. The normal flow is reviewer final approval → `handoff-to-operator`
→ operator `save-skill`.

Role history entries use explicit directions:

```text
recordHandoff(ctx, { from: previousRole, to: nextRole, action, state })
```

with invariants `from !== to`, `roleHistory[n].to === activeRole`, and
`roleHistory[i-1].to === roleHistory[i].from`.

Skill save is possible for the operator role but remains blocked until human
approval. Role restrictions are enforced in `scripts/machine.js`, not by UI
disabled states alone.

## Deterministic focus restoration

No unconditional "focus first button" policy. After each render, focus moves by
contract using `data-focus-key` / `data-focus-target` markers:

```text
일반 상태 전환:   새 상태의 heading(data-focus-key="view-heading")
validation-error: error-summary
drawer open:      drawer-heading 또는 닫기 버튼
drawer close:     증거 열기 버튼 복귀 (opener)
role handoff:     role-banner 또는 첫 허용 action
retry/return:     이전 focus key 복원
```

The evidence drawer has an explicit in-drawer close button
(`data-action="toggle-evidence" data-focus-key="drawer-close"`). The opener
carries `aria-expanded` / `aria-controls="evidence-drawer"`; the drawer is
`role="dialog"` with `aria-labelledby`. `Escape` closes the drawer and returns
focus to the opener. Drawer buttons are included in the roving-focus collection.

## Trust and authority boundaries

Text labels used: `AI-ASSISTED STEP`, `HUMAN ACTION`, `SOURCE EVIDENCE`,
`MISSING EVIDENCE`, `CONFLICTING EVIDENCE`, `DRAFT RESULT`, `REVIEW CORRECTION`,
`NOT YET APPROVED`, `HUMAN-APPROVED`, `VERIFIED ORGANIZATIONAL AI SKILL`.

Safety invariants enforced by the machine:

- AI cannot approve; only the human reviewer actor (`actor: 'reviewer'`) can.
- Missing evidence is never auto-estimated.
- The lowest price is never automatically declared best (conflict requires a
  human decision payload).
- A skill cannot be saved before human approval (`save-skill` from
  `approval-pending` returns `validation-error`).
- Unresolved exceptions are retained on the final skill card.
- The memo never claims to be a real purchase recommendation.

## Browser memory only

State lives in the JS process memory and the DOM. No localStorage, sessionStorage,
fetch, network, persistence, or external runtime asset. The UI shows a
"저장되지 않음" note until the skill is saved.

## Run locally

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

Open `http://127.0.0.1:8000/` from this workspace. Keyboard: arrows move focus,
Enter/Space activates. `prefers-reduced-motion` is honored.

Demo scenarios in the app bar: `기본 업무`, `빈 업무대`, `오류 시뮬레이션`.

## Tests (repository-local, no browser)

```bash
bash tests/run_tests.sh
```

Coverage: state-transition contract, 15-step journey, missing-evidence journey,
conflicting-evidence journey, stop/resume, review correction/re-run, pre-approval
save block, approved skill save, exception retention, template↔machine
consistency, keyboard contract, required labels, external runtime dependency 0,
scope check, JavaScript syntax, `git diff --check`.

## Visual baseline

This workspace copies the approved Phase 1 repository-local SVG assets
(`assets/images/*`) without modifying the Phase 1 workspace or PR #251. Typography,
color tokens, evidence clips, exception flags, review marks, and the skill-version
stamp follow the accepted Phase 1 system.
