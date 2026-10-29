# 시한폭탄 테스트 전수 점검 (2026-10-29)

```text
DOC_ROLE=TEST_TIME_ANCHOR_AUDIT
STATUS=전수 스캔·분류 완료 / 수정: 이미 터진 1건(아스트라3, #6149) · 예정 폭발 0건 · 안내 주석 2곳
ISSUE=#5573 (품질), #82 (Qoder 큐 차동)
RELATED=PR #6148(큐 차동 앵커 수정, Qoder), PR #6149(lovetree identity 앵커 수정), COM2_CONTROL_PLANE_RPC_INGRESS_20261029.md
```

## 1. 오늘 두 번 터진 같은 종류

| 사례 | 고정 앵커 | 실클록 비교 지점 | 조치 |
|---|---|---|---|
| #6148 큐 차동(`apps/padiem-mesh-queue/tests/test_queue_differential_parity.py`) | 고정 dispatch 시각 | 큐 클레임이 `time.time()` | Qoder가 실클록 스테이징으로 수정(머지 완료) — 이 문서는 기록만 |
| #6149 lovetree identity(`packages/padiem-control-plane/tests/test_lovetree_identity_registration.py`) | `NOW = 2026-10-27 06:00Z` | DO `establish_auth_session`이 `datetime.now()`로 `not_after` 검사 | 앵커를 실클록으로 교체(단언 불변), #6149에 포함 |

## 2. 점검 방법

저장소 전체(`apps/`, `packages/`, `.github/tests/`, `deploy/`; mesh-queue는 소유권상 읽기만)에 네 가지 스캔:

1. 같은 테스트 파일에 ① 고정 `datetime(20xx…)`/`date(20xx…)`/ISO 날짜 문자열과 ② 실클록 호출(`datetime.now/utcnow/today`, `time.time`)이 함께 있는 파일 → 31개.
2. 고정 앵커 상수(`NOW/BASE/BRIDGED_AT… = datetime(20xx…)`)가 **오늘 ±75일 창**에 있는 파일 → 4개.
3. 만료 필드(`expires_at/not_after/claim/lease/ttl/valid_until`)에 고정 ISO 문자열(2026-11 이후)이 들어간 파일 → 14개.
4. epoch 초(10자리) 리터럴 + 만료 문맥 → 0개.

그 뒤 후보 파일을 실제로 실행해(로컬 Windows/3.13) 이미 실패하는 것을 가렸다. 달력 계열·DPAPI·엔진 컬렉션 실패는 **시한폭탄이 아니라 환경 조건**으로 분류했다(§4).

## 3. 결과 — 분류

### 3.1 이미 터진 것: 0건 남음
- lovetree identity 2건: #6149에서 수정·머지.
- 큐 차동: #6148에서 수정·머지, 현재 `test_queue_differential_parity.py` 3 passed.

### 3.2 앞으로 N일 안에 터질 것: 0건 (N=75)
- 창 내 고정 앵커 4개는 모두 **이미 지난** 값이고(10-27/10-28), 해당 경로는 실클록과 비교하지 않음을 실행으로 확인(테스트 green).
- 향후 고정 ISO 만료값 14개 중 근미래는 `test_local_agent_pc_access.py`의 `credential_expires_at=2026-11-01` 하나뿐이며, 이 값은 정책 투영의 **불활성 데이터**다(같은 픽스처의 session `expires_at=2026-10-02`와 heartbeat 10-12가 이미 과거인데도 green → 실클록 비교 없음). 2027/2030 상수는 원거리, 11-01·12-01 달력 값은 DST 산술(§4).

### 3.3 취약(오늘은 결정적, 실클록 비교가 추가되면 즉시 터짐)
아래 파일들은 **고정 앵커가 만료 필드에 들어가고, 같은 테스트가 실클록을 읽는 프로덕션 모듈을 import**한다. 오늘은 now 주입/명시 또는 불활성 데이터라 안전함을 확인했다. 이 경로에 실클록 비교가 추가되면 즉시 시한폭탄이 된다.

