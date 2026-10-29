# Chat COM2 전환: PC 연결·러브트리 결합 설계

STATUS=설계 초안 / 구현·실제 전환 없음 / 기준 main e858ce55ad098c9763ab49e2d5553ff2054ceee8.
관련: [큐 런북](COM2_PC_DISPATCH_QUEUE_CUTOVER_20261029.md),
[서비스 바인딩](../architecture/COM2_CHAT_SERVICE_BINDINGS_20261029.md),
[RPC 입구](../architecture/COM2_CONTROL_PLANE_RPC_INGRESS_20261029.md),
[앞단](CHAT_COM2_FRONT_RUNBOOK.md). 큐 및 PC 명령 수송은 별도 레인.

## 진입점·상태 지도

메서드·경로는 소스의 등록과 상수 기준이며 설정 조건에 따라 미등록일 수 있다. 실제 운영 활성은 미검증이다.

| 경로 | 기능 및 읽기/쓰기 권위 |
|---|---|
| GET 업그레이드 /api/claw/connector/gateway/session | Worker fetch에서 ASGI보다 먼저 처리. identity 권위와 broker 서비스 바인딩을 필요로 하며 live 경로는 broker DO의 기기 세션·인증·명령 상태를 사용. 세션 개설/메시지 처리는 단순 읽기가 아니다. |
| POST /api/claw/connector/gateway/bootstrap/begin, finish | 기기 등록 시작·완료; 브로커/identity 등록·자격증명 상태. 실제 마운트와 플래그는 UNKNOWN. |
| GET setup, setup.js 및 POST /api/claw/connector/enrollments/{동의·발급·관리} | 소스 조건부 마운트. identity consent/enrollment과 broker challenge/발급 경계를 사용한다. 개별 실제 등록 경로·설정은 확인 필요. |
| POST /api/claw/connector/mesh-reads/request | 요청 인가 및 enqueue; dispatch는 기존 D1 또는 큐 backend, 대화·실행 상태는 Chat 저장소. |
| POST /api/claw/connector/mesh-reads/poll | executor의 claim/lease, oracle_mesh_dispatch 정본. 큐 전환 시 큐. |
| POST /api/claw/connector/mesh-reads/renew, cancel, busy, lane-status | lease 갱신 및 상태 확인. 큐 구현은 동일 경로를 제공하고 서명/소유권은 기존 계약 유지. |
| POST /api/claw/connector/mesh-reads/result | 실행 결과 접수·consume은 큐 정본, 결과 framing·대화 저장은 Chat 정본. 두 단계가 분리되어 재시도/중복 처리를 검증해야 한다. |
| GET /api/claw/connector/mesh-results/{dispatch_id} | 결과 원본 조회. 관련 Chat 메타데이터와 객체 저장소 사용 여부는 케이스별 추적. |
| /api/pc/pairings (GET/POST), /claim, /handoff, /install-file, /install-exe, /adopt, /{link_id} (DELETE), /label, /pause, /resume, /roots, /roots/{root_ref} | pairing·기기 링크·승인 루트 조회/변경. pc_pairing_codes·pc_device_links: 전환 전 D1, 큐 선택 후 큐. 설치 경로가 곧 기기 인증 완료를 뜻하지 않는다. |
| POST /api/pc/browse, find, fetch, save, move, delete, cancel, reference; GET /api/pc/result, file | 고객 PC 작업 진입·결과/파일. dispatch 및 기기 링크/소유권을 거쳐 Chat의 기록·객체 결과에 연결. 개별 실행기는 별도 변경 금지 레인. |
| GET /api/b66/connect/devices; POST /api/b66/connect/txt-reads/request; POST /api/claw/connector/text-reads/request | 기기 목록·읽기 요청. broker device directory/session과 Chat 기록/큐의 관계를 추적해야 한다. |
| POST /api/claw/connector/android-text-reads/request; GET /api/claw/connector/android-text-reads/folders; Android enrollment challenge | 조건부 마운트. identity·broker와 기기별 권한/요청 상태. 정확한 배포 경로와 설정은 UNKNOWN. |
| GET /auth/lovetree/start; GET /auth/google/callback | LoveTree 시작은 lovetree_login_handoffs 생성, Google 콜백은 users·identity shadow 및 handoff 변경. GET이지만 쓰기다. 동일 핸드오프는 시작·콜백·claim 전체에서 한 Chat DB 정본을 사용해야 한다. |
| POST /internal/claw/engine-desktop, engine-pc-drive, engine-pc-files; /internal/chat/engine-pc-drive, engine-pc-files | 조건부 내부 PC 디스패치. 인증·Chat 기록·큐 정본 연결, 각 호출자는 운영 전환 전에 경로 확인. |

이 표는 제품별 route family를 나열한다. 모든 동적 등록 및 broker 30여 RPC별 데이터 필드 지도는 아직 완성되지 않았으므로 전체 입증으로 판정하지 않는다.

