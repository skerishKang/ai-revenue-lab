# Chat D1 전환 쓰기 정지 스위치와 리허설 절차 (2026-10-31)

계획(#6354)의 ③ D1 전환은 "쓰기 정지 창 → 늦은 쓰기 확인 → D1 내보내기 → COM2 반영 → 패리티 MATCH → 실패 시 핸드백" 순서입니다. 이 문서는 그 창을 여닫는 스위치와, 한 바퀴 도는 절차를 고정합니다.

## 1. 재사용 — 새 스위치를 만들지 않았다

`apps/padiem-chat/app/maintenance_mode.py`(#5573 stage 3)가 이미 "쓰기 503 · 읽기 통과 · 파일 센티널(재시작 불필요) · 기본 꺼짐"을 구현하고 있었습니다. 이번에 필요한 것은 세 가지뿐이었습니다.

1. 환경 스위치 — Cloudflare 진입은 파일시스템이 없다.
2. 늦은 쓰기 경로 목록 — 쓰기를 하는 GET을 코드 변경 없이 동결.
3. 두 진입점 공통 적용 — `local_cpython.build_app`(COM2 호스트)과 `worker.py`(Cloudflare)가 같은 헬퍼를 쓴다.

동결 응답은 기존 그대로입니다: `503` · `{"error":{"code":"maintenance","message":"잠시 점검 중입니다. 곧 다시 이용할 수 있습니다."}}` · `cache-control: no-store` · `retry-after: 120`.

## 2. 스위치

| 환경 변수 | 의미 | 기본 |
| --- | --- | --- |
| `PADIEM_CHAT_WRITE_FREEZE` | `0/false/no/off`만 명시적 꺼짐. 그 외 값은 켜짐(오타는 안전한 쪽으로 실패) | 미설정 = 꺼짐 |
| `PADIEM_CHAT_MAINTENANCE_SENTINEL` | 센티널 파일 경로. 파일이 있으면 켜짐, 없으면 꺼짐. 읽을 수 없으면 켜짐 | 미설정 = 꺼짐 |
| `PADIEM_CHAT_WRITE_FREEZE_PATHS` | 동결할 읽기 경로 목록(쉼표·공백 구분, `*` 접미사는 접두사 매칭) | 비어 있음 |

동작:
- 쓰기 메서드(`POST/PUT/PATCH/DELETE`) → 503.
- 읽기(`GET/HEAD`) → 통과. 단 `PADIEM_CHAT_WRITE_FREEZE_PATHS`에 든 경로는 503.
- `*` 단독은 무시합니다. 사이트 전체 읽기가 멈추는 설정은 실수로도 들어가지 않게 했습니다.
- 한 요청도 두 겹으로 막히지 않도록 `create_app` 반환 뒤 각 진입점에서 한 번만 감쌉니다. `app.state` 부착은 감싸기 전 Starlette 앱에서 끝냅니다.

## 3. 재배포 필요 여부

| 진입 | 창 여닫기 | 재배포 |
| --- | --- | --- |
| COM2 호스트(`local_cpython`) | 센티널 파일 생성·삭제 | 불필요(재시작도 불필요) |
| Cloudflare(`worker.py`) | `PADIEM_CHAT_WRITE_FREEZE` 값 변경 | 필요 — `wrangler deploy` 1회(1~2분) |

Cloudflare Workers에는 파일시스템이 없어 환경변수만 쓸 수 있습니다. D1에 플래그 행을 두면 배포 없이 열 수 있지만, 전환 창 하나를 위해 새 저장소 권위를 만드는 비용이 더 큽니다. ③의 정지 창은 계획된 짧은 구간이므로 배포 1회를 허용하고, 이 선택을 여기 기록합니다.

## 4. 늦은 쓰기 경로

아스트라5의 분류표(`CHAT_LATE_WRITE_INVENTORY_20261031.md`, #6367)에서 **쓰기 효과가 확인된 GET 4개**를 `PADIEM_CHAT_WRITE_FREEZE_PATHS` 예시 값으로 고정합니다. 운영 설정은 바꾸지 않습니다 — ③ 실행 때 CTO가 채웁니다.

```text
PADIEM_CHAT_WRITE_FREEZE_PATHS=/auth/google/callback,/auth/lovetree/start,/api/connectors/github/start,/api/connectors/github/callback
```

| 경로 | 확인된 쓰기 대상 |
| --- | --- |
| `/auth/google/callback` | `users`, `control_plane_identity_shadow`, `padiem_android_auth_handoffs`, `lovetree_login_handoffs`, `b66_signup_alert_delivery`, `b66_signup_alert_outbox` |
| `/auth/lovetree/start` | `lovetree_login_handoffs` |
| `/api/connectors/github/start` | `claw_github_oauth_states` |
| `/api/connectors/github/callback` | `claw_github_oauth_states`, `claw_github_connections` |

4개를 그대로 적고 접두사(`*`)로 묶지 않습니다. `/auth/*` 같은 접두사는 로그인 읽기 경로까지 함께 503으로 만들어, 창 안의 로그인 실패가 동결 때문인지 아닌지 구분할 수 없게 합니다.

## 4b. 경로로 막을 수 없는 것 — 창 전에 멈춘다

동결 스위치는 HTTP 요청만 막습니다. 아래 넷은 정지 창을 열기 전에 따로 멈추고, 진행 중인 작업이 끝났다는 증거를 남깁니다.

| 대상 | 확인된 쓰기 | 창 전에 할 일 |
| --- | --- | --- |
| 예약 실행(automation) | `claw_occurrences`, `claw_runs`, `claw_proposals`, `claw_task_alert`, `claw_run_history`, `claw_push_subscription` 삭제 | 새 tick 중단 → 진행 중 실행·history·push 투영 완료 대기 |
| WSS `/api/claw/connector/gateway/session` | Broker 권위 `canonical_local_agent_gateway_bootstrap` (Chat D1 표 아님) | 이미 열린 소켓은 동결을 통과하므로 연결 종료·드레인 확인 |
| queue 소비·외부 producer | 권위·대상 미확인 | 운영 큐 소비 중지, 스테이징 큐(8830)와 분리된 상태 확인 |
| 텔레메트리 `waitUntil` | 외부 전송, Chat D1 쓰기 미확인 | 차단 목록에 넣지 않고 2번 관찰 창에서 확인 |

## 5. 리허설 절차

합성 또는 스테이징에서 아래 순서로 한 바퀴 돕니다. ③ 실행 시에는 같은 순서를 운영에서 씁니다.

| 단계 | 하는 일 | 소요 목표 | 판정 기준 | 실패 시 |
| --- | --- | --- | --- | --- |
| 0 사전 | 최신 main SHA 고정, 스위치 준비, 기준선 스냅숏 보관 | 5분 | `git rev-parse HEAD` = 기록한 SHA | 중단 |
| 1 쓰기 정지 | 센티널 생성(호스트) 또는 스위치 설정 후 배포 | 2분 | 쓰기 503·`code=maintenance`, `/health`·`/api/auth/status` 200 | 스위치 롤백 |
| 1b 창 전 중지 | 예약 실행 tick 중단, WSS 드레인, queue 소비 중지(§4b) | 3분 | 새 tick 0, 열린 WSS 0, 운영 큐 소비 중지 확인 | 창을 열지 않고 원인 해결 |
| 2 늦은 쓰기 확인 | 4개 동결 경로 GET 503 확인 + D1 스냅숏 2회 비교(관찰 창 10분) + §4b 관찰 목록 확인 | 12분 | 두 스냅숏의 행 수·정렬 해시·`updated_at` 최대값 차이 0, 동결 경로 4개 모두 503 | 창 유지, 원인 경로를 목록에 추가 |
| 3 D1 내보내기 | `wrangler d1 export --remote` | 5분 | 파일 크기 > 0, 표 수가 기준선과 동일 | 재시도 |
| 4 COM2 반영 | 동기화 러너로 내보내기 반영 | 5분 | 반영 스크립트 종료 코드 0 | 핸드백 |
| 4b 객체 참조 | `chat_object_reference_check`로 참조 키 ↔ 미러 목록 대조 | 3분 | `CHAT_OBJECT_REFERENCE=MATCH` (종료 코드 0) | 누락 키를 R2로 올린 뒤 재실행, 해결되지 않으면 6번 대신 CTO 보고 |
| 5 패리티 | `chat_copy_parity` | 2분 | `CHAT_COPY_PARITY=MATCH` (종료 코드 0) | 6번 |
| 6 되돌림 | `chat_d1_handback_gate` plan → apply | 10분 | 적용 후 5번이 `MATCH` | 창 유지, CTO 보고 |

총 목표 48분 이내(1b 3분 추가). 6번은 데이터를 되돌리는 경로이고, 스위치를 끄는 것은 별개입니다. 4b는 6번 뒤에도 한 번 더 돌립니다.

관찰 목록(분류표의 미확인 항목을 2번 창에서 확인): 전체 SQL 저장소의 HTTP·비동기 진입점 역추적, 일부 GET의 부수 호출, WSS Broker의 추가 저장 대상, 스트리밍 완료·취소 후 저장, queue 소비·외부 producer. 창 안에서 새 쓰기 경로가 확인되면 목록에 추가하고 창을 유지합니다.

### 5.1 실행 스크립트

위 순서를 손으로 반복하면 단계를 건너뛰거나 판정을 놓칠 수 있으므로, 같은 순서를 **기존 도구만 호출해** 묶은 스크립트가 있습니다: `.github/scripts/chat_cutover_rehearsal.py`.

```bash
python .github/scripts/chat_cutover_rehearsal.py \
  --base-url https://chat-com2-staging.padiem.net \
  --generation-pointer D:/.../snapshots/current_generation.json \
  --generations-dir D:/.../snapshots/generations \
  --snapshot-a /mnt/d/padiem/chat-staging/baseline.sqlite3 \
  --snapshot-b /mnt/d/padiem/chat-staging/window-end.sqlite3 \
  --staging-db /mnt/d/padiem/chat-staging/chat.sqlite3 \
  --sentinel /mnt/d/padiem/chat-staging/MAINTENANCE \
  --mirror-inventory /mnt/d/padiem/chat-staging/r2-inventory.json \
  --confirm-stop-tick --confirm-stop-wss --confirm-stop-queue
```

- 단계 순서: 사전(preflight) → 1b 창 전 중지 확인 → 1 쓰기 정지 → 동결 경로 503 확인 → 2 스냅숏 2회 비교 → 3·4 스테이징 DB 생성 → 5 패리티 → 4b 객체 참조.
- 판정은 각 도구의 종료 코드와 그 도구가 출력한 판정 줄입니다(`CHAT_COPY_PARITY=MATCH`, `STAGING_DB_FROM_GENERATION=READY`, `CHAT_OBJECT_REFERENCE=MATCH`). 스크립트가 판정을 새로 만들지 않습니다.
- 실패하면 그 자리에서 멈추고 되돌림 안내를 출력한 뒤, 읽기 전용인 `chat_d1_handback_gate plan` → `verify`만 실행합니다. `apply`는 CTO 승인 뒤 별도 실행입니다. 창은 스크립트가 닫지 않습니다.
- 운영 주소(`chat.padiem.net`), 운영 DB 경로(`/mnt/d/padiem/chat-com2`), `b62-chat-api`, 큐 `8797`이 인자에 있으면 아무것도 실행하지 않고 거부합니다. 운영 전환은 별도 지시로 이 제한을 풉니다.
- `--dry-run`은 실행 없이 단계·명령만 출력합니다. `--synthetic`은 배치 규칙만 완화하고 운영 거부는 그대로 둡니다(합성 검증용).
- 1b 중지는 스크립트가 관측할 수 없습니다. `--confirm-stop-tick`·`--confirm-stop-wss`·`--confirm-stop-queue`로 운영자 확인을 받고, 없으면 동결을 켜기 전에 멈춥니다.

## 6. 합성 리허설 실행 결과

합성 SQLite 두 개(2표 5행)로 **실제 도구**를 그대로 돌린 출력입니다. 기준선을 복사한 뒤 COM2 쪽에 insert 1·update 1·delete 1을 만들고, 패리티 → 핸드백 plan → apply → 다시 패리티 순서로 진행했습니다.

```
STEP0 baseline copied, then 1 insert / 1 update / 1 delete on the COM2 side
STEP parity-before exit=1
    CHAT_COPY_PARITY=DRIFT tables=2 rows=4 mismatch_rows=3 mismatch_tables=2
    CHAT_COPY_PARITY_SUMMARY=2표 4행 불일치 5
    CHAT_COPY_TABLE_DRIFT conversations d1_rows=1 com2_rows=0 missing_on_com2=1 missing_on_d1=0 changed=0
    CHAT_COPY_TABLE_DRIFT users d1_rows=3 com2_rows=4 missing_on_com2=0 missing_on_d1=1 changed=1
STEP plan exit=0
    CHAT_HANDBACK_PLAN=OK tables=2 statements=3 digest=84275eced9c338173154fbddc0c6326b271dd07e96ed1945ee28a874ec82b1de
STEP apply exit=0
    CHAT_HANDBACK_APPLY=READY statements=3 digest=84275eced9c338173154fbddc0c6326b271dd07e96ed1945ee28a874ec82b1de
STEP handback showed 3 statements inside one transaction
STEP parity-after exit=0
    CHAT_COPY_PARITY=MATCH tables=2 rows=4 mismatch_rows=0 mismatch_tables=0
    CHAT_COPY_PARITY_SUMMARY=2표 4행 불일치 0
```

읽는 법:
- 패리티가 먼저 불일치를 정확히 셉니다(추가 1·변경 1·삭제 1).
- 핸드백 plan의 문장 수(3)와 apply의 문장 수(3), 다이제스트가 같습니다 — 승인한 계획과 적용한 계획이 동일합니다.
- 적용 뒤 패리티가 0으로 닫힙니다. 되돌림 경로가 실제로 닫힌다는 증거입니다.

도구는 이 PR 워크트리에 아직 없는 #6360 브랜치 사본(`chat_copy_parity.py`, `chat_d1_handback_gate.py`)을 썼습니다. #6360이 main에 들어오면 경로만 `.github/scripts/`로 같습니다.

## 7. 테스트

`tests/test_chat_write_freeze.py` + `tests/test_maintenance_mode.py` → **19 passed**

- 설정 없음 = 기존 동작(앱을 감싸지 않음), 쓰기 200.
- `0/false/no/off/빈 값` = 꺼짐, 오타(`ture`) = 켜짐.
- 스위치 켜짐: POST·PUT·PATCH·DELETE 503, `/health`·`/api/files/capabilities` 200.
- 동결 경로 목록: 지정한 GET 503, 미지정 GET 200, 접두사 매칭, `*` 단독 무시, 정규화·중복 제거.
- 센티널 파일: 생성 시 503, 삭제 시 200(재시작 없이 여닫힘). 읽을 수 없는 센티널은 동결로 계산.
- 호스트 조립(`build_app`)에서 스위치만으로 503이 되고 `/health` 200 — Cloudflare 진입과 같은 헬퍼 경로 확인.

## 8. 이 PR이 하지 않은 것

- 운영 스위치를 켜지 않았고, 운영 D1·COM2 운영 DB에 접근하지 않았습니다.
- 실제 80표 3,308행 규모의 리허설은 하지 않았습니다(합성 2표). ③ 실행 시 같은 절차로 운영 규모를 한 번 돕니다.
- 동결 경로에는 확인된 GET 4개만 예시로 적었고 운영 설정에는 적용하지 않았습니다. 분류표의 미확인 항목은 §5의 관찰 목록으로 옮겼습니다.
- 객체 단계는 합성 DB와 합성 미러 목록으로만 검증했습니다(실제 R2 목록 미조회). 계획은 `CHAT_OBJECT_ROLLBACK_PLAN_20261031.md`.
