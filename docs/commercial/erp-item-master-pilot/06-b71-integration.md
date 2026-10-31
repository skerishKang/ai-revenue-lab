# 06 — B71 연계

```text
DOC_STATUS = TECHNICAL_INTEGRATION
SCOPE = docs/commercial/erp-item-master-pilot/06-b71-integration.md
ISSUE = #5447
B71_ISSUE = #5451
B71_WORKSPACE_PR = #5452
INDEPENDENT_VALIDATOR = NOT_REQUIRED
RUNTIME_DEPLOYED = NO
```

## 1. B71이 무엇인지 (#5451)

B71은 **제안 번호**이며 포트폴리오 정본 등록 전에는 확정 번호가 아니다. B71의
기술 흐름은 이미 세 개의 과제로 나뉘어 있다.

| 기술 흐름 | 이슈 | 이 저장소의 위치 |
|---|---|---|
| 상품 데이터 처리 | #5446 | 별도 워크스림 |
| ERP 품목 정리 | #5447 | `apps/erp-item-master/` |
| 주문·배송 상태 처리 | #5448 | 별도 워크스림 |

B71은 별도 신규 Business가 아니라 이 세 기술 흐름의 공통 실행 계약이다. 그래서
B71 작업을 시작하면서 ERP 품목 정리를 다시 만들면 안 된다.

## 2. B71 작업공간 구조

`apps/business-71-ai-operations/` 는 B71의 통합 계약·샘플·공통 워크플로를 담는
작업공간이다. PR #5452가 이 폴더의 `README.md` 를 만든다.

B71 작업계약은 그 README에 적혀 있다.

```text
입력 : workspace_id, job_id, workflow_kind, source_ref, requested_action
결과 : status, output_refs, validation_findings, human_review_needed,
       execution_evidence_ref, error_code
```

## 3. ERP 쪽 어댑터

`apps/business-71-ai-operations/erp_item_master_adapter.py` 가 ERP 품목 정리의
B71 계약 어댑터다.

| 항목 | 값 |
|---|---|
| `workflow_kind` | `erp_item_master_import_prepare` |
| `requested_action` | `normalize_and_prepare_import` |
| 위임 대상 | `apps/erp-item-master` 의 파이프라인 |

어댑터는 정규화도 중복 판정도 파일 기록도 직접 하지 않는다. 전부 기존
`apps/erp-item-master/` 구현에 위임한다. 이 어댑터 안에는 `normalize_`,
`parse_price`, `detect_duplicates` 같은 구현이 없고 `openpyxl` 도 직접 쓰지
 않는다. 회귀 테스트가 이 사실을 코드 문자열로 확인한다.

### 3.1 결과 필드 매핑

| B71 결과 필드 | ERP 어댑터가 채우는 값 |
|---|---|
| `status` | `completed` / `failed` / `rejected` |
| `output_refs` | 실행이 만든 파일들의 절대 경로 목록 |
| `validation_findings` | 행 수, 자동 확정 행 수, 사람 확인 행 수, 중복 그룹 수, 오류 수, 그리고 행별 검토 사유 |
| `human_review_needed` | 사람 확인이 필요한 행이 하나라도 있으면 `True` |
| `execution_evidence_ref` | `pipeline_report.json` 의 경로 (재현 가능한 근거) |
| `error_code` | `ok` / `unknown_workflow_kind` / `unsupported_requested_action` / `missing_argument` / `source_unreadable` / `job_failed` |

### 3.2 경계

- **한 작업은 자기 출력 폴더 안에만 쓴다.** 출력 경로는
  `<output_dir>/<workspace_id>-<job_id>/` 로 만들어지고, 어댑터는 그 밖의 경로에
  쓰지 않는다. 한 워크스페이스의 작업이 다른 워크스페이스의 파일을 건드릴 수 없다.
- **모르는 계약은 거절한다.** `workflow_kind` 나 `requested_action` 이 이 어댑터가
  구현하지 않은 값이면 `rejected` 와 오류 코드로 끝난다. 가까운 동작으로 대신하지
  않는다.
- **가져오기는 하지 않는다.** `apps/erp-item-master` 패키지를 고유한 모듈 이름으로
  적재하므로, 다른 앱이 같은 `app` 패키지 이름을 쓰더라도 서로 섞이지 않는다.

## 4. 중복 구현이 없다는 근거

| 확인 방법 | 위치 |
|---|---|
| 어댑터가 직접 구현하지 않음 | `apps/business-71-ai-operations/tests/test_erp_item_master_adapter.py` 의 `test_the_adapter_does_not_reimplement_the_pipeline` |
| 기존 구현이 그대로 쓰임 | `apps/erp-item-master/app/pipeline.py` 의 `run_pipeline` 호출 1곳 |
| 정규화·중복·파싱 재구현 없음 | 같은 테스트의 금지 문자열 검사 |

## 5. 이 문서가 주장하지 않는 것

- B71 작업공간의 런타임이나 배포가 없다는 것이다. 이 어댑터는 소스다.
- B71의 첫 기술 수용 기준을 충족했다는 것이다. 그 기준은 B71 작업공간 소유자가
  판단한다.
- 이카운트 업로드가 성공한다는 것이다. 이카운트 서식과 API 매뉴얼은 아직 없다.
- 세 기술 흐름의 통합 완료. #5446과 #5448은 각자 워크스림이 진행 중이며 이 변경은
  그 파일들을 건드리지 않는다.

## 6. 조율 메모

`apps/business-71-ai-operations/` 안에는 이 변경이 추가한 파일이 하나 있다.

```text
erp_item_master_adapter.py     ERP 쪽 어댑터
tests/test_erp_item_master_adapter.py
```

PR #5452가 만든 `README.md` 는 건드리지 않았다. B71 작업공간 소유자가 통합 계약을
최종 확정하면 이 어댑터의 `workflow_kind` 와 `requested_action` 값을 그 계약에
맞춰 조정하면 되고, ERP 구현 자체는 다시 만들지 않아도 된다.
