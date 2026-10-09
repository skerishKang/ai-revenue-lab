# B66 — 고객 본인 Google Drive 저장·불러오기 실제 검증 런북 (#3871)

```text
DOC_STATUS=LIVE_VERIFICATION_RUNBOOK
PRODUCT=B66_STANDALONE_QUOTATIONS
ISSUE=#3871
SOURCE_MERGED=YES  (PR #3924 squash merge → main b5a177de3ac1e1d3e241b492cbc43922e9cd24ce)
SOURCE_EVIDENCE=docs/products/b66/GOOGLE_DRIVE_SAVE_OPEN.md
LIVE_DRIVE_VERIFIED=NOT_TESTED
CROSS_BROWSER_DRIVE_REOPEN=NOT_TESTED
REAL_PHONE=NOT_TESTED
PRODUCTION_MUTATION=0
```

이 문서는 **소스 병합 이후의 실제(라이브) 검증** 절차다.
소스·오프라인 검증은 이미 완료됐고(위 `SOURCE_EVIDENCE`), 여기서는 실제 Google 계정·Drive 로만 증명할 수 있는
항목을 다룬다. **오프라인 스텁 통과를 라이브 증거로 사용하지 않는다.**

## 1. 현재 차단 사유 (2026-10-10 기준 조사 결과)

### 1.1 B66 전용 브라우저 OAuth 클라이언트가 없다

| 조사 대상 | 결과 | B66 고객 Drive 에 재사용 가능? |
|---|---|---|
| `B66_DRIVE_CLIENT_ID` (브라우저 전역) | 저장소·배포 어디에도 값 없음 | — (이 값이 필요함) |
| `production` 환경 시크릿 `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` / `_ALLOWED_ORIGIN` / `_SEAL_KEY` | 존재함 | **불가** — B54/Engine **서버 측** OAuth(엣지 오리진·seal key·connect ticket)이며, B66 Pages 오리진이 승인 origin 으로 등록되어 있지 않다. 고객 개인 Drive 권위로 임의 전용 금지 |
| `production` 환경 시크릿 `PADIEM_CHAT_GOOGLE_CLIENT_ID` / `_SECRET` | 존재함 | **불가** — Padiem Chat 제품 OAuth |
| `.github/scripts/b54_oauth_browser_canary_contract.py` | 읽기 전용 `drive.readonly` 카나리 | **불가** — write 스코프(`drive.file` 포함)를 계약이 명시적으로 거부한다 |
| `apps/korean-ai-code-agent/.../google_drive_artifact_upload.py` | `SOURCE_ONLY`, `PRODUCTION_DRIVE_WRITE_ACTIVATED=False` | **불가** — 활성화되지 않았고 커넥터는 별도 승인 호스트가 주입한다 |
| B67 case-folder 브라우저 카나리 | 명시 승인 + 로컬 CDP 브라우저 필요 | **불가** — B67 케이스 폴더 흐름 |

결론: **B66 고객 Drive 용 브라우저 GIS 클라이언트가 저장소에 존재하지 않는다.**
기존 값을 재사용하면 제품 경계를 침범하므로, 승인된 신규(또는 B66 전용 등록) 클라이언트가 필요하다.

### 1.2 프로덕션 번들에 아직 이 기능이 없다

`quick-quote-kr` Pages 프로젝트의 프로덕션 배포는 `workflow_dispatch` 게이트에서만 수행된다
(`b66-neutral-pages-beta.yml` 의 deploy 단계는 `if: github.event_name == 'workflow_dispatch'`).
main 병합 push 는 검증만 실행했고 배포하지 않았다.

확인 방법(읽기 전용):

```bash
curl -fsS "https://quick-quote-kr.pages.dev/" | grep -c 'driveStoragePanel'   # 0 = 아직 미배포
curl -fsS "https://quick-quote-kr.pages.dev/" | grep -c 'quote-drive-ui.js'   # 0 = 아직 미배포
```

따라서 라이브 검증 전에 **승인된 프로덕션 릴리스 1회**가 필요하다(Production 활성화 = CENTRAL 보고 대상).

## 2. 선행 조건 (정확히 이 값들만 필요)

