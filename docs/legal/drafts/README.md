# 법률 문서 초안 (docs/legal/drafts)

**법률 전문가 확인 전 게시 금지.** 이 폴더의 모든 문서는 게시 전 초안입니다.
사이트 게시·링크 연결은 이 README와 각 문서의 경고 문구가 제거되고, 아래
대표 결정 칸이 모두 채워지고, 법률 전문가의 확인을 거친 뒤에만 진행합니다.

## 파일

| 파일 | 내용 |
|---|---|
| `terms_of_service_ko.md` | 이용약관 초안 |
| `privacy_policy_ko.md` | 개인정보처리방침 초안 |

작성 규칙: 한국어, 서비스명·브랜드는 PADIEM. 비공개 사업방침 본문은 저장소에
옮기지 않고, 공개 가능한 권한 원칙 문장만 실었습니다. 확인하지 않은 사실은
사실처럼 쓰지 않았고, 법령 이름·시행일은 확인되지 않아 적지 않았습니다.

## 대표 결정 필요 칸

두 문서에 `[대표 결정: …]`로 표시한 칸입니다.

1. 판매 주체 상호·대표자·사업자등록번호·통신판매업 신고번호·주소·연락처
2. 개인정보 보호책임자(성명·연락처)
3. 시행일(양 문서)
4. 요금·결제 수단·환불 기준 (유료 서비스 자리만 확보한 상태)
5. 이용 제한 기준, 면책 범위, 준거법, 관할 법원
6. 공지 방식·기간, 문의 창구, 권리 행사 창구·처리 기한
7. PC 작업 기록·PC 화면 캡처·백업의 보관 기간
8. 자동 삭제 경로가 확인되지 않은 데이터의 파기 시점·절차
9. 국외 이전: 외부 AI 모델 공급사 위치, Cloudflare 리전, 메일 발송 서비스(Resend) 위치

## 근거 표 (항목 → 코드 근거)

초안에 쓴 기술 사실의 근거입니다. 기준 커밋: `docs/legal/drafts` 초안이 만들어진
브랜치 `docs/legal-drafts-261103`의 최상위 커밋(원본 `origin/main` `2caee3fed`).

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
| 북AI 기록(운영 서버 SQLite) | `apps/padiem-chat/app/bookai_records.py:1,19` |
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

## 코드에서 확인 못 한 사실 (초안이 단정하지 않은 것)

1. `expires_at` 필드가 있는 데이터의 자동 삭제 실행 경로(스위퍼·정기 작업) — 코드에서 확인하지 못했습니다. 최종 파기 시점은 대표 결정 칸으로 남겼습니다.
2. 계정 전체 탈퇴(계정 삭제) 라우트 — 확인하지 못했습니다.
3. 광고·추적 쿠키의 부재 — 세션 쿠키 사용은 확인했지만, 추적 도구의 전수 부재까지 확인하지 못했습니다. 게시 전 점검 항목으로 남겼습니다.
4. Cloudflare 데이터 리전, 외부 AI 공급사·Resend의 서버 위치 — 코드 밖의 사실입니다.
5. 서버 로그·접속 기록의 보관 기간 — 코드에서 기간을 확인하지 못했습니다.

## AI 생성 결과 고지

두 초안 모두 "AI 생성 결과는 이용자가 검토한 뒤 사용해야 하며 전문가의 확인을
대체하지 않는다"는 고지 문단을 포함합니다.
