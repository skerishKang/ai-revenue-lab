# B66 CGI 첫 고객 MVP — Production 배포 및 고객 인수 기준 (2026-10-10 KST)

> **CENTRAL 시점별 스냅샷.** 제품 원칙은 [B66 README](README.md), [SOURCE_TEMPLATE_FIDELITY](SOURCE_TEMPLATE_FIDELITY.md), 각 이슈가 우선한다. 이 문서는 특정 배포 및 검증 상태를 기록하며 이후 `main` 이동이 과거 배포 SHA를 바꾸지 않는다.

## 결론

- **기존 1차 MVP 인수 게이트 [#3521](https://github.com/skerishKang/ai-revenue-lab/issues/3521)는 CLOSED**, Guided·Free-form·견적 결과·미리보기·PDF 기본 여정의 기존 수용 기록이 있다. 이를 이유 없이 다시 OPEN하거나 통합 고객 인수를 완료했다고 주장하지 않는다.
- **현재 추가 고객 인수 [#4076](https://github.com/skerishKang/ai-revenue-lab/issues/4076)는 OPEN.** 실제 로그인·견적·저장·재열기 및 4품목 이상 Sol 네이티브 인증이 아직 완료되지 않았다.
- **B66 Pages Production 배포는 새 코드로 완료.** Owner 승인 후 수동 [Actions #38006616259](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38006616259) `workflow_dispatch` 한 번 실행, 대상 커밋 `52b05ae4623fb211c32d31fe286d8e483803330f`, 배포 작업·사후 계약 검사 **둘 다 SUCCESS**. 이전 확인된 Production `ee11c1cbe...`보다 최신이다.
- 배포된 버전에는 [#4073](https://github.com/skerishKang/ai-revenue-lab/pull/4073) OAuth 콜백 `state/code` 쿼리 보존이 포함된다. 중복 Draft [#4074](https://github.com/skerishKang/ai-revenue-lab/pull/4074)는 **CLOSED, UNMERGED**; LOCAL3 실측 증거·커밋은 보존한다.
- **배포 성공과 실제 인증 성공은 다르다.** Google 실제 로그인, Drive 기존 초안의 불러오기 취소·승인, D1/다른 계정·브라우저·실기기 E2E는 새 배포에서 PASS를 확보하기 전까지 **NOT_TESTED**다.

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
| 실 사용자 인증 | **NOT_TESTED (새 Production 버전)** — status API HTTP 200은 로그인 인증 성공이 아님 |
| 실제 Google Drive JSON/PDF Save/Open | 이전 버전 LOCAL3 부분 실측 존재, **새 버전 전체 LIVE E2E NOT_TESTED** |
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
| 고객 본인 Google Drive | 이전 배포에서 LOCAL3 JSON+PDF 저장·빈 편집기 재열기 부분 실측, [#4029](https://github.com/skerishKang/ai-revenue-lab/pull/4029) 병합 | 내용 있는 기존 견적에서 불러오기 **취소=보존**/**승인=원자적 교체**, QuoteCore 일치, 재연결·계정별 차단 | LOCAL3 |
| 고객 전달 패키지 | [#4076](https://github.com/skerishKang/ai-revenue-lab/issues/4076) 신설 | 개인정보 제거된 시연 흐름·화면 증거·제약·승인한 출력 범위·연락/재현 절차 | LOCAL2 + CENTRAL |

**PDF Owner lock:** 김범신 CGI 출력에는 **기존 Sol 6.1에서 출발한 단일 승인 구현만** 사용한다. 3품목 초과를 HTML 인쇄/GLM/모델 생성 PDF로 대체할 수 없다. Sol은 최초 템플릿 분석·엔지니어링, 반복 출력은 **결정적 코드 + QuoteCore**(PDF 출력 모델 호출 0). 자동 범용 원본 학습기·두 번째 고객 양식 인증·고객 원본 R2 보관·음성 입력은 이번 CGI 고객 인수를 자동 차단하는 조건이 아니다.

## 3. 병렬 업무 경계

1. **LOCAL1 = #3839 Sol 네이티브 4+품목/다중 페이지**: 기존 #4001/#4010을 조사, 수정본 시각·벡터·해시 검증, v2 인증 후보를 CENTRAL에 제출. 승인·병합·Production 활성화 전까지 v1 인증 보호. 완료 전 "전체 품목 PDF 완성" 금지.
2. **LOCAL2 = #4076 고객 MVP 실제 여정 + #3906 B66 측**: 새 독립 작업트리에서 운영 브라우저 로그인 기반 Guided/Free-form/단가 누락/QuoteCore/실제 PDF/D1. #3839 v2 인증 이후 4+ 행 통합. shared Core·Sol 양식·LOCAL3 OAuth/Drive 작업 불침범.
3. **LOCAL3 = #3871 Google OAuth 및 고객 Drive**: 새 배포에서 실제 로그인 성공 확인 후 채워진 초안의 취소·승인, JSON/PDF 쌍, 재로그인·다른 계정/브라우저/폰 E2E. **#4074 중복 PR 재병합 금지.**
4. **CENTRAL = 공유 PR/CI 검토, Sol v2 시각 인증 승인 게이트, 출고 여부 최종 판정.** 이번 문서 갱신 자체는 배포를 반복하지 않는다.

## 4. 고객 인수 결정표

```text
B66_PAGES_PRODUCTION=PASS      # run 38006616259 / SHA 52b05ae...
OAUTH_CALLBACK_SOURCE_MERGED=YES
OAUTH_REAL_LOGIN_NEW_DEPLOY=NOT_TESTED
B66_GUIDED_NEW_DEPLOY=NOT_TESTED
B66_FREEFORM_COMPLETE_NEW_DEPLOY=NOT_TESTED
B66_FREEFORM_FOLLOWUP_NEW_DEPLOY=NOT_TESTED
CGI_SOL_V1_1_TO_3=CERTIFIED_EXISTING_SCOPE
CGI_SOL_V2_4_PLUS=NOT_CERTIFIED
D1_CROSS_BROWSER_NEW_DEPLOY=NOT_TESTED
DRIVE_CANCEL_APPROVE_NEW_DEPLOY=NOT_TESTED
CGI_FIRST_CUSTOMER_FULL_MVP_HANDOFF=NOT_READY
```

인수 가능한 축소 범위(예: **1~3품목만**)는 **Owner가 명시적으로 승인하고 고객에게 제한을 설명한 경우에만** 별도 판정할 수 있다. 일반적인 "전체 MVP 완성"으로 표기할 수 없다.

### 다음 갱신 순서

- LOCAL3 새 Production 실제 인증·Drive 증거 → #3871 및 #4076 반영
- LOCAL2 1~3품목 운영 견적·D1 고객 여정 → #4076 반영
- LOCAL1 Sol v2 시각 승인·정확한 SHA·고객 4+ E2E → #3839 및 #4076 반영
- CENTRAL 최종 범위·증거 비교 후에만 `CGI_FIRST_CUSTOMER_FULL_MVP_HANDOFF=READY` 전환
