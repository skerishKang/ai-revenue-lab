# B66 · Padiem Quote

```text
DOC_STATUS = CANONICAL_PRODUCT_ENTRYPOINT
OWNER = B66 product
PRODUCT_EPIC = #3180
SOURCE_ANALYSIS_AUTHORITY = #3542
REPRODUCTION_CERTIFICATION_AUTHORITY = #3595
SOURCE_FORMAT_POLICY = #3586
```

B66 is Padiem's standalone quotation product for businesses that already have quotation formats they use repeatedly.

The user-facing reusable concept is **내 견적서 / Saved Quote Skill**. Internal template/profile/compiler terminology is not the primary user concept.

## 신규 고객 원본 보존·편집형 출력 장기 정책 — #4106 (현재 CGI와 분리)

> **[공식 정책 문서: SOURCE_PRESERVING_EDITABLE_OUTPUT_ROADMAP.md](SOURCE_PRESERVING_EDITABLE_OUTPUT_ROADMAP.md)** · [오픈 이슈 #4106](https://github.com/skerishKang/ai-revenue-lab/issues/4106)

**앞으로의 다른 고객 견적서**는 PDF/이미지 원본 재현, XLSX 원본 패키지 유지, 추후 HWPX 원본 구조 보존을 **형식별로 다르게** 처리한다. 최종 출력은 인증된 **PDF + 편집 가능한 원본 계열 XLSX/HWPX** 제공을 목표로 하지만 현재 모든 파일 형식을 지원한다는 뜻은 아니다. **QuoteCore 금액 정확성은 필수**, 양식의 비핵심 시각 차이는 고객/Owner가 명시적으로 승인한 허용 오차만 인정한다. 최초 원본 분석/인증은 한 번, 반복 견적은 경량·결정적으로 실행한다.

**형식 제한은 여전히 [#3586](https://github.com/skerishKang/ai-revenue-lab/issues/3586) 기준**(XLSX 현재 등록 사전검증 허용, HWPX 추후, 구형 XLS/HWP 거부). PDF/이미지 사실 추출 ≠ 자동 인증되는 재사용 템플릿. 이전 XLSX 출력 [#3496](https://github.com/skerishKang/ai-revenue-lab/issues/3496) 및 원본 재현 [#3595](https://github.com/skerishKang/ai-revenue-lab/issues/3595), 연기된 대형 컴파일러 [#3708](https://github.com/skerishKang/ai-revenue-lab/issues/3708)을 중복 개발하지 않는다. **현재 김범신 대표 CGI의 유일한 PDF 템플릿은 아래의 기존 Sol 6.1**이며 이번 P1 정책을 이유로 첫 고객 인수 #4076을 지연하거나 CGI PDF를 다른 렌더러로 교체하지 않는다.

## CGI 첫 고객 최종 MVP 상태 — 2026-10-10 KST

> **최신 운영·인수 기준:** [CGI_FIRST_CUSTOMER_MVP_CHECKPOINT_2026-10-10.md](CGI_FIRST_CUSTOMER_MVP_CHECKPOINT_2026-10-10.md) · 인수 이슈 [#4076](https://github.com/skerishKang/ai-revenue-lab/issues/4076) **OPEN**. 기존 한정 범위 MVP [#3521](https://github.com/skerishKang/ai-revenue-lab/issues/3521) **CLOSED**와 구분한다.

- **B66 Pages Production 배포 완료:** 승인된 단일 수동 [Actions #38006616259](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38006616259) **SUCCESS**. 정확한 배포 SHA `52b05ae4623fb211c32d31fe286d8e483803330f`; 기존 `https://quick-quote-kr.pages.dev/` 및 버전 URL `https://6c937f60.quick-quote-kr.pages.dev/` 정상 응답, 배포 후 계약 검사 성공.
- **OAuth 프록시 코드 수정 포함:** [PR #4073](https://github.com/skerishKang/ai-revenue-lab/pull/4073) **MERGED**; [중복 Draft #4074](https://github.com/skerishKang/ai-revenue-lab/pull/4074)는 원인 분석 기록을 보존한 채 **CLOSED/UNMERGED**. *B66 계정의 Google 로그인은 아직 NOT_TESTED* (LOCAL3 #3871 담당); 이번 운영 검증의 B66 계정 로그인은 비밀번호 방식이고 Google Drive 동의/연결은 별도 성공 보고.
- **LOCAL2 CGI 고객 여정 통합 테스트 완료 (오프라인):** [PR #4088](https://github.com/skerishKang/ai-revenue-lab/pull/4088) **MERGED**, exact-head CI 9 SUCCESS / 16 SKIPPED. Chromium에서 승인 스킬·수동 모델 선택·자연어 완성/누락 단가 질문·Guided 0모델 호출·QuoteCore·PDF POST·이력 API 클라이언트 흐름 PASS. 하지만 **모델은 스텁, PDF는 가짜 테스트 응답, D1/타계정은 스텁 JSON**이므로 실제 Production/인증 Sol 출력·D1 저장 및 서버 접근 통과로 계산하지 않는다. 증거 캡처 7장 중 6·7번은 파일 해시가 동일해 다른 계정의 시각 증거로 불인정한다. [검증 등급](CGI_FIRST_CUSTOMER_MVP_CHECKPOINT_2026-10-10.md), [#4076](https://github.com/skerishKang/ai-revenue-lab/issues/4076) 참고.
- **Sol CGI PDF:** 1~3품목은 기존 인증 범위, 4+품목은 **LOCAL1 #3839 미완료/시각 승인 HOLD**. 기존 Sol 6.1 구현을 확장·재인증해야 하며 대체 PDF 렌더러는 금지.
- **고객 전체 여정:** LOCAL2 #4076이 Guided/Free-form/누락 단가 후속질문/QuoteCore/실제 PDF/D1 저장·재열기를 검증 중이며 **전체 고객 인수는 NOT_READY**. LOCAL3는 Google Drive **연결·기존 초안 취소 처리 분기(임시 `confirm(false)`)·네이티브 승인·QuoteCore 재계산·파일 쌍·로그아웃 및 다른 계정 UI 세션 분리**를 새 Production에서 PASS로 보고했다. **B66 계정 Google 로그인, 네이티브 취소 클릭, 서버 타 계정 직접 접근 차단, 다른 브라우저·폰·late-callback은 미검증**이다.
- **추론 수준:** B66 [#3998](https://github.com/skerishKang/ai-revenue-lab/pull/3998)와 공유 Core [#4069](https://github.com/skerishKang/ai-revenue-lab/pull/4069) **MERGED**. 모델별 실제 공급자 wire 검증·기본값 제거·고객 활성화는 **#3906/#3977/#3988에서 OPEN**; 이것이 Sol PDF 인증 완료를 뜻하지 않는다.

**릴리스 판단:** `CODE_MERGED` ≠ `PRODUCTION_DEPLOYED` ≠ `LIVE_E2E_ACCEPTED` ≠ `SOL_V2_CERTIFIED`. 승인되지 않은 4+품목 CGI PDF를 HTML/GLM/다른 형식으로 우회하거나 전체 MVP 완료라고 표시하지 않는다.

## Owner-locked CGI rendering decision — 2026-10-09

**For the current Kim Beom-shin CGI quotation, the existing Sol 6.1 source-derived CGI template is the ONE AND ONLY layout and PDF output implementation.** Do not select, re-create, substitute, or silently fall back to another template for any item count.

- **Use the Sol implementation for all CGI quotations.** The GLM 5.3 package is historical comparison evidence only; it is **NOT a product template**. HTML/browser-print PDF and model-generated HTML/PDF are **NOT replacements or fallbacks** for the Sol CGI final document.
- **If an item, row, page, field, label or layout element must be added, modified or deleted, extend the SAME Sol implementation**. Reuse its layout, fonts, logo, stamp, margins and field semantics. Do not build a competing "four-plus rows" template or renderer.
- **Three rows are an existing certification boundary, not a template-selection rule.** Existing Sol scope is verified only for 1–3 line items. Issue [#3839](https://github.com/skerishKang/ai-revenue-lab/issues/3839) must extend this very same Sol template to dynamically repeat rows and paginate. Above the currently supported limit, do **not** substitute a different renderer; implement, test and re-certify the Sol modification before declaring ready.
- **QuoteCore** remains the single money authority; a customer-selected B14 model may extract free-form inputs only. There are **zero model calls for routine PDF rendering**.
- A browser HTML preview can remain a UI but is **not an independent PDF authority**. Offline HTML-print test evidence is not evidence of Sol CGI product PDF success. All CGI PDF evaluation (including F6 in [#3867](https://github.com/skerishKang/ai-revenue-lab/pull/3867)) must identify the Sol renderer and actual template version.
- The user-approved [public CGI source library](../../../reference/b66-public-standard-templates/cgi/v1/README.md) versions the Sol implementation and keeps GLM as comparator only. Git publication alone does not prove Production deployment or certify new row counts.

```text
CGI_PDF_TEMPLATE=EXISTING_SOL_6_1_ONLY
ALTERNATE_TEMPLATE_SELECTION=FORBIDDEN
GLM_CUSTOMER_RENDER=FORBIDDEN
HTML_PRINT_PDF_FALLBACK=FORBIDDEN
ITEM_ROWS_GT_3=EXTEND_AND_RECERTIFY_SAME_SOL_TEMPLATE
TEMPLATE_CHANGES=MODIFY_ADD_DELETE_ON_SOL_ONLY
QUOTECORE_MONEY_AUTHORITY=YES
PER_PDF_RENDER_MODEL_CALLS=0
LIVE_4PLUS_ROW_PROOF=NOT_YET_ESTABLISHED
```

This is the owner lock for the **current CGI product rendering implementation**. Customer source custody (#3884) and D1 quote history (#3405) are separate concerns, not permission to select a different CGI output template.

## 최신 이슈·PR·담당 작업 현황 (2026-10-10)

- [CGI_FIRST_CUSTOMER_MVP_CHECKPOINT_2026-10-10.md](CGI_FIRST_CUSTOMER_MVP_CHECKPOINT_2026-10-10.md): 최신 승인된 B66 Pages Production SHA·실배포/사후검증 증거·LOCAL1/2/3 담당·CGI 고객 인수 PASS/NOT_TESTED 기준과 남은 Blocker.
- [ACTIVE_ISSUES_2026-10-10.md](ACTIVE_ISSUES_2026-10-10.md): B66 원본 양식·견적의 활성 이슈, 로컬 담당, 소스 병합과 실서비스 수용 차이, #3542 Sol 6.1 임시 담당 및 #3839 네이티브 다중 페이지 병목, #3884·#3871·#3906 후속 조건을 중앙에서 정리한 **시점별 현황표**.
- 이 문서는 상태 **인덱스**다. 확정된 Owner 정책과 기술 수용 기준은 아래의 원래 B66 README, [SOURCE_TEMPLATE_FIDELITY.md](SOURCE_TEMPLATE_FIDELITY.md), 그리고 각 GitHub 이슈가 우선한다.

## Canonical product flow

```text
existing quotation
-> source analysis
-> Canonical Quote Template candidate
-> reference reproduction
-> certification
-> approved Saved Quote Skill
-> repeat quote execution with new facts
```

Routine repeat use must be fast and deterministic. The **approved Saved
Quote Skill** supplies the reusable structure; **new facts** provide only this
customer's changed quotation values:

```text
approved Saved Quote Skill + new facts
-> QuoteDraft
-> QuoteCore
-> certified template renderer
-> Preview / PDF
```

QuoteCore remains the sole calculation authority. The renderer does not become a second money/tax/date calculation engine.

## Stage ownership — one canonical answer for Sol, B14 and final PDF

**These are different operations, not three interchangeable PDF-producing models.**
For B66, "AI is used in the quote workflow" does not mean "an AI makes the PDF."
The following is the product's **single stage/role truth**; downstream documents
link to it and must not define competing stage owners.

| Stage / trigger | Responsible component | Model call contract | Output |
|---|---|---|---|
| **A. Source onboarding / template engineering** — an existing quotation source is first analyzed, reproduced or materially reworked | A document-capable **development model** (Sol 6.1 was used for the CGI source-derived template) plus compiler and independent fidelity/certification gates | Sol is an **authoring/engineering tool at this stage**, not a customer repeat-generation route, required B14 default or hard-coded production dependency. Any future development-model decision follows its authorized owner/tooling context. | Versioned **certified template / Saved Quote Skill** |
| **B1. Repeat quote from natural language** — a customer describes new recipient, items, quantities, prices or corrections | Exactly **one customer-selected B14 registered, Owner-allowed and runtime-ready model** performs **field extraction only**; user confirms missing/ambiguous facts | **At most one authorized interpretation dispatch; zero retry, auto-pick or fallback.** Optional visible/editable default follows the Owner model policy. A model does **not** construct HTML/PDF, decide the template, or compute money. | Structured customer quote facts / QuoteDraft |
| **B2. Repeat quote from complete structured inputs** — the customer directly enters all required facts | Deterministic input validation / QuoteDraft construction | **Zero inference/model calls.** Do not require Sol or B14 when interpretation is unnecessary. | Structured customer quote facts / QuoteDraft |
| **C. Amounts and tax** — facts are validated | **QuoteCore**, the sole business arithmetic authority | **Zero model calls.** No model-generated price, total, discount, tax or rounding. | Validated QuoteCore totals and render values |
| **D. Preview / final downloadable PDF / repeat or reopen** — use an approved Saved Quote Skill | **Certified deterministic renderer/converter**, using the already certified template and QuoteCore values | **Zero model calls to Sol, B14 or any other provider for rendering.** No per-quote source reanalysis, layout reconstruction, certification or paid route. | HTML preview and/or final PDF, with identical rows and totals |

### Unambiguous request paths

```text
ONBOARD_ONCE:
  original source -> Sol-assisted source analysis / initial implementation
  -> independent template reproduction + certification -> approved Saved Quote Skill

CUSTOMER_FREEFORM_REPEAT:
  customer text -> ONE explicitly selected, allowed B14 interpreter (facts only)
  -> QuoteDraft -> QuoteCore -> approved Saved Quote Skill
  -> deterministic renderer -> preview / downloaded PDF

CUSTOMER_STRUCTURED_REPEAT:
  customer-entered fields -> QuoteDraft -> QuoteCore
  -> approved Saved Quote Skill -> deterministic renderer -> preview / downloaded PDF

REPEAT_PDF_RENDER_PROVIDER_CALLS=0
REPEAT_PDF_RENDER_SOL_CALLS=0
REPEAT_PDF_RENDER_B14_CALLS=0
QUOTE_FACT_INTERPRETATION_B14_CALLS=0_OR_1_IF_REQUESTED
QUOTECORE_MODEL_CALLS=0
```

**Interpretation is not rendering:** if someone says "the customer uses another
B14 model to make a PDF," the exact technical meaning is **B14 optionally
interprets that customer's new free-form facts; the certified code renders the
PDF**. B14 inference must not replace the certified renderer, and Sol must not
be called per quote. A multi-page/overflow change (e.g. #3839) modifies
template engineering and certified rendering, **not** the runtime model route.
Its new geometry/page behavior must pass independent certification before
customer use; new PDF pages must not be AI-generated at request time.

**Authority split:** B14 model identity/allowed status, runtime readiness and
per-request user choice are governed only by
[Owner model policy §0A](../../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md)
and the live B14 registry; source fidelity, certification and render correctness
are governed by [SOURCE_TEMPLATE_FIDELITY.md](SOURCE_TEMPLATE_FIDELITY.md).
[The quote-model evaluation protocol](../../operations/B14_B66_QUOTE_MODEL_EVALUATION_PROTOCOL.md)
grades **extracted quote fields**, not AI-generated PDF quality. Neither the
development model's identity nor its earlier success authorizes model activation,
hidden fallback, PDF production release or skipped visual/customer E2E gates.

## Current authority map

| Area | Current authority | Status meaning |
|---|---|---|
| Product / Saved Quote Skill | #3180 | overall product epic |
| Source analysis | #3542 | source facts -> ANALYZED candidate |
| Reproduction / certification / compiler generalization | #3595 | source certification/generalization proven (including a second unrelated template); parent issue #3595 remains OPEN for tracking disposition |
| Template registration source formats | #3586 | XLSX now; HWPX future; legacy XLS/HWP rejected |
| Quote shell / single composer UX | #3536 | product UX |
| **Quotation storage / customer-owned Drive** | [QUOTE_STORAGE_STRATEGY.md](QUOTE_STORAGE_STRATEGY.md), #3405, #3871 | **기존 D1 이력 불변.** Google Drive JSON/PDF #4007/#4029 및 OAuth 콜백 #4073 모두 MERGED·[Production #38006616259](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38006616259) 배포 SUCCESS. LOCAL3 새 운영 브라우저에서 **B66 비밀번호 로그인/승인 CGI 스킬, Drive 연결·재연결, 내용 있는 초안의 취소 처리 분기, 실제 대화상자 승인·QuoteCore 재계산, 파일 쌍 존재/소유권, 로그아웃/다른 계정 세션 격리 PASS_REPORTED**. B66 계정의 Google 로그인, 네이티브 취소 클릭, 타계정 서버 읽기 차단, 서로 다른 브라우저·실기기·late callback·바이트 무결성은 NOT_TESTED, #3871 OPEN. |
| **Public standard template + private customer custody** | [TEMPLATE_CUSTODY_POLICY.md](TEMPLATE_CUSTODY_POLICY.md), [CGI public standard v1](../../../reference/b66-public-standard-templates/cgi/v1/README.md), #3883, #3884 | Owner-authorized CGI source / Sol renderer and GLM comparator tracked separately in Git; customer originals remain private in R2 (future full custody/return E2E). No automatic release. |
| Native XLSX output | #3496 | optional editable output; not PDF critical path |
| B66 quote-model decision authority | [Single model authority index](../../models/README.md), [Owner approval policy §0A](../../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md), #3760 | **Owner policy corrected and merged (#3796):** user selects one exact registered, allowed, ready B14 model per run; optional visible/replaceable default only if configured; no free/paid filter, backend automatic selection or fallback. Matching B66 UI/API implementation was merged via #3831; no claim of served Production readiness or accepted customer E2E follows from that merge. |

Historical renderer experiments are evidence, not current authority: #3545, #3574, #3578, #3581 and #3584.

## Shared platform and release rules

The quotation workflow, QuoteCore calculations and template certification remain B66-specific responsibilities. The common [architecture and ownership index](../../common/README.md) provides shared platform boundaries, and the [development lifecycle index](../../lifecycle/README.md) points to the repository-wide validation, approval and deployment contracts. Neither link changes the current customer readiness or permits a Production release.

## Model decision versus executable runtime

The **current Owner decision** is an authenticated user's one exact, registered, Owner-allowed and runtime-ready B14 model per quote interpretation. An optional default is only a visible editable preselection, never a hidden picker. An absent, invalid, excluded or unavailable `model_id` fails closed; no automatic free-first choice, ranking, retries or fallback. This stable contract is owned by the [canonical Owner policy](../../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md), not this B66 README.

**Status is split:** the Owner policy (#3796) and B14 single-JSON registry consolidation (#3819) are **MERGED**. B66 manual UI/API choice source is also MERGED (#3831). The older combined #3836 is **pre-merge integration test evidence only**, not a fresh current-main proof or a merge candidate. Model registration/configured credential and protected customer Production E2E remain separate acceptance gates. The current merged user-choice source replaces historical automatic free-first selection assumptions, but its actual Production availability and CGI customer handoff remain to be verified separately.

## Current CGI result

The CGI reference quotation has reached a certified template result inside its declared scope:

```text
CGI_REFERENCE_TEMPLATE = CERTIFIED
GENERIC_RUNTIME_RENDERER = YES
CGI_TEMPLATE_REUSABLE = YES
GENERIC_ANALYZER_COMPILER = PROVEN
SECOND_UNRELATED_TEMPLATE = CERTIFIED
SOURCE_PRODUCT_INTEGRATION = MERGED
PRODUCTION_GUIDED_BROWSER_PREVIEW_AND_PDF = PASS
PRODUCTION_COMPLETE_FREEFORM = HTTP_502_UPSTREAM_TIMEOUT
PRODUCTION_PARTIAL_FOLLOWUP = NOT_TESTED
CUSTOMER_READY = NO
```

The runtime renderer consumes compiled template data without CGI/customer literals, and the
generic analyzer/compiler no longer carries CGI-specific source/cell structure: a materially
different second quotation (landscape, left-aligned header block, gapped item columns,
`[소계]/[V.A.T]/[총계]` totals, no camera object, 80 vs 23 source merges) was compiled and
certified by the same generic code path with no document-specific cell/path literal
(`tools/b66_generic/`, with evidence under `tools/b66_generic/evidence/`). The authenticated
Saved Quote Skill -> QuoteCore -> certified PDF download path is source-integration validated.

The latest recorded authorized CGI Production browser E2E passed login, the assigned Saved
Quote Skill, Guided QuoteCore entry/calculation, certified preview and an actual downloaded
browser PDF. The first Complete Freeform interpretation instead returned HTTP 502 classified
as upstream_timeout on one POST, with no retry/fallback; Partial Freeform/follow-up was not
reached. The exact selected model and timeout origin were not proven. These are
run-specific Production observations, not proof that the current deployed revision passes
all customer scenarios. The full CGI customer handoff remains incomplete (CUSTOMER_READY=NO).
See #3751 and #3733 for the protected-run evidence and remaining acceptance gates.

The separate source certification/generalization evidence is PROVEN, but its parent
tracking issue #3595 is still OPEN; the proof result must not be confused with the
GitHub issue's closure state.

## Source formats: intake capability vs template-registration policy

Lower-level file intake/parser capability and B66 template registration are different contracts.

```text
GENERIC_INTAKE_CAPABILITY
!=
B66_TEMPLATE_REGISTRATION_ALLOWLIST
```

The current template-registration policy is:

```text
XLSX = ACCEPT
HWPX = FUTURE
XLS = REJECT
HWP = REJECT
```

PDF/DOCX/PPTX and images may still be accepted by other bounded intake/extraction paths where the product explicitly supports them. That does not automatically make them authoritative source formats for registering a reusable B66 quotation template.

## Preview / PDF / editable outputs

A certified fast PDF path is the critical repeat-generation path. Editable XLSX/Google Sheet output is optional and may be generated separately.

Do not insert Excel, Google Sheets, HanCell or another office engine into every PDF request merely because it can open the source format.

## Canonical documentation

- [TEMPLATE_CUSTODY_POLICY.md](TEMPLATE_CUSTODY_POLICY.md) — shared public standard-template library vs customer-private immutable source/template/quote data, D1 + R2 authority, customer download and encryption design, #3883/#3884.
- [QUOTE_STORAGE_STRATEGY.md](QUOTE_STORAGE_STRATEGY.md) — Owner-approved B66 storage decision: keep browser cache and current account-bound D1 quote history; add optional customer-owned Google Drive JSON+PDF save/reopen separately (#3871); do not change #3405, QuoteCore, the approved renderer, model selection or present billing rules.
- [GOOGLE_DRIVE_SAVE_OPEN.md](GOOGLE_DRIVE_SAVE_OPEN.md) — #3871 implementation contract: versioned editable quote JSON + certified PDF pair in the customer's own Google Drive, lossless QuoteDraft schema, explicit rejection policy, partial-failure reporting, and what is still NOT_TESTED (live OAuth, cross-browser, real phone).
- [GOOGLE_DRIVE_LIVE_VERIFICATION.md](GOOGLE_DRIVE_LIVE_VERIFICATION.md) — #3871 실제 검증 런북: 기존 OAuth/Pages 설정과 JSON+PDF save/reopen은 LOCAL3 부분 실측 보고가 있고, #4029 후속 Pages Production 배포까지 SUCCESS. 다만 새 Production에서 실제 승인·취소 처리 분기·QuoteCore 합계·UI 세션 격리까지 LOCAL3 보고 PASS; 네이티브 취소 클릭, 서로 다른 브라우저·실기기·서버 접근 격리는 여전히 NOT_TESTED. 소스 병합·배포·운영 수용을 혼동하지 않는다.
- [SOURCE_TEMPLATE_FIDELITY.md](SOURCE_TEMPLATE_FIDELITY.md) — source analysis, reproduction, certification, PDF/image fidelity implementation, current CGI architecture and development-model operating guidance.
- This README — product boundary, current authority map and current status.
- [Model decision and runtime evidence index](../../models/README.md) — unified entrypoint to the Owner policy, actual B14 catalog, product route declarations and deployment evidence. The canonical B66 Owner policy correction was **merged in PR #3796**; the B66 exact-model user-choice UI/API source is now [merged in PR #3831](https://github.com/skerishKang/ai-revenue-lab/pull/3831). That source merge does not prove the currently served deployment, model readiness or customer Freeform result. [#3819](https://github.com/skerishKang/ai-revenue-lab/pull/3819) has now **MERGED** the B14 JSON registry; [#3836](https://github.com/skerishKang/ai-revenue-lab/pull/3836) is earlier integration CI proof only and MUST NOT be merged as a substitute. No model/provider activation or customer E2E is claimed.

Implementation/demo references such as `reference/business-66-padiem-quote-v1/` remain useful source/evidence, but they are not the canonical B66 product-policy authority.
