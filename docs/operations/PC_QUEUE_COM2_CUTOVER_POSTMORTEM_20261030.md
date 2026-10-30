# PC 작업 대기열 컴2 전환 사후 기록 (2026-10-30)

- 작성 기준: 2026-10-30 19:44 KST (최초 작성 18:42:56)
- 대상: PC 작업 대기열 D1 → 컴2 큐 전환
- 관련: #5573, #5881, #6216, #6261, #6270, #6279, #6281, #6283, #6291, #6303, #6104
- 상태: PR (미병합). 병합·배포 판단은 CTO가 한다.

## 1. 요약 (5줄)

- 2026-10-30 PC 작업 대기열을 D1에서 컴2 큐로 옮기는 전환을 네 차례 시도했고, 19:10 재시험 기준 실제 PC 작업 1건 E2E는 아직 통과하지 못했다.
- 확인된 직접 원인은 8개다. 6개는 수정·배포됐고, `create_oracle_mesh_dispatch` 소유권 조회 결함 #6303은 18:36:42에 병합된 뒤 큐 호스트에 적용됐다. 8번째는 Chat Worker가 결과 저장 때 dispatch를 D1에서 다시 읽는 결함으로, Qoder 수정 PR이 진행 중이다. E2E는 여전히 미통과다.
- 전환 창에서는 코드 배포와 백엔드 값 전환이 한 배포에 묶였고, 가짜 클라이언트·신선한 DB·presence 성공이 실제 경로를 대신했다.
- PC 작업을 받을 수 없는 창은 1차 31분, 2차 11분 33초, 3차 4분 30초, 4차 14:13 이후 지속(18:42 기준 약 4시간 29분, 19:10 기준 종료 미확정)이다.
- 이 문서는 PR로만 올린다. 병합과 운영 판단은 CTO가 한다.

## 2. 타임라인 (2026-10-30, KST)

