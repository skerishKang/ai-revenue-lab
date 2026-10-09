# B14 모델 등록 CI 경량화 계약 (#3989)

2026-10-10. **모델 추가 PR과 공통 실행 코드 변경의 검증 깊이를 분리**한다. 모델 자체가 새로 등록되거나 해당 모델의 실제 API를 시험한다는 사실만으로 B62 전체 Pyodide/Engine/R2 런타임 테스트가 필요한 것은 아니다.

## 변경 경계

- **빠른 경로:** `apps/korean-ai-platform/app/pilot/b14_models.json`에만 기존 모델·provider 값을 변경하지 않고 신규 정확 모델 ID 1개 이상을 **목록 뒤에 추가**. 동일 변경에서 새로운 제공업체가 추가되면 `worker.py`에는 `PADIEM_*_API_KEY` 화이트리스트 문자열 **추가만**, `wrangler.toml`에는 Secret Store 바인딩 메타데이터 **추가만** 허용. 테스트 코드와 정해진 모델 평가 문서의 변경을 허용하며, 기타 앱/Engine/Core/identity/라이브 라우팅 파일은 불허한다.
- **전체 경로:** 모델 교체·삭제·수정, 기존 제공업체 endpoint·호스트·인증 소스 수정, 기존 Secret 변경, temperature/reasoning/gateway/worker 실행 로직, 공통 라이브러리, B62·B66 로직, 워크플로 자체 수정, PR+다른 제품 혼합 변경, 불분명한 GitHub diff, API 오류, 비표준 이벤트 → **fail-closed 전체 CI**.
- PR뿐 아니라 main push에도 Github changed-files/compare 메타데이터와 **이전 버전의 canonical JSON**을 검사해 빠른 경로를 판단한다. 모델 증분에 대해 기존 ID 순서, tier groups, provider 계약 권위가 변경되지 않았다는 사실을 정확한 구조 비교로 확인한다.
- **새로운 제공업체의 credential 바인딩 일치** 검사가 빠른 경로 조건이다. 키 값은 읽지 않으며 Secrets Store에 등록한 상태를 테스트에서 추정하지 않는다.

## 작업 게이트

1. **B62 Padiem Chat CI:** 빠른 모델 추가에서는 B14 GET canonical exact ID 집합, Owner manual-only, no-auto/fallback, registry source 연동 테스트만 실행. 공통 런타임 변경에는 B62 전체/Core/Pyodide/Engine/R2/Worker dry-run과 기존 b14 multimodal을 그대로 실행한다.
2. **Validate B14 Alpha:** 빠른 모델 추가에서는 locked dependencies를 기반으로 B14 registry, manual registered routes, native parameters omission, provider credential isolation, legacy Worker binding 증명을 수행. 그 외에는 기존 Alpha 전체 pytest + warning-strict pytest, Chromium, boot 실험을 모두 유지한다.
3. **Stable statuses:** `b62-test`와 `Locked Alpha contract`는 실제 선택된 테스트 레인의 PASS만 성공으로 보고한다. 계획·빠른 레인 실패 또는 잘못된 skip은 병합용 상태를 실패로 처리한다.
4. **별도 실행되는 안전 게이트:** B14 Worker JSON Bundle Preflight, B66 견적 모델 원본 계약, 운영 정책·보안검사 및 정확한 main의 B14 Production Deploy Gate는 변경하지 않는다. 특히 secret-store metadata와 실제 배포 바인딩은 Worker preflight/배포 게이트에서 검증한다.
5. **실제 제공업체 POST:** PR CI는 자격증명이나 사용자 데이터를 사용하지 않는다. 사전 검증은 MockTransport. 병합 후 정확한 B14 Production 배포를 완료하고 Owner 승인 모델 1회 실호출로 확인한다.

## 측정 기준

기준 사례 Kira #4021은 GitHub workflow 9개, 합산 runner 시간 367초(병렬·중복 시간 합계), 별도 test-only PR #4024의 B62 CI 한 건 8분 8초. 이 수정의 목표는 **단순 모델 등록 PR의 최장 critical path 2~3분 이내**지만 **측정 전에는 달성 선언 금지**.

병합 검증 시 실제로 **모델 등록만 변경한 합성 PR**과 **provider/gateway 런타임 파일 하나가 섞인 PR**을 각각 검증한다. 전자는 빠른 레인 + Worker 번들 검증 + 기타 관련 정책 CI만, 후자는 풀 레인을 실행해야 한다. 현 main의 모델/CI 테스트 자체는 새로운 경로를 만들기 위한 mixed 변경이므로 전체 레인이 선택되는 것이 정상이다.

분류 소스: `.github/scripts/b14_model_registration_ci_plan.py`. 오프라인 회귀: `.github/tests/test_b14_model_registration_ci_plan.py`.

**주의:** CI가 빨라졌다는 이유로 모든 모델 API 파라미터나 품질 점수를 검증 완료로 해석하지 않는다. 공용 등록 JSON의 실제 실행에서의 권위는 유지한다.