## 목표 구조 판정

| 부분 | 현재 확인 | 필요한 변경·검증 |
|---|---|---|
| 컴2 큐 :8797 | 큐 서비스와 Worker proxy 코드 준비. Worker의 PC_QUEUE_BACKEND=com2에서 dispatch/pairing/presence가 큐로 간다. executor queue 경로 별도 준비. | CPython local_cpython은 같은 proxy 조립을 확인하지 못했다. 기존 QueueStoreClient는 HTTPS origin만 허용하므로 localhost :8797 직접 사용을 추정하지 않는다. 인증된 로컬 연결·두 호출자 동일 정본·원자 claim을 구현/시험해야 한다. 운영 flag 변경 없음. |
| 기존 Cloudflare broker | broker DO가 기기 자격증명·세션을 계속 보유하면 pepper는 그 권위에 남을 수 있다. | broker Worker는 기존 private service-binding fetch/RPC이며 2-B identity/google처럼 외부 HTTPS RPC 입구가 없다. 기존 DO 단일 정본으로 allowlist·proof·fail-closed 입구와 CPython 호출 결속을 설계·구현해야 한다. 세 비밀/값을 옮기지 않는다. 세 PC 재연결 불필요는 해당 경로 실증 전 목표다. |
| Worker 전용 WSS | 기존 JS 앞단은 모든 URL을 COM2에 보내고 오류 시 기존 폴백만 한다. 특정 WSS 경로 직접 분기 없음. | 기존 앞단에 정확한 경로·업그레이드만 기존 Worker의 Service Binding으로 전달하는 것은 설계 후보이며 코드·실제 101/양방향·인증·세션 검증이 필요하다. 사용자 지시의 JS 우회 금지 범위에 해당하는지 승인 없이 구현하지 않는다. 대안은 CPython WSS 이식과 동일 권위/권한 검증이다. 어느 쪽도 현재 완성되지 않았다. |
| PC 명령 shell 수송 결함 | 큐 자체의 데이터 적재와 원자 claim은 shell 실행과 별개다. | 실제 PC 명령 왕복 수용과 운영 큐 전환은 실행기 shell 결과를 포함하므로 결함이 남아 있는 동안 정상 전환 가능하다고 결론 내리지 않는다. 코드상 분리와 운영 가능 판정은 다르다. |

## Split-brain과 제거 조건

| 대상 | 갈라지는 지점 | 차단·확인 |
|---|---|---|
| dispatch/pairing/presence | Worker D1과 큐 SQLite가 동시에 쓰는 전환 창 | 두 producer 및 executor를 같은 큐로 바꾸고 이전 후 old 쓰기 거부·계수/해시·claim 단일성 검증. |
| Chat 대화·결과 | 결과 submit이 Worker D1에 남고 새 Chat은 COM2로 기록 | 결과 framing/재시도·중복·최종 응답을 COM2 Chat 정본으로 묶고 기존 Worker의 D1 쓰기를 막는다. 큐 consume과 Chat 저장의 장애 복구 검증이 필요. |
| broker 자격증명 | 새 broker·새 pepper와 기존 DO 동시 사용 | 이번 목표는 기존 broker DO만 권위. 인증 HTTPS 입구가 없으면 전환 금지. 신원/동의 및 회전 계약 보존. |
| WSS | 오래된 Worker의 세션·데이터 접근과 새 Chat 정본이 교차 | WSS가 사용하는 authority를 경로별 조사하고 D1 쓰기를 남기지 않음. 한 경로 proxy만으로 무조건 안전하다고 보지 않는다. |
| LoveTree handoff | 시작·Google callback·claim이 서로 다른 DB에 도착 | 3단계 한 정본, 전환 전 동결/기존 진행 세션 완료·재로그인 처리. 공통 identity 권위 유지. |
| 문서 객체 | COM2 LocalDiskR2와 Cloudflare R2가 서로 다른 객체 | 원본 파일 참조·복사/삭제·크기/해시 대조, 실패 시 데이터 복귀 및 쓰기 재개 금지. |

## 동결 종료 증명 — NOT READY

Worker의 isolate 로컬 카운터를 전역 종료 증거로 쓰지 않는다. 실행 승인 후 동결을 모든 HTTP 쓰기·쓰기를 수행하는 GET·WebSocket·cron·queue consumer·waitUntil 및 외부 producer에 적용한다. 이미 시작한 쓰기는 완료를 기다리는 방향이다. 동결 전 운영 로그로 최대 요청 시간을 측정하되, 관측 최대는 보장된 상한이 아니며 장기 요청/외부 작업의 종료 증거를 대체하지 못한다. 수집 부족·계속 실행 중인 작업·미포함 쓰기 경로가 있으면 UNKNOWN으로 멈춘다.

