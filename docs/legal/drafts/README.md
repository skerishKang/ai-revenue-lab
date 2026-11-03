# 법률 문서 초안 (docs/legal/drafts)

**법률 전문가 확인 전 게시 금지.** 이 폴더의 모든 문서는 게시 전 초안입니다.
사이트 게시·링크 연결은 이 README와 각 문서의 경고 문구가 제거되고, 아래
대표 결정 칸이 모두 채워지고, 법률 전문가의 확인을 거친 뒤에만 진행합니다.

## 구조 (공통 1벌 + 서비스별 부속)

법률 문서는 공통 계정을 쓰는 모든 서비스에 적용합니다. 같은 조항을 서비스마다 반복하지
않도록 공통 문서 1벌 + 서비스별 부속 문서로 나눕니다.

| 파일 | 내용 |
|---|---|
| `terms_common_ko.md` | 공통 이용약관 — 운영자, 공통 계정, 계정 책임, 탈퇴, 이용 제한, 유료 서비스 자리, 면책, 분쟁, 약관 변경 |
| `privacy_common_ko.md` | 공통 개인정보처리방침 — 운영자·보호책임자, 공통 계정 정보, 위탁·국외 이전, 이용자 권리, 파기 원칙, 쿠키 원칙, 안전성 확보 |
| `services/padiem_chat_claw_ko.md` | Chat·Claw 부속 — PC 작업·컴퓨터 사용 권한 원칙, 화면 캡처, 쓰기 전 백업, 서비스 수집 항목·보관 기간 |
| `services/bookai_ko.md` | 북AI·StoryMemory 부속 — 기기 저장 + 계정 저장 규칙, 원격 동기화, 삭제 |
| `services/lovetree_ko.md` | 러브트리 부속 — 점검에서 확인된 사실만 |
| `services/cgi_shop_ko.md` | CGI 쇼핑몰 부속 — 상품 판매, 주문·배송, 청약철회·환불, 견적 접수, 결제·ERP 위탁, 판매자 정보 |

새 서비스는 부속 문서 하나(`services/<이름>_ko.md`)를 추가하는 것으로 이 체계에 들어옵니다.
공통 문서는 서비스 이름을 나열하지 않고 "공통 계정으로 이용하는 서비스"로 정의합니다.

작성 규칙: 한국어, 서비스명·브랜드는 PADIEM. 비공개 사업방침 본문은 저장소에
옮기지 않고, 공개 가능한 권한 원칙 문장만 실었습니다. 확인하지 않은 사실은
사실처럼 쓰지 않았고, 법령 이름·시행일은 확인되지 않아 적지 않았습니다.

## 대표 결정 필요 칸

두 문서에 `[대표 결정: …]`로 표시한 칸입니다.

1. 판매 주체 상호·대표자·사업자등록번호·통신판매업 신고번호·주소·연락처
2. 개인정보 보호책임자(성명·연락처)
3. 시행일(공통·부속 문서)
4. 요금·결제 수단·환불 기준 (유료 서비스 자리만 확보한 상태)
5. 이용 제한 기준, 면책 범위, 준거법, 관할 법원
6. 공지 방식·기간, 문의 창구, 권리 행사 창구·처리 기한
7. PC 작업 기록·PC 화면 캡처·백업의 보관 기간
8. 자동 삭제 경로가 확인되지 않은 데이터의 파기 시점·절차
9. 국외 이전: 외부 AI 모델 공급사 위치, Cloudflare 리전, 메일 발송 서비스(Resend) 위치, 데이터베이스 서비스(Neon) 계약상 위치
10. 계정 탈퇴 절차·기한과 탈퇴 후 남는 데이터(공통 약관 4조 — 계정 삭제 라우트가 확인되지 않은 서비스 포함)
11. 서버 접속 기록·B14 호출 원장·B14 서비스 로그의 보관 기간(점검 B 결과 참조)
12. 러브트리 워크스페이스 문서·계정 삭제 절차
13. 북AI·StoryMemory의 서비스 단위(별도 운영 여부)와 계정 기록 삭제 기능·기간
14. CGI 쇼핑몰의 배송 기준, 거래 기록 보관 기간, 사용 결제 대행사·계약 상태, 견적 상담 창구·기한, 공통 계정 연동 여부

