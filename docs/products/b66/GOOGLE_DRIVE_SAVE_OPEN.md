# B66 — 고객 본인 Google Drive 저장·불러오기 구현 계약 (#3871)

```text
DOC_STATUS=IMPLEMENTATION_SOURCE_AND_OFFLINE_TESTS
PRODUCT=B66_STANDALONE_QUOTATIONS
ISSUE=#3871
OWNER_DECISION_DOC=QUOTE_STORAGE_STRATEGY.md
EXISTING_D1_HISTORY_OWNER=#3405
D1_HISTORY_CHANGED=NO
LIVE_DRIVE_VERIFIED=NOT_TESTED
REAL_PHONE=NOT_TESTED
PRODUCTION_DEPLOYMENT=NOT_PERFORMED
```

이 문서는 2026-10-09 기준 **소스 구현과 오프라인 테스트 상태**를 기록한다.
실제 Google 계정 연결, 다른 브라우저 재열기, 실제 휴대전화 검증은 수행하지 않았으므로
이 문서로 실서비스 완료를 주장하지 않는다.

## 범위

- 저장 위치는 **고객이 명시적으로 고른다**. 자동 저장·자동 동기화·충돌 해결은 없다.
- Google Drive 를 연결하지 않아도 견적 작성, 최근 견적(D1 #3405), PDF 다운로드는 그대로 동작한다.
- 저장 대상은 **편집 가능한 JSON + 인증된 최종 PDF 한 쌍**이다.
- 불러오면 **항상 QuoteCore 가 공급가액·부가세·합계를 다시 계산한다.** 저장된 합계는 권위가 아니다.
- 모델 호출은 0이다. Google Sheets 변환이나 새 PDF 렌더러는 없다.

## 소스

| 파일 | 역할 |
|---|---|
| `reference/business-66-padiem-quote-v1/quote-drive-contract.js` | 버전 명시 JSON 스키마, JSON·PDF 연결 매니페스트, 파일명/중복 규칙, 크기·형식·스키마 검증, 부분 실패 결과 모델, QuoteCore 재계산 |
| `reference/business-66-padiem-quote-v1/quote-drive-client.js` | Google OAuth(GIS) + Drive API v3 통신, 최소 권한 `drive.file`, Picker, 소유 검증, 부분 실패 복구 |
| `reference/business-66-padiem-quote-v1/quote-drive-ui.js` | '내 Google Drive에 저장' / 'Google Drive에서 열기' / 연결 상태 / 부분 성공 표시 |
| `reference/business-66-padiem-quote-v1/app.js` | 외부 저장용 인증 PDF 바이트 seam(`certifiedPdfBytes`) 추가. 기존 다운로드 경로는 변경 없음 |

## 저장 데이터 계약 (`b66.quote-drive.v1`)

```text
kind            = b66.quote-package
contract        = b66.quote-drive.v1
schemaVersion   = 1
packageId       = JSON 과 PDF 를 묶는 한 쌍 식별자
quote           = QuoteDraft 전체(detailGroups · calculationPolicy · meta.projectName 포함)
template        = { savedSkillId, fingerprint, rendererContract } 참조(값이 아님)
assets          = { json: {...}, pdf: {...} } 두 파일 모두 같은 packageId 를 가진다
manifest        = 표시용 메타데이터(quoteNo/issueDate/거래처/항목 수/저장 시각)
totalsAuthority = quote-core      (다른 값이 오면 명시 거부)
totals          = null            (저장된 합계는 쓰지도 읽지도 않는다)
```

### 기존 D1 스냅샷(`b66.quote-draft.v1`)과의 차이

`quote-history-server.js`의 D1 스냅샷은 `detailGroups`와 `calculationPolicy`를 보존하지 않는다.
이 문서와 무관하게 **#3405의 기존 동작은 그대로 유지**하며, 고객 Drive 계약은
그 값들을 포함한 **무손실 독립 계약**을 새로 정의한다. D1 을 대체하지 않는다.

### 거부 정책(명시 거부, 조용한 보정 없음)

| 상황 | 코드 |
|---|---|
| JSON 손상 / 빈 값 | `invalid_json`, `invalid_json_text` |
| 프로토타입 오염 키 | `unsafe_json_key` |
| 다른 문서 종류 | `package_kind_unsupported`, `contract_unsupported` |
| 지원하지 않는 스키마 버전(구버전·미래 버전) | `schema_version_unsupported`, `schema_version_newer_than_supported` |
| 크기 초과 | `json_too_large`, `pdf_too_large` |
| PDF 형식 아님 | `pdf_format_invalid`, `pdf_too_small` |
| 합계 권위를 quote-core 가 아닌 값으로 선언 | `totals_authority_unsupported` |
| 파일 안의 신원 주장 필드(owner/user/account …) | `unsupported_package_field`(허용 목록 밖) |
| 허용 목록 밖 필드 | `unsupported_package_field` |
| 다른 Google 계정 파일 / 권한 없음 | `drive_file_not_found`, `drive_file_access_denied`, `drive_file_not_owned_by_connected_account` |
| 로그아웃·미연결 | `drive_not_connected` |
| 토큰 만료 / 401 | `drive_token_expired` |

파일 안의 사용자 ID·이메일은 **접근 권한의 근거로 쓰지 않는다.** 권한 근거는 항상
연결된 Google 세션과 Drive 가 돌려준 파일 소유 정보(`owners[].me`)다.

## 부분 실패

| 상태 | 의미 |
|---|---|
| `complete` | JSON + PDF 모두 저장 |
| `partial_json` | JSON 만 저장됨. 메시지 표시 + PDF 만 재시도 가능 |
| `partial_pdf` | PDF 만 저장됨. 메시지 표시 + JSON 만 재시도 가능 |
| `failed` | 둘 다 실패 |

부분 성공은 `ok=false` 이며 화면에 반드시 표시된다. 재시도는 없는 쪽만 다시 올리고
같은 `packageId` 를 재사용한다. PDF 바이트가 처음부터 잘못되면 **아무것도 올리지 않는다**(외톨이 파일 방지).

## 운영 배포 전 필요한 승인 항목 (CENTRAL)

```text
GOOGLE_OAUTH_CLIENT_ID=REQUIRED_OWNER_APPROVAL   저장소에 값 없음(window.B66_DRIVE_CLIENT_ID 로 주입)
AUTHORIZED_JAVASCRIPT_ORIGINS=REQUIRED           Pages 배포 오리진 등록
DRIVE_PICKER_APP_ID_AND_DEVELOPER_KEY=REQUIRED   Picker 사용 시
LIVE_DRIVE_E2E=NOT_TESTED
CROSS_BROWSER_REOPEN=NOT_TESTED
REAL_PHONE=NOT_TESTED
```

권한은 `https://www.googleapis.com/auth/drive.file` 하나만 요청한다.
전체 드라이브 목록 권한(`drive.readonly` 등)은 요청하지 않는다.
액세스 토큰은 메모리에만 두며 어떤 브라우저 저장소에도 기록하지 않는다.

## 검증 상태

오프라인(주입된 스텁)으로 검증한 항목은 `tests/quote-drive-*.test.cjs` 에 있다.

```text
SLICE_A=SOURCE_IMPLEMENTED · OFFLINE_TESTED
SLICE_B=SOURCE_IMPLEMENTED · OFFLINE_TESTED · LIVE NOT_TESTED
SLICE_C=SOURCE_IMPLEMENTED · OFFLINE_TESTED · LIVE NOT_TESTED
SLICE_D=SOURCE_IMPLEMENTED · OFFLINE_TESTED
SLICE_E=OFFLINE_TESTED(15개 시나리오)
CROSS_BROWSER_DRIVE_REOPEN=NOT_TESTED
REAL_PHONE=NOT_TESTED
PRODUCTION_DEPLOYMENT=NOT_PERFORMED
```
