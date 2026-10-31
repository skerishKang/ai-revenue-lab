# Chat COM2 이전: 늦은 쓰기 분류표 (진행 중)

기준 main `cf48966bd2948d8c0756a8ceccf544c92b84568a`. 이 표는 전체가 아니다. HTTP 저장소 호출과 cron·queue·WSS·응답 후 작업의 전체 추적 전까지 전환 허가 근거로 사용하지 않는다. 운영 데이터 조회 없음. 아래 `app/`은 `apps/padiem-chat/app/`이다.


## 확인 완료 경로

- GET 4개: Google callback, LoveTree start, GitHub start·callback의 확인된 저장소 쓰기.
- 예약 실행: automation 발생·실행·task/alert·history 투영, push 실패 시 구독 제거.
- 텔레메트리 `waitUntil`: Grafana HTTP 전송으로 연결되며 해당 호출에서 D1 쓰기는 확인되지 않음.
- WSS는 Chat D1이 아닌 Broker 권위 RPC 경로임을 확인.

## 미확인 항목

- 전체 SQL 저장소의 HTTP 및 비동기 진입점 역추적, 일부 GET 부수 호출.
- WSS의 Broker DO 페어링·자격증명 추가 저장 대상과 전체 RPC 쓰기, queue 소비·외부 producer 및 정지 증거.
- 스트리밍 완료·취소 후 호출의 모든 저장 대상과 대기 중 요청 드레인 보장.
- 정지 창 도중의 일시 쓰기 감지: 두 스냅숏만으로 증명 불가능.

## 쓰기 효과가 확인된 GET (4개 진입점)

| 진입점 | 저장소 함수 | 대상 표 | 실행 | 근거 |
|---|---|---|---|---|
| GET `/auth/google/callback` | `upsert_google_user`, `save_projection`, `bind_user`, `bind_verified_identity`, 가입 알림 기록 | `users`, `control_plane_identity_shadow`, `padiem_android_auth_handoffs`, `lovetree_login_handoffs`, `b66_signup_alert_delivery`, `b66_signup_alert_outbox` | 응답 전 await, 조건부 | `app_factory.py:569`, `auth_routes.py:526`, `:532`, `:562`, `:567`, `:575`; `history.py:1082`-1094; `control_plane_identity_shadow.py:113`-122; `android_auth_routes.py:506`-511, `android_auth_store.py:161`-163; `lovetree_auth_routes.py:211`-224, `lovetree_auth_store.py:270`; `b66_signup_notifications.py:102`-114, `:126`-132, `b66_member_admin.py:456`, `:467` |
| GET `/auth/lovetree/start` | `D1LoveTreeLoginHandoffStore.create` | `lovetree_login_handoffs` | 응답 전 await | `app_factory.py:578`, `lovetree_auth_routes.py:141`, `lovetree_auth_store.py:215`, `:231` |
| GET `/api/connectors/github/start` | `D1GitHubOAuthStore.begin` | `claw_github_oauth_states` | 응답 전 await | `app_factory.py:603`, `github_oauth_routes.py:60`, `github_oauth_store.py:39`, `:44` |
| GET `/api/connectors/github/callback` | `D1GitHubOAuthStore.consume`, `save` | `claw_github_oauth_states`, `claw_github_connections` | 응답 전 await, 단계별 조건부 | `app_factory.py:604`, `github_oauth_routes.py:96`-102, `github_oauth_store.py:48`-51, `:70`-73 |

Google callback의 Control Plane 및 B54 세션은 외부 identity authority 호출이며 Chat D1 표와 별도 권위다 (`auth_routes.py:391`, `:558`, `b54_canonical_session.py:162`-185). GitHub 자격증명 갱신 호출자(`github_oauth_routes.py:125`-130)의 GET 연관 여부는 추가 확인 필요.

## 응답 이후 / 백그라운드: 조사 중

| 진입점 | 저장소 함수·대상 | 실행 | 근거 및 상태 |
|---|---|---|---|
| 요청 텔레메트리 | Grafana OTLP HTTP 전송; 해당 호출에서 Chat D1 표 없음 | `waitUntil` | `request_telemetry.py:420`-434, `worker.py:1260`-1264, `:1304`, `:1844`-1864, `grafana_otlp_exporter.py:83`-89. 다른 응답 후 쓰기의 부재를 뜻하지 않음 |
| Worker scheduled / 로컬 cron | automation store: `claw_occurrences`, `claw_runs`, `claw_proposals`; 출력 투영 `claw_task_alert`. history `claw_run_history` 및 push 실패 시 `claw_push_subscription` 삭제(아래 별도 행 참조) | 백그라운드 await | `worker.py:228`, `:256`, `:287`, `:331`, `:1048`-1050; `claw_automation_store.py:226`-258; `claw_automation_scheduled_execution.py:83`, `:113`-120; `claw_automation_projection_bridge.py:285`, `:328`; `claw_task_alert_store.py:43`, `:180`, `:240` |
| WSS `/api/claw/connector/gateway/session` | Broker RPC `begin`·`finish`·`authorize`, 별도 Broker DO 권위; 해당 코드에서 Chat D1 표 미확인 | 장시간 연결 | `canonical_connector_gateway_source_composition.py:71`-80, `connector_gateway_websocket_session.py:100`-104, `:257`, `:285`, `:301` |
| queue / 외부 producer | 진입점·대상·정지 절차 미확인 | 비동기 | 별도 queue 권위와 Chat D1 범위를 구분해 추적 필요 |
| Claw streaming 작업 | `produce` → 실행 및 quota 환불; 구체적인 저장소·표 추적 필요 | `asyncio.create_task` | `claw_live_events.py:141`-147, `:182`, `dispatch_quota.py:49`-67 |