## 서비스별 근거 표 (항목 → 코드 근거)

초안에 쓴 기술 사실의 근거입니다. 기준 커밋: `docs/legal/drafts` 초안이 만들어진
브랜치 `docs/legal-drafts-261103`의 최상위 커밋(원본 `origin/main` `2caee3fed`).
러브트리는 그 저장소의 2026-11-03 점검 시점 최상위 커밋 기준입니다.

### PADIEM Chat·Claw

| 항목 | 근거 |
|---|---|
| 계정(공통 로그인, 구글 식별자·이메일·표시 이름·프로필 사진) | `apps/padiem-chat/migrations/001_auth_history.sql:6-16`, `apps/padiem-chat/app/shared_login_flow.py:1-3` |
| 대화·메시지 저장과 이용자 삭제 경로 | `apps/padiem-chat/migrations/001_auth_history.sql:18-26`, `apps/padiem-chat/app/history.py:327,1432,336,1520`, `apps/padiem-chat/app/b66_conversation_store.py:1-12` |
| 첨부 파일(계정 스코프) | `apps/padiem-chat/app/tus_chat_attachment.py:1-10` |
| 프로젝트 파일(원본은 브라우저→COM2, Chat은 메타데이터·추출 텍스트만) | `apps/padiem-chat/app/file_lane.py:1-6`, `apps/padiem-chat/app/workspace_storage.py:17-19` |
| 서비스에서 만든 문서 30일 보관 | `apps/padiem-chat/app/workspace_storage.py:11` |
| PC 작업 기록(내용 없는 카운터만) | `packages/padiem-ai-core/padiem_ai_core/pc_work_metrics.py:1-5`, `apps/padiem-chat/app/pc_work_context.py:1-6` |
| PC 화면 캡처(1장, PC 저장, 소유자 세션만 조회) | `apps/korean-ai-code-agent/src/kagent/pc_browser_tools.py:10`, `apps/padiem-chat/app/claw_pc_browser_routes.py:19,197-207` |
| 컴퓨터 사용 입력 1회성·재사용 금지, 실행 전 확인(스텝업) 분류 | `docs/operations/PC_BROWSER_USE_20261101.md:36,78`, `apps/korean-ai-code-agent/src/kagent/browser_control_actions.py:10-19` |
| 북AI 계정 기록(운영 서버 저장소, 공개 경로 본인 주제만 접근) | `apps/padiem-chat/app/bookai_records.py:1,19`, `deploy/host-com2/chat/BOOKAI_RECORDS.md`(API·소유권) |
| BYOK 키 암호화 봉인(AES-GCM)·끝 4자리만 표시 | `apps/padiem-chat/app/byok_credentials.py:3-11`, `apps/padiem-chat/app/byok_client.py:858,905`, `apps/korean-ai-platform/app/pilot/credential_slots_admin.py:183` |
| 알림 채널(메일·텔레그램·디스코드), 고객 내용 미포함 | `apps/padiem-chat/app/b66_signup_notifications.py:5,40-56`, `docs/operations/NOTIFY_CHANNELS_20261102.md` |
| 메일 발송 서비스(Resend) | `apps/padiem-chat/app/password_reset_delivery.py:62` |
| 대화 내용의 외부 AI 공급사 전송 | `apps/korean-ai-platform/app/pilot/gateway.py:174`, `apps/padiem-chat/app/byok_client.py:3-10` |
| Cloudflare 앞단·로그인(D1)·파일 객체(R2)·외부 백업 | `apps/padiem-chat/worker.py:1-5`, `deploy/host-com2/offsite-backup/offsite.py:2,17,36` |
| 쓰기 전 백업(이용자 PC `.padiem-backup`) | `apps/padiem-chat/app/oracle_mesh_read_return_routes.py:3828-3840` |
| 만료 속성 데이터(임시 저장·선택값·승인 대기·첨부 이미지·문서 바이트) | `apps/padiem-chat/migrations/006_orchestration_continuations.sql:12`, `016_claw_approval_handoff.sql:23`, `029_claw_web_xlsx_selection.sql:14,17`, `008_claw_document_metadata.sql:9,14`, `apps/padiem-ai-engine/migrations/0004_engine_attachment_images.sql:14,20-21`, `0006_engine_document_bytes.sql:27,33-34` |
| 브라우저 작업 임대 만료(300초 기본·900초 상한) | `apps/korean-ai-code-agent/src/kagent/browser_control_actions.py:11-13` |
| 로그인 확인 캐시(최대 30초) | `apps/padiem-chat/app/auth_validation_cache.py:54-58` |
| 1회용 인증 코드의 접속 기록 미저장 | `apps/padiem-chat/app/access_log.py:1-5` |
| 세션 쿠키 | `apps/padiem-chat/app/tus_chat_attachment.py:9` |

