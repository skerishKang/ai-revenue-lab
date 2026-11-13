# 컴2로컬2 읽기 전용 점검 기록 — 2026-11-03
A: 로그 보관 실측 (8 유닛) / B: CLAW_ENGINE_DESKTOP_SECRET (#6666)
## A. 서비스별
| 서비스 | 로그 위치 | 보관 설정 | 최초 기록 | 항목 종류(최근 60줄) |
|---|---|---|---|---|
| padiem-chat-com2 | journald(+data/workers2-trial.log 1KB) | 무기한(기본 크기 상한만) | 10-31 18:58 | HTTP 요청 라인, IP, 본문 언급 |
| padiem-mesh-queue | journald(drop-in restart) | 무기한 | 10-29 18:27 | 해당 없음 |
| padiem-b14 | journald + 파일(/opt/padiem/b14/logs, logrotate daily·rotate7·maxsize50M·compress·copytruncate=최대7일) | 파일 7일 / 저널 무기한 / ledger DB 무기한 | 10-31 16:38 | 해당 없음 |
| padiem-p01 | journald | 무기한 | 10-31 16:46 | IP 있음 |
| padiem-meshcentral | journald | 무기한 | 10-18 09:32 | IP 있음 |
| cloudflared-chat-com2 | journald | 무기한 | 10-31 19:04 | IP, 사용자/세션 식별자 |
| cloudflared-padiem | journald(drop-in) | 무기한 | 10-27 07:51 | IP 있음 |
| padiem-file-lane | journald | 무기한 | 10-27 08:10 | 해당 없음 |
- journald: 전부 기본값(Storage/SystemMaxUse/MaxRetentionSec 주석, conf.d 없음) → 시간 기준 무기한, 기본 크기 상한(10%fs)만 작동. --disk-usage 1.0G, 저널 전체 최초 Oct 18.
- Chat DB(chat.sqlite3): 감사 테이블 rows 작음(13~308), 최초 2026-10-08(claw_web_xlsx_p01_requests). 정리 코드: password_reset.py:44(30일), workspace_storage.py(문서 30일, web_xlsx 1일) 확인 — claw_run_history(308행) 등은 정리 코드 미확인.
- b14 DB(b14-call-ledger.db): model_call 38행(started_at 10-31~11-03), attempt 43행(started_at 전부 NULL) — 정리 코드 없음(무기한).
- 일일 SQLite 스냅샷(chat/queue backup timer): 백업 파일 누적 중(삭제 흔적 없음).
## B. CLAW_ENGINE_DESKTOP_SECRET (#6666)
- env 파일 4종(chat/p01/b14/queue) + 유닛 인라인: 이름 0건
- /proc environ(chat 79272, p01 864, b14 78992, queue 769, file-lane 877): 전부 이름 없음
- 길이·끝4자리·Chat/P01 일치 비교: 값이 어디에도 없어 산출 불가
- 판정: 컴2 필수 아님 — Cloudflare Secrets Store 전용 바인딩
  (apps/padiem-chat/wrangler.toml:65+67, apps/padiem-ai-engine/wrangler.toml:25+27),
  chat 호스트 코드 미참조(/opt/padiem/chat-com2/app grep 0건),
  P01은 /opt/padiem/p01/app/worker_identity.py:1141-1146에서 바인딩 값을 None 허용으로 읽음
  (현재 없는 상태로 padiem-p01 active 정상 서비스 중). 1139-1140에 "Never log or persist the value" 주석.
## 규칙 준수
읽기 전용(설정 변경·재시작·삭제 없음), Chat/PC 큐는 상태 조회만, 비밀값 미출력, pkill 미사용.
