# B66 — 고객 본인 Google Drive 저장·불러오기 구현 계약 (#3871)

```text
DOC_STATUS=IMPLEMENTATION_SOURCE_AND_OFFLINE_TESTS (CENTRAL review round 1 반영)
PRODUCT=B66_STANDALONE_QUOTATIONS
ISSUE=#3871
OWNER_DECISION_DOC=QUOTE_STORAGE_STRATEGY.md
EXISTING_D1_HISTORY_OWNER=#3405
D1_HISTORY_CHANGED=NO
LIVE_DRIVE_VERIFIED=NOT_TESTED
CROSS_BROWSER_DRIVE_REOPEN=NOT_TESTED
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
| `reference/business-66-padiem-quote-v1/quote-drive-contract.js` | 버전 명시 JSON 스키마, 내용 지문, 필드 단위 무손실 검증, JSON·PDF 연결 매니페스트, 파일명/중복 규칙, 크기·형식·스키마 검증, 부분 실패 결과 모델과 재시도 쌍 고정, QuoteCore 재계산 |
| `reference/business-66-padiem-quote-v1/quote-drive-client.js` | Google OAuth(GIS) + Drive API v3 통신, 최소 권한 `drive.file`, Picker, **소유권 fail-closed 검증**, 페이지 전체 조회, 세션 epoch, 부분 실패 복구 |
| `reference/business-66-padiem-quote-v1/quote-drive-ui.js` | **1회성 시작 훅(자동 mount)**, 저장/불러오기/연결 상태/부분 성공 표시, **B66 로그아웃·계정 전환 시 Drive 토큰 폐기**, 승인 템플릿 확인 후에만 편집기 적용, Picker 경로 |
| `reference/business-66-padiem-quote-v1/app.js` | 외부 저장용 인증 PDF 바이트 seam(`certifiedPdfBytes`)과 승인 Skill 목록(`listApprovedSkills`) 추가. 기존 다운로드 경로는 변경 없음 |

## 시작 훅 (고객이 실제로 버튼을 본다)

`quote-drive-ui.js` 가 로드될 때 스스로 `installStartHook(window, api)` 를 호출한다.

```text
DOMContentLoaded(또는 이미 로드됨) → bootstrap()
bootstrap() → B66QuoteAppBridge 존재 확인 → 있으면 1회 mount
            → 없으면 250ms 간격 최대 40회 재시도 후 bridge_unavailable 로 포기