### 북AI·StoryMemory

| 항목 | 근거 |
|---|---|
| 기기 저장(읽기 기록·Memory가 이 기기에 저장) | `apps/bookai/public/index.html:179`(authGateCopy), `apps/bookai/public/bookai-login-ui.js:16-17` |
| 계정 저장(로그인 시 계정에도 저장, 다른 기기에서 이어짐) | `apps/bookai/public/index.html:179`, `apps/bookai/public/bookai-sync.js:5,26`(`endpoint='/api/bookai/records'`) |
| 기기 로컬 DB(IndexedDB `bookai-local-v1`) | `apps/bookai/public/bookai-local-db.js:6,14` |
| 로그인한 세션의 원격 동기화(Neon, `sources`·`annotations`) | `apps/bookai/public/index.html:2385-2390,2448,2626-2664` |
| 기록 백업 내보내기·복원 | `apps/bookai/public/index.html:189-194` |
| StoryMemory 로컬 키(`storymemory.*`) | `apps/storymemory/public` 키 전수 목록(점검 결과 절) |

### 러브트리

| 항목 | 근거(러브트리 저장소 `lovetree-4.0`) |
|---|---|
| 공통 계정 로그인(`auth.padiem.net`) | `functions/_lib/shared-auth.mjs:2`, `functions/_lib/padiem-access-verify.mjs:1` |
| 로그인 관련 쿠키 4종(15분·30일·600초) | `functions/_lib/shared-auth.mjs:55-59,73`, `server/credentials/lovetree-session.js:91` |
| 워크스페이스 문서(주제 ID별 문서 JSON) | `server/db/schema.sql:5-12` |
| 로그인 state의 해시 보관·만료 | `server/db/schema.sql:28-33` |
| 공유(공개·비공개, 취소 즉시 반영) | `server/db/schema.sql:61-79` |
| 커뮤니티(댓글 1,000자·신고 500자 이내) | `server/db/schema.sql:83-131` |
| 댓글·즐겨찾기·감정·공유·개인 미디어 삭제 | `server/community-service.js:79,81`, `server/share-service.js:132-137`, `server/private-media.js:70-84` |
| 워크스페이스 삭제·계정 탈퇴 라우트 없음 | `server/workspace-service.js`(DELETE 0건), 전수 검색 0건 |
| 영상 임베드(이용자가 넣은 YouTube) | `src/media.js:14,96`, `public/v41/views/track58-pinboard.html:379` |
| 기기 저장 1키(디자인 뷰 한정) | `public/v41/design/views/src064-orbit.html:193` |

