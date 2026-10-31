# 05 — 이카운트 실제 서식 바인딩 절차

```text
DOC_STATUS = OPERATIONAL_PROCEDURE
SCOPE = docs/commercial/erp-item-master-pilot/05-ecount-template-binding-procedure.md
ISSUE = #5447
PROCEDURE_DATE = 2026-10-21
REAL_TEMPLATE_AVAILABLE = NO
```

## 1. 이 절차가解决하는 것

`ecount_excel_template` 프로파일은 지금 `upload_ready=False`다. 열 이름을 모르기
때문이다. 이 절차는 **실제 서식 파일이 도착한 뒤** 그 파일을 읽어 열 이름을 그대로
확정하는 방법이다. 서식이 없으면 어떤 것도 확정하지 않는다.

이 절차가 하는 일과 하지 않는 일:

| 하는 일 | 하지 않는 일 |
|---|---|
| 서식 파일의 헤더 행을 그대로 읽는다 | 필드 이름을 추정하거나 번역하지 않는다 |
| 정규화 필드와 서식 열의 대응을 확정한다 | 대응이 없는 필드를 다른 열에 밀어 넣지 않는다 |
| 서식의 열 순서를 그대로 보존한다 | 열 순서나 이름을 임의로 바꾸지 않는다 |
| 대응이 안 된 필드를 보고한다 | 대응이 안 된 필드를 지워 버리지 않는다 |
| 필수 정규화 필드가 모두 묶였을 때만 `upload_ready=True`로 만든다 | 부분 대응 상태로 업로드 가능이라고 하지 않는다 |

## 2. 구현된 도구

`apps/erp-item-master/app/template_binding.py` 와 그 테스트가 이 절차의 구현이다.

- `bind_template(path)` — 서식 파일을 읽고 헤더 행을 찾고 정규화 필드를 묶는다.
  헤더 행은 서식의 **비어 있지 않은 행** 중 정규화 필드와 가장 많이 겹치는 행이다.
  제목 행과 안내 행이 위에 있어도 실제 헤더 행을 찾는다.
- `binding_profile(binding, profile_id=...)` — 묶은 결과를 임포트 프로파일로 만든다.
  프로파일의 열은 **서식의 열을 서식의 순서대로** 그대로 담는다. 묶이지 않은 서식 열도
  빈칸으로 포함된다. 서식에 붙여넣을 때 열 모양이 어긋나면 오류가 나기 때문이다.
- `binding_report_rows(binding)` — 무엇이 묶였고 무엇이 묶이지 않았는지 표로 만든다.

서식 파일을 읽는 경로는 기존 Core의 `read_xlsx_table` 을 재사용한다. 두 번째
파서 권한을 만들지 않는다.

## 3. 실행 절차

### 3.1 서식 파일 받기

1. 이카운트 계정으로 로그인한다.
2. `재고Ⅰ - 기초등록 - 품목등록` 화면을 연다.
3. 하단 `웹자료올리기` → `엑셀 서식 받기`로 서식 파일을 받는다.
4. 받은 파일을 **아무것도 고치지 않은 상태로** 보관한다. 열 이름이나 순서를 바꾸면
   업로드 오류가 난다는 것이 운영 자료에서 확인되어 있다.
5. 같은 화면의 `등록자료 변경하기` 탭에서 받는 서식도 따로 보관한다. 기존 자료
   갱신 경로는 열 구성이 다를 수 있다.

### 3.2 바인딩하기

저장소 루트에서:

```powershell
$env:PYTHONPATH = "$PWD\packages\padiem-ai-core;$PWD\apps\erp-item-master"
python -m app.cli `
  --source apps/erp-item-master/samples/source_items_raw.csv `
  --out <결과 폴더> `
  --extraction apps/erp-item-master/samples/extraction_results.json `
  --template "<받은 서식 파일.xlsx>"
```

실행하면 결과 폴더에 다음이 생긴다.

| 파일 | 내용 |
|---|---|
| `erp_import_template_bound.csv` | 서식의 헤더 행과 서식의 열 순서를 그대로 가진 이관 파일. 바인딩이 완전할 때만 `upload_ready` |
| `template_binding_report.csv` | 정규화 필드별 바인딩 결과, 묶이지 않은 필드, 서식 파일 해시 |
| `erp_field_mapping_status.csv` | 프로필 전체의 열 단위 근거 상태 |
| `item_master_workbook.xlsx` | 검토용 통합 워크북 (바인딩된 프로필 시트 포함) |

### 3.3 결과를 읽는 법

`template_binding_report.csv` 를 먼저 본다.

- `템플릿열` 이 비어 있지 않으면 그 정규화 필드가 서식의 어느 열로 갔는지 확정된 것이다.
- `(템플릿에 해당 열 없음)` 이면 그 정규화 필드는 서식에 없는 것이다. 두 가지
  선택지가 있다. **(가)** 그 필드를 이관 파일에서 빼고, **(나)** 서식의 다른 열이
  같은 뜻인지 확인한다. 임의로 넣지 않는다.
- `확인상태` 가 `NOT_FOUND` 인 행은 아직 확정되지 않은 것이다.

`upload_ready` 가 `False` 로 남았다면 필수 정규화 필드(품목코드·상품명) 중 하나가
서식에 묶이지 않은 것이다. 이 상태의 파일을 ERP에 올리면 안 된다.

## 4. 여전히 사람이 확인해야 하는 것

바인딩이 성공해도 아래는 자동으로 정해지지 않는다. 서식 파일만으로는 알 수 없다.

| 항목 | 확인 방법 |
|---|---|
| 서식이 표시하는 필수 항목 | 서식에서 노란색으로 표시된 칸을 눈으로 확인한다. 바인딩 도구는 셀 색을 읽지 않는다 |
| 서버가 받는 1회 행 수 상한 | 공식 매뉴얼 또는 실제 업로드 테스트 |
| 파일명 규칙·인코딩 | 같은 방식으로 몇 번 받아본다 |
| 가격 항목의 부가세 포함 여부 | ERP 화면의 항목 정의와 실제 거래 확인 |

이 항목들은 모두 `template_binding_report.csv` 의 근거 상태와 별개로, 비공개
사업방침 문서에서 관리하는 확인 절차에 따라 처리한다.

## 5. API 후보 프로파일은 별개다

`ecount_api_candidate` 프로파일은 **엑셀 서식이 아니라 API 요청 필드** 후보다.
서식을 확보해도 이 프로파일의 필드 이름이 곧 확정되지는 않는다. API 세부 매뉴얼을
확보한 뒤에 별도로 상태를 바꾼다.

두 프로파일의 근거 상태는 각각 따로 움직인다.

| 프로파일 | 확정 조건 | 근거 |
|---|---|---|
| `ecount_excel_template` | 실제 서식 파일을 바인딩해 필수 필드가 모두 묶임 | 서식 파일 자체 |
| `ecount_api_candidate` | 공식 API 매뉴얼 확보 후 필드 이름·필수 여부 확인 | 공식 매뉴얼 |

## 6. 현재 상태

```text
REAL_TEMPLATE_AVAILABLE = NO
ECOUNT_EXCEL_TEMPLATE_CONFIRMED = NO
ECOUNT_API_CANDIDATE_CONFIRMED = NO
GENERIC_PROFILE_UPLOAD_READY = YES
```

`generic` 프로파일만 지금 바로 쓸 수 있다. 이카운트 후보 파일은 `CANDIDATE`가 붙은
검토용이며 업로드 파일이 아니다.