```text
REQUIRED_1=B66_DRIVE_CLIENT_ID
  형식: <project-number>-<hash>.apps.googleusercontent.com
  종류: OAuth 2.0 클라이언트 ID (웹 애플리케이션)
  승인된 JavaScript origin: B66 배포 오리진과 정확히 일치해야 한다
    (예: https://quick-quote-kr.pages.dev)
  스코프: https://www.googleapis.com/auth/drive.file  하나만

REQUIRED_2=승인된 프로덕션 릴리스 1회
  b66-neutral-pages-beta.yml workflow_dispatch (target_sha=main 정확한 SHA, confirmation 입력)

OPTIONAL_3=B66_DRIVE_PICKER_APP_ID + B66_DRIVE_PICKER_DEVELOPER_KEY
  Google Picker 를 쓰는 경우에만. 없으면 앱이 제공하는 목록 선택으로 동작한다.

TEST_ASSETS=격리된 테스트 Google 계정 1개 + 테스트 견적 1건
  실제 고객 문서·계정을 사용하지 않는다.
```

## 2b. 설정 전달 경로 (구현됨 — 운영자가 실행할 절차)

값은 저장소에 커밋하지 않는다. **`quick-quote-kr` Pages 프로젝트 환경변수**로만 주입한다.

```text
Cloudflare Pages 프로젝트(quick-quote-kr) → Settings → Environment variables (Production)
  B66_DRIVE_CLIENT_ID              = <승인된 웹 애플리케이션 클라이언트 ID>
  B66_DRIVE_PICKER_APP_ID          = <프로젝트 번호>        (Picker 사용 시에만)
  B66_DRIVE_PICKER_DEVELOPER_KEY   = <브라우저 API 키>       (Picker 사용 시에만)
```

전달 경로: `_worker.js` 의 정확한 경로 핸들러 `GET|HEAD /drive-config.js` 가 위 환경변수에서
**공개 브라우저 값만** 읽어 `window.B66_DRIVE_*` 로 내보낸다. `index.html` 은 이 경로를 Drive 모듈보다
먼저 로드한다.

```text
- 값이 없거나 형식이 틀리면 빈 문자열 → 기능 비활성(연결 버튼 비활성)
- 형식: 클라이언트 ID 는 <...>.apps.googleusercontent.com, Picker App ID 는 숫자, 키는 영숫자/._-
- 응답: Content-Type: application/javascript; charset=utf-8, Cache-Control: no-store, nosniff
- GET/HEAD 만 허용(그 외 405, Allow: GET, HEAD). 오류 응답에도 값을 담지 않는다.
- 자격증명·토큰·서버 시크릿은 어떤 경우에도 내보내지 않는다.
```

### 값 노출 없이 주입을 확인하는 방법

```bash
# 1) 설정이 전달되는지: 값 자체를 출력하지 않고 "비어 있지 않은지"만 확인한다.
curl -fsS -H 'Cache-Control: no-cache' https://quick-quote-kr.pages.dev/drive-config.js \
  | grep -E '^window\.B66_DRIVE_[A-Z_]+ = ".*";$' \
  | sed -E 's/= ".*";/= "<non-empty>";/'      # 빈 문자열이면 아직 미설정

# 2) 헤더 계약 확인
curl -fsSI https://quick-quote-kr.pages.dev/drive-config.js \
  | grep -iE '^(content-type|cache-control|x-content-type-options):'

# 3) HEAD 는 본문이 없어야 한다
curl -fsSI https://quick-quote-kr.pages.dev/drive-config.js | head -1

# 4) 허용되지 않은 메서드는 405 여야 한다
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://quick-quote-kr.pages.dev/drive-config.js
```

**값을 화면·로그·이슈에 그대로 출력하지 않는다.** 위 명령은 값의 존재 여부만 본다.

배포는 `b66-neutral-pages-beta.yml` 의 `workflow_dispatch` 게이트로만 수행한다(정확한 main SHA + 확인 문구 입력).
환경변수를 추가한 뒤에는 **재배포 1회**가 필요하다.

## 3. 검증 절차

### STEP 1 — 연결 준비 확인

```bash
# 배포된 페이지에서 설정 상태를 확인한다(값은 화면에 노출되지 않는다).
# 설정이 없으면 패널이 "필요한 설정이 없습니다: B66_DRIVE_CLIENT_ID" 를 표시한다.
```

