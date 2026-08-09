# Business 29 Phase 2 UX — meeting-to-public-notice governance ledger

합성 frontend UX execution contract 구현 (Issue #351).

## What this is

A synthetic, deterministic meeting-to-public-notice **governance ledger** (주민총회 원장) for
**솔빛마루 2단지 / Solbit Maru 2** (420 households, fictional). It implements the Issue #351
24-state contract, the quorum semantics from #351 comment (QUORUM_STATE_SEMANTICS_CORRECTION),
the private/redacted/public disclosure model, six synthetic roles, and the meeting-to-public-notice
flow with manual review gates.

**No real data, no backend, no database, no authentication, no real voting, no legal judgement.**

## Files

```text
index.html                 — semantic HTML (Phase 1 ledger grammar preserved)
styles/main.css            — Phase 1 visual system (charcoal/forest/brick/brass) + state/UX contract styles
scripts/fixture.js         — synthetic fixture (mirrors data/fixture.json)
scripts/state-machine.js   — pure deterministic state machine (UMD, Node-testable)
scripts/app.js             — role switcher + state rendering controller
data/fixture.json          — canonical synthetic fixture (JSON)
tests/state-machine.test.js— repo-local Node test suite (19 checks, no browser)
evidence/self-check.json   — recorded self-check results
```

## Run the test suite

```bash
node reference/business-29-apartment-governance-ux/tests/state-machine.test.js
```

## State model (24 states)

```text
empty, draft, agenda-ready, notice-review, notice-published,
attendance-open, quorum-incomplete, quorum-recorded, discussion-open,
dissent-recorded, resolution-draft, resolution-review, resolution-approved,
action-pending, action-overdue, disclosure-review, redaction-required,
public-notice-ready, public-notice-published, version-history,
system-error, retry, cancelled, completed
```

## Quorum semantics (per #351 correction comment)

- `quorum-recorded` requires the 대표회의 관리자's manual confirm of attendance vs the synthetic rule threshold.
- `quorum-incomplete` blocks `discussion-open` and `resolution-*`; only postpone/reschedule notice (→ `cancelled`) or
  attendance supplement (→ `attendance-open`) are allowed. No legal validity judgement.
- Recheck path: `quorum-incomplete → attendance-open (supplemented) → manual recheck → quorum-recorded | quorum-incomplete`.

## Disclosure model

Default is `private`. A `private` object never renders on the public surface.
`redacted` copies are created only through the `redaction-required` flow and confirmed by a human.
`public` is reachable only through the `disclosure-review` manual gate and the final `public-notice-ready` review.

## Roles

대표회의 관리자 · 동대표·위원 · 관리사무소 · 감사 · 일반 주민 · 외부 검토자
Role switching is synthetic; disallowed controls are disabled with an explanation.

## Boundary

No backend, database, authentication, persistent storage, upload, OCR, live AI, external API,
analytics, billing, real electronic voting, contract execution, payment, or legal judgement.
No external runtime resources. Browser verification is deferred; validation is repo-local only.
