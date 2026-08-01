# Business 32 · AI Skill Studio — Pilot UX Handoff Package

UX operations handoff for the validated Phase 2 UX (Issue #349 → PR #354). This
package prepares the validated frontend UX for a future pilot, backend
connection, and usability evaluation. It does **not** implement a backend,
analytics, or a real usability study.

## Validation authority

```text
Validated UX PR: #354 (OPEN / Draft / unmerged)
Validated exact head: 73ec4718d0835248ab20d56bc68f3956536112b4
Repository-local checks: 87 PASS
Browser validation: BUSINESS_32_BROWSER_VALIDATION_PASS
```

Browser validation PASS is recorded in PR #354 as a top-level comment
(`BUSINESS_32_BROWSER_VALIDATION_PASS` at the exact head above). See
`08-accessibility-responsive-evidence-index.md`.

## Protected boundary

The validated product code must not change:

```text
PR #354
feat/business-32-ai-skill-studio-ux
reference/business-32-ai-skill-studio-ux/**
validated exact head
```

Any product mutation would invalidate the browser validation and require
revalidation. This package only adds documentation under
`docs/product/business-32-ai-skill-studio/ux-handoff/**`.

## Contents

```text
README.md
01-demo-facilitator-script.md         — 10~12분 진행 대본
02-usability-test-plan.md             — 가상 참가자 기준·과업·측정 항목
03-state-role-action-matrix.md        — 24 state × role × action matrix
04-copy-and-trust-label-inventory.md  — 화면 문구와 신뢰 라벨 목록
05-backend-integration-ux-contract.md — UX 관점 backend 연결 계약
06-analytics-event-spec.md            — UX 측정 event spec (구현 아님)
07-pilot-acceptance-checklist.md      — 파일럿 시작 전 확인 목록
08-accessibility-responsive-evidence-index.md — 브라우저 검증 기록
09-known-limitations-and-non-goals.md — 제한사항과 비목표
tests/validate_ux_handoff.py          — 패키지 검증기
```

## Product reference

- Product: Business 32 · AI Skill Studio / AI 업무 실습실
- Visual direction: Operational Training Bench / 업무 실습대
- Synthetic fixture: Nori Works (fictional), 세 개의 합성 공급업체 견적서 비교 및
  구매 추천 메모 작성, 검토자: 합성 운영 책임자
- States: 24 (16 domain + 8 general)
- Roles: `operator` (업무 실행자), `reviewer` (합성 운영 책임자 · 사람 검토자)
- Final result: `VERIFIED ORGANIZATIONAL AI SKILL`

## Validation

```bash
python3 tests/validate_ux_handoff.py
```

The validator confirms required files, the 24-state matrix, role separation,
trust labels, browser head match, anti-optimistic-approval wording, PII
forbidden fields, absence of real customer/supplier names, absence of backend
implementation files, and that the validated product workspace is untouched.
