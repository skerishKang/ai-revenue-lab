<!-- B14_OWNER_ROLE_SOURCE_OF_TRUTH_20261010 -->
> **B14 역할 최신 원칙(2026-10-10):** [원제작사 모델·서빙 제공업체·변형 모델의 공식 사양 및 B14 실행 권한](../architecture/B14_MODEL_PROVIDER_EXECUTION_AUTHORITY_2026-10-10.md)을 우선 확인합니다. **B14는 정확히 사용자가 선택한 모델을 해당 업체의 공식 API로 실행**하며, temperature/토큰/리즈닝을 임의 지정하거나 옵션을 조용히 바꾸지 않습니다. 원본 모델의 공식 사양과 실제 API 제공업체의 계약은 별도 증빙합니다. 과거 코드·평가 수치는 이 원칙의 구현 증명이 아닙니다.
<!-- /B14_OWNER_ROLE_SOURCE_OF_TRUTH_20261010 -->

<!-- B14_OFFICIAL_PARAMETER_AUDIT_20261010 -->
> **2026-10-10 최신 해석:** [B14 공식 파라미터·재시험 판단 감사](../models/final-evaluation/B14_OFFICIAL_PARAMETER_REVALIDATION_2026-10-10.md)를 먼저 확인하세요. 현재 canonical 등록은 **10모델/7제공자**입니다. 아래 '9개'는 2026-10-09 역사적 현황입니다. 기존 평가에서 사용한 temperature=0 및 공통 max_tokens는 공식 권장 설정으로 간주하지 않습니다. 공식 공급사 기본값/추론/출력 예산을 검증하는 별도 재시험과 B14 전달 검증 전에는 최종 성능 우열로 사용하지 않습니다. 모델 자동 선택, 대체 라우팅 또는 운영 배포를 승인하는 문서가 아닙니다.
<!-- /B14_OFFICIAL_PARAMETER_AUDIT_20261010 -->

# B14 중앙 모델 레지스트리 — 단일 원본 운영 계약

## 2026-10-11 #3790 Owner 운영 정정 — 등록 / 실행 가능 / 품질 평가 분리

- 중앙 원본은 `apps/korean-ai-platform/app/pilot/b14_models.json` 하나입니다. 2026-10-11 시점 현재 원본은 **12모델 / 9공급업체**입니다. 예전 9개·10개 수치는 역사적 기록입니다.
- **REGISTERED**: 모델·공급업체의 ID, 메타데이터, API 계약을 등록한 상태입니다. 모델별 B66/Claw 실호출 또는 견적 성능 비교가 등록의 선행 조건이 아닙니다.
- **ENABLED**: JSON `enabled` 불리언으로 개별 모델/공급업체 실행 허용 여부를 지정합니다. `false`는 등록 데이터를 유지하지만 실행을 막습니다. 비밀키 값이나 고객 기본 모델을 새로 생성하지 않습니다.
- **AVAILABLE**: B14 운영 모드·사용 권한·Owner 제외 모델·필수 chat capability·공급업체 바인딩/경로 준비 조건을 통과한 exact ID만 포함합니다. B66과 Claw는 **같은 B14 모델/제공자 준비 상태 GET**을 통해 이 집합을 구성하며 제품별 고정 모델 목록을 관리하지 않습니다.
- **QUALITY_EVALUATED**: 모델이 특정 견적/코딩/일반 대화 과제를 얼마나 잘 처리하는지 별도 실행 시 평가합니다. BEST/BAD 등의 미래 품질 메타데이터는 사용 가능 여부 및 등록 상태와 다릅니다. 아무 점수도 자동 계산하거나 자동 라우팅에 사용하지 않습니다.
- 모델 추가 → B14 source+경량 계약 테스트 → 준비 상태에 따라 목록 반영이 기본 흐름입니다. 제품별 신규 모델 실호출, B66 견적 PDF E2E, Claw 업무 E2E, 장기 안정성 시험은 **해당 작업을 실제로 검증할 때만 별도 수행**합니다.
- 선택은 사용자별 **exact `model_id`** 한 개로 유지합니다. 로그인·권한·사용량·Engine/B14 실행 게이트는 유지하고, 실행 불가 모델 거절 / 미선택 거절 / 자동 fallback 금지 정책도 유지합니다. Plus/Pro/Max 등급은 모델 등록과 별개의 제품 기능이며 B66 견적 UI에는 적용하지 않습니다.



> **OWNER CORRECTION 2026-10-10:** `experiential/qwen3.8-flash-next-uncensored` is the tenth canonical B14 model (seven providers).
> The Owner authorizes manually selected live evaluation during the ExLab free promotion. Data retention is not an Owner-imposed blocker.
> Do not reintroduce `model_data_policy_pending` or the last-egress privacy refusal.
> The existing Secret Store binding name is `PADIEM_EXLAB_API_KEY`; a successful credential-backed completion still requires measurement.
> Auto selection, silent fallback and tier/default mutation remain unapproved. Old B.AI Qwen and ExLab Luna stay excluded.


기준일: 2026-10-08. 실 모델 및 제공자 등록 원본은 apps/korean-ai-platform/app/pilot/b14_models.json 하나입니다.
기존 공급자별 Python 등록 함수나 제품별 복제된 목록은 모델 관리의 권위가 아닙니다.

