# PC Mesh 테넌트 격리 설계 — 2026-11-02

상태: 설계 문서 (코드 변경 없음)
작성: 아스트라8 (CTO 지시 2026-11-02)
근거 실측: 컴2 MeshCentral(127.0.0.1:4443, 공개 주소 mesh.padiem.net) — 장치 그룹은 `PADIEM-MC-TRIAL` 하나, 장치 문서 400개 이상.

## 0. 결론 요약

- **현재 사용자 간 격리는 "페어링 기록 + 서버측 소유권 재검증"으로 성립한다.** MeshCentral 자체는 단일 공유 그룹이므로 격리 경계가 아니며, 메시 레벨에서는 모든 에이전트가 같은 그룹에 있다.
- 강한 지점: 명령 전달은 매번 서버가 소유자 링크와 루트를 재검증하고, Engine↔Chat 호출은 HMAC 서명+스코프 동결로 고정된다. 임의 node 지정으로 남의 PC에 명령을 보내는 경로는 닫혀 있다.
- 빈 곳(외부 사용자 수용 전 정리 필요): ① 공유 그룹 안에서 장치 나열이 MeshCentral 계정 권한으로 열려 있으면 어떤 설치 에이전트든 같은 그룹의 다른 장치 메타데이터를 볼 수 있다. ② 채택(adopt)은 전역 관리자 전용이지만, 페어링 코드 자체는 "코드를 아는 사람 + 그 코드를 에이전트 이름에 심은 PC"면 임의 계정에 링크된다(일회용·단기 만료로 완화됨). ③ 설치 URL이 전 사용자 동일 그룹이라 그룹 ID가 노출된다.

**추천안: 선택지 B(단일 그룹 유지 + 서버측 소유권 검사 강화) + 선택지 C(계정별 설치 토큰)의 조합을 단계적 PR로 시행한다.** MeshCentral 대규모 그룹 재구성(선택지 A)은 400+ 장치 마이그레이션 부담 대비 격리 이득이 적고, 지금 격리를 만드는 실제 경계는 Chat 서버이기 때문이다.

## 1. 현재 구조: 설치 → 그룹 가입 → 페어링 연결 → 명령 전달

```
[사용자 PC]                          [Chat 서버(컴2 CPython)]              [MeshCentral]
1. 설치 URL 수신 (Chat 화면)
   PC_AGENT_INSTALL_URL = https://mesh.padiem.net/meshagents?id=4&meshid=<그룹ID>
   └─ 모든 사용자 동일 그룹 ID (worker.py:1678-1682, local_cpython.py:398)
2. 에이전트 설치 → PADIEM-MC-TRIAL 그룹 가입
3. Chat 페어링 코드 발급 (pc_device_pairing_routes.py)
   └─ 코드 → tag → 에이전트 이름 심기 (pc_device_pairing_store.py:677+)
4. presence 비트 보고 (oracle_mesh_read_return_routes.py:1947 _record_mesh_presence)
   └─ agent_name의 tag로 소유자 확정 → pc_device_links (user_id, mesh_node_id)
5. 명령 전달
   chat_pc_drive.py _check_mesh_grant(:504) → oracle_mesh_read_return_routes.py
   _engine_pc_files_target(:4274) → _pc_files_directory_target(:4222, 소유자 링크 우선)
   → 서버가 HMAC 서명 명령 생성 (engine claw_pc_query_step_driver.py:188)
   → MeshCentral → node_ref 장치 실행
```

## 2. 사용자 A → 사용자 B PC 명령 차단 지점 (파일:줄)

### 2.1 막는 지점 (현재 닫혀 있는 경로)

