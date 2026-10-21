# ERP 품목 마스터 파이프라인 — 구현·검증 안내

```text
DOC_STATUS = IMPLEMENTATION_README
SCOPE = apps/erp-item-master/
ISSUE = #5447
ERP_PRODUCT_CONFIRMED = NO
ECOUNT_OFFICIAL_TEMPLATE_CONFIRMED = NO
AI_PROVIDER_CALLS_IN_THIS_APP = 0
CUSTOMER_DATA_IN_THIS_REPOSITORY = NONE
```

이 폴더는 **공급처 상품목록을 읽어 → 정규화하고 → 중복을 찾아 → 사람이 볼 항목을
나누고 → ERP 품목 임포트 파일을 만드는** 파이프라인과 그 테스트를 담습니다.
이카운트(ECOUNT)는 이 폴더가 처음 조사한 ERP 후보이며, **공식 임포트 규격이 아직
확정되지 않았습니다.** 이 폴더의 코드와 산출물은 이카운트 계정, 고객 ERP,
고객 가격표 어느 쪽에도 연결되어 있지 않습니다.

## 1. 파일과 실제 책임

| 파일 | 실제 구현 책임 |
|---|---|
| `app/contracts.py` | 정규화 레코드·필드 출처·검토 상태·중복 종류의 정식 계약. 값은 항상 출처와 함께 보관된다 |
| `app/normalization.py` | 공백·전각/반각·대소문자·통화기호 정리와 금액 파싱. **값을 만들어내지 않는다** |
| `app/source_reader.py` | CSV·XLSX 원본을 읽고 열 이름 정규화 필드에 매핑. 헤더가 매핑되지 않으면 보고한다 |
| `app/duplicate_detection.py` | 중복 판정(품목코드 동일 / 이름·규격·단위 동일 / 이름 유사). 대량 처리용 차단을 포함한다 |
| `app/review_rules.py` | 사람이 확인해야 하는 항목과 그 이유 토큰 결정 |
| `app/extraction.py` | **외부에서 만들어진** AI 추출 결과의 검증 계약을 소유한다. 모델을 호출하지 않는다 |
| `app/erp_profile.py` | ERP 임포트 프로파일과 **필드별 근거 상태**(공식 확인 / 제3자 미검증 / 고객 양식 대기) |
| `app/template_binding.py` | **실제 서식 파일(.xlsx)** 을 읽어 정규화 필드를 서식 열에 묶는다. 서식에 없는 열 이름을 만들어내지 않는다 |
| `app/exporter.py` | CSV·Excel 기록. 수식 유사 문자열을 무력화하고, 채우지 못한 값은 비워 둔다 |
| `app/pipeline.py` | 전체 실행과 처리시간·건수 측정 |
| `app/cli.py` | `python -m app.cli` 실행 진입점 |
| `samples/` | 익명 합성 샘플 10건, 추출 입력, 실행 결과물 |
| `scripts/scale_check.py` | 대규모 카탈로그 규모에서의 처리량 측정 |

## 2. 이 앱이 하지 않는 것

- 모델 호출, 제공자 선택, API 키 보유 (`AI_PROVIDER_CALLS_IN_THIS_APP = 0`).
  모델·제공자 결정은 소유자 권한이며 `docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md`를 따른다.
- ERP 계정 접속, 실제 업로드, 실제 ERP 데이터 변경.
- **원본에 없는 가격·규격·품목코드를 만들어내는 것.** AI 추출이 이를 제안하면
  필드 이름으로 거절되고 사유가 기록된다.
- 고객의 실제 품목목록·가격표·거래처 정보를 이 저장소에 담는 것.
  샘플 10건은 전부 이 파일을 위해 만든 합성 데이터다.

## 3. 정규화 레코드

정규화 레코드는 ERP에 무관한 10개 필드로 이루어진다.

| 필드 | 뜻 | 필수 |
|---|---|---|
| `item_code` | 품목코드 (ERP 키) | 예 |
| `item_name` | 상품명 | 예 |
| `model_name` | 모델명 | 아니오 |
| `manufacturer` | 제조사 | 아니오 |
| `supplier` | 공급사 | 아니오 |
| `specification` | 규격 | 아니오 |
| `unit` | 단위 | 아니오 |
| `category` | 상품 분류 | 아니오 |
| `purchase_price` | 매입가 | 아니오 |
| `sales_price` | 판매가 | 아니오 |

각 값은 `출처(SOURCE_ROW / AI_EXTRACTION / RULE_NORMALIZATION / MISSING)`,
`신뢰도`, `원본 위치`를 함께 가진다. 읽지 못한 값은 `MISSING`이고 사유가 붙는다.

## 4. 실행 방법

저장소 루트에서 **Windows PowerShell**:

```powershell
$env:PYTHONPATH = "$PWD\packages\padiem-ai-core;$PWD\apps\erp-item-master"
python -m app.cli --source apps/erp-item-master/samples/source_items_raw.csv `
  --out apps/erp-item-master/samples/out `
  --extraction apps/erp-item-master/samples/extraction_results.json
```

저장소 루트에서 **Linux / macOS (bash)**:

```bash
PYTHONPATH=packages/padiem-ai-core:apps/erp-item-master \
  python -m app.cli --source apps/erp-item-master/samples/source_items_raw.csv \
  --out apps/erp-item-master/samples/out \
  --extraction apps/erp-item-master/samples/extraction_results.json
```

가용 프로파일 확인:

```bash
python -m app.cli --list-profiles
```

실제 ERP 서식 파일(.xlsx)이 있으면 서식의 헤더 행을 읽어 프로파일을 확정한다:

```bash
python -m app.cli --source <원본> --out <결과 폴더> --template "<서식 파일.xlsx>"
```

서식 바인딩의 절차와 판정 기준은
[05-ecount-template-binding-procedure.md](../../docs/commercial/erp-item-master-pilot/05-ecount-template-binding-procedure.md)에 있다.

## 5. 검증 실행

저장소 루트에서:

```bash
python -m pytest apps/erp-item-master/tests -q
python -m pytest packages/padiem-ai-core/tests/test_document_normalization.py -q
```

테스트는 네트워크 호출이 없는 **로컬 단위·계약 검사**다. 이 앱의 테스트는
`tests/conftest.py`가 앱과 Core 패키지 경로를 함께 넣으므로 `PYTHONPATH` 없이도
저장소 루트에서 그대로 실행된다.

2026-10-21 기준 이 소스에서 앱 테스트 66개와 Core 문서 정규화 테스트 36개가 통과했다.
이 결과는 **로컬 회귀 검사**이며, 고객 ERP 접속, 실제 이카운트 업로드,
브라우저 동작, Production 배포의 통과를 입증하지 않는다.

B71 작업공간과의 연계는 `apps/business-71-ai-operations/erp_item_master_adapter.py`
에 있고, [06-b71-integration.md](../../docs/commercial/erp-item-master-pilot/06-b71-integration.md)에
정리되어 있다. 그 어댑터는 이 앱을 위임 대상으로만 쓰고, 정규화·중복·파일 기록을
다시 구현하지 않는다.

## 6. 규모 측정

```bash
python apps/erp-item-master/scripts/scale_check.py --rows 30000
```

2026-10-21 측정(합성 30,000행, COM2 로컬): 총 39.7초, 초당 756행.
가장 느린 단계는 8개 시트 Excel 기록(32.4초)이며, 중복 탐색은 2.8초였다.
자세한 수치는 [실증 보고](../../docs/commercial/erp-item-master-pilot/03-sample-run-report.md)에 있다.

## 7. 이카운트 프로파일의 상태

`ecount_api_candidate` 프로파일은 **후보**다.

- 이카운트 공식 페이지에서 확인된 것: 품목등록 입력 API와 품목 조회 API의 존재,
  API 사용 추가 비용 없음, API 테스트 기능, 실패 사유를 즉시 볼 수 있는 엑셀 업로드,
  기존 등록 자료의 엑셀 갱신, 자료 엑셀 다운로드.
- 공식 페이지에서 확인되지 않은 것: 품목등록 요청 필드 이름, 엑셀 품목 시트의 열 구성.
  이카운트 공개 매뉴얼 URL은 로그인하지 않은 요청에 HTTP 410을 반환한다.
- `PROD_CD`·`PROD_DES`·`SIZE_DES`·`UNIT`·`IN_PRICE`·`OUT_PRICE`·`REMARKS`·`SIZE_FLAG`는
  **이카운트가 제공한 예시 파일을 제3자가 보고한 내용**이며 전부 `THIRD_PARTY_UNVERIFIED`다.
- 제조사·모델명·공급사·상품분류의 대응 필드는 찾지 못했다(`NOT_FOUND`).
  공급사와 분류는 이카운트가 **코드**를 요구하므로 이름을 그대로 옮길 수 없다.

`ecount_excel_template` 프로파일은 **열 이름이 아직 없는 상태**로 남는다.
열 구성은 고객 계정의 기본 탭 설정에 따라 달라지므로, 고객이 서식을 내려받은 뒤
확정해야 한다. 근거 상태는 `erp_field_mapping_status.csv`에 행 단위로 남는다.

## 8. 연결 문서

- [이카운트 공식 기능 조사](../../docs/commercial/erp-item-master-pilot/01-ecount-official-capability-review.md)
- [입력 방식 비교 (엑셀 대량등록 vs Open API)](../../docs/commercial/erp-item-master-pilot/02-input-method-comparison.md)
- [샘플 10건 실행 결과](../../docs/commercial/erp-item-master-pilot/03-sample-run-report.md)
- [적용 전 확인 필요 항목](../../docs/commercial/erp-item-master-pilot/04-remaining-customer-information.md)
- [이카운트 실제 서식 바인딩 절차](../../docs/commercial/erp-item-master-pilot/05-ecount-template-binding-procedure.md)
- [B71 연계](../../docs/commercial/erp-item-master-pilot/06-b71-integration.md)
- [공유 XLSX 구조 판독 권한](../../packages/padiem-ai-core/padiem_ai_core/document_normalization.py) — `read_xlsx_table`

관련 이슈: #5447.