작업 종료가 확인된 뒤 일관된 D1 읽기 스냅숏을 두 번 취해 모든 표의 행 수와 정렬된 행 해시, 존재하는 표의 updated_at 최대값을 비교한다. updated_at이 없는 표는 해시·행 수로 본다. 동일 두 관측만으로 이후 지연 쓰기 부재가 증명되지는 않는다. 게이트·모든 producer 차단과 진행 작업 종료 증거를 함께 확인한 뒤 최종 export한다. 정확한 대기 간격/최대시간은 실측 전 UNKNOWN이다.

## 원복 설계와 제한

#6200은 SQLite 전용 시험이며 D1 게이트, 원격 원자성, 객체 복원을 제공하지 않는다. 기존 D1 gate와 같은 정확 SHA·확인 문자열·readonly 선행을 갖춘 새 handback plan/apply/verify 계약이 필요하다. 적용 직전 D1 기준 스냅숏과 각 표 해시를 대조하여 변화 시 쓰기 0. INSERT/UPDATE/DELETE 및 객체 원본·삭제를 계획하고 소유 표는 명시적으로 제외한다. D1 단일 원자 적용과 객체 저장소까지 하나의 트랜잭션이라고 가정하지 않는다. 실패 시 동결을 유지하고 복구·검증한다. 실제 D1 batch 크기·원자성은 현 환경 실측 없음; 승인 없는 D1 gate 실행 금지.

## 판정

NOT_READY: broker HTTPS 입구/CPython 바인딩, WSS 방향, 큐 공유 연결, 결과 저장 정본, 정지 증명, R2 핸드백, PC 왕복과 LoveTree 전체 로그인 모두 미검증이다. 작업 승인 또는 이번 문서 PR은 설치·배포·전환을 허용하지 않는다.

## 조건부 등록 경로 상세

다음 경로는 app_factory의 connector_owner_enrollment 및 oracle_mesh_return_source 조건이 맞아야 실제로 등록된다. 로컬 기본 앱의 243개 표에 빠져 있을 수 있다.

| 메서드·경로 | 소유/효과 |
|---|---|
| GET /api/claw/connector/enrollments/setup, /setup.js | 소유자 등록 UI·정적 스크립트. 인증·인가 경계 유지. |
| POST /api/claw/connector/enrollments/consent/grant, /consent/revoke | identity consent 변경. |
| POST /api/claw/connector/enrollments/issue, /approve-link, /bootstrap-owner-role, /install-schema | identity 동의·enrollment, broker challenge/기기 등록 또는 스키마·관리자 설정. 호출별 실제 기능·활성 상태 검토 필요. |
| POST /api/claw/connector/android-enrollment/challenge | identity 동의 및 broker 페어링 challenge. |
| GET /api/claw/connector/android-text-reads/folders; POST /android-text-reads/request; POST /api/claw/connector/text-reads/request | broker 기기 목록/읽기와 작업 등록. 출처와 정본에 대한 호출별 대조 필요. |
| POST /api/claw/local-access/connect; GET /api/claw/local-access/connect; GET /api/claw/local-access | 기기 연결·상태. 브로커/identity 연결 방식은 실제 구성 확인 필요. |
| POST /api/claw/runs/{run_id}/local-result | 로컬 결과 회수와 Chat run/대화 기록 경계. |

broker Worker RPC 메서드에는 register_binding, rotate_credential, revoke_binding, open_session, authenticate_device_session, enqueue_command_with_material, resolve_command_material, poll, admit_command, acknowledge, reconcile_expired_command, handle_device_http, device_truth, device_directory, set_owner_usage, terminal_command_result, read_office_artifact_part, read_verified_file_text, installed_execution_profile, android_saf_profile(s), install_pairing_schema, issue_enrollment_challenge, get_enrollment_binding, recovery_verdict, verify_enrollment_bootstrap, gateway_bootstrap_rpc, redeem_enrollment이 있다. 상태 소유자는 기존 broker DO이며, 각각의 읽기·변경 범위와 단일 권위 검사는 미완료다. 이 열거를 배포된 공개 HTTPS 권한이나 모든 경로 동작의 증거로 사용하지 않는다.

## 추가 위험: GET 폴백

앞단은 HTTP 메서드로 GET/HEAD/OPTIONS를 read로 분류한다. Google callback, LoveTree 시작, GitHub OAuth 시작/콜백은 GET이지만 데이터를 쓴다. COM2 정본 전환 후 service 폴백이 켜져 있다면 이 요청이 기존 Worker로 돌아가 D1에 쓸 수 있다. static 폴백만 설정되어 있어도 제품 전체의 직접 Worker 접근·동적 등록·예외 경로가 안전하다는 증거는 아니다. 쓰기 효과 기준의 fail-closed 분류와 통합 테스트가 선행되어야 한다.