mount 결과는 window.B66QuoteDriveUiInstance 로 노출
재호출해도 기존 인스턴스를 그대로 돌려준다(중복 mount 없음)
```

시작 훅이 실패해도 기존 견적 작성 흐름은 막지 않는다.

## 저장 데이터 계약 (`b66.quote-drive.v1`)

```text
kind               = b66.quote-package
contract           = b66.quote-drive.v1
schemaVersion      = 1
packageId          = JSON 과 PDF 를 묶는 한 쌍 식별자
contentFingerprint = 견적 편집 데이터 + 템플릿 권위(savedSkillId/fingerprint) 지문
quote              = QuoteDraft 전체(detailGroups · calculationPolicy · meta.projectName 포함)
template           = { savedSkillId, fingerprint, rendererContract } 참조(값이 아님)
assets             = { json: {...}, pdf: {...} } 두 파일 모두 같은 packageId
manifest           = 표시용 메타데이터(quoteNo/issueDate/거래처/항목 수/저장 시각)
totalsAuthority    = quote-core      (다른 값이 오면 명시 거부)
totals             = null            (저장된 합계는 쓰지도 읽지도 않는다)
```

### 무손실은 필드 단위로 증명한다

`assertLosslessDraft()` 가 편집 데이터의 **모든 필드**를 나열해(`meta` 5, `sender` 8, `recipient` 4,
`items[]` 각 7, `detailGroups[].items[]` 각 8, `tax` 2, `memo`, `calculationPolicy` 2 …) 원본과
정규화 결과를 하나씩 비교한다. 다른 필드가 하나라도 있으면 그 경로를 `lost` 로 보고한다.

- 저장 경로: 손실이 감지되면 `draft_lossy_round_trip` 로 **저장을 거부**한다.
- 읽기 경로: 손실이 감지되면 `quote_lossy_round_trip` 로 **불러오기를 거부**한다.
- `contentFingerprint` 가 없거나 재계산 값과 다르면 `content_fingerprint_missing` /
  `content_fingerprint_mismatch` 로 거부한다(견적 본문·수량·단가·상세내역 변조 탐지).

### 기존 D1 스냅샷(`b66.quote-draft.v1`)과의 차이

`quote-history-server.js` 의 D1 스냅샷은 `detailGroups` 와 `calculationPolicy` 를 보존하지 않는다.
**#3405 의 기존 동작은 그대로 유지**하며, 고객 Drive 계약만 그 값들을 포함한 무손실 독립 계약으로
새로 정의한다. D1 을 대체하지 않는다.

### 거부 정책(명시 거부, 조용한 보정 없음)

| 상황 | 코드 |
|---|---|
| JSON 손상 / 빈 값 | `invalid_json`, `invalid_json_text` |
| 프로토타입 오염 키 | `unsafe_json_key` |
| 다른 문서 종류 | `package_kind_unsupported`, `contract_unsupported` |
| 지원하지 않는 스키마 버전(구버전·미래 버전) | `schema_version_unsupported`, `schema_version_newer_than_supported` |
| 크기 초과 | `json_too_large`, `pdf_too_large`, `pdf_too_small` |
| PDF 형식 아님 | `pdf_format_invalid` |
| 합계 권위를 quote-core 가 아닌 값으로 선언 | `totals_authority_unsupported` |
| 파일 안의 신원 주장 필드 | `unsupported_package_field`(허용 목록 밖) |
| 견적 본문 변조 | `content_fingerprint_mismatch` |
| 편집 데이터 손실 | `quote_lossy_round_trip`, `draft_lossy_round_trip` |
| 소유 정보 없음/비어 있음 | `drive_file_ownership_unverified` |
| 다른 계정 소유 | `drive_file_not_owned_by_connected_account` |
| 다운로드 불가 | `drive_file_not_downloadable` |
| 휴지통 / 없음 / 권한 없음 | `drive_file_trashed`, `drive_file_not_found`, `drive_file_access_denied` |
| 로그아웃·미연결 | `drive_not_connected` |
| 연결 진행 중 중복 시작 | `drive_connect_in_progress` |
| 팝업 대기 중 계정 변경으로 폐기된 연결 | `drive_auth_superseded` |
| 토큰 만료 / 401 | `drive_token_expired` |
| 계정 변경으로 취소된 in-flight 응답 | `drive_session_changed` |
| 이름 점검 불가/불완전 | `naming_check_unavailable`, `naming_check_incomplete` |

파일 안의 사용자 ID·이메일은 **접근 권한의 근거로 쓰지 않는다.** 권한 근거는 항상
연결된 Google 세션과 Drive 가 돌려준 **소유 정보**(`owners[].me === true`)다.
소유 정보가 없거나 비어 있으면 **허용하지 않는다(fail-closed)**. 본문(`alt=media`)은
소유 검증을 통과한 뒤에만 내려받는다.

## 계정 격리

- Drive 토큰은 모듈 메모리 클로저에만 존재하며 어떤 브라우저 저장소에도 기록하지 않는다.
- Drive 세션은 **B66 계정 권위가 유지되는 동안에만** 보존한다.

| 신호 | 처리 |
|---|---|
| `b66:auth-changed` `authenticated=true` (로그인·세션 갱신, action 없음) | **세션 유지** — 계정 전환으로 오인하지 않는다 |
| `b66:account-scope-changed` action `owner_bound` / `same_account_resume` | **세션 유지** |
| `b66:auth-changed` `authenticated=false` | 즉시 폐기 (`b66_signed_out`) |
| `b66:account-scope-changed` `authenticated=false` | 즉시 폐기 (`b66_account_authority_lost`) |
| action `quarantined_foreign_owner` / `quarantined_malformed_owner` | 즉시 폐기 (`b66_account_changed`) |
| action `authenticated_owner_unusable` / `unresolved` | 즉시 폐기 |
| action 을 알 수 없음(예: 저장소 읽기 실패) | 안전하게 폐기 |

- 다른 계정으로 로그인한 경우에는 뒤이어 오는 `account-scope-changed`(`quarantined_foreign_owner`)가
  계정 변경을 알려 준다. 따라서 `auth-changed` 만으로 폐기할 필요가 없다.
- **폐기는 세션이 연결되어 있지 않아도 항상 수행한다.** 그래야 OAuth 팝업이 떠 있는 동안의
  로그아웃/계정 전환이 뒤늦게 도착한 토큰을 무효화한다.
- 폐기할 Drive 세션이나 보류 작업이 없으면 화면에 경고를 띄우지 않는다(로그아웃 상태의
  페이지 로드마다 알림이 반복되지 않는다).

### OAuth 팝업과의 경합(보안)

```text
connect() 시작 → 세대(epoch) 캡처
   ↓ 팝업 대기 중 B66 로그아웃/계정 전환 → 세대 증가
