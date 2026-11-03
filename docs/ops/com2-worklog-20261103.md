# COM2 운영 작업 기록 — 2026-11-03

COM2(컴2) 로컬에서 2026-11-03 수행한 배포·마이그레이션·점검 작업의 기록.
당시 작업 사본은 COM2 로컬에만 남아 있었고 GitHub에 본 기록이 최초 반영이다.
원문 증거 파일은 같은 날짜의 `padiem-reports/2026-11-03/`에 보관했다.
비밀값은 문서화하지 않았다(길이·일치 여부·파일 경로만 기록).

## 1. 만료 데이터 purge 타이머 + 배포 git 권한

- PR **#6738** 머지 `0e67fdffc61f57c917b3cd50e6c5940fc8816ec7` — `deploy/host-com2/deploy_from_main.sh`의 `apply_pending_chat_migrations`에서 `runuser -u <db user>` 안에서 실행되는 `git show`에만 `git -c safe.directory=<체크아웃>` 적용. 전역 git 설정은 변경하지 않음. 회귀 시험 `MigrationServiceUserGitTest` 추가(해당 파일 39개 통과).
- PR **#6739** 머지 `f31471869636bea23d45b58e65954263b0ccf381` — `install-cron.sh`이 렌더하는 타이머가 `@UNIT_NAME@`(자동화 틱)을 가리키는 템플릿 결함 수정.
- PR **#6740** 머지 `ad069bdf9ad4ddb144c907c7f9b2f78b59583a75` — 만료 purge가 영수증이 인용한 행을 남기도록 가드 추가, 실패 시 비0 종료. 기존에는 `CHAT_EXPIRED_PURGE=ERROR reason=purge_failed`(NO ACTION 외래 키)가 나면서도 ExitMainStatus=0이라 실패가 성공처럼 보였다.
- purge 실행 근거: `VACUUM INTO` 백업 후 dry-run 행 수 `p01_requests 12`, `quote_write_pauses 6`, `selections 13`, `android_auth_handoffs 18`, `password_reset_tokens 10`(총 59), 나머지 0. 타이머는 `2026-11-03 18:00 KST`로 활성화.
- 상세: `padiem-reports/2026-11-03/com2-purge-gitperm-progress.md`, PR 본문 3건 같은 폴더.

## 2. 데스크톱 Claw Engine 시크릿 배선

- PR **#6733** 머지 `e1dbeb825cb23d4828b2a9c21dc31506c0f29df7` — CPython 호스트 `local_cpython.py`가 env 시크릿(32자 이상)을 `create_app(claw_engine_desktop_secret=...)`으로 전달하고, P01 `local_runtime.py`에 `PADIEM_ENGINE_LOCAL_CHAT_ORIGIN → PADIEM_CHAT_SERVICE` 바인딩(`LocalChatServiceBinding`) 추가. Chat·P01 `check_config` 경고는 시작을 막지 않도록, `p01.env.example`·README 갱신.
- 시험: Chat 7, P01 12, 데스크톱 경로 91, P01 `local_runtime` 30(1 스킵), deploy 패키징 통과.
- 이후 운영 반영: 마이그레이션 093 적용, 4서비스 active·NRestarts 0, 시크릿 길이 48·Chat/P01/보관 사본 SHA-256 일치(값 미출력).
- 발견된 결함: 호스트 `create_app`은 내부 엔진 레인(데스크톱/PC-files)을 마운트하지 않아 서명 요청이 405(StaticFiles 캐치올)로 떨어진다. `app_factory.py`는 `connector_owner_enrollment`와 create_app 시점의 return source를 요구하는데 `local_cpython`은 이를 넘기지 않는다(`worker.py`만 조립된 소스를 넘김). 두 번째 PR(센티넬 마운트)은 열지 않았다 — 내부 레인이 #4139 `connector_owner_enrollment` 블록 안에 있고 COM2 Chat env에 `PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED`가 없어 게이트 자체가 닫혀 있었기 때문이다. 이후 parity 백업과 함께 해당 env를 추가했다.
- 부수 관찰: websocket 예외는 Starlette `staticfiles.py:91`의 `assert(scope["type"] == "http")`에 떨어진 것(경로 `/api/claw/connector/gateway/session`, COM2는 커넥터 WSS 미마운트). 재발 0.
- 상세: `com2-desktop-secret-wire-progress.md`, `…-step4-check.txt`, `…-step4-observation.txt`.

## 3. COM2 읽기 전용 점검 — 로그 보관과 시크릿 필요성

- 8개 유닛 로그 보관 실측: journald는 전부 기본값(시간 기준 무기한, 기본 크기 상한만), `padiem-b14`만 파일 로그가 logrotate daily·rotate 7·maxsize 50M·compress·copytruncate. 저널 사용량 1.0G, 최초 기록 10-18.
- Chat DB 감사 테이블은 13~308행, 최초 2026-10-08. 정리 코드는 `password_reset.py`(30일), `workspace_storage.py`(문서 30일·web_xlsx 1일)만 확인. `claw_run_history`(308행)와 b14 call ledger(`model_call` 38·`attempt` 43)는 정리 코드 없음. 일일 SQLite 스냅샷은 삭제 흔적 없이 누적 중.
- `CLAW_ENGINE_DESKTOP_SECRET`(#6666) 판정: env 파일 4종·유닛 인라인·`/proc environ` 어디에도 이름이 없고 값 산출 불가. Cloudflare Secrets Store 전용 바인딩(`apps/padiem-chat/wrangler.toml`, `apps/padiem-ai-engine/wrangler.toml`)이며 Chat 호스트 코드는 참조하지 않고 P01은 None 허용으로 읽어 정상 서비스 중 → **COM2에서 필수 아님**.
- 상세: `com2-audit-report.md`.

## 4. Claw 장애 점검 (읽기 전용)

- 5개 유닛(chat-com2·p01·mesh-queue·b14·meshcentral) active·NRestarts 0, 창 내 시작/중지 이벤트 없음, health 200.
- presence: Chat DB 0행, queue DB 4행(디바이스별 connected 상태 상이, 일부 11-02 08:50에서 정지), mesh-heartbeat 매 분 실패.
- 상세: `com2-claw-outage-report.txt`.

## 5. 배포 6695 (PR-2/PR-3) 사전 기록

- 09:34 기준 target main `31fa10752e17665f6b6dd3074872f34eb5c7a69e`, chat ledger 90개(최신 `090_mesh_device_presence_last_connected.sql`), queue ledger 목록, presence chat 0·queue 4, 백업 2종 integrity ok.
- 상세: `com2-deploy-6695-pre-record.txt`.

## 6. com2local1 배포 (`6a24faf1`)

- 08:57 사전 상태: chat `5315e0fd…`, b14 `21ea9edc…`, ledger 088/089/090.
- 09:09 사후 상태: chat·b14 모두 `6a24faf139f0e9a787e1fc1a2398f2f945bc63eb`로 통일, active 200, 재시작 0, b14 `ReadWritePaths` 유지.
- 상세: `com2local1-pre-state.txt`, `com2local1-post-state.txt`.

## 관련 자격증명 보관

같은 날 COM2에 남아 있던 고유 자격증명 사본은 COM1의 정식 자격증명 저장소(`BatangD\task\workdiary\0000apikey`)로 통합하고 로컬 사본은 삭제했다: Google OAuth 클라이언트, ayeT Publisher 운용 자료, b-creds, b62 chat/b14 env 백업. 값은 이 문서에 없다.
