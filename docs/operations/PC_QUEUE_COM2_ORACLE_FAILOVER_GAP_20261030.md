# PC 대기열 com2 모드의 컴2 전장 시 오라클 페일오버 빈틈 — 분석·보완 절차 (2026-10-30)

**문서·분석 전용.** 이 문서는 코드·워크플로·운영 설정을 바꾸지 않았고, 아래 절차 중
실행된 것도 없다. 머지는 Qoder 검토 뒤 CTO 판정 대상이다.

## 0. 배경과 읽은 근거

Chat의 PC 작업 대기열을 컴2 로컬 큐(`queue.padiem.net` → 컴2 `127.0.0.1:8797`)로
옮기는 전환이 진행 중이다. Chat 쪽은 `PC_QUEUE_BACKEND=com2|d1`, 실행기 쪽은
`ORACLE_MESH_QUEUE_ORIGIN`이 분기점이다. 1차 전환은 엣지 봇 차단(1010)으로 되돌려졌고
(#6270, UA 명시, 병합 2026-10-29 23:33 UTC) 재전환을 준비 중이다. 오라클(1차 백업)에는
2026-10-21에 컴2↔오라클 메시 실행 자동 전환 장치가 설치·배포돼 있다.

문제: 대기열이 com2 모드면 대기열의 데이터도 컴2 디스크 위에 산다. 컴2가 죽으면
오라클이 실행 권리를 넘겨받아도 **일감을 받을 곳이 없다.** 이 문서는 그 빈틈을
단계별로 확정하고 보완 절차를 제안한다.

읽은 근거:

| 근거 | 위치 |
| --- | --- |
| 오라클 전환 장치 정의 | `docs/operations/MESH_FAILOVER_ORACLE_COM2_20261021.md`, `apps/korean-ai-code-agent/src/kagent/local_agent_mesh_failover.py` |
| 실행기 쪽 전환 준비 | `docs/operations/COM2_EXECUTOR_QUEUE_SWITCH_20261030.md` (#6262) |
| 큐 설치·전환·롤백 런북 | `docs/operations/COM2_PC_DISPATCH_QUEUE_CUTOVER_20261029.md` |
| Chat 분기 코드 | `apps/padiem-chat/app/queue_store_proxy.py`, `apps/padiem-chat/worker.py:1583-1590`, `apps/padiem-chat/app/oracle_mesh_read_return_routes.py:1895-1938` |
| 큐 서비스 | `apps/padiem-mesh-queue/service.py:63-76` (같은 store 코드 재사용), `copy_state.py` |
| 1010 원인·수정 | PR #6270 (병합) |
| 백업·백업2 | #5093 (오프사이트 백업 가동, 10-29), #5302 (Modal 백업2, BACKLOG) |

## 1. 오늘의 오라클 전환 장치 — 무엇을 감시하고 무엇을 바꾸는가

전환 장치가 답하는 질문은 하나다: **"지금 원격 실행 dispatch를 claim할 권리가 어느
호스트에 있나."** 대기열, 자격 증명, 결과, 장치는 소유하지 않는다.

| 구성 | 내용 |
| --- | --- |
| 건강 신호 | 컴2가 오라클로 heartbeat(`padiem_mesh_heartbeat/v1`)를 푸시 — `device_connected`, `executor_alive`. 제한된 SSH 키로 heartbeat 수신기에 고정. **누락·지연·device 미연결은 실행 가능의 증거가 아니다**는 원칙 |
| 결정 위치 | 오라클 `padiem-mesh-failover.service/.timer` — 1분당 1회 supervisor pass: heartbeat을 읽고 판정을 `failover-state.json`에 기록. 확인 연속(streak)과 fencing epoch를 함께 적어 요동 컴2가 진동하지 않게 하고 오래된 소비자를 벤다 |
| 실행기 대기 조건 | 오라클 `padiem-oracle-mesh-executor.service`는 decision이 자신을 가리키고 **자기 MeshCentral에 장치가 실제로 연결된 경우에만** 실행한다. 실행 불가능한 호스트는 claim하지 않는다. route는 컴2 건강을 따라가고, claim은 장치를 따라간다 — "com2 복귀" 신호 하나만으로 claim이 돌아오지 않는다 |
| 이벤트·알림 | `COM2_FAULT` / `ORACLE_ACTIVE` / `COM2_RESTORED` / `FAILBACK_COMPLETE`. 오라클이 로컬 로그에 기록 → COM1 `PADIEM-Mesh-Failover-Notify`(읽기 전용 SSH) → Hermes CLI → Telegram/Discord. 전달만 하는 릴레이며 판정하지 않는다 |

**컨트롤러의 시야 밖에 있는 것:** 대기열의 생존. heartbeat은 MeshCentral 장치 연결과
실행기 프로세스만 말하고, `queue.sqlite3`(dispatch·페어링·presence)의 도달 가능성은
어떤 신호에도 없다. 이벤트 어휘에도 큐에 대응하는 항목이 없다.

## 2. 시나리오 — com2 모드에서 컴2가 죽는 단계별 추적

전환 완료 후의 정상 상태(T0):

| 경로 | 흐름 |
| --- | --- |
| Chat Worker → 큐 | dispatch 12개 메서드(`QUEUE_DISPATCH_METHODS`) + 페어링 20개 + presence 2개가 `queue.padiem.net/internal/store`로 전달되고, 그 외 대화·프로젝트·R2는 D1에 남는다 (`queue_store_proxy.py`) |
| 실행기(컴2) → 큐 | poll/renew/cancel/busy 4개 다리가 `http://127.0.0.1:8797` 루프백 (`COM2_EXECUTOR_QUEUE_SWITCH_20261030.md` §1) |
| 결과 제출 | 실행기 → Chat Worker 직접(`https://chat.padiem.net`) — 봉합(consume)만 큐에 물어봄 |

T1 — 컴2 다운(Windows·WSL·네트워크 어느 층이든):

1. **큐 서비스 사망.** systemd·in-process watchdog(liveness exit 87)은 같은 호스트 안의
   방어라 호스트 사망에는 무력. 큐 SQLite(`queue.sqlite3`)는 접근 불가.
2. **Chat Worker가 fail-closed로 죽는다.** `/internal/store` 호출이 tunnel 오류/타임아웃(8초
   상한) → `QueueUnavailable` → poll 라우트는 except로 **503 `oracle_mesh_dispatch_unavailable`**
   (`oracle_mesh_read_return_routes.py:1926-1928`). #6270이 실측한 92/92 503이 바로 이 형상이다.
   새 PC 명령 생성(`create_oracle_mesh_dispatch`)·presence 기록·페어링 발급도 같은 이유로
   실패한다 — **"PC 연결" UI까지 같이 죽는다.** 사용자에게는 PC 명령 전반이 불가 상태.
3. **컴2 실행기 소멸.** poller가 사라져 갱신이 멈춘 claimed row는 큐의 lease 만료 후 pending으로
   돌아오지만(같은 store 코드) 받을 주체가 없다.
4. **오라클 supervisor가 판정 전환.** heartbeat 부재 → `COM2_FAULT` → 확인 연속 후
   `ORACLE_ACTIVE`, epoch bump. 장치 agent가 route 전환을 따라가면 오라클 MeshCentral에
   `oracle_device_connected=1`이 된다(전송로 다리 — 이 문서 범위 밖, §5.1 경로는 이미
   정의돼 있음).
5. **오라클 실행기 투입 — 여기서 빈틈이 드러난다.** 실행 조건(decision=oracle, 장치 연결)은
   충족하지만 poll은 `ORACLE_MESH_CHAT_ORIGIN`(chat.padiem.net) → Worker(com2 모드) → 큐
   프록시 → 죽은 큐 → **503 반복. 오라클은 오라 클 수 있는 권리만 있고 일감이 없다.**
6. **진행 중·미전달 상태는 전부 죽은 호스트 디스크에 좌초한다:**
   - 컴2가 실행하던 명령: 중단, 큐 안에서 lease 만료 후 pending 복귀, 그러나 소비자 부재 → 좌초
   - 큐가 이미 받은 결과(`received`/`store_failed`): 봉합(consume)을 큐에 물어봐야 수용되므로
     큐 사망 시 사용자 대화에 미반영
   - com2 창 동안 발급된 페어링 코드·완성된 PC 연결(`pc_pairing_codes`, `pc_device_links`)과
     presence 수신분 — D1에는 없음
7. **관측 신호가 사실상 사라진다.** 큐 `/health`는 루프백 전용, `lane-status`도 컴2 위에서만
   읽히고, 실행기 측 모니터(#82)는 컴2 상주라 함께 죽는다. 남는 외부 신호는 ① Worker의
   503률(ops 측에서 읽음), ② 오라클 mesh 이벤트(큐와 무관), ③ 사용자 보고뿐이다. 큐 전용
   이벤트·알림 경로는 존재하지 않는다.

## 3. 빈틈 목록

| # | 빈틈 | 근거 |
| --- | --- | --- |
| G1 | 페일오버가 claim **권리**만 옮기고 claim **lane 데이터**는 옮기지 못한다. 오라클 활성화 후에도 오라클 실행기 poll은 503 반복 | §2-5, `MESH_FAILOVER_ORACLE_COM2_20261021.md` §2("does not own the queue") |
| G2 | d1 자동 폴백이 없다. `PC_QUEUE_BACKEND`는 사람이 배포 게이트로 바꾸는 값이고 컨트롤러·감시 어느 쪽도 이 값을 바꿀 수 없다 | `worker.py:1583-1590`(조립 시 스위치), 런북 §6 |
| G3 | com2 창의 상태가 큐 단독 소유(소유권 (가)). d1 복귀 시 마지막 사본 이후의 dispatch·페어링·presence가 D1에 없다 | 런북 §1 소유권 표, `queue_store_proxy.py` 메서드 집합 |
| G4 | 큐→D1 역방향 복사 도구가 없다. `copy_state.py`는 D1 스냅샷→큐 방향의 `copy`/`diff`만 제공 | `apps/padiem-mesh-queue/copy_state.py:159-163` |
| G5 | 큐 장애의 전용 감지·이벤트가 없다. mesh 이벤트 어휘(`COM2_FAULT` 등)에 큐 항목이 없고 알림 릴레이도 mesh 판정만 전달한다 | 전환 장치 문서 §2-§4 |
| G6 | 외부 관측 불가. `/health` 루프백 전용, lane-status도 컴2 위에서만 읽히고 실행기 모니터는 컴2 상주 | 런북 §7, `COM2_EXECUTOR_QUEUE_SWITCH_20261030.md` §4 |
| G7 | "장애 → d1 → 컴2 복구 → com2" 전체 사이클 문서가 없다. 전환(§5)·롤백(§6)은 따로 있고, 장애 맥락에서 d1 창의 D1 신규 row를 큐로 되돌려 담는 순서(§4 재실행)가 미정의다 | 런북 §4-§6 대조 |

참고로 백업은 존재한다(#5093 오프사이트, 매일 05:10, 큐 포함 — 10-29 `OFFSITE_RUN=PASS`).
백업은 데이터 보존이지 가용성이 아니다: 컴2가 죽은 동안 그 백업으로 claim lane을 살릴
수는 없다.

## 4. 보완 절차 제안 (절차·문서 수준 — 코드 변경은 별도 과제)

### 4.1 감지 (자동화 가능)

- **Chat 측(1차 제안):** ops 읽기 전용 점검이 Worker의 mesh-reads 503(`oracle_mesh_dispatch_unavailable`)
  연속 횟수를 스캔한다(#82 모니터가 이미 읽는 계열). 임계(예: 5분 연속) 도달 시 기존
  Hermes 경로(Telegram/Discord)로 "큐 불가 — d1 복귀 대기" 알림. lane-status 읽기는
  컴2 생존 시에만 유효하므로 503률이 주 신호다.
- **오라클 측(2차 제안, 코드 수반):** heartbeat에 `queue_ok` 필드를 추가해 supervisor가
  함께 판정하고, 이벤트 어휘에 `QUEUE_UNAVAILABLE`을 더한다. 컨트롤러 변경이라 본
  문서 범위 밖의 별도 승인 과제다.

### 4.2 d1 복귀 순서 (사람 게이트 — 컴2 죽은 직후)

1. **판정:** 4.1 알림 + 오라클 `COM2_FAULT`/`ORACLE_ACTIVE` 이벤트(또는 담당 실측)로 컴2
   장애 확정.
2. **진행 중 명령의 처분을 명시적으로 기록.** 죽은 큐의 `pending_claimed`는 기다려도 0이
   되지 않는다(회수 불가). zero-flight 조건을 만족할 수 없으므로 "큐가 쥔 명령은 폐기하고
   d1 기준으로 재개한다"는 결정을 이슈에 남긴다. 복구 후 회수는 4.3.
3. **Cloudflare 게이트로 `PC_QUEUE_BACKEND=d1` set_var → 배포 게이트 publish.**
   프록시는 조립 시 선택되므로 코드 재배포는 불필요하다
   (`worker.py:1583-1590`, 런북 §6). `PC_QUEUE_ORIGIN`·시크릿은 재전환 대비 그대로 둔다.
   `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY` 절차·감사를 따른다.
4. **확인:** Worker 기동 라인 `PC_QUEUE_BACKEND=d1` + 실제 PC 명령 1건 E2E.
5. **오라클 실행기는 손대지 않는다.** 오라클에 `ORACLE_MESH_QUEUE_ORIGIN`을 넣지 않은
   현재 설계(오라클은 Chat 직접 poll)이기 때문에 d1 복귀 즉시 오라클이 D1에서 일감을
   받는다. **이 특성이 복구 경로의 핵심이므로 오라클 실행기에 큐 origin을 넣지 말 것**을
   이 문서로 권고한다.
6. **사용자 안내:** com2 창 동안 접수된 PC 명령은 d1 경로에 없다. 재시도를 안내하거나
   컴2 복구 후 4.3으로 회수한다.

### 4.3 상태 손실 범위와 회수

| 상태 | d1 복귀 후 | 회수 |
| --- | --- | --- |
| 전환 전부터 있던 device links | D1에 있음 — 그대로 사용 | 불필요 |
| com2 창의 페어링 코드·신규 연결 | D1에 없음 — 그 PC는 d1 모드에서 "미연결"로 보임 | 컴2 복구 후 역방향 반영 |
| com2 창의 dispatch(pending/claimed/received) | D1에 없음 — 재접수 필요 | 역방향 반영 또는 사용자 재시도 |
| 결과 원문(R2)·대화 행 | Worker 소유 — 무영향 | 불필요 |
| presence 수신분 | D1에 없음 — 재수집됨 | 자연 복구 |

회수 절차(컴2 복구 후, 사람 실행): 죽은 큐 SQLite를 읽기 전용으로 열어
`copy_state.py diff`로 변동 목록을 뽑고, **큐→D1 역방향 반영**을 한다. 이 방향의 도구가
없다(G4) — 수동 export/변환/D1 insert 또는 `copy_state`에 역방향 모드를 추가하는 것을
별도 코드 과제로 제안한다. dispatch 중복은 `record_oracle_mesh_first_result` 계약과
consume 단일성으로 흡수 가능한지 사전 테스트가 필요하다(별도 테스트 과제).

### 4.4 컴2 복구 후 com2 재전환 순서 (사람 게이트)

1. 컴2 복구 확인: `padiem-mesh-queue.service` 기동, `/health`, 필요 시 런북의 백업 복원
   절차(stop → 파일 교체 → start → health)와 `integrity_check`.
2. **d1 창의 상태를 큐로 되돌려 담는다:** `copy_state.py copy --source <D1 스냅샷>
   --target queue.sqlite3` + `diff` — 기존 §4의 재실행이고 이 방향은 이미 지원된다.
3. 4.3의 역방향 반영을 먼저 끝내 d1↔큐 어긋남을 최소화한 뒤 2를 실행한다
   (순서: 역방향 반영 → §4 재실행 → diff 0).
4. 런북 §5를 그대로 재실행: zero-flight(pending_unclaimed/claimed/received = 0) →
   tunnel 경로 확인(**1010 재발 여부 포함 — #6270 버전이 배포돼 있어야 한다**) →
   `PC_QUEUE_BACKEND=com2` set_var → 기동 라인 확인 → 실행기 drop-in 유지 확인 →
   30분 관측(읽기 1건·find 1건·페어링 1건).

### 4.5 자동과 사람의 경계

| 자동화 가능 | 사람 게이트 필수 |
| --- | --- |
| 503 streak 감지·알림, `copy_state.py diff` 증거 수집, 백업 무결성 점검, 복구 후 diff 0 검증, 오라클 mesh 이벤트 전달(기존) | `PC_QUEUE_BACKEND` set_var 전환(com2↔d1 모두 — production 구성 변경), zero-flight 판정, 좌초 명령 폐기 결정, 큐→D1 역방향 반영 실행, 재전환 승인 |

향후 옵션(대표 결정 대상, 본 문서 미구현): heartbeat에 `queue_ok` 추가 + 사전 승인된
자동 d1 폴백(워크플로가 게이트 set_var 실행). 컨트롤러·정책 변경을 수반하므로 별도
과제로만 검토한다.

## 5. 후속 구현의 수용 기준(요약)

| 항목 | 기준 |
| --- | --- |
| 감지 | com2 모드에서 큐 차단 주입 시 5분 내 알림 1건, 오탐 0(정상 창 7일) |
| d1 복귀 | set_var 게이트 감사 기록 + 기동 라인 `d1` + PC 명령 1건 E2E PASS |
| 상태 회수 | 역방향 반영 후 `diff` 추가/변경 = 의도분만, 중복 dispatch 0 |
| 재전환 | §5 전 절차 통과, 30분 관측에서 503률 사전 창 대비 유의미한 개선 |
| 1010 | 재전환 배포 버전이 #6270 포함을 기동 라인·버전 ID로 확인 |

## 6. 비목표

- 코드·워크플로·운영 설정 변경 없음(본 PR은 이 문서 1개뿐).
- 자동 d1 폴백·컨트롤러 변경·`copy_state` 역방향 모드 구현 없음 — 별도 과제로 제안만.
- 메시 전송로(route) 다리의 자체 분석 없음 — `MESH_FAILOVER_ORACLE_COM2_20261021.md`
  §5의 기존 정의를 참조로 인용.