콜백 도착 → 세대 불일치 → 토큰을 저장하지 않고 즉시 폐기 요청
          → 결과 drive_auth_superseded, 세션 없음
```

- 연결이 진행 중일 때 중복 시작은 `drive_connect_in_progress` 로 거부한다.
- 세션 epoch 이 바뀐 뒤 도착한 in-flight 응답은 편집기나 화면 상태를 갱신하지 못한다
  (`drive_session_changed`).

## 부분 실패와 재시도

| 상태 | 의미 |
|---|---|
| `complete` | JSON + PDF 모두 저장 |
| `partial_json` | JSON 만 저장. 메시지 표시 + PDF 만 재시도 |
| `partial_pdf` | PDF 만 저장. 메시지 표시 + JSON 만 재시도 |
| `failed` | 둘 다 실패 |

부분 성공은 `ok=false` 이며 화면에 반드시 표시된다. 부분 결과에는 **원래 쌍이 고정**된다.

```text
pair = { packageId, createdAt, jsonName, pdfName, baseName, renamed,
         draftFingerprint, pdfFingerprint }
```

재시도는 이 고정값만 사용한다.

- 파일명을 **재계획하지 않는다**(원래 이름을 그대로 쓴다).
- 견적 내용이 바뀌었으면 `pending_pair_stale`, PDF 가 바뀌었으면 `pending_pdf_changed` 로 중단하고
  새 견적서로 저장하도록 안내한다.
- 유지된 파일이 아직 존재하고 소유되어 있는지 확인한 뒤에만 완료를 주장한다
  (`kept_file_unavailable`).
- 고정 이름이 이미 점유되었으면 이름을 바꾸지 않고 `duplicate_name_conflict` 로 중단한다.
- PDF 바이트가 처음부터 잘못되면 **아무것도 올리지 않는다**(외톨이 파일 방지).

## 파일명과 목록

- 파일명: `견적서_{quoteNo}_{거래처}.json` / `.pdf`. 제어문자·`\ / : * ? " < > |` 제거, 길이 제한.
- 중복 시 기존 파일을 **덮어쓰지 않고** `-2`, `-3` … 접미사. 상한(999) 초과 시 `duplicate_name_limit`.
- 저장 전 목록을 **`nextPageToken` 으로 끝까지** 조회한다(최대 10페이지). 잘렸으면 저장을 거부한다.
- 계획한 이름을 업로드 직전에 이름 질의로 다시 확인한다(그 사이 생성된 파일 대비).
- 이름 점검이 실패하면 `taken=[]` 로 넘어가지 않고 **저장을 거부한다(fail-closed)**.