### CGI 쇼핑몰

| 항목 | 근거(쇼핑몰 저장소 `kbs261022`) |
|---|---|
| 독자 계정(이메일+비밀번호·쿠키 세션·CSRF)과 비밀번호 재설정 | `backend/worker.js:22-49` |
| 구글 로그인(openid email profile) | `backend/lib/google-oauth.mjs:130,176-178` |
| 비회원 주문·견적(공개 경로) | `backend/worker.js:5,9-10,2153` |
| 수집 항목(주문자·수령인·주소·회사) | `backend/schema.sql:27-29,64-66,100-102,224-229` |
| 결제 어댑터(Toss·Nicepay) | `backend/worker.js:46,69-73`, `backend/schema.sql:79-81` |
| 이카운트 ERP 판매전표(상품·수량·단가+주문자 정보) | `backend/worker.js:17,74`, `backend/lib/erp.mjs:55-66` |
| 메일 발송(Resend 어댑터), 문자 없음 | `backend/lib/mail.mjs:13-23,75` |
| 계정 삭제(DELETE /api/me)·주소 삭제 | `backend/worker.js:33,2028-2043,2139-2140` |
| 세션 쿠키 `cgi_member`(30일)·`cgi_oauth_state` | `backend/worker.js:1317-1318,1520-1530,1605,1642`, `backend/lib/auth.mjs:30` |
| 저장 위치(Cloudflare D1) | `backend/wrangler.toml:6`, `backend/schema.sql:1-13` |

## 코드에서 확인 못 한 사실 (초안이 단정하지 않은 것)

1. `expires_at` 필드가 있는 데이터의 자동 삭제 실행 경로(스위퍼·정기 작업) — 코드에서 확인하지 못했습니다. 최종 파기 시점은 대표 결정 칸으로 남겼습니다.
2. 계정 전체 탈퇴(계정 삭제) 라우트 — 확인하지 못했습니다.
3. ~~광고·추적 쿠키의 부재~~ → **2026-11-03 코드 전수 점검으로 저장소 안에서는 부재가 확인됐습니다.** 남은 것은 저장소 밖 설정입니다: Cloudflare 대시보드에서 자동으로 넣어지는 기능(Web Analytics 비콘 등)은 저장소에서 확인할 수 없으므로, 게시 전 점검 항목으로 남깁니다(아래 "점검 결과" 참조).
4. Cloudflare 데이터 리전, 외부 AI 공급사·Resend의 서버 위치 — 코드 밖의 사실입니다.
5. ~~서버 로그·접속 기록의 보관 기간~~ → **2026-11-03 점검으로 로그 종류별 기록 내용·위치·회전 설정은 확인했습니다(아래 "점검 결과"). 기간을 정한 설정은 B14 파일 로그 회전 템플릿뿐이고 나머지는 저장소 기준 무기한이므로, 보관 기간의 최종 결정은 대표 결정 칸으로 남겼습니다. 운영 서버에 실제로 설치된 설정은 이 저장소 밖 사실이므로 컴2 확인 항목으로 남깁니다.**

## 점검 결과 (2026-11-03)

점검 A·B는 `docs/legal-audit-261103` 브랜치에서 저장소 안의 코드만으로 수행했습니다.
근거의 행 번호는 점검 시점 커밋 기준입니다. 러브트리(`lovetree-4.0`)와 CGI 쇼핑몰(`kbs261022`)
저장소는 읽기만 했고 그 저장소에는 push하지 않았습니다.

### 점검 A — 쿠키·브라우저 저장·외부 스크립트

**결론: 광고·추적 쿠키와 외부 분석 스크립트는 저장소 안에서 확인되지 않았습니다(3개 저장소 전체).**
추적 도구 키워드(googletagmanager, google-analytics, gtag, analytics, facebook, pixel, hotjar,
clarity, sentry, posthog, amplitude, mixpanel, segment, cloudflareinsights, beacon)의 일치는
전부 문학 텍스트·CSS 주석·HTML 속성 같은 오탐이었고, 외부 `<script src>`는 1건도 없습니다
(모두 같은 디렉터리의 상대 경로).