| # | 지점 | 파일:줄 | 역할 |
|---|------|---------|------|
| G1 | 페어링 코드→소유자 확정 | `apps/padiem-chat/app/pc_device_pairing_store.py:677-752` (`complete_claim_from_observation`) | 일회용 코드 tag만이 링크를 만든다. tag는 단일 사용(state≠pending → `pairing code used`), 만료 검사(:723-733), 코드-노드 일치 재확인(:735-737) |
| G2 | 소유자 링크 우선 규칙 | `apps/padiem-chat/app/oracle_mesh_read_return_routes.py:4222-4271` (`_pc_files_directory_target`) | 디렉터리가 답한 계정은 `pc_device_links`의 자기 링크로만 한정. 링크 없으면(legacy 맵 폴백, :4352-4361 TODO(#5573)) 기존 운영 장치만 허용 |
| G3 | 루트(승인 폴더) 경계 | `apps/padiem-chat/app/oracle_mesh_read_return_routes.py:4256-4262` | 승인 폴더 없는 링크는 파일 호출 거부. 루트는 소유자가 `PC_PAIRING_ROOTS_PATH`로 직접 승인 (`pc_device_pairing_routes.py:63`) |
| G4 | 명령 대상 단일성 | `apps/padiem-chat/app/oracle_mesh_read_return_routes.py:406-428` (`command_target`) | account_ref 일치 + `command_exec` 명시 행만, 후보 2개 이상이면 None(임의 선택 금지) |
| G5 | 그랜트 재검증 | `apps/padiem-chat/app/chat_pc_drive.py:504-536` (`_check_mesh_grant`) | 매 명령 전 canonical 세션·owner scope·command_target 일치 재확인. 세션 없음/owner scope 실패/대상 불명확 = 거부 |
| G6 | 모델 요청 무권한 원칙 | `apps/padiem-chat/app/chat_pc_drive.py:836-841` (lane docstring), `:335-342` (`_declared_plan_for_tool`) | 모델의 tool call은 진입일 뿐 권한 아님. plan은 도구 이름에서 서버가 유도하고 선언값은 축소만 가능 |
| G7 | Engine→Chat 서명 + 스코프 동결 | `apps/padiem-ai-engine/app/claw_pc_query_step_driver.py:188-247` (`_signed_files_call`), `apps/padiem-chat/app/oracle_mesh_read_return_routes.py:4573-4580` (scope 동결 검사) | HMAC proof + `X-Claw-PC-Scope` 2차 서명, `pin_pc_run_scope` 후 불일치 403. subject/run/app/device는 서버 소유 |
| G8 | 관리자 채택 가드 | `apps/padiem-chat/app/pc_device_pairing_routes.py:825-833` | adopt는 전역 플랫폼 관리자만, 존재 확인된 장치만, 실패 응답은 정보 노출 없음 |
| G9 | 노출 최소화 | `apps/padiem-chat/app/pc_device_pairing_store.py:697-706` (tag 미저장: sha256만), `oracle_mesh_read_return_routes.py:1956-1965` (claim 실패 로그는 예외 유형만) | 페어링 비밀·계정·경로가 로그에 남지 않음 |

### 2.2 빈 곳 / 약한 곳 (외부 사용자 수용 전 정리 필요)

| # | 빈 곳 | 위치·근거 | 위험 |
|---|-------|-----------|------|
| W1 | **공유 그룹 가시성**: MeshCentral 계정이 그룹 내 다른 장치 나열을 허용하면, 설치만 한 외부 에이전트(=그 그룹 소속)가 같은 그룹 장치 메타데이터를 볼 수 있다. Chat 저장소 코드에는 그룹 멤버십/가시성 검사가 없다(`meshctrl`/그룹 관련 검사 코드 전무 — 저장소 grep 결과 권한 포트 존재만 확인). | MeshCentral 서버 측 설정(코드 밖) | 장치 메타데이터(이름·OS·IP) 사용자 간 노출 가능. 명령은 G1-G7로 막히지만 메타데이터는 별도 경계 |
| W2 | **동일 설치 URL·그룹 ID 노출**: `worker.py:1678-1682`, `local_cpython.py:398` — 모든 사용자가 같은 `meshid`를 받는다. URL은 화면 노출 값이므로 그룹 ID가 반공개가 된다. | 배포 변수 1개 | 그룹 ID만으로는 명령 불가(G5)이나, "설치만 하면 우리 그룹" 상태가 되어 W1의 전제 강화 |
| W3 | **코드 엿보기 창**: 페어링 코드는 단기 만료·일회용이지만, 코드를 획득한 제3자가 자기 PC 에이전트 이름에 tag를 심으면 그 제3자 PC가 코드 발급 계정에 링크된다(타인 PC 탈취가 아니라 "내 PC가 남 계정에 붙는" 방향). 피해는 코드 발급자가 존재하지 않는 자기 PC를 보는 정도이며, 루트 승인 전에는 파일·명령 불가(G3). | `pc_device_pairing_store.py:677-740` | 낮음(완화됨). 코드 전달 경로가 화면 복사뿐인지 확인 필요 |
| W4 | **legacy 맵 폴백**: `_engine_pc_files_target`의 TODO(#5573) 폴백(`oracle_mesh_read_return_routes.py:4352-4361`)은 링크 없는 계정을 배포 맵 행으로 허용한다. 맵은 운영자 소유라 사용자 간 침범은 아니지만, 링크 우선 규칙과 이중 권한원으로 남아 있다. | 동일 파일 :4343-4361 | 낮음. 외부 사용자 확대 시 폴백 제거가 정리 대상 |
| W5 | **채택 대상 계정 확인이 관리자 수동**: adopt의 `target`은 관리자가 타이핑하는 값(`pc_device_pairing_routes.py:810-822`). 잘못 지정하면 고객 PC가 엉뚱한 계정에 붙는다(관리자 실수 벡터, 공격 벡터 아님). | 동일 파일 :766-841 | 낮음. 운영 절차로 관리 |

## 3. 선택지 비교

| 항목 | A. 사용자별 MeshCentral 장치 그룹 자동 생성 | B. 단일 그룹 유지 + 서버측 소유권 검사 강화 | C. 계정별 설치 토큰(그룹은 단일, 가입 토큰 분리) |
|------|--------------------------------------------|----------------------------------------------|------------------------------------------------|
| 보안 수준 | 높음(메시 계층에서 그룹 자체가 격리). MeshCentral 계정·그룹 권한 설계에 의존 | 중~높음(명령 경계는 이미 서버측 G1-G7; 메타데이터 가시성은 MeshCentral 계정 권한 설정으로 보완 필요) | 높음(토큰→사용자 대응표로 가입 추적 가능, 유출 토큰 폐기 가능) |
| MeshCentral 관리 부담 | 큼: 사용자마다 그룹 생성, 초대 링크 관리, 400+ 기존 장치 재분류. 자동화용 meshctrl 스크립트 상시 운영 | 작음: 지금 구조 유지, 서버 로직만 강화 | 중간: 토큰 발급·검증·폐기 화면/로직 추가, MeshCentral은 무변경 |
| 기존 에이전트 이전 | 전부 재설치 또는 그룹 이동 필요(400+). 중단 위험 큼 | 이전 불필요 | 기존 에이전트 그대로(토큰 무관 가입 상태 유지), 신규만 토큰 경로 |
| 구현 범위(파일 수) | 큼: meshctrl 자동화 스크립트 + 설치 URL 생성기 + 그룹 동기화 잡 + Chat 화면(예상 8~12파일, 운영 스크립트 포함) | 작음: 설치 화면 안내 문구 + presence 디렉터리 스코프 강화 + 맵 폴백 제거 스위치 + 문서(예상 4~6파일) | 중간: 토큰 모델·발급 라우트·설치 URL 개인화·검증(예상 6~9파일) |
| 외부 사용자 수용 적합성 | 장기적으로 가장 깔끔하나 지금 단계엔 과도 | 즉시 시행 가능, 현재 실측(단일 그룹 400+)과 맞음 | W2를 정면으로 해소, 단계 B 이후 접목 용이 |

## 4. 추천안과 단계별 구현 계획 (PR 단위)

**추천: B(즉시) → C(외부 사용자 개시 전) → A(장기 옵션, 사용자 수 규모가 커질 때 재평가).**

### PR-1 (B-1): 문서화 + 설치 화면 경계 안내
- `docs/architecture/PC_MESH_TENANT_ISOLATION_20261102.md`(본 문서) 병합.
- Chat 설치 화면 안내 문구에 "에이전트는 배포 공용 MeshCentral 그룹에 가입되며, 장치-사용자 대응은 PADIEM 서버의 페어링 기록으로 관리된다"를 명시(사용자 기대 정합).

### PR-2 (B-2): presence 디렉터리 스코프 강화
- `_record_mesh_presence`(`oracle_mesh_read_return_routes.py:1947+`)에서 `pairing.device_scope` 응답의 `account_refs`를 presence 레코드에 저장해, 이후 디렉터리 조회가 소유자 계정 목록 없이 장치만 노출하지 않도록 스코프를 고정.
- `drive_roots_for_node`(`pc_device_pairing_store.py:895-919`)처럼 노드 전역 조회를 하는 경로에 호출자 소유자 검증 추가.

### PR-3 (B-3): legacy 맵 폴백 종료 스위치
- `_engine_pc_files_target`의 TODO(#5573) 폴백(`oracle_mesh_read_return_routes.py:4352-4361`)을 `ORACLE_MESH_LEGACY_MAP_LANE=off`와 동일한 운영 스위치로 종료 가능하게 하고, 컴1·컴2 링크 이전 완료 후 기본 off.
- 관련 테스트: 폴백 on/off 두 모드에서 G2-G5 회귀 유지.

### PR-4 (C-1): 계정별 설치 토큰
- 페어링 코드 발급 시 설치 URL을 `PC_AGENT_INSTALL_URL?Token=<계정 바운드 토큰>` 형태로 개인화하고, 토큰→계정 대응을 `pc_pairing_codes`와 같은 D1 테이블에 기록. 유출 시 토큰 폐기로 가입 추적 차단.
- `worker.py:1678-1682`·`local_cpython.py:398`의 단일 URL 상수를 "기본 URL + 계정 토큰 조립"으로 교체. 기존 에이전트는 URL 무관 가입 상태 유지(무중단).

### PR-5 (C-2): MeshCentral 메타데이터 가시성 점검 (운영 작업, 코드 변경 최소)
- mesh.padiem.net 계정 권한에서 그룹 내 장치 나열을 "자기 장치만"으로 제한하는 MeshCentral 설정 적용 가능 여부 확인(운영 서버 접촉은 대표 승인 범위). 코드 변경은 확인 결과 기록뿐.

### 기존 컴1·컴2·CGI-1 에이전트 이전 순서 (끊지 않기)

1. **현행 유지**: B 계열 PR은 기존 에이전트·링크·맵을 전혀 건드리지 않는다(재설치 불필요).
2. **PR-3 스위치 off 전 확인 순서**: ① 컴1(대표 PC) 링크 존재 확인 → ② 컴2(테스트 PC) 링크+루트 승인 확인 → ③ CGI-1(고객 시연 PC) 링크+루트 확인 → ④ 세 장치 모두 디렉터리 응답으로 G2-G5 통과 확인(명령 1회 실측) → ⑤ 스위치 off → ⑥ 폴백 관련 테스트 갱신.
3. **PR-4 토큰 도입**: 신규 사용자만 개인화 URL. 기존 에이전트는 재설치 없이 페어링 기록 그대로. 토큰 폐기 절차와 재발급 화면을 함께 배포.
4. **선택지 A 재평가 트리거**: 외부 사용자 20명 초과 또는 그룹 장치 1,000개 초과 시 A 전환 설계 재검토(그때는 meshctrl 일괄 이동 스크립트와 단계별 그룹 분할을 설계 문서로 별도 확정).

## 5. 미결·보고 사항

- MeshCentral 계정 권한 설정(그룹 내 장치 가시성)은 운영 서버 확인이 필요해 본 문서에서는 미확정(PR-5).
- 페어링 코드 전달 경로가 화면 복사 외에 있는지(메신저 전달 등)는 운영 관행 확인 필요(W3 완화 전제).
- 본 문서는 코드 변경을 포함하지 않는다. 모든 파일:줄 근거는 2026-11-02 main(09b4b473f) 기준 실제 소스에서 확인했다.
