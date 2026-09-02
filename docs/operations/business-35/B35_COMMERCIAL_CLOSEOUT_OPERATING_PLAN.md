# B35 V3.1 Commercial Closeout Operating Plan

## 1. Objective

Bring Business 35 from the current merged V3.1 product authority to a reusable, internally accepted customer package without restarting product development.

The program closes four gaps:

```text
PRODUCT AUTHORITY GAP
→ commercial documents aligned to V3.1

GENERATION GAP
→ current source deterministically produces current artifacts

VERIFICATION GAP
→ machine + pixel QA prove the exact package

COMMERCIAL HANDOFF GAP
→ reusable master is ready while customer-specific fields remain explicit
```

## 2. Current product authority

```text
PRODUCT = 파디엠 AI 미디어 업무전환 스튜디오
MERGED_PRODUCT_PR = #370
MERGED_PRODUCT_COMMIT = 05932da3af774220372f0e9f3716b07cd83511f9
PRODUCT_CONTRACT = reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md
```

Current product promise:

> AI 교육을 듣는 데서 끝내지 않고, 팀의 실제 미디어 업무 한 흐름을 사람이 승인하는 운영체계로 바꾼다.

Current primary journey:

```text
현재 미디어 업무 병목 이해
→ 조직·결과물·병목·팀 규모·AI 사용 상태 입력
→ 조직별 진단 + 새 업무 흐름 + 추천 파일럿
→ 운영체계 산출물 이해
→ 진단 워크숍 또는 6주 파일럿 범위 판단
→ 자기 조직용 전환 요약으로 상담 준비
```

## 3. Existing assets to preserve selectively

### Draft PR #355 — commercial-source lineage

Useful material includes:

- product authority bridge and README;
- one-page offer;
- ten-page proposal source;
- diagnostic questionnaire;
- six-week pilot plan;
- statement of work draft;
- risk/data annex;
- KPI framework;
- customer qualification scorecard;
- source validators.

### Draft PR #359 — generated customer-package lineage

Useful material includes:

- Master Proposal PPTX/PDF;
- One Page Offer source/PDF;
- Diagnostic Questionnaire DOCX/PDF;
- Pilot Quote Template XLSX;
- Customer Meeting Script;
- Follow-up Email Templates;
- generation scripts;
- source mapping;
- render evidence;
- visual/structural validators.

The existing generated binaries are historical pre-V3.1 evidence. They are not current send-ready artifacts.

## 4. Execution sequence

### W0 — Authority lock

Issue #1502.

Create the exact gap matrix. No downstream model may widen its own scope beyond this lock.

### Parallel Wave — three same-model lanes

#### Lane A — Commercial source

Issue #1503.

Reconcile all customer-facing source copy to the merged V3.1 journey and terminology.

#### Lane B — Builder and regeneration

Issue #1504.

Recover and reconcile the #359 generation pipeline. It may prepare build infrastructure in parallel, but final binaries must consume the accepted Lane A source revision.

#### Lane C — Independent QA harness

Issue #1505.

Prepare and execute machine-checkable structural, formula, source-mapping, privacy-boundary and revision-trace validation. Final PASS occurs only against the exact regenerated package.

### W4 — Pixel and comprehension gate

Issue #1507.

Review every customer-facing page/sheet for visual hierarchy, Korean fit, table readability, brand continuity and customer comprehension.

### W5 — Final closeout

Issue #1508.

Record exact revisions, output hashes, QA verdicts and the remaining customer-specific fields. Declare the reusable master package either not ready or conditionally ready.

## 5. Path ownership

W0 establishes exact paths. Default intent is:

```text
Lane A
→ current closeout commercial-source markdown only

Lane B
→ customer-package generation/build scripts, generated artifacts and generation manifest

Lane C
→ independent validation scripts, evidence and verification reports
```

No lane may mutate the merged B35 V3.1 product source unless a blocking defect is proven and explicitly re-scoped.

## 6. Parallel collision rule

- one file path has one owning lane;
- cross-lane changes require a new explicit handoff, not silent edits;
- final artifacts depend on accepted Lane A source;
- final QA depends on exact Lane B outputs;
- Lane C cannot rewrite commercial copy merely to make a validator pass;
- if a validator exposes a source defect, return it to Lane A;
- if pixel QA exposes a generator/layout defect, return it to Lane B.

## 7. Commercial truth boundary

The reusable master package may contain clearly identified price hypotheses and customizable provider/customer fields.

It may not claim:

- confirmed market pricing when not validated;
- a real customer or case study when none exists;
- revenue or contract evidence that does not exist;
- completed legal or contract review unless actually completed;
- a named-customer send authorization merely because the master package passed QA.

## 8. Definition of done

The program is complete only when all of the following are true:

```text
AUTHORITY_LOCKED = YES
COMMERCIAL_SOURCE_V3_1_ALIGNED = YES
PACKAGE_REGENERATED_FROM_ACCEPTED_SOURCE = YES
PACKAGE_INVENTORY_PASS = YES
SOURCE_MAPPING_PASS = YES
STRUCTURAL_QA_PASS = YES
FORMULA_QA_PASS = YES
TEXT_FIT_PASS = YES
PIXEL_VISUAL_QA_PASS = YES
MASTER_PACKAGE_STATUS = CONDITIONALLY_READY
CUSTOMER_SPECIFIC_GATES = EXPLICIT
OUTREACH_EXECUTED = NO
PRODUCTION_MUTATION = NO
```

A later named-customer send is a separate operating action.