**서버가 설정하는 쿠키 (8종, 모두 인증·상태 보호 목적):**

| 쿠키 | 목적 | 만료 | 속성 | 설정 위치 |
|---|---|---|---|---|
| `padiem_session` | 로그인 세션 | 7일(기본값) | HttpOnly·SameSite=Lax·Secure(배포 설정)·path=/ | `apps/padiem-chat/app/auth.py:21,302-313`, `config.py:138`, `auth_routes.py:597,749`, `android_auth_routes.py:360` |
| `padiem_oauth_state` | 구글 로그인 state 보호 | 600초 | HttpOnly·Secure·SameSite=Lax·path=/ | `apps/padiem-chat/app/auth.py:22,316-323`, `auth_routes.py:355` |
| `padiem_claw_github_oauth_state` | 깃허브 연동 state 보호 | 600초 | HttpOnly·Secure·SameSite=Lax | `apps/padiem-chat/app/github_oauth_routes.py:16,66-68` |
| `__Host-padiem-shared-state` | 공통 로그인 state 보호 | 600초 | HttpOnly·Secure·SameSite=Lax·path=/ | `apps/padiem-chat/app/shared_login_flow.py:22,155` |
| `__Host-padiem-shared-access` | 공통 접근 토큰 | 15분 | HttpOnly·Secure·SameSite=Lax·path=/ | `apps/padiem-chat/app/shared_login_flow.py:23,27,104-105` |
| `padiem_shared_refresh` | 공통 재발급 토큰 | 30일 | HttpOnly·Secure·SameSite=Lax·path=/auth/shared(공통 인증 경로로만 전송) | `apps/padiem-chat/app/shared_login_flow.py:24,26,28,106-107` |
| `__Host-padiem-shared-marker` | 화면 표시용 힌트(값 '1', 자격 증명 없음) | 30일 | HttpOnly·Secure·SameSite=Lax·path=/ | `apps/padiem-chat/app/shared_login_flow.py:25,108-111` |
| `__Host-padiem-compare-state` | 공통 인증 비교 state 보호 | 600초 | HttpOnly·Secure·SameSite=Lax·path=/ | `apps/padiem-chat/app/shared_auth_compare_flow.py:20,190` |

앞단 Worker(`apps/padiem-chat/worker.py`)와 브라우저 자바스크립트는 쿠키를 설정하지 않습니다
(`document.cookie` 사용 0건). 러브트리 쿠키 4종과 쇼핑몰 쿠키 2종은 각 서비스 부속 문서 점검 표를 따릅니다.

**브라우저 저장 (앱별):**

| 앱 | 저장소 | 키(접두어) | 담는 것 |
|---|---|---|---|
| PADIEM Chat | sessionStorage | `padiem.androidHandoff.v1` | 안드로이드 앱 연결 안내 진행 상태 |
| 북AI | localStorage | `storymemory.readerProgress.*` 등 상수 키(읽기 위치·Memory·어노테이션·책 순서·이어보기·핀) | 읽기 기록과 Memory(기기 저장) |
| 북AI | IndexedDB | `bookai-local-v1`(스토어: entries·meta·records·outbox) | 읽기 기록·기기 로컬 DB·동기화 대기열 |
| StoryMemory | localStorage | `storymemory.readerProgress.*`, `storymemory.annotations.vN`, `storymemory.libraryOrder.vN`, `storymemory.motionFactor`, `storymemory.lastHighlightClass` | 읽기 진행·어노테이션·책 순서 등 |

**외부 도메인(이용자 브라우저가 닿는 곳, 저장소 기준 전수):**

