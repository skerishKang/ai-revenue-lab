# Business 29 Phase 2 UX — meeting-to-public-notice governance ledger

## Authority and provenance

- HISTORICAL_PROVENANCE: Issue #351 / PR #352
  (PR head `8e610bd040c6d48ba17fe087fd917be026c35cb2`).
  PR #352 is CLOSED and unmerged; its artifacts are historical UX evidence
  only, never merge authority.
- CURRENT AUTHORITY: Issue #2471 / Draft PR #2476, reconciled onto current
  main (`e227f8cde3a97eaaeed3498261e73b009f72c456`).
- Current workspace: `reference/business-29-apartment-governance-v1/ux`.
- Allowed scope: this `ux/**` tree plus `guide.html` only. Phase 1 canonical
  root is byte-unchanged.

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
tests/state-machine.test.js— repo-local Node test suite (34 checks; provenance in Current validation below)
evidence/self-check.json   — recorded self-check results
```

## Run the test suite

```bash
node reference/business-29-apartment-governance-v1/ux/tests/state-machine.test.js
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
- Direct `quorum-incomplete → quorum-recorded` is forbidden.

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
No external runtime resources. The historical PR #352 evidence (recorded 2026-08-01)
deferred browser verification; that deferral applies to the historical record only.
Current #2471 validation performed desktop + mobile browser QA — see Current validation below.

## Current validation (Issue #2471 / Draft PR #2476)

- Current main base: `e227f8cde3a97eaaeed3498261e73b009f72c456`
- Correction parent head: `ced37e29536c9e680cb6095e29c8eed1fa1cd672`
- Validated at: `2026-09-12`
- Focused suite: **34/34 PASS**
  (`node reference/business-29-apartment-governance-v1/ux/tests/state-machine.test.js`)
- `node --check` across all UX JS: clean. `git diff --check`: clean.
- Browser QA: desktop `1440x1100` = PASS, mobile `390x844` = PASS,
  console errors = 0, page errors = 0, external runtime requests = 0.
- Full machine-readable record: `evidence/self-check.json` (`current_authority` block).
  The `historical_provenance` block in that file preserves the PR #352 record
  (Issue #351 / PR #352, recorded 2026-08-01, browser verification deferred)
  so the two runs are never confused.