- `B66_DRIVE_CLIENT_ID` 가 채워지고 형식이 맞으면 연결 버튼이 활성화된다.
- 형식이 틀리면 "설정값 형식이 올바르지 않습니다: B66_DRIVE_CLIENT_ID" 로 구분해 표시된다.

### STEP 2 — 실제 저장 (브라우저 A)

```text
1  B66 정상 로그인 (승인된 B66 계정)
2  개인 설정 → '내 Google Drive 연결' → Google 동의 화면에서 drive.file 만 승인
3  견적 작성 → 인증된 CGI PDF 생성 가능 상태 확인
4  '내 Google Drive에 저장' → JSON + PDF 한 쌍 저장
5  Drive 에서 두 파일의 존재·소유자(내 계정)·내용 확인
6  같은 견적을 다시 저장해 중복 파일명이 -2 로 늘어나고 기존 파일이 덮어써지지 않는지 확인
7  PDF 저장만 실패하도록 유도(예: 저장공간 부족)해 부분 실패가 화면에 보고되는지 확인
```

증거로 남길 것: 저장된 파일 2건의 **이름·ID·소유자·수정시각**, 부분 실패 시 표시된 문구,
JSON 파일을 다시 열었을 때의 `kind=b66.quote-package`, `contract=b66.quote-drive.v1`,
`totalsAuthority=quote-core` 값. **고객 문서 내용·토큰은 기록하지 않는다.**

### STEP 3 — 다른 브라우저에서 불러오기 (브라우저 B)

```text
1  다른 실제 브라우저에서 같은 Google 계정으로 B66 로그인
2  'Google Drive에서 열기' → 파일 선택
3  원래 견적 내용과 승인 템플릿이 복원되는지 확인
4  수량·단가 수정 → QuoteCore 가 공급가액·VAT·총액을 다시 계산하는지 확인
5  변경 후 인증 PDF 생성
6  불러오기 실패를 유도(예: 다른 승인 템플릿 선택 상태)해
   작성 중 견적과 템플릿이 그대로 남는지 확인
```

### STEP 4 — 계정·데이터 안전성

```text
1  로그아웃 후 Drive 접근 거부
2  다른 B66 계정으로 전환 시 기존 Drive 연결 해제·격리
3  다른 Google 계정이 소유한 파일 접근 거부
4  OAuth 팝업 대기 중 로그아웃 → 뒤늦은 토큰이 연결되지 않음
5  업로드 부분 실패 후 재시도(같은 쌍 유지)
6  불러오기 실패 시 편집기 내용·템플릿 원상 유지
```

### STEP 5 — 실제 휴대전화

실기기에서 같은 Google 계정으로 파일을 열고 수정한다.
불가능하면 `REAL_PHONE=NOT_TESTED` 로 보고한다. **데스크톱 모바일 에뮬레이터를 실기기 증거로 쓰지 않는다.**

## 4. 금지 사항

- 실제 고객 데이터·문서 수정·삭제
- 운영 OAuth 클라이언트·origin·시크릿 임의 생성·변경
- 저장소에 클라이언트 ID/키 값 커밋
- `drive.file` 외 스코프 요청
- Google Drive 를 필수 저장소로 만들거나 D1(#3405)을 대체
- Google Sheets 변환·모델 호출을 저장·불러오기 경로에 도입
- 오프라인 스텁 통과를 라이브 PASS 로 보고

## 5. 보고 형식

```text
LIVE_GOOGLE_OAUTH=
DRIVE_FILE_SCOPE=
JSON_SAVE=
CERTIFIED_PDF_SAVE=
JSON_PDF_PAIR_VERIFIED=
CROSS_BROWSER_REOPEN=
EDITOR_ROUND_TRIP=
QUOTECORE_RECALCULATION=
ACCOUNT_ISOLATION=
IMPORT_ATOMICITY=
PARTIAL_FAILURE_RECOVERY=
REAL_PHONE=
PRODUCTION_MUTATION=NO
```

검증하지 못한 항목은 추정 PASS 없이 `BLOCKED`(선행 조건 명시) 또는 `NOT_TESTED` 로 기록한다.