| 도메인 | 용도 | 근거 |
|---|---|---|
| `fonts.googleapis.com`, `fonts.gstatic.com` | 웹폰트 스타일시트(북AI·StoryMemory 화면, Chat 공용 CSS) | `apps/bookai/public/index.html:18-20,7793`, `apps/padiem-chat/static/padiem-foundation.css:3` |
| `cdn.jsdelivr.net` | 폰트 스타일시트(SUIT, Chat 공용 CSS) | `apps/padiem-chat/static/padiem-foundation.css:1-2` |
| `ep-odd-surf-avfp55rv.apirest...neon.tech`, `ep-odd-surf-avfp55rv.neonauth...neon.tech` | StoryMemory 원격 메타데이터·어노테이션 동기화(로그인한 세션의 단기 JWT로 인증; 데이터 API는 `sources`·`annotations` 테이블) | `apps/bookai/public/index.html:2385-2390,2448,2626-2664` |
| `drive.google.com` | 회의 캡처 결과 파일 보기 링크(이용자 클릭 시에만 이동) | `apps/padiem-chat/static/meeting-capture.js:421,551` |
| `youtube.com` 등 영상 호스트(러브트리) | 이용자가 순간에 넣은 영상의 임베드·재생 링크 | `lovetree-4.0` `src/media.js:14,96`, `public/v41/views/track58-pinboard.html:379` |

`chat.padiem.net`·`auth.padiem.net`·`padiem-ai-engine-ingress...workers.dev`는 자사 인프라 주소입니다.
`third-party-licenses.html`의 `github.com`·폰트 라이선스 문서의 `hangeul.pstatic.net` 등은 문서·주석
링크이고 런타임 호출이 아닙니다(러브트리 폰트는 자체 호스팅).

**게시 전 점검 항목(저장소 밖):** Cloudflare 대시보드에서 자동으로 넣어지는 기능(Web Analytics 비콘
등)은 이 저장소에서 확인할 수 없습니다. 게시 전에 각 도메인(채트·북AI·러브트리·쇼핑몰)의 응답
HTML에 그런 스크립트가 없는지 브라우저로 확인해야 합니다.

### 점검 B — 서버 로그 보관 기간 (저장소 기준)

| 로그 | 기록 내용 | 위치 | 보관·회전 | 근거 |
|---|---|---|---|---|
| Chat 접속 기록(uvicorn access) | 경로만 기록(쿼리 문자열 제거 — 1회용 인증 코드 미저장). IP·사용자 식별자·본문은 uvicorn access 표준 항목에 따라 요청 라인의 경로 외에는 없음 | journald(파일 미지정) | 저장소 기준 무기한(회전·삭제 설정 없음) → [대표 결정: 보관 기간] | `apps/padiem-chat/app/access_log.py:1-25`, `deploy/host-com2/chat/padiem-chat-com2.service:28-29` |
| B14 서비스 구조 로그 | 서비스 표준 출력(stdout) | journald + 선택적 파일 로그 `/opt/padiem/b14/logs` | 파일 로그 회전 **템플릿**: daily·7세대·50M 상한(저장소가 설치하지 않음, 예시 파일) → [대표 결정: 설치·기간] | `deploy/host-com2/b14/20-log-to-file.conf.example`, `deploy/host-com2/b14/logrotate.conf.example:1-17` |
| B14 모델 호출 원장 | 주제 참조(≤128자)·모델 id·토큰 수·비용. 프롬프트·응답·헤더·쿠키·IP는 스키마 주석 수준에서 의도적으로 기록하지 않음 | `/opt/padiem/b14/ledger/b14-call-ledger.db`(SQLite) | 정리·삭제 코드 없음 → 저장소 기준 무기한 → [대표 결정: 보관 기간] | `apps/korean-ai-platform/migrations/0001_b14_model_call_ledger.sql:13,17-57`, `deploy/host-com2/b14/padiem-b14.service.example:31`, `apps/korean-ai-platform/app/pilot/call_ledger_store.py`(삭제 코드 0건) |
| 앱 실행 결과 출력(OutputStore) | 작업 결과 바이트·미리보기 | 서버 임시 디렉터 | 기본 7일, 만료분 자동 삭제 | `packages/padiem-ai-core/padiem_ai_core/output_store.py:7-8,33,50-63` |
| 러브트리·쇼핑몰 서버 로그 | — | — | 저장소에 보관 기간 설정 없음(Cloudflare·호스트 측은 저장소 밖) | 각 저장소 전수 검색 0건 |