## JSON 계약
- providers: HTTPS API origin/허용 host/Secret Binding 이름. API 키 값은 절대 저장하지 않습니다.
- models: exact 모델 ID, upstream ID, 제공자, 표시 이름, capability, 가격 출처. 추가/삭제는 이 배열 항목만 변경합니다.
- groups: plus/pro/max에 노출할 exact 모델 ID 배열. 소속은 Owner 결정 전까지 비워 두며 임의 배정하지 않습니다.
- 신규 OpenAI 호환 제공자는 providers 설정으로 추가합니다. 기존 프로토콜과 다른 경우만 어댑터 검토가 필요합니다.
- 모델과 제공자 삭제 시 고아 group 참조가 있으면 검증이 실패합니다.
- JSON 유효성은 B14 시작 시 검증하며 오류 시 실행을 차단합니다. 과거 Python 목록으로 자동 복구하지 않습니다.
- 변경은 테스트/리뷰/승인/배포가 필요한 소스 변경입니다. Hot reload는 하지 않습니다.
- 제공자 Secret 존재, 실제 실행 준비, Production 배포는 등록 여부와 분리합니다.

## 2026-10-08 명시적 삭제
기존 등록 14개 가운데 다음 5개를 실 카탈로그/실행 경로에서 제거합니다.
b-ai/qwen3.8-flash
experiential/gpt-5.6-luna
infron/motif/motif-3
kilo/nvidia-nemotron-3-ultra-550b-a55b-free
kilo/poolside-laguna-s-2.1-free

남은 등록 9개. 직접 제공자 poolside/laguna-s-2.1은 별개로 유지합니다.
이전 파일의 역사적 모델 상수/문서/검증 fixture는 모델 등록이나 실행 권한을 의미하지 않습니다.

## 소비자 및 검증
GET /api/pilot/models의 registered_routes/catalog/model_groups는 중앙 JSON에서 나옵니다.
B66/Claw/Engine은 별도 모델 등록부를 만들지 않습니다. 단 B66의 수동 선택 UI/API 연결은 후속 작업입니다.
B14 고정 auto 및 구버전 제품 HOLD는 사용자 지정 모델이 아닙니다. 임의 선택, 재시도, 유료 모델 무단 전환 금지.
테스트: cd apps/korean-ai-platform && uv run python -m pytest tests/test_b14_model_registry_file.py tests/test_registered_routes_truth.py -q
기존 Owner 승인·유료·배포 정책은 여전히 MODEL_CHANGE_OWNER_APPROVAL_POLICY.md 및 B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md가 관할합니다.

## 2026-10-08 migration follow-up
- All ten legacy register_*_provider Python functions now fail closed (RuntimeError); adding a provider/model must edit the JSON, not invoke a legacy function.
- app/pilot/__init__.py no longer registers Poolside on import. KILO_FREE_ROUTES has no executable entries. Historical model ID constants may remain for retirement audits; they do not create routes.
- PR #3819 is MERGED. The earlier Windows 875-pass/81-fail/38-error statement was an intermediate historical snapshot, not current CI truth. Merge does not attest real API access, valid credentials, tier assignments or production activation.

## 2026-10-09 exact Owner-registry evaluation contract

- Detailed workflow/rubric: docs/operations/B14_B66_QUOTE_MODEL_EVALUATION_PROTOCOL.md. No live current-catalog bulk benchmark is authorized by a source-only preflight.
- Canonical registered candidates: only enabled exact IDs from apps/korean-ai-platform/app/pilot/b14_models.json. Historical 2026-10-09 count: nine. Current count is determined only from the canonical JSON (10 as of 2026-10-10). .github/scripts/b14_owner_evaluation_registry.py verifies this before model assessment; provider discovery is NOT registration.
- Direct Poolside Laguna S 2.1 is poolside/laguna-s-2.1 using https://inference.poolside.ai/v1 and the PADIEM_POOLSIDE_API_KEY binding NAME. All Kilo Laguna aliases remain Owner-excluded.
- Other excluded identities: B.AI Qwen, Motif 3, GPT-5.6 Luna, NVIDIA Nemotron. Historic five-model comparative fixture aliases are not authorization. The old live workflow is registry-gated, with the deleted models and all-five selector excluded.
- StepFun #3835 is Draft and does not extend the current-main registered roster. Nor does API availability, a synthetic test or an empty credential binding establish live provider readiness.
- Evaluate B66 repeat use on Korean request-to-QuoteDraft data extraction (recipient, item names, quantities, unit price and omissions), NOT on repeated re-creation of the HTML/PDF. QuoteCore calculates; the certified template renderer deterministically prints. No hidden paid/Auto/fallback inference.

## 2026-10-09 browser/B62 integration regression contract

- B14 app/pilot/workspace.py Start-screen manual model dropdown and its JavaScript b14CatalogModels used nine CATALOG_BY_ID entries at the 2026-10-09 test baseline, installed from canonical b14_models.json, NOT historical empty CATALOG_MODELS.
- The standalone Alpha UI still has a legacy b14/auto option. This task does not authorize that option as a new Plus/Pro/Max group, nor does it implement a B66 manual selector. Group membership remains Owner-only.
- The Alpha browser smoke test selects approved agnes-ai/agnes-3.0-flash and supplies a dummy credential ONLY to the mock child process; no real API calls.
- B62 source authority verified nine registered model IDs at the 2026-10-09 baseline and five completely unregistered Owner-deleted IDs; no public/free/auto route is authorized for B66.
- B62 retry-budget fixture copies the schema of a surviving Agnes model in an isolated child with mocked provider dispatch and test-only key; the max_retries=0 execution guard still ensures exactly one provider attempt.
- Verification: focused B62 21 passed, local B14 full 995 passed, desktop Alpha browser 28 passed, mobile Alpha browser 6 passed. Exact-head Linux CI and independent approval remain mandatory prior to Ready/merge.
