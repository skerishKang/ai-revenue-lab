# PC 명령 수명 모델 (R4) — 2026-11-09

이슈 #7188. 근거 코드: `origin/main` 84038b2497 기준. 파일 축약:
실행기 = `apps/korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py`,
포트 = `apps/korean-ai-code-agent/src/kagent/local_agent_meshcentral_command_port.py`,
채팅 = `apps/padiem-chat/app/`, 엔진 = `apps/padiem-ai-engine/app/`.

## 1. 명령 한 건의 수명 표

실제 코드의 상태·위상 이름 그대로. 대기열 행 상태는 `pending` → (`received`,
`store_failed`는 결과 수납 중간 상태) → `done` | `failed`이고, 종료 방식은
`termination` 컬럼에 기록된다. 저널 위상(phase)은 실행기가
`oracle-mesh-command phase=<이름> ts= elapsed_ms=` 한 줄로 남긴다.

| # | 단계 | 상태/이름 | 상한·기본값 | env | 정리 주체 | 코드 위치 |
|---|------|-----------|-------------|-----|----------|-----------|
| 1 | 발행 | 대기열 행 생성, `state=pending`, `expires_at=now+600s` | TTL 600초(고정, 환경변수 없음) | — | 채팅(만료 조건은 claim WHERE 절) | 채팅 `oracle_mesh_read_return_routes.py:177,1490-1503` |
| 2 | 인계(claim) | `UPDATE ... SET nonce_sha256, claimed_until` — 행은 `pending` 유지 | 리스 60초 | `ORACLE_MESH_CLAIM_LEASE_SECONDS`=60 (상수, history.py:100) | 채팅(대기열 DB) | 채팅 `history.py:3396-3424` |
| 3 | 저널 claimed | `phase=claimed` | — | — | 실행기 | 실행기 2778 (`run_once`) |
| 4 | 저널 start | `phase=start` | — | — | 실행기 | 실행기 1890(SYSTEM)·1824(사용자) |
| 5 | 리스 갱신 | 20초마다 `renew_oracle_mesh_claim` | 갱신 간격 20초 | 상수 `RENEW_INTERVAL_SECONDS`=20 (실행기:73) | 실행기 스레드 → 채팅 | 실행기 2815, 채팅 `history.py:3426-3448` |
| 6 | spawn | `phase=spawn` — meshctrl runcommand 자식 프로세스 기동 | — | — | 포트 | 포트 1671(스트리밍 `_run_streaming`)·1365(버퍼 경로) |
| 7 | frames | 콘솔 출력 청크 읽기 루프. 받은 바이트마다 무음 시계 재시작 | 라인 정체 관측 창 120초 | 상수 `LINE_STALL_WAIT_SECONDS`=120 (포트:261) | 포트 | 포트 1673-1760 |
| 8 | result(정상) | `phase=result`, `termination=exited`·`no_exit_code` | 명령 자체에 상한 없음(#5895) | — | 실행기 → 채팅 결과 경로 | 실행기 1934-1935(termination 이름), 포트 975(`parse_transcript`) |
| 9 | timed_out(명시) | `phase=timeout` — 호출자가 deadline을 준 경우만 | 호출자 지정 | — | 포트(자식 kill) | 포트 1372(버퍼)·1688,1697(스트리밍) |
| 10 | silent_timeout | `phase=silent_timeout`, `termination=timed_out` — 총 무음 상한 | 600초, 0=끔 | `PADIEM_MESH_SILENT_WAIT_SECONDS`=600 | 포트(클라이언트 kill, PC는 건드리지 않음) | 포트 655-656(이름·기본값), 1729 |
| 11 | cancelled | `phase=cancel`, `termination=cancelled` — 소유자 중지 | 취소 폴링 3초 간격 | 경로 상수 `ORACLE_MESH_READ_CANCEL_POLL_PATH` (채팅:116) | 실행기(포트가 PC 정지 요청→자식 kill) | 포트 1718, 1780(`_stop_on_pc`), 233(`cancel_kill_command`); 실행기 1405(`_cancel_probe`) |
| 12 | 만료 | `expires_at` 경과 시 claim WHERE가 거부 — 대기열이 영원히 안 넘김 | TTL 600초 | — | 채팅(claim 조건) | 채팅 `history.py:3410-3412` |
| 13 | 결과 제출 | `submit` → nonce 게이트 → `state=done`/`failed` | 재제출 백오프 5→60초, 거부 3회 후 보관 | 상수 `MAX_RESULT_REJECTIONS`=3(287), `_BACKOFF_FIRST_SECONDS`=5·`_BACKOFF_MAX_SECONDS`=60(291-292) | 실행기(보관) → 채팅(수납) | 실행기 2535(`submit`), 2104(`_persist_pending`), 2420(백오프); 채팅 `history.py:3486` |
| 14 | 유휴 콘솔 정리 | `phase=idle_reap` — timed_out 뒤에만 실행 | 최소 나이 900초 | `PADIEM_MESH_IDLE_CONSOLE_REAP`(기본 on), `PADIEM_MESH_IDLE_CONSOLE_MIN_AGE_SECONDS`=900 | 포트(PC에서 pid kill) | 포트 1585-1640, 337-346(sweep 모드) |
| 15 | 대기 소비자(응답 조립) | 엔진 첫 대기 / 채팅 완료 대기 | 엔진 21초(clamp 1-120), 채팅 600초 | `PADIEM_PC_FILES_WAIT_SECONDS`=21, `PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS`=600 | 엔진·채팅 | 엔진 `claw_pc_query_step_driver.py:141-153`; 채팅 `config.py:120` |

사용자 모드 명령은 6-9가 클라이언트 스크립트 안에서 이렇게 바뀐다:

| 단계 | 내용 | 상한·기본값 | env | 정리 주체 | 코드 위치 |
|------|------|-------------|-----|----------|-----------|
| 클라이언트 생성 | `build_user_helper_pipe_client_ps` — 파이프 클라이언트 PS를 만들어 파일 전달로 실행(`deliver_as_file=True`) | — | — | 실행기 → 포트 | 실행기 1463(정의), 1799-1807(호출), 1834-1840(파일 전달) |
| 첫 프레임 | 헬퍼의 첫 반응 대기 | 30초 | `PADIEM_MESH_USER_HELPER_FIRST_FRAME_SECONDS`=30 (PC 측 env) | 클라이언트 PS(예외→종료) | 실행기 1635, 1589 |
| 전체 응답 | 헬퍼 응답 백스톱 | max(180, 요청 timeout+120)초, >0 고정·<0 끔 | `PADIEM_MESH_USER_HELPER_REPLY_SECONDS` (PC 측 env) | 클라이언트 PS | 실행기 1528-1530, 1640 |
| 셀프 취소 | 취소 폴링 3초 간격, 토큰 불일치·URL 없으면 비활성 | 3초 간격, 요청 타임아웃 3초 | 없음(토큰은 dispatch별 발행) | 클라이언트 PS → 헬퍼가 사용자 자식 종료 | 실행기 1563-1570(폴링), 1811-1817(프롬브 병행) |

## 2. SYSTEM 모드와 사용자 모드가 갈라지는 지점

1. **채팅 도구 게이트** — `mcp_gateway_execution.py:259-321`: `mode`
   인자 검증, `mode=system`은 관리자·계약 PC 게이트
   (`_pc_system_mode_allowed`), `PADIEM_MCP_PC_SHELL_USER_MODE` 끔이면
   사용자 모드 도구 자체 거부.
2. **dispatch 행** — `oracle_mesh_read_return_routes.py:1339,1503`:
   `user_mode` 불리언이 대기열 행 컬럼으로 들어감(migration 102).
3. **실행기 분기** — 실행기 1875-1877: `_execute_command` 첫 줄에서
   `_execute_user_mode_command`로 갈라짐. 이후 명령 본문 해석(SYSTEM은
   셸 래퍼 문자열, 사용자는 helper 요청 material JSON), 잠금(사용자 모드는
   노드 실행 잠금 없음, 실행기 2699), 결과 파싱(SYSTEM은 센티넬
   `$LASTEXITCODE`, 포트 975, 사용자는 JSON, 실행기 1731)까지 전부 다른
   함수 안에 있다.
4. **전송 래핑** — 포트 1319-1331: 사용자 모드만 `deliver_as_file=True`
   (7KB 클라이언트를 콘솔 본문으로 보내면 닫히지 않는 블록이 생김,
   #7199). SYSTEM은 콘솔 래퍼 `_wrap`.
5. **PC 셸 선택** — SYSTEM: 채팅이 만든 정적 디스패처 스크립트 안의
   `$env:PADIEM_MCP_SHELL`이 powershell/cmd/bash를 고름
   (`mcp_gateway_shell.py:246-267`). 사용자: 요청 material의 `shell`
   필드를 헬퍼 서비스가 받아 사용자 자식을 고름(실행기 1483-1486).
6. **중지 경로** — SYSTEM: 실행기 취소 프롬브(서버 poll) → 포트가 PC에
   정지 요청(`_stop_on_pc`) 후 자식 kill. 사용자: 클라이언트 PS가
   cancel-poll 공개 경로를 3초마다 읽어 스스로 끝나고, 헬퍼가 사용자
   자식을 종료(실행기 1563-1570). #7215가 사용자 모드에 이 경로를 붙였다.
7. **응답 상한** — SYSTEM: 무음 상한 600초(포트). 사용자: 첫 프레임 30초
   + 전체 백스톱(클라이언트 PS). 두 상한의 소재가 다르다(포트 vs PC).

**"실행 셸 한 곳에서만 갈라지게" — 무엇을 옮기는가**

지금 셸 선택은 세 곳에 흩어져 있다: (a) 채팅 화이트리스트 검증
(`PC_SHELL_SHELLS`, `mcp_gateway_shell.py:27`), (b) SYSTEM 디스패처
스크립트 안의 `$env:PADIEM_MCP_SHELL` 분기(`mcp_gateway_shell.py:266`),
(c) 사용자 모드 material의 `shell` 필드 → 헬퍼. 옮길 것:

- dispatch가 셸 **이름 하나**만 운반하게 하고, (b)의 인라인 분기를 없앤다.
  SYSTEM은 실행기가 이름을 받아 래퍼 인자 한 줄로 넘기고, 사용자는 같은
  이름을 helper 요청 material의 `shell`에 그대로 넣는다.
- 실행기(또는 헬퍼)에 `resolve_shell(name) -> launcher` 단일 함수를 두어
  두 레인이 같은 이름 집합·같은 기본값(powershell)·같은 미지원 거부를
  쓰게 한다. 채팅은 이름 화이트리스트 검증만 남긴다.
- 결과: 셸 추가는 한 함수의 표 한 줄이고, 두 모드의 셸 동작 차이는
  "실행 주체가 누구인가" 한 곳으로 모인다.

## 3. env 스위치 전체 목록

운영 값 확인 방법: 컴2는 systemd `EnvironmentFile`의 **이름만** 나열해
설정 여부를 확인했다(값은 읽지 않음). 컴1(이 PC)은 머신·사용자 환경변수
이름만 확인. 아래 "운영" 칸에서 ○ = 설정됨, ✕ = 기본값 사용.

### 실행기 접속·대기열 (컴2 `/opt/padiem/oracle-mesh/executor.env`)

| 이름 | 기본값 | 운영 | 없애도 되는가 | 합칠 대상 |
|------|--------|------|---------------|-----------|
| `ORACLE_MESH_URL` | — | ○ | 아니오(접속 지점) | — |
| `ORACLE_MESH_CHAT_ORIGIN` | — | ○ | 아니오 | `ORACLE_MESH_URL` 계열 접속 설정과 한 그룹 |
| `ORACLE_MESH_QUEUE_ORIGIN` | — | ○ | 아니오 | 같은 그룹 |
| `ORACLE_MESH_CHANNEL_SECRET_FILE` | — | ○ | 아니오(비밀) | — |
| `ORACLE_MESH_EDGE_SECRET_FILE` | — | ○ | 아니오(비밀) | — |
| `ORACLE_MESH_LOGIN_USER` / `ORACLE_MESH_PASSWORD_FILE` / `ORACLE_MESH_LOGIN_KEY_FILE` | — | ○ | 아니오(비밀) | 셋은 "meshctrl 로그인" 한 그룹 |
| `ORACLE_MESH_MESHCTRL_JS` | — | ○ | 아니오 | — |
| `ORACLE_MESH_WORK_DIR` | — | ○ | 아니오 | — |
| `ORACLE_MESH_POLL_SECONDS` | 5 | ✕ | 유지(대기 cadence) | `ORACLE_MESH_IDLE_POLL_MAX_SECONDS`(설정됨)와 같은 그룹 |
| `MESH_FAILOVER_DEVICE_ID` | — | ○ | 유지 | — |

### 명령 수명·레인 (실행기·포트; 컴2 모두 기본값)

| 이름 | 기본값 | 운영 | 없애도 되는가 | 합칠 대상 |
|------|--------|------|---------------|-----------|
| `ORACLE_MESH_READ_TIMEOUT_SECONDS` | 30(read/desktop ×4) | ✕ | 유지(읽기 상한) | — |
| `ORACLE_MESH_READ_SINGLE_ROUNDTRIP` | on | ✕ | 유지 — off가 롤백 스위치 | — |
| `PADIEM_MESH_SILENT_WAIT_SECONDS` | 600, 0=끔 | ✕ | 유지 — #7177/#7178 봉합, 기본값이 운영값 | — |
| `PADIEM_MESH_IDLE_CONSOLE_REAP` | on | ✕ | 유지 — 끄면 11-07 고아 콘솔 재발 | — |
| `PADIEM_MESH_IDLE_CONSOLE_MIN_AGE_SECONDS` | 900 | ✕ | 유지 | 위와 한 그룹 |
| `PADIEM_MESH_SESSION_COMMAND_LANE` | off | ✕ | 판단 필요 — 세션 레인은 아직 실험 | 아래 3개와 함께 "레인 선택" 1개로 |
| `PADIEM_MESH_LINE_PROBE` | off | ✕ | 예 — 콘솔 레인이 입력을 에코하는 게 관측됨(#7232 측정) | 같은 그룹 |
| `PADIEM_MESH_PROCESS_LANE` | off | ✕ | 판단 필요 — 켜면 SYSTEM 중지가 프로세스 kill로 감 | 같은 그룹 |
| `PADIEM_MESH_RUN_AS_USER` / `PADIEM_MESH_RUN_AS_USER_ONLY` | off | ✕ | 예(후자) — 제품 사용자 모드(#7107 이후)가 사실상 대체. `..._ONLY`는 중복 | 사용자 모드 레인으로 흡수 |

### 사용자 모드 PC 클라이언트 (컴1·CGI-1 측 env; 컴1 미설정 = 기본값)

| 이름 | 기본값 | 운영 | 없애도 되는가 | 합칠 대상 |
|------|--------|------|---------------|-----------|
| `PADIEM_MESH_USER_HELPER_FIRST_FRAME_SECONDS` | 30 | ✕ | 유지 — 첫 프레임 방어 | — |
| `PADIEM_MESH_USER_HELPER_REPLY_SECONDS` | max(180, timeout+120), >0 고정·<0 끔 | ✕ | 유지 — 장시간 명령 보호 | first-frame과 "사용자 모드 응답 상한" 1개로 합칠 수 있음 |

### 채팅·엔진 (컴2 `/opt/padiem/chat-com2/.env`, P01 유닛)

| 이름 | 기본값 | 운영 | 없애도 되는가 | 합칠 대상 |
|------|--------|------|---------------|-----------|
| `PADIEM_MCP_PC_SHELL_ENABLED` | off | ○ | 아니오(제품 스위치) | — |
| `PADIEM_MCP_PC_SHELL_USER_MODE` | off | ○(사용자 모드 ON) | 아니오(현재 ON 유지 중) | — |
| `ORACLE_MESH_CHANNEL_SECRET` | — | ○ | 아니오(비밀) | `*_SECRET_FILE`과 표기 통일 후보 |
| `ORACLE_MESH_EXECUTION_MODE` | — | ○ | 배포 성숙 후 정리 검토 | — |
| `ORACLE_MESH_LEGACY_MAP_LANE` / `ORACLE_MESH_OWNERSHIP_MAP` | — | ○ | 마이그레이션 완료 후 제거 후보 | 서로 한 그룹(지도 경로) |
| `ORACLE_MESH_CLAIM_LEASE_SECONDS` | 60(상수) | ✕ | 상수인 채 유지 | — |
| `PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS` | 600 | ○ | 유지(응답 조립 상한) | `PADIEM_CHAT_TIMEOUT_SECONDS`(○)와 같은 그룹 |
| `PADIEM_PC_FILES_WAIT_SECONDS` | 21(clamp 1-120) | ✕ | 유지 | — |

요약: 명령 수명에 직접 걸린 스위치는 위 표 기준 19개(접속·비밀 제외).
합칠 수 있는 것 — ① 레인 선택 3개(`SESSION_COMMAND_LANE`/`LINE_PROBE`/
`PROCESS_LANE`) → 1개, ② 사용자 모드 응답 상한 2개 → 1개, ③
`RUN_AS_USER_ONLY` 제거, ④ 지도 경로 2개는 마이그레이션 후 제거.
없애면 안 되는 것 — 무음 상한·유휴 리퍼·단일 왕복 롤백 스위치.

## 4. 11-07 장애가 수명 표의 어느 칸에서 났는가

11-07 20:05경부터 약 하루 동안 PC 명령이 한 건도 끝나지 않았다. 저널에는
`claimed`와 `start`가 찍히고 그 뒤가 없었다 — 즉 표의 6(spawn)~7(frames)
구간에서 명령이 조용히 멈춘 것인데, 원인은 둘이 겹쳐 있었다. 첫째,
사용자 모드 클라이언트를 콘솔 본문으로 보내면서 `powershell -command -`가
닫히지 않은 블록을 기다렸고(#7199가 재현·측정: 2026-11-07~08 콘솔 점유
약 19시간), 그 콘솔이 실행기의 단일 명령 슬롯을 계속 점유해 MeshCentral이
이후의 runcommand를 큐에 넣지 않고 버렸다(실행기 1834-1840 주석). 둘째,
그 무응답을 끝내는 주체가 어디에도 없었다 — 표의 10(silent_timeout)과
14(유휴 콘솔 정리) 칸이 비어 있었던 것이다. #7177/#7178이 10번 칸(무음
상한 600초 + phase 저널)을, #7180/#7182가 14번 칸(유휴 콘솔 리퍼, 최소
나이 900초)을, #7199가 6번 칸의 원인(파일 전달)을, #7215/#7205가 11번
칸의 사용자 모드 중지 경로를 각각 메꿨다. 요약: 장애 칸은 "frames에서의
무응답 + 정리 주체 부재"이고, 현재 표에는 그 두 칸이 상한·주체와 함께
채워져 있다.

## 5. 리팩터링 단계안 (작은 PR 3~6개)

각 단계의 완료 기준에는 공통 수동 확인이 들어간다: 컴1에서
① SYSTEM 모드 whoami, ② 사용자 모드 whoami, ③ 장시간 출력 명령(예:
90초 이상 출력되는 명령)이 상한에 걸리지 않고 끝나는 것, ④ 사용자 모드
중지(pc_shell_stop)가 3초 내 자식 종료로 이어지는 것.

**PR-1 — 저널 위상 상수 단일화.** `claimed/start/spawn/frames/result/
timed_out/cancelled/silent_timeout` 문자열이 실행기·포트에 흩어져 있다.
한 모듈에 상수로 모으고 두 파일이 import해 쓰게 한다. 완료 기준: 기존
시험 통과, 저널 출력이 문자열까지 동일함을 회귀로 고정, 컴1 수동 확인
4항목. 시험: 저널 스파인 스냅샷 시험 1건(위상 나열 비교).

**PR-2 — 셸 선택 한 곳으로.** §2의 이동안 실행: dispatch는 셸 이름만
운반, `resolve_shell(name)` 단일 함수가 두 레인의 구동기를 결정, 채팅
디스패처 스크립트의 `$env:PADIEM_MCP_SHELL` 분기 제거. 완료 기준:
powershell/cmd/bash 각각 컴1 SYSTEM·사용자 whoami, 장시간 출력, 중지
확인; 셸 이름 미지원 시 두 레인이 같은 오류 코드로 거부함을 시험.
시험: 셸 해석 단위 시험 + 기존 셸 관련 회귀 전부.

  실행 기록(2026-11-09, R4 ②): `padiem_ai_core.pc_shell_selection` 한 표로
  모았다. 채팅은 화이트리스트 검증만 남기고, SYSTEM 디스패처 스크립트는
  분기 없는 공통 꼬리로 바뀌었으며 런처 세 줄(`PADIEM_MCP_SHELL_FILE/`
  `ARGS/ENC`)은 표가 결정한 값을 채팅이 dispatch 안에 실어 보낸다.
  이동안의 "실행기가 이름을 받아 주입" 대신 채팅 생성 시점 해석을 택한
  이유: dispatch 행 자체가 완결되어 chat·실행기 배포 순서가 갈려도
  동작이 깨지지 않고(동작 변경 0의 배포 안전), 실행기 코드는 손대지
  않는다. 사용자 레인은 PC 측 헬퍼(단일 파일 빌드)를 바꾸지 않기 위해
  bash→wsl 번역을 채팅 측 `resolve_user_helper_shell`이 유지한다 — 헬퍼는
  최종 허용 기관으로 그대로이고, 계약 시험이 두 이름 집합의 일치를 고정한다.

**PR-3 — 레인 스위치 정리.** `SESSION_COMMAND_LANE`/`LINE_PROBE`/
`PROCESS_LANE`를 "레인 선택" 하나로 줄이거나(세션 레인 채택 시), 채택
보류라면 각 스위치의 소유·실험 상태를 코드 주석과 이 문서에 명기.
완료 기준: 기본 동작 불변(기존 회귀 통과), 컴1 수동 확인 4항목, 스위치
조합별 시작 거부 사례 시험.

**PR-4 — 사용자 모드 상한 하나로.** 첫 프레임 30초와 전체 백스톱을
"사용자 모드 응답 상한" 한 체계로 합치고 `USER_HELPER_REPLY_SECONDS`의
>0 고정·<0 끔 의미를 문서화된 하나의 값으로 정리. 완료 기준: whoami 즉시
응답, 장시간 명령 미컷, 첫 프레임 초과 시 `user_helper_timeout` 회귀,
컴1 수동 확인 4항목.

**PR-5 — 정리 주체 명시.** 표의 10·11·14 칸에 해당하는 코드 경로에
"누가 언제 정리하는가" 주석과 저널 마커 정리(코드 동작 변경 최소).
완료 기준: 유휴 리퍼·무음 상한 시험이 존재하고 통과, 컴1에서 무응답
명령 1건을 의도적으로 걸어 silent_timeout → reap 저널 확인.

순서: PR-1 → PR-2가 핵심이고, PR-3~5는 각각 독립 착수 가능. 각 PR은
단일 목적, 컴1 수동 확인 증거를 PR 본문에 붙인다.
