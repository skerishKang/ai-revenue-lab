# B14 중앙 모델 레지스트리 — 단일 원본 운영 계약

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
