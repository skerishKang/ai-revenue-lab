# COM2 CPython 호스트: P01 엔진 연결 (2026-10-31)

상태: 구현 완료(기본 꺼짐). 컴2 서비스 기동·설정 적용·운영 호출은 하지 않았다.
범위: Cloudflare Worker 쪽 P01 호출 방식은 변경 없음. CPython 호스트에만 전송을 추가했다.

## 1. 비어 있던 지점

| 호스트 | Engine 클라이언트 구성 | 결과 |
| --- | --- | --- |
| Cloudflare Chat Worker | `claw_p01_composition` → `p01_engine_config_from_worker_bindings` → `CloudflareEngineServiceTransport(P01_ENGINE_SERVICE)` | 정상 |
| COM2 CPython 호스트 | 같은 함수가 Worker 바인딩을 읽음 → 바인딩 없음 → `None` | `CHAT_LOCAL_CRON=NOT_CONFIGURED reason=p01_engine_transport_unbound` |

즉 빠진 것은 **엔진 클라이언트 자체가 아니라 전송**이다. Worker에서는 Service Binding이
`https://padiem-ai-engine.internal`을 받아 주지만, 네이티브 프로세스에는 그 바인딩이 없다.
`padiem_ai_engine_client`의 `EngineTransport` 프로토콜(`async request(method, url, headers, body)`)이
그 교체 지점이고, 이번 작업은 그 구현 하나를 추가했다.

## 2. 재사용한 것 (새 판정 로직 없음)

| 요소 | 출처 |
| --- | --- |
| `PadiemAiEngineClient`, `EngineTransport`, `EngineTransportResponse`, 엔진 경로 상수 | `apps/padiem-ai-engine/clients/python/padiem_ai_engine_client` |
| 두 P01 레인 구성 | `claw_p01_composition.compose_p01_lanes` — 이번에 인자만 받는 함수로 분리해 Worker·호스트가 같은 배선을 씀 |
| 호출자 ID·자격 증명 형식 검증 | `worker_config.validate_p01_caller_and_credential` — 이번에 한 곳으로 모아 Worker 바인딩 경로와 호스트 경로가 같은 규칙을 씀 |
| 경로 허용 목록·요청/응답 바이트 한도 | `worker_orchestration`의 값과 동일. `test_local_p01_engine_transport_261031.py`의 parity 테스트가 두 값을 묶어 두어, 한쪽만 넓히면 테스트가 실패한다 |
| 크론 진입 게이트 | #6356의 `PADIEM_CHAT_CPYTHON_HOST=1` (변경 없음) |

## 3. 설정 (기본 꺼짐)

세 값이 모두 있어야 켜진다. 값은 설치 시 호스트 env 파일에만 넣고 저장소·로그·보고서에 쓰지 않는다.

| 변수 | 의미 | 제약 |
| --- | --- | --- |
| `PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN` | 같은 호스트의 엔진 주소 | `http://` + 루프백(`127.0.0.1`, `localhost`, `::1`) + 포트. 경로·쿼리·자격 증명 포함 금지 |
| `PADIEM_CHAT_LOCAL_P01_CALLER_ID` | 엔진이 보는 호출자 ID | Worker와 같은 형식 검증(최대 길이·안전 문자) |
| `PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL` | 엔진 호출 자격 증명 | 32–512바이트 |

없으면 지금까지와 같이 `NOT_CONFIGURED reason=p01_engine_transport_unbound`다.
형식이 틀리면 `p01_engine_origin_invalid` / `caller_id_shape_invalid` /
`credential_length_invalid` / `client_constructor_error` / `composition_unavailable` 중
하나만 출력한다. 주소·값·길이·예외 원문은 출력하지 않는다.

## 4. 전송 규칙

- 주소 재작성은 origin 하나뿐이다. 클라이언트가 만든 `https://padiem-ai-engine.internal<path>`의
  origin만 설정된 루프백으로 바꾸고, 경로·메서드·본문·헤더는 그대로 전달한다.
- 허용 경로는 Worker와 같은 7개(health, research, orchestrate, resume, cancel,
  multimodal attachments, document admission)이고, `GET`은 health만, 나머지는 `POST`만.
- 본문 한도: 일반 256KiB / 모델 경로 6MB / 첨부 6MB 기반 base64 한도. 응답은 10MB에서 읽는 중 중단.
- 리다이렉트를 따르지 않는다. 302는 상태 코드로 호출자에게 돌려준다.
- 타임아웃 30초, 재시도 없음, NDJSON 스트리밍 없음(요청 시 명시적 거부).
  스트리밍은 이 호스트 레인의 범위가 아니며, 버퍼링으로 대신하지 않는다.
- 연결·타임아웃 오류는 URL·예외 형식을 노출하지 않는 한 개의 오류로 바뀐다.

## 5. 크론 게이트 순서 (변경 후)