| 파일(대표) | 안전 근거 |
|---|---|
| `test_5881_claw_file_lane_admission.py` | 문서 컨텍스트의 `BRIDGED_AT`/`expires_at=10-28`은 **브리지 시각 쌍**으로만 검사됨. 실클록 검사가 추가되면 10-28 만료로 실패 예정 → 주석 추가 |
| `test_google_oauth_workspace_connector_state.py` | 자격증명 픽스처 `expires_at=None`(만료 없음) + read에 실클록 전달. 만료 있는 픽스처를 만들 땐 NOW+delta와 now 주입 필요 → 주석 추가 |
| `test_5094_candidate_review_host_composition.py` | `NOW`는 `now=lambda:`로 주입, 세션은 실클록 생성 — 결정적 |
| `test_padiem_calendar_phase_a.py`, `test_padiem_calendar_d1_store.py`, `test_calendar_automation_projection.py` | `now_utc=`/`ref_now=` 전면 주입(실클록은 “오늘/미래” 계산용). 단 Windows 로컬에서는 tzdata 부재로 실행 불가(§4) |
| `packages/.../test_connector_workspace_read_resolver.py` | `_PinnedNow` 서브클래스로 worker 모듈 시계 자체를 NOW에 고정 — **모범 패턴** |
| `test_local_agent_device_session_auth.py`, `test_b62_3436_desktop_conversation_read_activation.py` | 실클록으로 프로비저닝(주석에 이유 명시) — 결정적 |
| `test_local_agent_pc_access.py` | 만료값이 투영 데이터에만 존재(§3.2) |
| `test_5360`, `test_b66_saved_skill_candidate`, `test_4089`, `test_b54_*_session_*`, `.github/tests/test_b54_engine_caller_registry_v1_provision_gate.py` | 실클록 상대 생성 또는 `now=`/`issued_at=` 명시 주입 — 결정적 |
| `apps/claw-connect/tests/test_device_wss_enrollment_4139.py`, `apps/korean-ai-code-agent/tests/test_4139_resident_restart_registered_binding.py` | 세션 now를 인자/실클록으로 주입(파일 내 주석·skipif 포함) — 결정적 |

나머지 스캔 대상(모듈 내 `now=` 없음 + 실클록 import)은 실행 green이며 만료 필드에 고정값이 없어 목록에서 제외했다.

### 3.4 환경 조건(폭탄 아님)
- `apps/padiem-chat/tests/test_padiem_calendar_*`: Windows 로컬에 `tzdata` 없음 → `ZoneInfo("Asia/Seoul")` 실패. CI(Linux)에서는 zoneinfo 사용. 코드/날짜 문제 아님.
- `apps/korean-ai-code-agent/tests/test_4139_resident_restart_registered_binding.py`: 실제 DPAPI 사용 → 비 Windows에서 `skipif`(의도된 skip).
- `apps/padiem-ai-engine/tests/*` 중 일부: 로컬에서 컬렉션 불가(엔진 런타임 의존) — 이 레인의 CI가 담당.

## 4. 재발 방지 — 승인 패턴 두 가지

1. **now 주입**: 생산 코드가 `now=`를 받으면 테스트는 고정 앵커를 주입한다(가장 단순).
   예: `test_connector_workspace_read_resolver.py`(resolve_existing(now=NOW)), `test_padiem_calendar_phase_a.py`(now_utc=).
2. **모듈 시계 고정**: 생산 코드가 `datetime.now()`를 직접 읽으면 테스트가 그 모듈의 `datetime`을 `_PinnedNow`(datetime 서브클래스)로 바꿔 시계를 고정한다.
   예: `packages/padiem-control-plane/tests/test_connector_workspace_read_resolver.py:757+`.

규칙: **고정 시각은 “실클록과 비교되는 경로”에 넣지 않는다.** 넣어야 하면 (1) 또는 (2)를 쓴다. 공용 `frozen_clock` fixture는 현재 저장소에 없으며, 위 두 패턴이 이미 파일 단위로 존재한다 — 새 전역 fixture는 도입하지 않는다(중복 권한 방지). 새 테스트가 실클록 경로를 건드릴 때 이 문서의 두 패턴을 참조한다.