## 쓰기 정지 창에서 막거나 드레인할 경로 (확인된 일부)

- GET `/auth/google/callback`, `/auth/lovetree/start`, `/api/connectors/github/start`, `/api/connectors/github/callback`. callback의 외부 authority와 알림 전달도 별도 권위에서 처리한다.
- 예약 실행의 신규 tick을 중단하고 진행 중인 automation 실행·history/push 투영까지 드레인한다.
- `/api/claw/connector/gateway/session` WSS의 Broker 권위에 대한 별도 중단·드레인 판단이 필요하다.
- `waitUntil` 텔레메트리는 확인된 경로상 외부 전송이다. 스트리밍 작업·환불, 큐·외부 producer는 추가 식별이 필요하므로 이 목록은 불완전하다.

## 수정 제안

- 쓰기 효과가 있는 GET도 쓰기 정지 분류에 포함하고 전환 창에 fail-closed 처리한다. 인증 흐름 변경은 별도 설계·검증한다.
- cron, 장시간 WSS, 큐와 비동기 작업을 각 권위별로 중지하고 진행 중 작업 완료를 독립 증거로 확인한다.

## 한계와 미완료

스냅숏 비교는 정지 창 안에서 생겼다가 되돌려진 쓰기를 잡지 못한다. 따라서 분류표로 위험 경로를 미리 막는 것이 본 대책이다. `.github/scripts/chat_d1_digest.py:snapshot`은 표별 기본키·행 다이제스트를 제공하나 queue·broker·시스템 표를 제외하므로 그 비교 결과는 제외 범위의 무쓰기를 증명하지 않는다. 두 시점 비교도 독립적인 드레인 증거를 대체하지 못한다.

전체 저장소 SQL의 진입점 역추적, 예약 실행 history·push, WSS의 Broker 대상, 큐와 스트리밍 작업의 상세 대상은 미완료다. 숫자는 확인된 진입점 수이며 전체 개수가 아니다.


## 예약 실행 history·push 추가 추적

| 진입점 | 저장소 함수 | 대상 | 실행 | 근거 |
|---|---|---|---|---|
| scheduled automation terminal | `project_terminal_scheduled_run_to_history` → `record_claw_run` | `claw_run_history` | cron 진행 중 await, 조건부 | `app/claw_automation_background_execution.py:557`-562, `app/claw_automation_history_bridge.py:196`-202, `app/history.py:1756`, `:1819`, `:1830` |
| scheduled automation terminal push | `notify_terminal_run` → `deliver_inbox_push` → `unregister` | `claw_push_subscription` 삭제(404/410 시) | cron 진행 중 외부 push 응답 후 await | `app/claw_automation_background_execution.py:569`-579, `app/claw_automation_push_notification.py:122`, `app/claw_push_subscriptions.py:339`-391, `:273`-288 |

WSS의 Broker는 기존 Durable Object 권위이며 COM2 새 skeleton은 동일 pairing/runtime을 SQLite storage에 감싼다(`apps/padiem-broker/service.py:1`-6, `:27`-30, `:131`-142). 이것은 WSS RPC별 저장 키의 완전한 목록은 아니다. 스트림은 완료 callback을 await하고 종료 시 producer를 취소·await한다(`app/claw_live_events.py:263`, `:277`-286). callback의 모든 대상과 취소 경합은 추가 확인이 필요하다.


## WSS Broker gateway 저장 대상 추가 추적

| 진입점 | 저장소 함수 | 대상 | 실행 | 근거 |
|---|---|---|---|---|
| WSS `/api/claw/connector/gateway/session` → Broker gateway `begin` | `DurableBrokerGatewayBootstrap.begin` | `canonical_local_agent_gateway_bootstrap` 만료 행 삭제·행 생성 | WSS 프레임 처리 중 RPC, 조건부 | `apps/padiem-chat/app/connector_gateway_websocket_session.py:257`; `packages/padiem-control-plane/canonical_broker_pairing_rpc.py:238`-243; `canonical_broker_gateway_bootstrap.py:165`, `:184`, `:194` |
| 같은 WSS → Broker gateway `finish` | `DurableBrokerGatewayBootstrap.finish` | `canonical_local_agent_gateway_bootstrap` 상태 업데이트 | WSS 프레임 처리 중 RPC | `connector_gateway_websocket_session.py:285`; `canonical_broker_pairing_rpc.py:244`-249; `canonical_broker_gateway_bootstrap.py:214`, `:240`, `:246` |
| 같은 WSS → Broker gateway `authorize` | `DurableBrokerGatewayBootstrap.authorize_action` | `canonical_local_agent_gateway_bootstrap` 상태 업데이트 | WSS 프레임 처리 중 RPC | `connector_gateway_websocket_session.py:301`; `canonical_broker_pairing_rpc.py:250` 이하; `canonical_broker_gateway_bootstrap.py:264`, `:316`, `:322` |

위 표는 Broker 저장 표이며 Chat D1 다이제스트 범위가 아니다. WSS에서 이어지는 pairing redeem 및 identity authority의 모든 저장 대상까지 완료한 것은 아니다. 장시간 연결을 막는 것과 기존 연결이 종료될 때까지 드레인하는 것은 별개다.
