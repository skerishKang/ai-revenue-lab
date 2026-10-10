# B66 CGI 첫 고객 MVP — Production 배포 및 고객 인수 기준 (2026-10-10 KST)

> **CENTRAL 시점별 스냅샷.** 제품 원칙은 [B66 README](README.md), [SOURCE_TEMPLATE_FIDELITY](SOURCE_TEMPLATE_FIDELITY.md), 각 이슈가 우선한다. 이 문서는 특정 배포 및 검증 상태를 기록하며 이후 `main` 이동이 과거 배포 SHA를 바꾸지 않는다.

## 결론

- **기존 1차 MVP 인수 게이트 [#3521](https://github.com/skerishKang/ai-revenue-lab/issues/3521)는 CLOSED**, Guided·Free-form·견적 결과·미리보기·PDF 기본 여정의 기존 수용 기록이 있다. 이를 이유 없이 다시 OPEN하거나 통합 고객 인수를 완료했다고 주장하지 않는다.
- **현재 추가 고객 인수 [#4076](https://github.com/skerishKang/ai-revenue-lab/issues/4076)는 OPEN.** LOCAL3는 새 Production에서 **B66 비밀번호 로그인 + Drive 연결/기존 견적 승인·취소 처리/재계산·로그아웃** 실브라우저 E2E를 PASS로 보고했다. LOCAL2 고객 Guided/Free-form/D1 수용, B66 계정 Google 로그인(별도 경로), LOCAL1 Sol 4+품목 인증은 아직 미완료다.
- **B66 Pages Production 배포는 새 코드로 완료.** Owner 승인 후 수동 [Actions #38006616259](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38006616259) `workflow_dispatch` 한 번 실행, 대상 커밋 `52b05ae4623fb211c32d31fe286d8e483803330f`, 배포 작업·사후 계약 검사 **둘 다 SUCCESS**. 이전 확인된 Production `ee11c1cbe...`보다 최신이다.
- 배포된 버전에는 [#4073](https://github.com/skerishKang/ai-revenue-lab/pull/4073) OAuth 콜백 `state/code` 쿼리 보존이 포함된다. 중복 Draft [#4074](https://github.com/skerishKang/ai-revenue-lab/pull/4074)는 **CLOSED, UNMERGED**; LOCAL3 실측 증거·커밋은 보존한다.
- **운영 검증 진전 (LOCAL3 보고, 중앙에서 별도 재현하지 않음):** B66 계정 **비밀번호 로그인**, 승인 CGI 스킬, Google **Drive OAuth 연결**, 편집 중인 초안의 취소 처리 분기(임시 `confirm(false)`), 실제 대화상자 승인·견적 교체·QuoteCore 재계산, JSON/PDF 2쌍 존재/소유권, 로그아웃·다른 계정 UI 세션 분리 **PASS_REPORTED**. B66 계정 자체의 **Google 로그인**, 네이티브 취소 버튼, 서버 직접 타 계정 읽기 차단, 다른 브라우저·폰·late-callback은 **NOT_TESTED**. 파일 쌍 존재 확인은 PDF 바이트/서명·시각 인증과 구분한다.

## LOCAL2 고객 여정 오프라인 통합 인수 업데이트 — 2026-10-10 KST

- **[PR #4088](https://github.com/skerishKang/ai-revenue-lab/pull/4088) SQUASH MERGED** `c5c4d0345f7ab47bdde5add4113dc5b05eff5ede`, 원 HEAD `b12b4d80cf0b61eaf88e444e60adeebcb0f7c3bb`, exact-head CI **9 SUCCESS / 16 의도적 SKIPPED / 0 FAILURE**. 527줄 브라우저 고객 여정 Python 하네스와 **기존** B66 PDF Preview Parity workflow의 한 스텝만 추가, 신규 CI lane 없음. 고객 앱/Worker/PDF/Drive/Engine/Control Plane 코드는 변경되지 않았다.
- **확인된 성공 범위는 `OFFLINE_BROWSER_INTEGRATION=PASS`:** loopback Chromium에서 승인 CGI 스킬·회사정보 준비/재접속, 정확한 모델 ID 수동 선택 및 기본 추론값 wire 생략, Free-form 완성형, 누락 단가 한 번 질문 후 정확한 사용자 단가 반영, QuoteCore 합계, Guided 수량 편집 시 모델 0호출, PDF 엔드포인트 POST(브라우저 인쇄 폴백 없음), B66 견적이력 API 클라이언트 동작을 검증했다. 공급자 호출·실 계정·실 Google 로그인·Production 호출은 0건.
- **범위를 과장하지 않는다:** 인터프리터는 스크립트 스텁, PDF 응답은 실제 Sol PDF가 아니라 `%PDF-1.4 / %certified-sol-stub` 테스트 바이트, D1 데이터도 실 DB 대신 스텁의 `/b66/quotes` JSON이다. 다른 계정 테스트는 실제 계정을 바꾸지 않고 스텁 응답을 빈 배열로 변경한 검사다. 따라서 `LIVE_REAL_B14 / ACTUAL_SOL_PDF_BYTES / ACTUAL_D1_PERSIST_REOPEN / SERVER_FOREIGN_ACCOUNT_DENIAL` 모두 **NOT_TESTED_BY_4088**.
- **증거 보존:** CENTRAL은 원격 `E:\local2-4076-evidence\`에서 PNG 7장과 보고서 존재를 확인했다. 다만 `06-d1-recent.png`와 `07-foreign-account-empty.png`의 SHA-256 해시가 **동일**하여, 서로 다른 계정 화면을 보여 주는 독립 시각 증거로 사용할 수 없다. LOCAL2가 보고한 Google Drive 업로드 `403 storageQuotaExceeded`는 보조 보고서 업로드 실패이며 인수 하네스나 B66 고객 Drive 서비스의 실패로 혼동하지 않는다. 기존 로컬 원본을 보존하고 업로드 재시도를 인수 차단으로 만들지 않는다.
- **운영·인수:** #4088은 테스트 전용 소스 병합이며 이 PR로 Production 새 배포를 수행하거나 필요하다고 판단하지 않는다. LOCAL2는 [#4076](https://github.com/skerishKang/ai-revenue-lab/issues/4076)에서 승인된 계정 실제 Guided/Free-form/후속 질문/1~3행 Sol PDF/D1 API 고객 여정 수용을 이어 간다. LOCAL1 [#3839](https://github.com/skerishKang/ai-revenue-lab/issues/3839) Sol v2 시각 인증, LOCAL3 [#3871](https://github.com/skerishKang/ai-revenue-lab/issues/3871) Drive 후속 검증은 별도. **`FULL_CGI_MVP_HANDOFF=NOT_READY`**.

## Sol CGI v2 통합 소스 및 기술 인증 패킷 — 2026-10-10 KST

- **[PR #4111](https://github.com/skerishKang/ai-revenue-lab/pull/4111) SQUASH MERGED** `66a34b5796e48bd16959a31e5be98cbcbd6cdbbd`: #4001 오른쪽 외곽선 + #4092 내부 세로선/합계 밴드 수정. #4010 얇은 단일 선 변경은 **원본 양식 충실도 우선으로 제외·CLOSED/UNMERGED**. 원본 인증 Sol v1 파일 0개 변경.
- **검증:** exact-head CI 4 workflows SUCCESS, 7 checks SUCCESS+16 path skips; CENTRAL 원격 Windows 기하/원본 계약 63 PASS/6 SKIP/5 제외 및 실제 Sol PDF 집중 19 PASS. 새 통합 소스로 1/2/3/4/8/25/100품목 실 PDF 생성, PDF 해시 일치·QuoteCore 합계·페이지 1/1/1/2/2/4/11 검증. 1~3 인증 해시는 기존 v1과 동일. 자세한 파일별 SHA·판정 범위는 [Sol v2 기술 인증 패킷](SOL61_MULTIPAGE_V2_CERTIFICATION_CHECKPOINT_2026-10-10.md) 참조.
- **구분:** `SOURCE_INTEGRATED=YES`, `REAL_PDF_OFFLINE_PROVEN=YES`, **`NEW_V2_CERTIFICATE=NO` / `PRODUCTION_V2_ACTIVE=NO` / `CUSTOMER_E2E=NOT_TESTED`**. Owner가 새로운 다중페이지 원본 양식 차이·허용 오차를 확정하고, 별도 버전 인증서를 발급·운영 라우트에서 확인한 후 #4076 실로그인 견적 여정을 검증해야 한다. 기존 배포 SHA `52b05ae...`는 변경하지 않았다.

## 1. 확정된 릴리스 근거

| 구분 | 결과 / 근거 |
|---|---|
| 저장소·배포 환경 | `skerishKang/ai-revenue-lab`, B66 독립 Pages `quick-quote-kr` (`main` Production) |
| 검증된 배포 SHA | `52b05ae4623fb211c32d31fe286d8e483803330f` (시점별 고정값; 현재 HEAD 별개) |
| Owner 승인·수동 배포 | [#38006616259](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38006616259) · `workflow_dispatch` · **1회** · SUCCESS |
| 배포 전 | exact-main 일치, B66 전체 JS 56개, 인증·Pages 프로젝트 존재·배포 간격 검사 PASS |
| 배포 후 | Pages 배포·고객 UI 정적 바이트 확인 PASS, B66 계약·서버 intake adapter·로컬 HTTP smoke PASS |
| URL | 안정 주소: https://quick-quote-kr.pages.dev/ · 실행 기록의 불변 배포 주소: https://6c937f60.quick-quote-kr.pages.dev/ |
| 공개 읽기 전용 확인 | 안정 메인 HTML, `/drive-config.js` JS, `/api/padiem/auth/status` JSON, 불변 배포 주소 메인 HTML 모두 **HTTP 200** |
| 실 사용자 인증 | LOCAL3 **B66 비밀번호 로그인 PASS_REPORTED**, 승인 CGI 스킬 확인. **B66 계정 Google 로그인 NOT_TESTED**. Drive OAuth 연결은 별도 PASS_REPORTED |
| 실제 Google Drive JSON/PDF Save/Open | **새 배포 LOCAL3 주요 E2E PASS_REPORTED:** Drive 연결·재연결, 내용 있는 초안의 취소 처리 분기/실제 승인·QuoteCore 재계산, JSON/PDF 2쌍 소유자 확인, 세션 격리. 다른 브라우저/실기기/late-callback·직접 서버 차단·파일 바이트 검증은 NOT_TESTED |
| Production 외 변경 | 이 배포 작업에서 Google Cloud 설정/Secrets/B14/Engine/다른 제품·유료 호출·Sol v2 활성화 **없음** |

**검증 용어:** `SOURCE_MERGED`, `OFFLINE_CI_PASS`, `PRODUCTION_DEPLOYED`, `LIVE_USER_E2E_PASS`, `CERTIFIED_RENDERER`는 독립된 게이트이다. API 응답 200·MockTransport·배포 성공을 실제 OAuth 완료나 PDF 시각 인증으로 전용하지 않는다.

## 2. 고객 인수 범위와 증거 상태

| 고객 기능 | 현재 근거 | 고객 인수 시 필요한 마지막 증거 | 담당 |
|---|---|---|---|
| B66 독립 URL 및 접근 | Production 진입 화면 HTTP 200 | 실제 사용자 화면·반응형 실행 | LOCAL2 |
| Google 로그인/재로그인 | [#4073](https://github.com/skerishKang/ai-revenue-lab/pull/4073) 병합+새 운영 배포, LOCAL3의 Google Console redirect URI 등록 보고 | 새 운영 브라우저에서 start→Google→callback→signed-in 실성공; `redirect_uri_mismatch`/`invalid_oauth_state` 없음 | LOCAL3 [#3871](https://github.com/skerishKang/ai-revenue-lab/issues/3871) |
| 기본 CGI Saved Quote Skill / 단계별 작성 | 기존 [#3521](https://github.com/skerishKang/ai-revenue-lab/issues/3521) 수용 | 현행 승인 계정에서 1건 입력·수정·결과 | LOCAL2 |
| 자연어 완성형 및 단가 누락 후속 질문 | [#3391](https://github.com/skerishKang/ai-revenue-lab/issues/3391) CLOSED / 코드 검증 | 새 Production 완성형 1건과 부분형→추가 질문→동일 견적 완성 | LOCAL2 |
| 금액·세금·PDF 출력 | QuoteCore 단일 계산 권위, 기존 Sol **1~3품목 인증** | 실제 인증된 Sol PDF의 금액·로고·도장·무숨김 이전 데이터, 다운로드 | LOCAL2 |
| **4품목 이상·다중 페이지 PDF** | [#4001](https://github.com/skerishKang/ai-revenue-lab/pull/4001), [#4010](https://github.com/skerishKang/ai-revenue-lab/pull/4010) Draft, 오른쪽 외곽선 벡터 검사 부분 PASS | 중간 페이지 내부 열선·마지막 합계 격자 수정, 4/8/25/100행 동일 Sol v2 재인증·실고객 E2E, 1~3 v1 불변 | LOCAL1 [#3839](https://github.com/skerishKang/ai-revenue-lab/issues/3839) |
| D1 최근 견적 / 다른 브라우저 | 브라우저 로컬 이력 존재, [#3405](https://github.com/skerishKang/ai-revenue-lab/issues/3405) OPEN | 서버 D1 저장·재로그인·다른 브라우저 재열기·복사 새 번호·계정 격리 | LOCAL2 |
| 고객 본인 Google Drive | **새 Production LOCAL3 보고:** 기존 내용 있는 견적에서 취소 처리 분기 초안/합계 보존 PASS, 실제 대화상자 승인으로 견적 교체 및 QuoteCore 680,000+68,000=748,000 일치 PASS, JSON/PDF 파일 2쌍·로그아웃·다른 계정 UI 세션 격리 PASS | **네이티브 취소 클릭, 새 브라우저, 실기기, late-callback, 서버 타계정 403/404, 파일 바이트 해시 등은 NOT_TESTED**. B66 계정 자체 Google 로그인도 별도 | LOCAL3 [#3871](https://github.com/skerishKang/ai-revenue-lab/issues/3871) |
| 고객 전달 패키지 | [#4076](https://github.com/skerishKang/ai-revenue-lab/issues/4076) 신설 | 개인정보 제거된 시연 흐름·화면 증거·제약·승인한 출력 범위·연락/재현 절차 | LOCAL2 + CENTRAL |

**PDF Owner lock:** 김범신 CGI 출력에는 **기존 Sol 6.1에서 출발한 단일 승인 구현만** 사용한다. 3품목 초과를 HTML 인쇄/GLM/모델 생성 PDF로 대체할 수 없다. Sol은 최초 템플릿 분석·엔지니어링, 반복 출력은 **결정적 코드 + QuoteCore**(PDF 출력 모델 호출 0). 자동 범용 원본 학습기·두 번째 고객 양식 인증·고객 원본 R2 보관·음성 입력은 이번 CGI 고객 인수를 자동 차단하는 조건이 아니다.

## 3. 병렬 업무 경계

1. **LOCAL1 = #3839 Sol 네이티브 4+품목/다중 페이지**: 기존 #4001/#4010을 조사, 수정본 시각·벡터·해시 검증, v2 인증 후보를 CENTRAL에 제출. 승인·병합·Production 활성화 전까지 v1 인증 보호. 완료 전 "전체 품목 PDF 완성" 금지.
2. **LOCAL2 = #4076 고객 MVP 실제 여정 + #3906 B66 측**: 새 독립 작업트리에서 운영 브라우저 로그인 기반 Guided/Free-form/단가 누락/QuoteCore/실제 PDF/D1. #3839 v2 인증 이후 4+ 행 통합. shared Core·Sol 양식·LOCAL3 OAuth/Drive 작업 불침범.
3. **LOCAL3 = #3871 Google OAuth 및 고객 Drive**: 새 배포에서 비밀번호 B66 로그인·Drive 연결·기존 초안 취소 처리/실제 승인·파일쌍/QuoteCore·세션 격리를 **보고 PASS**. 다음은 B66 자체 Google 로그인, 다른 브라우저·실기기·late-callback, 네이티브 취소 클릭·서버 격리 증명. **#4074 중복 PR 재병합 금지.**
4. **CENTRAL = 공유 PR/CI 검토, Sol v2 시각 인증 승인 게이트, 출고 여부 최종 판정.** 이번 문서 갱신 자체는 배포를 반복하지 않는다.

## 4. 고객 인수 결정표

```text
B66_PAGES_PRODUCTION=PASS      # run 38006616259 / SHA 52b05ae...
OAUTH_CALLBACK_SOURCE_MERGED=YES
B66_ACCOUNT_GOOGLE_SIGNIN_NEW_DEPLOY=NOT_TESTED
B66_PASSWORD_SIGNIN_NEW_DEPLOY=PASS_REPORTED_LOCAL3
DRIVE_OAUTH_CONNECT_NEW_DEPLOY=PASS_REPORTED_LOCAL3
B66_OFFLINE_BROWSER_CUSTOMER_JOURNEY=PASS_PR4088
B66_OFFLINE_PDF_ENDPOINT_ROUTE=PASS_STUBBED_PDF
B66_OFFLINE_QUOTE_HISTORY_CLIENT=PASS_STUBBED_D1
B66_4088_REAL_SOL_PDF_BYTES=NOT_TESTED
B66_4088_REAL_D1_PERSISTENCE=NOT_TESTED
B66_4088_REAL_FOREIGN_ACCOUNT_DENIAL=NOT_TESTED
B66_GUIDED_NEW_DEPLOY=NOT_TESTED
B66_FREEFORM_COMPLETE_NEW_DEPLOY=NOT_TESTED
B66_FREEFORM_FOLLOWUP_NEW_DEPLOY=NOT_TESTED
CGI_SOL_V1_1_TO_3=CERTIFIED_EXISTING_SCOPE
CGI_SOL_V2_4_PLUS=NOT_CERTIFIED
D1_CROSS_BROWSER_NEW_DEPLOY=NOT_TESTED
DRIVE_CANCEL_HANDLER_NEW_DEPLOY=PASS_REPORTED_STUBBED_CONFIRM_FALSE
DRIVE_NATIVE_APPROVE_NEW_DEPLOY=PASS_REPORTED
DRIVE_NATIVE_CANCEL_CLICK_NEW_DEPLOY=NOT_TESTED
DRIVE_PAIR_EXISTS_OWNER_NEW_DEPLOY=PASS_REPORTED
DRIVE_CROSS_BROWSER_NEW_DEPLOY=NOT_TESTED
DRIVE_REAL_PHONE_NEW_DEPLOY=NOT_TESTED
CGI_FIRST_CUSTOMER_FULL_MVP_HANDOFF=NOT_READY
```

인수 가능한 축소 범위(예: **1~3품목만**)는 **Owner가 명시적으로 승인하고 고객에게 제한을 설명한 경우에만** 별도 판정할 수 있다. 일반적인 "전체 MVP 완성"으로 표기할 수 없다.

### 다음 갱신 순서

- LOCAL3 새 Production **Drive 연결·초안 승인·취소 분기·세션 격리** 보고를 #3871 및 #4076에 반영. 남은 브라우저/폰/late-callback·Google **B66 계정 로그인** 검증은 별도
- LOCAL2 1~3품목 운영 견적·D1 고객 여정 → #4076 반영
- LOCAL1 Sol v2 시각 승인·정확한 SHA·고객 4+ E2E → #3839 및 #4076 반영
- CENTRAL 최종 범위·증거 비교 후에만 `CGI_FIRST_CUSTOMER_FULL_MVP_HANDOFF=READY` 전환
