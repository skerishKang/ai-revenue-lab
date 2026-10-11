# B66 — 고객 본인 Google Drive 저장·불러오기 실제 검증 런북 (#3871)

```text
DOC_STATUS=LIVE_VERIFICATION_RUNBOOK
PRODUCT=B66_STANDALONE_QUOTATIONS
ISSUE=#3871
SOURCE_MERGED=YES  (#3924/#3960/#3981; fingerprint #4007; confirm #4029 MERGED)
SOURCE_EVIDENCE=docs/products/b66/GOOGLE_DRIVE_SAVE_OPEN.md
LIVE_DRIVE_VERIFIED=CORE_SCENARIOS_PASS_REPORTED_LOCAL3
B66_ACCOUNT_PASSWORD_SIGNIN=PASS_REPORTED
B66_ACCOUNT_GOOGLE_SIGNIN=NOT_TESTED
GOOGLE_DRIVE_OAUTH_CONNECT=PASS_REPORTED
LIVE_POPULATED_DRAFT_CANCEL_HANDLER=PASS_REPORTED_STUBBED_CONFIRM_FALSE
LIVE_NATIVE_DIALOG_APPROVE=PASS_REPORTED
LIVE_NATIVE_DIALOG_CANCEL_CLICK=NOT_TESTED
QUOTECORE_IMPORT_PARITY=PASS_REPORTED
DRIVE_JSON_PDF_PAIR_EXISTENCE_OWNER=PASS_REPORTED
DRIVE_BINARY_HASH_PARITY=NOT_INDEPENDENTLY_VERIFIED
OTHER_ACCOUNT_DRIVE_SESSION_ISOLATION=PASS_REPORTED
FOREIGN_ACCOUNT_SERVER_READ_DENIAL=NOT_TESTED
CROSS_BROWSER_DRIVE_REOPEN=NOT_TESTED
LATE_OAUTH_CALLBACK=NOT_TESTED
REAL_PHONE=NOT_TESTED
LAST_CONFIRMED_PAGES_RELEASE=38006616259_SUCCESS_SHA_52b05ae4623f
```

