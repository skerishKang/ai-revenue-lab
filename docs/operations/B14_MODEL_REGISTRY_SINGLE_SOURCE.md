# B14 중앙 모델 레지스트리 — 단일 원본 운영 계약

> **CURRENT SOURCE AS OF 2026-10-10:** Owner-added ExLab
> `experiential/qwen3.8-flash-next-uncensored` is the tenth canonical B14
> model (seven providers), with existing `PADIEM_EXLAB_API_KEY` binding.
> Previous nine-model references below refer to historical benchmark cohorts,
> not the current registry. ExLab model is listed for manual selection but
> **live dispatch is explicitly blocked** until ExLab model data policy review
> and a separate release approval; no automatic fallback, customer activation,
> changed tiers or Production deployment. Old B.AI Qwen and ExLab Luna remain
> retired. See
> `docs/models/final-evaluation/B14_EXLAB_QWEN38_NEXT_UNCENSORED_2026-10-10.md`.


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

- Detailed workflow/rubric: docs/operations/B14_B66_QUOTE_MODEL_EVALUATION_PROTOCOL.md. No live nine-model benchmark is authorized by a source-only preflight.
- Canonical registered candidates: only enabled exact IDs from apps/korean-ai-platform/app/pilot/b14_models.json. Current-main count: nine. .github/scripts/b14_owner_evaluation_registry.py verifies this before model assessment; provider discovery is NOT registration.
- Direct Poolside Laguna S 2.1 is poolside/laguna-s-2.1 using https://inference.poolside.ai/v1 and the PADIEM_POOLSIDE_API_KEY binding NAME. All Kilo Laguna aliases remain Owner-excluded.
- Other excluded identities: B.AI Qwen, Motif 3, GPT-5.6 Luna, NVIDIA Nemotron. Historic five-model comparative fixture aliases are not authorization. The old live workflow is registry-gated, with the deleted models and all-five selector excluded.
- StepFun #3835 is Draft and does not extend the current-main nine-model roster. Nor does API availability, a synthetic test or an empty credential binding establish live provider readiness.
- Evaluate B66 repeat use on Korean request-to-QuoteDraft data extraction (recipient, item names, quantities, unit price and omissions), NOT on repeated re-creation of the HTML/PDF. QuoteCore calculates; the certified template renderer deterministically prints. No hidden paid/Auto/fallback inference.

## 2026-10-09 browser/B62 integration regression contract

- B14 app/pilot/workspace.py Start-screen manual model dropdown and its JavaScript b14CatalogModels use nine CATALOG_BY_ID entries installed from canonical b14_models.json, NOT historical empty CATALOG_MODELS.
- The standalone Alpha UI still has a legacy b14/auto option. This task does not authorize that option as a new Plus/Pro/Max group, nor does it implement a B66 manual selector. Group membership remains Owner-only.
- The Alpha browser smoke test selects approved agnes-ai/agnes-3.0-flash and supplies a dummy credential ONLY to the mock child process; no real API calls.
- B62 source authority verifies nine registered model IDs and five completely unregistered Owner-deleted IDs; no public/free/auto route is authorized for B66.
- B62 retry-budget fixture copies the schema of a surviving Agnes model in an isolated child with mocked provider dispatch and test-only key; the max_retries=0 execution guard still ensures exactly one provider attempt.
- Verification: focused B62 21 passed, local B14 full 995 passed, desktop Alpha browser 28 passed, mobile Alpha browser 6 passed. Exact-head Linux CI and independent approval remain mandatory prior to Ready/merge.