1. `PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED` — 꺼져 있으면 `SKIPPED`
2. 진입 모드 — `PADIEM_CHAT_CPYTHON_HOST=1` 또는 `PADIEM_LOCAL_DEV=1`, 둘 다면 거부
3. `Settings.from_env()` 설정 검증
4. `PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN`/`_SECRET` — 없으면 `NOT_CONFIGURED reason=identity_rpc_unbound`
5. P01 엔진 전송 — 없으면 `NOT_CONFIGURED reason=p01_engine_transport_unbound`,
   있으면 `CHAT_LOCAL_CRON=P01_ENGINE_CONNECTED transport=loopback_http`

5번은 **틱을 실행했다는 뜻이 아니다.** 실행에 필요한 나머지 포트(D1 기반 자동화 스토어,
소유자 해석, 이력, Task-Alert, 푸시)는 아직 Worker 바인딩에만 있다. 이 게이트를 "실행 완료"로
올리지 않으려고 `P01_ENGINE_CONNECTED`라는 별도 표기를 쓴다.

## 6. 남은 게이트 (다음 레인 후보)

1. 호스트용 자동화 스토어: `run_scheduled_automation_source(..., automation_store=, identity_authority=, discovery=, execution_ports=)`의 주입 seam(#6213)을 쓰되, D1 대신 COM2 SQLite 스토어가 필요하다. 이번 PR은 여기에 손대지 않았다.
2. `execution_ports`(adapter/owner_resolver/history_store/task_alert_store/push) 조립 — 1이 끝난 뒤.
3. 스테이징 8801에서 tick 1회 실행 관측(중복 실행 방지는 #6378의 타이머 락·전환 순서 사용).

## 7. P01 정본 추천 (결정 아님)

현재 COM2에는 Windows 릴리스 `D:\PADIEM-Servers\b62-chat-api` 계열 P01(18731)이 떠 있다.
B14는 CTO 결정으로 Linux 8789(`b14.padiem.net`)를 정본으로 삼았다. 같은 기준을 P01에 적용할 수 있는지 검토한 결과:

- **추천: P01도 Linux(WSL) 쪽 systemd 서비스 + 루프백 포트를 정본으로.** 근거는 B14 결정과 같다. ① COM2 운영 서비스는 이미 WSL/systemd에 있고 서버 이전 작업의 대상도 Linux 쪽이다. ② Windows 릴리스 프로세스는 로그온 세션·드라이브 마운트에 묶여 재부팅·세션 종료에 취약하다. ③ 이번 전송은 루프백 http만 허용하므로, 어느 쪽이든 "같은 호스트 다른 프로세스"여야 한다는 조건은 동일하다.
- **Windows 18731의 위치**: 전환 전까지 스테이징 검증용 임시 upstream으로만 쓸 수 있다. 이번 전송은 `127.0.0.1`만 받으므로 Windows 서비스에 붙이려면 WSL에서 Windows loopback으로 가는 주소(예: WSL2의 host 주소)가 필요하고, 그것은 지금 허용 목록 밖이다. 즉 Windows 18731을 붙이려면 정책 변경(호스트 주소 허용)이 먼저다.
- **포트 제안**: 8811(현재 사용 8788 파일 레인, 8789 B14 Linux, 8790 lovetree-api, 8797 큐, 8798 Chat, 8801 스테이징 Chat, 8830 스테이징 큐와 겹치지 않음). 최종 값은 CTO 결정.

## 8. 테스트

```bash
cd apps/padiem-chat
python -m pytest tests/test_local_p01_engine_transport_261031.py tests/test_local_cron.py
```

- parity: 경로 목록·모델 경로·4개 바이트 한도가 Worker 전송과 같은지
- 실제 소켓: 로컬 HTTP 서버(127.0.0.1:0)에 실제 `PadiemAiEngineClient.health()` 왕복
- 거부: 비루프백·https·경로/쿼리 포함·포트 없음·잘못된 포트, 허용 외 경로, 메서드 위반, 본문 초과, 응답 초과, 리다이렉트, 스트리밍
- 설정: 꺼짐/형식 오류 3종/정상 정규화
- 크론: 미설정 시 기존 `NOT_CONFIGURED` 유지, 설정 시 `P01_ENGINE_CONNECTED`, 주소 미출력, 조립 실패 시 `composition_unavailable`

## 9. 현재 확인 상태

- 컴2 서비스 기동·설치 없음, 실제 P01(18731/8811) 호출 없음, Cloudflare Worker 변경 없음
- 실제 80표 규모·운영 규모 tick 실행 없음
- `deploy/host-com2/cron/cron.env.example`(#6378, 별도 브랜치)에는 이 세 변수가 아직 없다. #6378 머지 후 이름 3줄 추가가 필요하다(이번 PR은 단일 목적 유지).