| 시각 | 버전 ID | 사건 | 근거 |
|---|---|---|---|
| 07:02:53 | `6730e5fd` | 전환 전 기준 배포(#6236 설치기 백업 디렉터리). 직전 `df488d7d`, 07:06:19 활성 | [run 40962771157](https://github.com/skerishKang/ai-revenue-lab/actions/runs/40962771157) |
| 07:42:19–07:43:00 | — | #6216(시크릿 기준선), #6261(Chat `PC_QUEUE_BACKEND=com2`) 병합 | [#6216](https://github.com/skerishKang/ai-revenue-lab/pull/6216), [#6261](https://github.com/skerishKang/ai-revenue-lab/pull/6261) |
| 07:43:28 | `265000e3` | 1차 com2 전환 배포. 직전 `a7aed03d`, 07:46:45 배포 | [run 40968011015](https://github.com/skerishKang/ai-revenue-lab/actions/runs/40968011015) |
| 07:46–08:17 | — | 1차 전환 창: `mesh-reads/poll`이 10초 창에서 **92/92 503**, PC 작업 불가 | [#6270](https://github.com/skerishKang/ai-revenue-lab/pull/6270) |
| 08:03:55 | `a7aed03d` | 1차 코드 롤백 시도. 이후 08:14 `set_var` 재배포가 다시 필요했음(바인딩 값은 로그에 없음) | [run 40970377476](https://github.com/skerishKang/ai-revenue-lab/actions/runs/40970377476) |
| 08:14:06 | `45c1f7c5` | d1 복귀를 위한 재배포(추정; 입력값은 로그에 미기재), 08:17:44 활성 | [run 40971708946](https://github.com/skerishKang/ai-revenue-lab/actions/runs/40971708946) |
| 08:33:28 | — | #6270 병합(큐 호출 UA 고정) | [#6270](https://github.com/skerishKang/ai-revenue-lab/pull/6270) |
| 08:36:08 | `c2f77d78` | #6270 배포, 08:39:38 활성. 큐 상태 재복사 generation은 `20261029T233938663045Z`(08:39:38 KST) | [run 40974249274](https://github.com/skerishKang/ai-revenue-lab/actions/runs/40974249274), [#6281](https://github.com/skerishKang/ai-revenue-lab/pull/6281) |
| 08:58:35 | `b7154083` | 2차 com2 전환, 09:02:23 활성 | [run 40976675777](https://github.com/skerishKang/ai-revenue-lab/actions/runs/40976675777) |
| 09:02–09:14 | — | 2차 전환 창: 큐 재시작 크래시 루프(`duplicate column name: kind`), PC 작업 불가 | [#6281](https://github.com/skerishKang/ai-revenue-lab/pull/6281) |
| 09:10:35 | `024882b5` | 2차 d1 롤백, 09:13:56 활성 | [run 40978004658](https://github.com/skerishKang/ai-revenue-lab/actions/runs/40978004658) |
| 10:11:52 | — | #6279 병합(Workers 호환 stream/aiter_bytes) | [#6279](https://github.com/skerishKang/ai-revenue-lab/pull/6279) |
| 10:13:22 | `44ad8695` | #6279 배포(d1 유지), 10:16:42 활성 | [run 40984527601](https://github.com/skerishKang/ai-revenue-lab/actions/runs/40984527601) |
| 12:34:32 | — | #6281 병합(스키마 적용 이력·backfill) | [#6281](https://github.com/skerishKang/ai-revenue-lab/pull/6281) |
| 12:43:41 | `dbc14651` | #6281 배포, 12:47:18 활성 | [run 40998982886](https://github.com/skerishKang/ai-revenue-lab/actions/runs/40998982886) |
| 12:54:43 | — | #6283 병합(워치독 exit 배선, queue.env 로그) | [#6283](https://github.com/skerishKang/ai-revenue-lab/pull/6283) |
| 13:05:39 | `7595e7a0` | 3차 com2 전환, 13:10:26 활성 | [run 41000953269](https://github.com/skerishKang/ai-revenue-lab/actions/runs/41000953269) |
| 13:10–13:15 | — | 3차 전환 창: presence upsert `502 ms=0 proof=ok`(`received_at` 누락), PC 작업 불가 | [#6291](https://github.com/skerishKang/ai-revenue-lab/pull/6291) |
| 13:11:26 | `30c8d635` | 3차 d1 롤백, 13:14:56 활성 | [run 41001496619](https://github.com/skerishKang/ai-revenue-lab/actions/runs/41001496619) |
| 13:56:25 | — | #6291 병합 | [#6291](https://github.com/skerishKang/ai-revenue-lab/pull/6291) |
| 14:07:34 | `7751d8b7` | 4차 com2 전환, 14:13:08 활성 | [run 41006660288](https://github.com/skerishKang/ai-revenue-lab/actions/runs/41006660288) |
| 14:11–지속 | — | 4차 전환 창: `create_oracle_mesh_dispatch` 502, `no such table: claw_run_history`; 19:09 생성 경로 복구 후 결과 저장 403(`oracle_mesh_conversation_forbidden`)으로 E2E 미통과 | [#6303](https://github.com/skerishKang/ai-revenue-lab/pull/6303) |
| 17:49:21 | — | `win.ini` 실제 요청이 큐에 도달(`proof=ok`)한 뒤 create에서 실패, 원인 확정 | [#6303](https://github.com/skerishKang/ai-revenue-lab/pull/6303) |
| 18:13:39 | — | #6303 PR 생성 | [#6303](https://github.com/skerishKang/ai-revenue-lab/pull/6303) |
| 18:36:42 | `e6692fcc` (main) | #6303 병합. 19:09 이전 큐 호스트 적용 확인(src → `e6692fcc137b`, install exit 0, 재시작 1회) | [#6303](https://github.com/skerishKang/ai-revenue-lab/pull/6303), [commit e6692fcc](https://github.com/skerishKang/ai-revenue-lab/commit/e6692fcc137b388e7dbb4120e3e0d5960580a6f4), Qoder 보고(CTO 전달) |
| 18:42:56 | — | 최초 작성 기준 시각. 4차 전환 유지, 실사용 PC 작업 차단 지속(공개 기록 기준) | 확인 시각 |
| 19:09:04 | — | 컴1 브라우저 레인 `win.ini` 재시험(#6303 반영 후). run_id `chat_pcq_0eae40eca6c34e4fb1bc47a7af402cb4`. "PC 요청 접수"까지 진행(생성 경로 복구 확인) → 결과 조회 `GET /api/claw/runs/<run_id>/pending-result` HTTP 503 → 19:10:20 연결 오류 | CTO 전달 — Qoder 보고(19:27) |
| 19:09:20.426 | — | dispatch 생성 성공. 이어 claim·PC 읽기 실행·결과 제출·큐 저널 거부 0건으로 큐 레인은 전부 성공 | Qoder 추적(CTO 전달, 19:44) |
| 19:10:20 | — | 원인 확정(Qoder 추적): Chat Worker가 결과 원본 저장 때 dispatch를 D1에서 다시 읽어 `mesh dispatch is not owned by current user` → finish(failed) → Chat Worker HTTP 403 `oracle_mesh_conversation_forbidden`. 상세 경로와 수정 방향은 D8. E2E 미통과 | Qoder 추적(CTO 전달, 19:44) |

## 3. 결함 목록

### D1. 1차 전환의 poll 503 — Workers `httpx_compat` 인터페이스 부재

- **증상:** 1차 전환 직후 `/api/claw/connector/mesh-reads/poll`이 503. 10초 창에서 92/92 연속 실패.
- **진짜 원인:** Workers Python `httpx_compat`의 AsyncClient에는 `post()`가, Response에는 `json()`이 없는데 `QueueStoreClient.call()`이 두 메서드를 사용했다. 요청이 나가기 전에 `AttributeError`가 났고, poll 라우트가 fail-closed로 503을 반환했다.
- **최초 오진:** 외부 PC 재현에서 본 Cloudflare 1010(UA `Python-urllib/3.12`)을 원인으로 판단해 #6270에서 UA를 고정했다. UA는 외부 재현의 원인이었지만 Worker 내부 503의 원인은 아니었다.
- **수정 PR:** #6279 — `stream("POST")` + `aiter_bytes()`로 Workers 호환 경로를 사용하고, 단계별 로그를 추가했다.
- **왜 놓쳤나:** 테스트 fake가 `post`/`json`을 제공했고 CI의 CPython httpx에도 두 메서드가 있었다. 실제 Workerd/Pyodide 경로에서 큐 클라이언트를 호출하는 테스트가 없었다.

### D2. 2차 전환의 큐 재시작 크래시 루프 — 매번 9개 마이그레이션 재적용

- **증상:** 2차 전환에서 큐 서비스가 뜨지 않고 재시작을 반복했다. `sqlite3.OperationalError: duplicate column name: kind`.
- **진짜 원인:** `schema.apply()`가 DB를 열 때마다 9개 마이그레이션을 다시 적용했다. 상태 복사본에는 이미 스키마가 있었고, 048의 `ALTER TABLE ... ADD COLUMN kind`가 중복 컬럼으로 실패했다.
- **최초 오진:** 마이그레이션 SQL 변경 자체를 잘못한 것으로 의심했다.
- **수정 PR:** #6281 — `queue_schema_applied`에 적용 이력을 기록하고, 기존 DB는 backfill하며, 신규 마이그레이션만 적용하고, 중복은 허용하되 필수 테이블은 검증한다. 재복사 generation은 `20261029T233938663045Z`(08:39:38 KST).
- **왜 놓쳤나:** 큐가 항상 새로 만든 DB에서만 검증됐다. 운영처럼 스키마가 이미 있는 DB를 여는 경로가 테스트에 없었다.

### D3. 워치독이 종료하지 않음 — `exit_process` 배선 누락

- **증상:** 워치독이 `exit_code=87`을 남기지만 프로세스는 `active`를 유지했다. 무응답 큐가 자동 재시작되지 않았다.
- **진짜 원인:** `start_liveness_watchdog`가 `liveness_rounds(..., pool=pool)`만 호출하고 `exit_process`를 넘기지 않았다. `liveness_rounds`는 `exit_process is None`이면 실패 목록만 반환하고 끝난다.
- **최초 오진:** 로그에 exit 87이 보여 워치독이 작동한다고 판단했다. 테스트도 `exit_process`를 주입해 통과했다.
- **수정 PR:** #6283 — `_exit_unresponsive`가 `os._exit(code)`를 호출하고, 워치독에 실제로 배선한다. 테스트가 `os._exit(87)` 호출을 단정한다.
- **왜 놓쳤나:** 테스트가 운영에서 빠진 의존성을 주입해 초록불이었다. 의존성 배선 자체를 검증하지 않았다.

### D4. drop-in `Environment=`가 먹지 않음 — 실행 프로세스 환경 미확인

- **증상:** `MESH_QUEUE_REQUEST_LOG`를 systemd drop-in `Environment=`로 바꿨는데 프로세스는 `off`였다. `systemctl show -p Environment`는 `refusals`를 보여 혼동을 키웠다.
- **진짜 원인:** 이 유닛의 실제 프로세스 환경은 `queue.env`에서 오고, drop-in `Environment=`는 효과가 없었다. 실행 중 프로세스의 환경을 봐야 했다.
- **최초 오진:** 유닛 설정(`systemctl show`)을 실행 프로세스 환경으로 신뢰했다.
- **수정 PR:** #6283 — `queue.env`만 유효하다고 문서화하고, `/proc/<pid>/environ` 확인 절차를 추가했다.
- **왜 놓쳤나:** 설정 파일과 실행 프로세스를 분리해 검증하지 않았다.

### D5. tail 0행 — JSON 배열을 JSONL로 읽음

- **증상:** 캡처가 `TAIL_LINES=4541`인데 `TAIL_ROWS=160`, `TAIL_FIELDS=`로 비어 있었다.
- **진짜 원인:** `wrangler tail --format json`은 줄 단위 JSONL이 아니라 여러 줄에 걸친 JSON 배열 하나를 출력한다. 파서가 줄 단위로 읽어 160개 객체를 하나의 dict로 오인했다.
- **최초 오진:** 출력이 JSONL이라고 가정했다.
- **수정 PR:** #6104 — `JSONDecoder.raw_decode`로 배열/JSONL을 모두 처리하고, 파싱 불가 시 `TAIL_EMPTY=1`을 남기며, tail 등록 해제를 API로 확인한다.
- **왜 놓쳤나:** 실제 출력 형태의 fixture가 없었고, 첫 캡처가 커서 육안 확인을 건너뛰었다. 이 결함은 10/30 전환 이전(10/29 07:19 병합)에 이미 들어와 있었다.

### D6. 3차 전환의 `502 ms=0 proof=ok` — `received_at` coerce 누락

- **증상:** 2단계 쓰기(대표적으로 presence upsert)가 `502 ms=0 proof=ok`로 실패했다. 큐 DB는 건강했고 행도 없었다. PC 작업은 불가였다.
- **진짜 원인:** `_coerce`가 시간으로 인정하는 순간 값이 `{"now", "issued_at"}`뿐인데 presence upsert는 `received_at`을 함께 넣었다. JSON에서 datetime이 텍스트로 바뀌고 `_stamp()`가 "trusted aware receipt time required"로 거부해 DB 전 단계에서 실패했다.
- **최초 오진:** cancel이 연 트랜잭션이 batch를 깨뜨린 것으로 의심했다. `batch()`의 BEGIN..COMMIT 안에 await가 없어 성립하지 않았다.
- **수정 PR:** #6291 — `MOMENT_ARGUMENTS`에 `received_at`을 추가하고 ISO 텍스트를 datetime으로 coerce한다. 실패 클래스명·트랜잭션 복구 로그를 남기고, `batch()`는 `BaseException`도 처리한다.
- **왜 놓쳤나:** 순간 값 집합이 하드코딩되어 새 timestamp 필드를 추가할 때 함께 갱신되지 않았다. ISO 텍스트 입력 테스트가 없었다.

### D7. 4차 전환의 dispatch 차단 — 공유 코드가 D1 테이블을 가정

- **증상:** 14:11부터 실제 PC 작업이 막혔다. `create_oracle_mesh_dispatch status=502 ms=0 proof=ok`, `MESH_QUEUE_STORE_FAILURE fail=OperationalError`. 본문은 `no such table: claw_run_history`.
- **진짜 원인:** `D1HistoryStore`의 소유권 확인이 항상 D1의 `claw_run_history`를 읽었다. 큐 DB에는 이 테이블이 없어 create dispatch가 거부됐다.
- **최초 오진:** presence/pairing이 정상이라 전환이 완료된 것으로 판단했다. 실제 PC 명령 E2E를 하지 않았다.
- **수정 PR:** #6303 — `run_ownership` 기본값을 None으로 두고, D1은 기존 경로를 유지하며, 큐는 `service._forwarded_run_ownership`을 사용한다. 18:36:42 병합됐고 19:09 이전 큐 호스트에 적용됐다(src → `e6692fcc137b`, install exit 0, 재시작 1회).
- **왜 놓쳤나:** 공유 코드가 D1 스키마를 전제했다. 큐 테스트가 `claw_run_history`를 만들거나 소유권 경로를 우회했고, E2E는 presence만 확인했다.

### D8. 19:09 재시험의 결과 저장 403 — Chat Worker가 dispatch를 D1에서 다시 읽음

- **증상:** 19:09:04 `win.ini` 재시험은 "PC 요청 접수"까지 진행됐지만, 결과 조회 `GET /api/claw/runs/<run_id>/pending-result`가 HTTP 503, 19:10:20 연결 오류. 실제 작업 1건 E2E는 미통과.
- **진짜 원인:** 큐 쪽은 전부 성공했다 — dispatch 생성 19:09:20.426, claim, PC 읽기 실행, 결과 제출, 큐 저널 거부 0건. 실패는 Chat Worker의 결과 원본 저장 단계 `_store_oracle_mesh_read_original` → `store_oracle_mesh_original`이 dispatch를 D1에서 다시 읽은 것이다. com2 모드에서는 그 행이 큐에만 있어 D1에 없고, "mesh dispatch is not owned by current user"로 거부돼 `finish(failed)` 후 Chat Worker HTTP 403 `oracle_mesh_conversation_forbidden`이 됐다. 명령 레인 `store_oracle_mesh_command_result`에도 같은 읽기가 있다.
- **최초 오진:** 큐 재시작(19:08:28·19:08:51)과 시각이 겹쳐 재시작 영향을 의심했지만, dispatch 생성 성공으로 원인 아님이 확인됐다.
- **수정 PR:** Qoder 수정 PR 진행 중(번호 미정).
- **수정 방향:** 같은 요청에서 소유자 확인을 거친 dispatch로 핀을 검증하고 D1 재읽기를 없앤다. Worker 전체에서 D1 직접 읽기를 전수 점검하고, com2 모드 경로 전체 계약 테스트를 추가한다.
- **왜 놓쳤나:** 큐 이전 시 표를 읽는 모든 호출부를 찾지 않았다. #6303과 같은 종류(큐로 옮긴 표를 다른 곳이 아직 옛 위치에서 읽음)이며, 위치만 Worker 쪽이다.

### D9. 롤백 절차 — 코드 버전만 되돌리고 바인딩 값을 확인하지 않음 (원인 일부 추정)

- **증상:** 08:03:55 코드 롤백(run 40970377476) 후에도 08:14 재배포가 필요했고, 08:17:44에 새 버전이 활성화됐다. 그 값이 d1이었다는 직접 로그는 없다.
- **진짜 원인(추정):** Cloudflare 버전 롤백은 코드만 되돌리고 `PC_QUEUE_BACKEND` 같은 바인딩 값은 현재 배포 값을 유지했을 가능성이 있다. 확인된 사실은 코드 롤백 후 재배포가 있었고, 08:17:44에 새 버전이 활성화됐다는 점이다.
- **최초 오진(추정):** 이전 버전 ID로 돌리면 전환 전 상태로 완전히 복귀한다고 판단했다.
- **수정 PR:** 없음(운영 절차). #6283의 설정 확인 절차와 이 문서의 체크리스트로 보완한다.
- **왜 놓쳤나:** 롤백 검증이 버전 ID/활성 버전 확인에 그쳤고, 바인딩 값과 실제 요청을 확인하지 않았다.

## 4. 사용자 영향 — PC 커넥터 다운타임

| 창 | 시작–끝 (KST) | 길이 | 증상 | 근거 |
|---|---|---:|---|---|
| 1차 | 07:46:45–08:17:44 | 31분 | poll 503(92/92) | [#6270](https://github.com/skerishKang/ai-revenue-lab/pull/6270), [run 40968011015](https://github.com/skerishKang/ai-revenue-lab/actions/runs/40968011015) |
| 2차 | 09:02:23–09:13:56 | 11분 33초 | 큐 재시작 크래시 루프 | [#6281](https://github.com/skerishKang/ai-revenue-lab/pull/6281), [run 40976675777](https://github.com/skerishKang/ai-revenue-lab/actions/runs/40976675777) |
| 3차 | 13:10:26–13:14:56 | 4분 30초 | presence 502(`received_at`) | [#6291](https://github.com/skerishKang/ai-revenue-lab/pull/6291), [run 41000953269](https://github.com/skerishKang/ai-revenue-lab/actions/runs/41000953269) |
| 4차 | 14:13:08–지속 | 18:42:56 기준 4시간 29분 48초, 이후 지속 | create dispatch 502(`claw_run_history`) → 생성 복구 후 결과 저장 403(`oracle_mesh_conversation_forbidden`) | [#6303](https://github.com/skerishKang/ai-revenue-lab/pull/6303), [run 41006660288](https://github.com/skerishKang/ai-revenue-lab/actions/runs/41006660288), Qoder 보고 |
| **합계** | — | **약 5시간 17분 + 지속(19:10 기준)** | 4차는 진행 중 | 19:10 기준 |

- 19:09:04 재시험에서 #6303 적용 후 생성 경로는 복구됐지만("PC 요청 접수"), Chat Worker의 결과 저장 단계가 dispatch를 D1에서 다시 읽어 403 `oracle_mesh_conversation_forbidden`으로 실패했다. `pending-result`는 503/19:10:20 연결 오류였고, 4차 종료 시각은 **미확인**이다.
- 위 수치는 **PC 작업을 받을 수 없는 창**의 합계다. 창 안에서 실제 사용자 요청이 몇 건 있었는지, 어떤 계정이 영향을 받았는지는 **미확인**이다.
- 전환/롤백 입력값은 Actions 로그에 남지 않는다. 구간은 버전 활성 시각과 PR 기록으로 계산했으며, 1차 종료 버전이 d1이었다는 직접 로그는 없다.
- 4차는 #6303의 "14:11부터" 기록과 배포 활성 14:13:08 사이에 2분 차이가 있다. 첫 실패 시각은 14:11–14:13 사이로 보며, 정확한 초 단위는 **미확인**이다.
- 1차는 08:03:55 코드 롤백 시도가 있었지만, 08:14 재배포 전까지 실제 복구가 확인되지 않아 08:17:44까지로 계산했다.

## 5. 교훈과 다음 전환 체크리스트

### 5.1 교훈

- **"배포 성공"은 "전환 성공"이 아니다.** 코드 배포와 백엔드 값 전환을 분리하고, 전환 후 실제 요청 1건으로 판정해야 한다.
- **가짜는 계약을 맞춰야 한다.** fake가 production interface의 메서드를 모두 갖추지 않으면, 테스트가 배선 누락을 숨긴다.
- **신선한 DB는 운영 DB가 아니다.** 마이그레이션은 적용 이력, backfill, 중복 허용, 필수 테이블 검증을 갖춰야 한다.
- **presence/pairing은 dispatch가 아니다.** "보인다"와 "실제 PC 작업이 된다"를 분리해서 봐야 한다.
- **표를 옮길 때는 그 표를 읽는 모든 호출부를 grep으로 전수 확인하고, 옛 위치에 행이 없는 상태로 경로 전체 테스트를 돌린다.**
- **row-level 오류를 보존해야 한다.** 92/92, 0 rows 같은 집계는 형태 결함과 원인을 숨긴다.
- **롤백은 코드만 되돌리는 것이 아니다.** 바인딩/환경값과 실제 요청까지 확인해야 한다.
- **설정은 실행 프로세스에서 확인해야 한다.** `systemctl show`나 drop-in만 믿지 말고 `/proc/<pid>/environ`을 읽어야 한다.
- **유휴 backoff를 판정 창에 넣어야 한다.** 첫 claim은 최대 63초까지 걸릴 수 있어, 짧은 창의 무응답을 장애로 단정하면 안 된다.

### 5.2 다음 전환 체크리스트 (필수 10개)

1. **실제 경로 증거만 인정한다.** 운영과 같은 Workerd/Pyodide, 실제 큐 HTTP, 실제 PC 명령 1건이 있어야 한다. fake/CPython-only 증거는 합격이 아니다.
2. **fake는 production interface와 일치시킨다.** `post`/`json` 부재 같은 차이를 테스트가 재현하고, 계약 테스트가 메서드 존재를 단정해야 한다.
3. **새 코드는 d1에 먼저 배포하고, 백엔드 전환은 별도 배포로 한다.** d1에서 실제 poll/result 1건을 확인한 뒤 com2로 전환한다.
4. **배포/DB apply 중 main을 동결한다.** 전환 창에 무관한 merge/deploy를 금지하고 exact SHA를 고정한다.
5. **row-level 오류를 보존한다.** tail/queue 로그는 원문 shape과 row count를 남기고, 0 rows/집계만으로 판정하지 않는다.
6. **롤백 기준과 1분 판정을 미리 정한다.** "이 신호면 1분 내 롤백"을 전환 전에 합의하고, 롤백 후 바인딩/환경값과 실제 요청까지 확인한다.
7. **presence만으로 판정하지 않는다.** pairing/presence/health가 정상이어도 실제 PC 명령 1건(예: `win.ini` 읽기)이 끝까지 가야 완료다.
8. **설정은 `/proc/<pid>/environ`에서 확인한다.** `systemctl show`/drop-in만으로 판정하지 않는다.
9. **idle backoff를 판정 창에 포함한다.** 첫 claim 최대 63초, presence max 65초 vs 180초 bound를 기준으로 창을 잡는다.
10. **공유 코드는 다른 DB의 테이블을 가정하지 않는다.** D1/큐 스키마 차이를 명시하고, ownership/dispatch create를 양쪽 DB에서 테스트한다.

## 6. 남은 작업

- **[P0] 실제 작업 1건 E2E 통과.** #6303은 큐 호스트에 적용됐고 19:09:04 재시험에서 "PC 요청 접수"까지 진행돼 생성 경로 복구를 확인했다. 큐 레인(생성 19:09:20.426·claim·PC 읽기·결과 제출·저널 거부 0건)도 성공했지만, Chat Worker가 결과 저장 때 dispatch를 D1에서 다시 읽어 403 `oracle_mesh_conversation_forbidden`으로 실패했다. Qoder 수정 PR 반영·배포 후 `win.ini` E2E를 다시 돌려 **E2E 통과**를 확인해야 한다.
- **[P0] 4차 전환 유지/롤백 결정.** E2E 미통과가 이어지면 PC 작업 차단도 계속된다. Qoder 수정 PR 배포가 지연되면 d1로 롤백해 PC 작업을 복구하는 것이 안전하다. 최종 판단은 CTO.
- **[P1] Qoder 수정 PR 배포 후 30분 관찰.** poll/claim/renew/result, create dispatch, 실제 PC 명령을 d1과 비교한다. 4차 창의 종료 시각을 기록한다.
- **[P1] Worker 전체 D1 직접 읽기 전수 점검.** com2 모드에서 D1 테이블을 직접 읽는 경로를 모두 찾아 큐 저장소로 바꾸거나 명시적으로 분기하고, com2 경로 전체 계약 테스트를 추가한다.
- **[P1] 롤백 절차 보강.** 코드 버전 + `PC_QUEUE_BACKEND`/`ORACLE_MESH_QUEUE_ORIGIN` + 실행 프로세스 환경 + 실제 요청을 한 세트로 확인하는 절차를 런북에 넣는다.
- **[P1] 실제 경로 CI 추가.** Workerd 큐 클라이언트, 복사된 DB에 대한 마이그레이션, dispatch create ownership을 운영 형태로 검증한다.
- **[P2] 실행기 loopback 전환 결정.** `COM2_EXECUTOR_QUEUE_SWITCH_20261030.md`는 실행 전 문서이며, `ORACLE_MESH_QUEUE_ORIGIN`의 호스트 적용 여부는 **미확인**이다. 큐 안정화 후 별도 창에서 결정한다.
- **[P2] 미확인 항목 정리.** 아래 §7의 14:11:50, 초기 상태 복사, 임시 JS Worker 시험과 34/34의 원본 로그(현재 출처는 CTO 세션 기록)를 확인한다.

## 7. 확인 한계

- **34/34 poll 실패 수치:** 출처는 CTO 세션 기록 — 2차 시도 09:04, poll **34/34 503**, 원인 `httpx_compat` `post`/`json` 부재(#6279). 1차 시도 수치는 #6270의 **92/92**(10초 창)로 별도 기록한다.
- **14:11:50 정확한 시각:** #6303은 "14:11부터"로만 기록한다. 14:11:50은 **미확인**.
- **"임시 JS Worker 시험":** 별도 실행 기록을 찾지 못했다. #6279에는 Qoder의 실제 Worker 경로 측정(`client.post`가 요청 전에 실패)만 있다. 임시 JS Worker 시험은 **미확인**.
- **첫 전환 전 초기 상태 복사 시각:** 확인되지 않았다. #6281에 기록된 재복사 generation은 `20261029T233938663045Z`(2026-10-30 08:39:38 KST)이다. 초기 복사 시각은 **미확인**.
- **1차 `265000e3`의 실제 서빙 구간:** 배포 로그의 `DEPLOYED_VERSION_ID`는 `265000e3`이지만, 08:14 런의 사전 읽기에서는 활성 버전이 `a7aed03d`였다. 정확한 서빙 구간은 Cloudflare 배포 감사 로그 없이는 **미확인**이며, 다운타임은 "전환 배포–08:17:44 복귀" 창으로 계산했다.
- **실제 사용자 요청 수/영향 계정:** **미확인**. 이 문서는 기능적 다운타임 창만 계산한다.
- **#6303 큐 호스트 적용 여부:** **확인됨**. Qoder 보고 — 호스트 src → `e6692fcc137b`, install exit 0, 재시작 1회, 문 경유 create 시험 200 `ok=True`(시험 행 즉시 삭제).

---

이 문서는 PR로만 제출한다. 병합·배포·롤백 결정은 CTO가 한다.
