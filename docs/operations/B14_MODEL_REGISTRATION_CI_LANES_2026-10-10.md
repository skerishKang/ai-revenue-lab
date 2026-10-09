# B14 모델 등록 CI 경량화 계약 (#3989)

2026-10-10. **모델 추가 PR과 공통 실행 코드 변경의 검증 깊이를 분리**한다. 모델 자체가 새로 등록되거나 해당 모델의 실제 API를 시험한다는 사실만으로 B62 전체 Pyodide/Engine/R2 런타임 테스트가 필요한 것은 아니다.

## 변경 경계

- **빠른 경로:** `apps/korean-ai-platform/app/pilot/b14_models.json`에만 기존 모델·provider 값을 변경하지 않고 신규 정확 모델 ID 1개 이상을 **목록 뒤에 추가**. 동일 변경에서 새로운 제공업체가 추가되면 `worker.py`에는 `PADIEM_*_API_KEY` 화이트리스트 문자열 **추가만**, `wrangler.toml`에는 Secret Store 바인딩 메타데이터 **추가만** 허용. 테스트 코드와 정해진 모델 평가 문서의 변경을 허용하며, 기타 앱/Engine/Core/identity/라이브 라우팅 파일은 불허한다.
- **전체 경로:** 모델 교체·삭제·수정, 기존 제공업체 endpoint·호스트·인증 소스 수정, 기존 Secret 변경, temperature/reasoning/gateway/worker 실행 로직, 공통 라이브러리, B62·B66 로직, 워크플로 자체 수정, PR+다른 제품 혼합 변경, 불분명한 GitHub diff, API 오류, 비표준 이벤트 → **fail-closed 전체 CI**.
- 분류기 함수는 PR과 main push 이벤트를 처리하지만 **실제 자동 실행 조건은 다르다**. B62 Padiem Chat CI는 PR과 main push 모두 실행되는 반면, Validate B14 Alpha는 PR과 수동 실행(workflow_dispatch)만 지원하고 main push에서는 자동 실행되지 않는다. 분류기는 GitHub changed-files/compare 메타데이터와 이전 canonical JSON을 비교한다. 모델 증분에 대해 기존 ID 순서, tier groups, provider 계약 권위가 변경되지 않았다는 사실을 정확한 구조 비교로 확인한다.
- **신규 제공업체의 credential 바인딩 일치** 검사가 빠른 경로 조건이다. 다만 2026-10-10 후속 점검에서 기존 제공업체의 단순 모델 추가에 무관한 Worker/Secret Store 메타데이터가 함께 변경돼도 빠른 경로를 선택할 수 있는 결함을 재현했다. 이 결함은 [#4042](https://github.com/skerishKang/ai-revenue-lab/issues/4042)에서 보완할 때까지 미해결로 표시한다. 실제 키 값은 CI에서 읽지 않으며 Secrets Store 운영 연결 상태를 추정하지 않는다.

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

## 합성 모델 등록 PR 실제 GitHub Actions 측정 (2026-10-10)

- 운영 `main`의 모델 등록소는 수정하지 않음. **병합 없이 종료된 DRAFT** [PR #4033](https://github.com/skerishKang/ai-revenue-lab/pull/4033)에만 기존 Google provider의 비실재 합성 정확 모델 ID `google/padiem-ci-synthetic-probe-261010`를 12번째로 추가하고 기존 모델 목록·설정·그룹·Secret 값을 유지함. 이 PR은 **실제 병합되지 않았으며 검증용 원격 브랜치도 삭제됐다**.
- 빠른 레인 실측 HEAD: `a4d5cfa81af0b7c93d798f0ce16b38cd03cc4286`. 분류기가 `model_registration_only`를 출력하였고 B14/B62 전체 CI는 정상 skip, B14 집중 테스트·B62 등록소 테스트·Worker 번들·정책·견적 계약·평가 소스 계약은 통과함. 요구 상태 `Locked Alpha contract`와 `b62-test` 둘 다 SUCCESS.
- 워크플로 실제 실행 시간(각 run의 `updated_at - created_at`, 초; 동일 PR 내 병렬 실행이며 합산 runner 시간과는 다름):

| GitHub workflow | Run ID | 실측 경과 시간 | 결과 |
| --- | --- | ---: | --- |
| B62 Padiem Chat CI | [37996092750](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37996092750) | **44초** | SUCCESS |
| Validate B14 Alpha | [37996092701](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37996092701) | 36초 | SUCCESS |
| B14 Python Worker JSON Bundle Preflight | [37996092690](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37996092690) | 38초 | SUCCESS |
| Operations Policy Guard | [37996092736](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37996092736) | 37초 | SUCCESS |
| B14 Historical Comparative Model Benchmark | [37996092760](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37996092760) | 17초 | SUCCESS |
| B66 Quote Interpretation Benchmark | [37996092742](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37996092742) | 18초 | SUCCESS |
| B62 Unified Browser QA | [37996092702](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37996092702) | 12초 | SUCCESS |

- 동일 SHA의 가장 늦게 끝난 워크플로 기준 **44초**로, 사전 정의한 2~3분 목표는 **이 합성 append-only PR에 한해 달성**. 기존 B62 전체 테스트 사례 [#4024](https://github.com/skerishKang/ai-revenue-lab/pull/4024)는 **8분 08초**였지만 서로 다른 변경 유형이므로 엄밀한 A/B 비교가 아님. 사람이 소요하는 실제 제공업체 등록·API 품질평가·배포는 이 44초에 포함되지 않음.
- 첫 검증에서 발견된 기존 고정 목록 결함 2건(평가 CLI가 정확히 11개여야 한다는 주장, Google 모델이 정확히 4개여야 한다는 주장)은 [PR #4035](https://github.com/skerishKang/ai-revenue-lab/pull/4035)로 수정. 원래 Owner가 승인한 기존 모델을 subset으로 계속 강제하면서 canonical 동적 개수를 허용. #4035는 전체 CI PASS 후 **병합 완료**(SHA bf79f0024ade2ad8db14ee598f20742fa5ae8ed8).
- `main push`의 분류는 `.github/scripts/b14_model_registration_ci_plan.py::classify_github`의 `push` 이벤트 분기 및 GitHub compare API를 통해 구현되어 있으며, #4027 병합 push의 mixed 변경은 **전체 레인**으로 동작한 것을 관찰. **빠른 모델 append-only 실제 main push는 의도적으로 시행하지 않았으므로 별도 실측 PASS로 주장하지 않는다**.
- 범용 CI fanout 및 Pending 방지는 상위 [#3989](https://github.com/skerishKang/ai-revenue-lab/issues/3989) 추적을 유지한다. 이 검증을 위해 운영 Secret·실제 모델·Production Deploy Gate는 변경하지 않았다.

## B14 전용 사후 감사 — 2026-10-10

이 문서는 B14 등록 CI 최적화의 **검증된 범위와 남은 결함**을 구분한다.

| 항목 | PR 자동 실행 | main push 자동 실행 | 수동 실행 |
| --- | --- | --- | --- |
| B14 Alpha | 예 | **아니요** | 예 |
| B62 Chat (B14 등록 연동) | 예 | 예 | 예 |

- **실측 PASS:** 합성 등록 PR #4033의 정확한 HEAD에서 7개 워크플로 PASS, 가장 긴 워크플로 44초. 임시 PR은 병합 없이 종료됨.
- **오프라인 PASS:** 분류기의 PR/main push 이벤트 모의 시험. 실제 새 모델만 추가한 main push의 B14 Alpha 검증이 완료됐다는 의미는 아님.
- **후속 결함 수정 완료:** [#4042](https://github.com/skerishKang/ai-revenue-lab/issues/4042)는 이전 분류기의 무관한 credential metadata 허용 결함을 기록한다. [PR #4045](https://github.com/skerishKang/ai-revenue-lab/pull/4045)로 수정하고 전체 B14·B62 CI 통과 후 main에 병합했다(merge `0cca5ae932819b1b385c3fb22d9c88ba5c202a8c`). 수정 후 신규 모델 추가 합성 PR #4047의 빠른 경로와 안정적 필수 상태도 재검증했다.
- **범위 구분:** 모델 등록 CI 속도는 모델 품질·유료 API 실호출·키 유효성·Production 배포를 보증하지 않는다. 변경이 병합됐다는 사실과 배포됐다는 사실을 별도로 확인한다.
- **상위 이슈:** [#3989](https://github.com/skerishKang/ai-revenue-lab/issues/3989)는 저장소 전체 CI 최적화로 계속 OPEN이다.

## #4042 — 모델 등록 빠른 경로의 인증 메타데이터 차단 규칙

- **기존 제공업체 신규 모델:** 등록소의 append-only 추가만 허용한다. 동일 PR에서 Worker 자격증명 허용목록이나 Wrangler Secret Store 메타데이터를 수정하면 `full`을 선택한다.
- **신규 제공업체 등록:** 신규 provider에 실제 append 모델이 있어야 한다. Worker에 추가한 credential alias는 신규 provider의 alias 집합과 중복 없이 정확히 같아야 한다. 기존 provider가 이미 사용하는 alias를 재사용할 수 없다.
- **Wrangler 변경:** 신규 provider별 완전한 `[[secrets_store_secrets]]` 블록(바인딩명/스토어 ID/secret_name)을 정확히 하나씩 추가해야 한다. 허용된 기존 스토어 메타데이터 ID를 유지하고, 추가 블록·미승인 스토어·중복/누락 필드를 거부한다.
- 분류 실패 시 기존 `full` 경로로 전환하며 해당 모델을 자동 활성화하거나 Secret 값을 참조하지 않는다. CI 합격과 실제 자격증명·모델 품질·Production 배포는 서로 별개의 조건이다.
- 이 규칙은 #4045를 통해 **코드·회귀 테스트·문서가 병합된 규약**이다. 이전 #4033의 44초 실측에 더하여, 보강 후 #4047 합성 모델 등록 PR에서도 7개 워크플로가 PASS하고 최장 44초로 재측정했다. 두 검증 PR 모두 운영 main에 병합하지 않았다.

### 보강 후 정확한 CI 증거

- 구현: [PR #4045](https://github.com/skerishKang/ai-revenue-lab/pull/4045), head `70ee582a6bd4220a81e2db4c98fed7d9e15b0733`, main merge `0cca5ae932819b1b385c3fb22d9c88ba5c202a8c`.
- 분류 규칙 8개 PASS, B14 Alpha full [run 37997903226](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37997903226) PASS(68초), B62 full [run 37997903185](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37997903185) PASS(474초), 운영 정책·브라우저 QA PASS. 병합용 `b62-test`와 `Locked Alpha contract` 모두 SUCCESS.
- **빠른 경로 재검증:** [Draft PR #4047](https://github.com/skerishKang/ai-revenue-lab/pull/4047), 정확한 head `13590f45a9fdfa6b2032a7a50cb5763580e722ef`. 기존 Google 제공업체에만 비실재 합성 모델 1개를 append. B14 Alpha [37998697690](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37998697690) 29초 PASS, B62 [37998697621](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37998697621) 36초 PASS, Worker JSON 번들 [37998697682](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37998697682) 44초 PASS. 별도 평가/정책/견적/QA 등 포함 **7/7 SUCCESS**, 전체 레인은 의도대로 SKIPPED, 두 병합용 상태 SUCCESS. Draft PR은 **병합 없이 종료**, 임시 원격 브랜치도 삭제.
- 다시 측정한 **44초**는 여전히 *합성 append-only PR*의 전체 GitHub Actions wall critical path이다. 실제 제공업체 API 검증, 운영 Secret 연동, Production Deploy Gate, 자동 main-push B14 Alpha 검증 완료를 의미하지 않는다.