**컴2 확인 항목(저장소 밖):** 실제로 설치된 logrotate·journald(SystemMaxUse·MaxRetentionSec)
설정과 서비스가 만든 로그 파일의 실제 보관 상태는 운영 서버에서 확인해야 합니다. 저장소의
logrotate 예시는 "template; not installed by this repo"라고 스스로 밝힙니다
(`deploy/host-com2/b14/logrotate.conf.example:1-2`).

### 러브트리·CGI 쇼핑몰 점검 요약

| 항목 | 러브트리(lovetree-4.0) | CGI 쇼핑몰(kbs261022) |
|---|---|---|
| 로그인 | 공통 계정(`auth.padiem.net`, `functions/_lib/shared-auth.mjs:2`) | 독자 계정(이메일+비밀번호, `backend/worker.js:22-49`) + 구글 로그인(`backend/lib/google-oauth.mjs:130`) |
| 쿠키 | 4종: `__Host-lovetree-access`(15분)·`lovetree_refresh`(/auth 경로, 30일)·`__Host-lovetree-shared`(표시용, 30일)·`lovetree_auth_state`(600초) — `functions/_lib/shared-auth.mjs:55-59,73` | 2종: `cgi_member`(세션, 30일, HttpOnly·SameSite=None·Secure)·`cgi_oauth_state`(600초) — `backend/worker.js:1317-1318,1520-1530,1605,1642`, `backend/lib/auth.mjs:30` |
| 브라우저 저장 | `lovetree.track64.handoff` 1키(디자인 뷰 한정, `public/v41/design/views/src064-orbit.html:193`) | 관리자 토큰·견적 장바구니·주문 이메일 등(`website/` `cgi*` 7키) |
| 광고·추적 | 없음(키워드·외부 스크립트 0건) | 없음(키워드·외부 스크립트 0건) |
| 수집 항목 | 주제 ID별 워크스페이스 문서(트리·순간), 공유, 커뮤니티 댓글(≤1000자)·신고(≤500자) | 주문자(이름·전화·이메일·회사·주소)·수령인·주소·견적(회사·담당자·연락처·지역·메모)·계정(이메일, 구글 id/email) |
| 삭제 경로 | 댓글·즐겨찾기·감정·공유·개인 미디어 DELETE. 워크스페이스 문서·계정 탈퇴 라우트 없음 → [대표 결정] | `DELETE /api/me`(계정 삭제, `backend/worker.js:2028-2043`)·주소 DELETE(:2139-2140). 주문 삭제 라우트 없음 |
| 결제·ERP | — | 결제 어댑터: Toss·Nicepay(`backend/worker.js:46,69-73`). ERP: 이카운트 판매전표(상품코드·품명·수량·단가 + 주문자 이름·회사·전화·이메일·주소) — `backend/lib/erp.mjs:55-66` |
| 알림 | — | 메일(Resend 어댑터, `backend/lib/mail.mjs:13-23,75`). 문자 없음 |

## AI 생성 결과 고지

공통 이용약관과 공통 개인정보처리방침(그리고 이를 받는 부속 문서)은 모두 "AI 생성 결과는
이용자가 검토한 뒤 사용해야 하며 전문가의 확인을 대체하지 않는다"는 고지 문단을 포함합니다.