> **2026-10-10 CENTRAL 최신 운영 기록:** Owner 승인 단일 Pages Production [run #38006616259](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38006616259) **SUCCESS**, 배포 SHA `52b05ae4623fb211c32d31fe286d8e483803330f`, OAuth 콜백 수정 #4073 포함. 이후 LOCAL3 **실브라우저 보고**로 B66 비밀번호 로그인·승인 CGI 스킬·Google Drive 동의/연결·재연결·내용 있는 초안의 **취소 처리 분기**(테스트 동안 `window.confirm = () => false` 주입 후 즉시 복구, 기존 초안/합계 보존)·**네이티브 승인**(저장 견적으로 교체, QuoteCore 680,000/68,000/748,000 일치)·Drive JSON/PDF 2쌍(총 4개) 존재 및 소유권·로그아웃·다른 계정에서 Drive 세션/이전 초안 미승계가 **PASS_REPORTED**. CENTRAL은 이 브라우저의 클릭/파일 바이트를 직접 독립 재현하지 않았음. **B66 계정 자체 Google 로그인은 미실행** (비밀번호 로그인과 Drive OAuth를 혼동 금지). 네이티브 **취소 클릭**, 직접 서버 타계정 접근 거부, 다른 실제 브라우저·실기기·late callback, 파일 전체 바이트 해시/인증 PDF 독립 확인은 **NOT_TESTED**. [#3871](https://github.com/skerishKang/ai-revenue-lab/issues/3871)은 OPEN. 아래 1절의 OAuth 클라이언트/JS 원본 부재와 미배포 기술 내용은 *구버전 초기 조사 이력*으로 보존하며 최신 운영 차단 상태가 아니다.

이 문서는 **소스 병합 이후의 실제(라이브) 검증** 절차다.
소스·오프라인 검증은 이미 완료됐고(위 `SOURCE_EVIDENCE`), 여기서는 실제 Google 계정·Drive 로만 증명할 수 있는
항목을 다룬다. **오프라인 스텁 통과를 라이브 증거로 사용하지 않는다.**

## 1. 초기 차단 사유 기록 (과거 조사 이력 · 현재 배포 상태로 해석 금지)

### 1.1 OAuth 클라이언트 재사용 인벤토리 (2026-10-10 LOCAL3 read-only 실측)

Google Cloud Console 을 **읽기 전용**으로 확인했다. 값(클라이언트 ID/시크릿)은 이 문서에 기록하지 않는다.
확인한 계정은 파디엠 운영 계정 두 개다.

| 계정 | 프로젝트 | OAuth 클라이언트 | 유형 | 승인된 JS 원본 | 승인된 리디렉션 URI | Drive API | `drive.file` 스코프 | 게시 상태 |
|---|---|---|---|---|---|---|---|---|
| padiemipu | `padiem-danjion` | `Padiem Chat Production` | 웹 애플리케이션 | **없음** | `…charliekant.workers.dev/auth/google/callback`, `chat.padiem.net/auth/google/callback` | 사용 설정 | 등록됨 | 테스트 중 |
| padiemipu | `padiem-danjion` | `DanjiOn Drive Production` | 웹 애플리케이션 | **없음** | (서버 측) | 사용 설정 | 등록됨 | 테스트 중 |
| padiemipu | `padiem-danjion` | `DanjiOn Production` | 웹 애플리케이션 | **없음** | (서버 측) | 사용 설정 | 등록됨 | 테스트 중 |
| charliekant | `my-project-padiem` | `Padiem Production Web` | 웹 애플리케이션 | **없음** | `oauth.padiem.net/v1/google/callback` | 사용 설정 | 없음 | 테스트 중 |

`Padiem Chat Production` 은 B66 로그인 브리지(`/api/padiem/auth/google/start`)가 사용하는
`PADIEM_CHAT_GOOGLE_CLIENT_ID` 후보이며, `openid email profile` 서버 측 authorization-code 흐름을 쓴다.

핵심 관측:

- 파디엠의 기존 Web OAuth 클라이언트는 **모두 `웹 애플리케이션` 유형**이다 → B66 Drive GIS 재사용 후보로 적격.
- 그러나 **어느 클라이언트에도 승인된 JavaScript 원본이 없다.** B66 Drive 는 브라우저 GIS
  (`initTokenClient`)를 쓰므로 JS 원본 등록이 필수다.
- `padiem-danjion` 프로젝트에는 **`drive.file` 스코프가 이미 등록**되어 있고 **Google Drive API 가 사용 설정**되어 있다.
- `padiem-danjion` 프로젝트는 `Padiem Chat Production`(로그인), `DanjiOn Drive Production`, `DanjiOn Production` 을
  **같은 OAuth 프로젝트에 공유**한다. 따라서 이 프로젝트의 토큰을 `/revoke` 하면 위 세 제품의 부여가 함께 무효화된다
  (§1.2 참조). 새 클라이언트를 같은 프로젝트에 만들어도 이 위험은 사라지지 않는다.

```text
EXISTING_PADIEM_WEB_OAUTH_CLIENT_REUSE=ELIGIBLE (웹 애플리케이션 유형 확인)
AUTHORIZED_JS_ORIGIN=MISSING (quick-quote-kr.pages.dev 가 어느 파디엠 클라이언트에도 미등록)
DRIVE_API_ENABLED=YES (padiem-danjion, my-project-padiem)
DRIVE_FILE_SCOPE_REGISTERED=YES (padiem-danjion)
OAUTH_APP_PUBLISH_STATUS=TESTING (외부 · padiem-danjion 테스트 사용자 0명)
GOOGLE_CONSOLE_WRITE=0
```

### 1.2 프로젝트 단위 revoke 위험 (소스 수정으로 제거함)

Google 의 토큰 철회는 클라이언트가 아니라 **OAuth 프로젝트 단위**로 적용된다.
`padiem-danjion` 처럼 여러 제품이 한 프로젝트를 공유하면, Drive 연결 해제 시 `/revoke` 를 호출하는 것만으로
같은 프로젝트의 로그인·다른 제품 부여까지 무효화된다.

이 슬라이스에서 `quote-drive-client.js` 의 일반 연결 해제/로그아웃/계정 전환/늦은 팝업 콜백에서
Google `/revoke` 호출을 **전부 제거**했다(메모리 토큰·스코프만 삭제 + 세대(epoch) 증가).
자세한 검증은 §1.3.

```text
PROJECT_WIDE_REVOKE_RISK=CONFIRMED_BY_CONSOLE_AND_GOOGLE_DOCS
ROUTINE_GOOGLE_REVOKE_CALLS=0 (소스 · 회귀 테스트로 고정)
```

### 1.3 연결 해제 안전성 (revoke-safety) 게이트

| 항목 | 요구 | 검증 |
|---|---|---|
| 일반 Drive 연결 해제 | Google `/revoke` 0회, 메모리 토큰·스코프 즉시 제거 | `tests/quote-drive-revoke-safety.test.cjs` |
| B66 로그아웃 | 로컬 Drive 세션만 비움, `/revoke` 0회 | `quote-drive-revoke-safety` · `quote-drive-ui` · `quote-drive-account-flow` |
| 계정 전환 | 즉시 격리, `/revoke` 0회, 이전 계정 접근 거부 | 위 동일 |
| 취소·지연 팝업 콜백 | 토큰 미저장, `/revoke` 0회 | 위 동일 |
| 재연결 | 같은 owner 로 정상 재연결 | 위 동일 |
| 스코프 | `drive.file` 단일 | `quote-drive-client` · `quote-drive-revoke-safety` |
| 영구(프로젝트 단위) 권한 철회 | 이 슬라이스 범위 밖(별도 승인 필요) | — |

프로젝트 전체 권한 철회가 필요하면 별도 명시 동작 + 영향 범위 검토 + Owner 승인을 거쳐야 한다.
일반 로그아웃을 Google 계정 전체 동의 철회로 바꾸지 않는다. UI 안내 문구도 이 구분을 반영한다.

### 1.4 초기 미배포 문제 (현재는 신규 Production 배포 완료)

`quick-quote-kr` Pages 프로젝트의 프로덕션 배포는 `workflow_dispatch` 게이트에서만 수행된다
(`b66-neutral-pages-beta.yml` 의 deploy 단계는 `if: github.event_name == 'workflow_dispatch'`).
main 병합 push 는 검증만 실행했고 배포하지 않았다.

확인 방법(읽기 전용):

```bash
curl -fsS "https://quick-quote-kr.pages.dev/" | grep -c 'driveStoragePanel'   # 0 = 아직 미배포
curl -fsS "https://quick-quote-kr.pages.dev/" | grep -c 'quote-drive-ui.js'   # 0 = 아직 미배포
```

**현재 정정 (2026-10-10):** 별도 Owner 승인 [run #38006616259](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38006616259)로 새 Production 배포·사후 계약 검사 **PASS**. 이 위의 웹 페이지 검사 예시는 **과거 미배포 상태를 분석하기 위한 것**이며 현재 다시 배포하라는 지시가 아니다. 실제 Drive 연결·승인/취소 처리 핵심 동작도 위 LOCAL3 보고 기준 PASS.

## 2. 초기 도입 선행 조건 (과거 설정 체크리스트; 현행 실운영은 상단 갱신 기록 우선)

```text
REUSE_FIRST=YES
  기존 파디엠 Web OAuth 클라이언트(Padiem Chat Production)를 우선 재사용한다.
  새 B66 전용 클라이언트 생성은 기본 전제가 아니다. 재사용이 부적합하거나
  자격증명 분리를 의도적으로 선택할 때만 새 클라이언트를 만든다.

REQUIRED_1=승인된 JavaScript origin 등록 (기존 클라이언트에)
  대상: Padiem Chat Production (또는 Owner 가 지정한 기존 웹 클라이언트)
  추가할 값: https://quick-quote-kr.pages.dev
  주의: 이 변경은 Google Cloud 소유자 승인이 필요하며 이 슬라이스에서 수행하지 않는다.
  등록 후 B66 Pages 환경변수 B66_DRIVE_CLIENT_ID 에 그 클라이언트 ID 를 넣는다.
  (클라이언트 시크릿은 쓰지 않는다 — 브라우저 GIS 는 공개 클라이언트 ID 만 필요하다.)

REQUIRED_2=승인된 프로덕션 릴리스 1회
  b66-neutral-pages-beta.yml workflow_dispatch (target_sha=main 정확한 SHA, confirmation 입력)

REQUIRED_3=OAuth 동의 화면 점검
  현재 padiem-danjion 앱은 게시 상태 '테스트 중'이다. B66 오리진에서 실제 승인을 받으려면
  Owner 가 테스트 사용자에 검증 계정을 추가하거나 앱 게시를 결정해야 한다.
  drive.file 스코프는 이미 등록되어 있다(민감하지 않은 범위).

OPTIONAL_4=B66_DRIVE_PICKER_APP_ID + B66_DRIVE_PICKER_DEVELOPER_KEY
  Google Picker 를 쓰는 경우에만. 없으면 앱이 제공하는 목록 선택으로 동작한다.

TEST_ASSETS=격리된 테스트 Google 계정 1개 + 테스트 견적 1건
  실제 고객 문서·계정을 사용하지 않는다.
```

금지: 같은 프로젝트에서 `/revoke` 를 호출해 다른 제품(Padiem Chat 로그인·DanjiOn)의 부여를 무효화하지 않는다(§1.3).

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
