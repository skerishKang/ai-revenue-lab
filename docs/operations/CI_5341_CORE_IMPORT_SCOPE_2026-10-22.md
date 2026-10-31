# CI #5341 — shared Core import-scope lane (2026-10-22)

## 문제

`packages/padiem-ai-core/**` 변경은 `B62 Padiem Chat CI`와 `Padiem AI Engine CI`를
동시에 시작시켰다. 그중 B62 분류기는 Core 파일이 2개(`isolated_parser_client.py`,
그 테스트) 외에는 모두 `full`로 분류해, **어떤 제품도 import하지 않는 Core 유틸리티
변경**에도 B62 전체 회귀 + Workerd 부팅 + B14 계약이 실행됐다.
실측 기준선은 격리 파서 PR #5332의 동일 HEAD 실행 기록이다.

## 정적 증명 (import closure)

`.github/scripts/ci_core_import_scope.py`가 제품 런타임이 실제로 import하는 Core
모듈 집합을 계산한다.

- 제품 소스 트리의 `padiem_ai_core` import(루트/서브모듈/상대 import)와
  `padiem_ai_core.<module>` 텍스트 참조를 모두 수집한다.
- Core 서브모듈을 import하면 패키지 `__init__`이 실행되므로, `__init__`의 eager
  import surface 전체가 closure에 포함된다. lazy `importlib` surface는 실제로
  요청될 때만 실행되므로 독립 모듈로 남는다.
- Core 모듈 간 상대 import를 따라 전이 closure를 만든다.
- closure에 **없는** Core 모듈만 그 제품에 대해 `independent` 이다.
- 판독 불가 파일, 구문 오류, 알 수 없는 경로, 100개 초과 변경 세트는 전부 `None`
  (증명 실패)이며, 호출자는 안전한 전체 검사 경로를 유지한다.

## 레인 매핑

| 변경 | B62 | Engine |
| --- | --- | --- |
| 제품이 import하는 Core 모듈 (`contracts`, `execution_runtime`, `b14_execution`, `document_normalization` …) | 전체 회귀 + Worker + B14 계약 | 전체 Engine + Core + Worker 증명 |
| 어느 제품도 import하지 않는 Core 모듈 (`isolated_parser_client`, `pdf_authoring`, `template_cloner_skill`, `workspace_storage` …) | `B62 focused independent Core` (변경 모듈 import smoke + 해당 Core 테스트) | `Focused independent Core contract` |
| Core 테스트만 변경 | 동일 집중 경로 | 동일 집중 경로 |
| 문서만 변경 | 실행 안 함 (path filter) | 실행 안 함 (path filter) |
| 분류 실패/불확실 | 전체 검사 | 전체 검사 |

## 보존된 계약

- 필수 체크 이름 `b62-test`, `engine-core-reuse`는 그대로다. 분류기는 저장소/브랜치
  보호 규칙을 변경하지 않는다.
- B62·Engine·B14 공통 실행 계약 변경은 필요한 통합 검사를 그대로 실행한다.
- 집중 경로도 변경 모듈을 실제로 import 하고 해당 Core 테스트를 실행하므로,
  실패를 성공으로 표시하는 우회가 아니다.
- 배포 게이트, 보안 검사(GitGuardian/Secret), 운영 게이트는 변경하지 않는다.

## 안전장치

- 집중 경로의 실행 대상은 분류기가 확정한 변경 모듈과 그 테스트 파일뿐이다.
  실행 대상이 비어 있거나, 경로 형식이 어긋나거나, 파일 수가 40을 넘으면
  전체 경로로 되돌아간다.
- `b62_host_pytest_overlap_4070.sh`는 모르는 scope를 `full`로 취급한다.
- 기존과 동일하게 동일 HEAD 재사용은 COM2 정책 검사에서 이미 구현되어 있다
  (PR #5351, `COM2 PR Auto Sandbox`).

## 근거 테스트

- `.github/tests/test_5341_core_import_scope.py` — closure 증명, B62/Engine 레인
  배선, 필수 체크 이름, 분류 실패 시 전체 경로.
- `.github/tests/test_b62_ci_impact_scope_3989.py` — B62 분류기의 Core scope.
- `.github/tests/test_3989_engine_living_learning_ci_scope.py` — Engine 트리거 소유권.
- `docs/operations/tests/test_ci_scope_policy.py` — B62 트리거 경로와 잡 그래프.