## 불러오기와 템플릿 권위

```text
파일 선택(목록 또는 Picker) → 메타데이터 조회 → 소유·다운로드 권한 검증 → 크기 검사
→ alt=media → 계약 검증(스키마·버전·크기·신원필드·프로토타입·무손실·내용지문)
→ QuoteDraft 복원 → QuoteCore 재계산 → 현재 인증된 승인 Skill 목록으로 템플릿 권위 확인
→ replaceDraft 결과 확인 → getDraft 재확인(내용 지문 일치) → 성공 표시
```

- 승인 템플릿 권위를 확인할 수 없으면(`none`/`unresolved`/`inactive`/`mismatch`)
  **편집기에 적용하지 않고** 안내를 표시한다. 다른 양식으로 자동 대체하지 않는다.
- **다른 승인 템플릿의 견적**: 불러온 견적의 승인 양식(`savedSkillId` + `fingerprint`)이 지금 편집기에
  선택된 양식과 다르면 **편집 내용을 바꾸지 않고** 안내를 표시한다. 양식을 자동으로 전환하지 않는다.
  사용자가 해당 양식을 선택한 뒤 다시 열어야 한다.
- **편집 중 내용 보호**: 현재 견적에 작성 중인 내용이 있으면(`hasMeaningfulDraft`)
  명시적 확인을 받은 경우에만 교체한다. 확인 수단이 없으면 교체하지 않는다(fail-safe).
  빈 편집기이고 양식이 같을 때만 확인 없이 적용한다.
- `replaceDraft` 가 실패/예외를 돌려주면 성공으로 표시하지 않는다.
- 적용 뒤 `getDraft()` 로 되읽어 내용 지문이 일치할 때만 성공을 표시한다.
- 파일 선택기는 `appId`/`developerKey` 가 설정된 경우에만 열리고, 없으면 목록 선택으로 대체한다.

## 운영 배포 전 필요한 승인 항목 (CENTRAL)

```text
GOOGLE_OAUTH_CLIENT_ID=REQUIRED_OWNER_APPROVAL   저장소에 값 없음(window.B66_DRIVE_CLIENT_ID 로 주입)
AUTHORIZED_JAVASCRIPT_ORIGINS=REQUIRED           Pages 배포 오리진 등록
DRIVE_PICKER_APP_ID_AND_DEVELOPER_KEY=REQUIRED   Picker 사용 시(window.B66_DRIVE_PICKER_APP_ID / _DEVELOPER_KEY)
LIVE_DRIVE_E2E=NOT_TESTED
CROSS_BROWSER_REOPEN=NOT_TESTED
REAL_PHONE=NOT_TESTED
```

권한은 `https://www.googleapis.com/auth/drive.file` 하나만 요청한다.
전체 드라이브 목록 권한(`drive.readonly` 등)은 요청하지 않는다.

## 검증 상태

오프라인(주입된 스텁)으로 검증한 항목은 `tests/quote-drive-*.test.cjs` 에 있다.

```text
SLICE_A=SOURCE_IMPLEMENTED · OFFLINE_TESTED
SLICE_B=SOURCE_IMPLEMENTED · OFFLINE_TESTED · LIVE NOT_TESTED
SLICE_C=SOURCE_IMPLEMENTED · OFFLINE_TESTED · LIVE NOT_TESTED
SLICE_D=SOURCE_IMPLEMENTED · OFFLINE_TESTED
SLICE_E=OFFLINE_TESTED(확장 시나리오)
CROSS_BROWSER_DRIVE_REOPEN=NOT_TESTED
REAL_PHONE=NOT_TESTED
PRODUCTION_DEPLOYMENT=NOT_PERFORMED
```
