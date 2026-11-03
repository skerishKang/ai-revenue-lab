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

## 5. PR-5 점검 결과(2026-11-03)

조사 방식: 컴2 WSL MeshCentral v1.2.5(유닛 `padiem-meshcentral.service`, 설치 `/opt/padiem/meshcentral`, 데이터 `/opt/padiem/meshcentral-data`)를 읽기 전용으로만 점검했다. 설정 변경·재시작·계정/장치/그룹 생성 없음, 웹 로그인 없음. 아래 설치본 줄 번호는 `/opt/padiem/meshcentral/node_modules/meshcentral/` 기준이다.

### 5.1 현재 상태 (MeshCentral DB·설정 실측)

- **고유 계정 1개**(최고관리자, `siteadmin=4294967295`, 계정명은 이 문서에 기록하지 않는다). 비관리자 계정 0개. 당초 "계정 4개"는 같은 계정이 NeDB에 여러 줄로 남은 것을 중복 집계한 값이며, CTO가 DB를 직접 확인해 고유 계정 1개로 정정했다.
- 장치 그룹 1개 — `mtype=2`(Agent 그룹, 그룹 유형 상수는 `meshuser.js:2167` "1 = AMT, 2 = Agent, 3 = Local"), meshid 앞 6자 `u$GdZq…`. 그룹-계정 연결 레코드는 4건이지만 모두 같은 계정의 중복 행이고, 고유 연결 1건의 `rights=4294967295`(전체 권한 비트)다.
- 고유 장치 6개(node 고유 `_id` 6개, `meshcentral.db` node 문서 18건은 NeDB 버전 중복). 2026-11-03 컴2로컬2 보고(장치 6·온라인 4)와 **대수 일치**. 온라인 수는 런타임 전용 필드(`conn` 미영속 — node 문서 어디에도 없음)라 DB에서 재검증할 수 없고 모순도 없다. 2026-11-02 실측 "장치 문서 400+"은 문서(중복 버전 포함) 수와 고유 장치 수의 정의 차이로 본다.
- 게스트 공유 레코드 0건, 그룹 초대 코드(`mesh.invite`) 레코드 없음.
- `config.json` 가시성·권한 관련 키: `settings.ignoreagenthashcheck=true`, `domains[""].newaccounts=false`(2026-11-03 컴2로컬2 적용분), `newaccountspass` 미설정, `agentinvitecodes` 미설정(초대 코드 페이지 비활성), `guestdevicesharing` 미설정(기본 허용이나 공유 레코드 0), 메일 서버 미설정(이메일 가입·재설정 불가), LDAP/SSPI 미설정(로컬 인증만).

### 5.2 노출 경로 판정

- **(a) 에이전트-only PC의 다른 장치 메타데이터 열람 — 불가.** 서버→에이전트 `obj.send` 호출 전수(`meshagent.js` 26곳)는 ping/pong(:666-667), amtconfig(:977, :1758), diagnostic(:1027, :1396-1398), sysinfo(:1037, :1469), errorlog(:1044-1046), coredump(:1053, :1056), iplocation(:1094), serverInfo(:1113), 사용자 명령 전달(:1261, :1605, :1685-1732), guestShare(:1742, :1750 — 에이전트 자신의 공유 설정만), tunnel 쿠키(:2173)뿐이고, 다른 장치의 목록·이름·OS·IP를 담는 메시지는 존재하지 않는다. 장치 이벤트는 `DispatchEvent`로 사용자(web) 세션만 향한다. W1이 전제한 "설치만 한 에이전트가 같은 그룹 장치 메타데이터를 본다"는 현재 서버 코드에서는 성립하지 않는다.
- **(b) 장치 목록은 계정 필요, 가입 경로 닫힘 — 예.** 장치 나열은 인증된 사용자의 웹소켓 `nodes` 명령(`meshuser.js:719`)에서 사용자 링크 기반으로만 이뤄진다(:751 `GetAllMeshIdWithRights(user)`, :760 `IsMeshViewable`; 정의 `webserver.js:9734` — `user.links[meshid]` 직접 링크 또는 `managealldevicegroups` 슈퍼 권한 필요). 계정 생성 경로: 셀프가입은 `newaccounts=false`+기존 사용자 존재로 차단(`webserver.js:3503-3504`), 초대 코드 페이지는 미활성(웹서버 :2202에서 404), 이메일 가입·재설정은 메일서버 미설정으로 불가(:3500), LDAP/SSPI는 미설정(:1587에서 404), 게스트 공유 링크는 레코드 0건(:4385 기능은 허용 상태이나 발급된 공유가 없음). 남는 계정 생성 경로는 최고관리자인 기존 고유 계정 1개의 수동 생성뿐이다(NeDB 중복 행 4건은 같은 계정).
- **(c) W2(설치 URL·meshid 반공개)의 실질 효과 — 무단 에이전트 가입.** meshid만으로 웹 계정·명령·장치 목록은 불가하다(G5·(b)). 그러나 `settings.ignoreagenthashcheck=true`(config)가 `meshagent.js:2178`에서 전역 바이패스로 작동해, meshid를 아는 임의 에이전트 바이너리가 자신의 meshid 선언(:532-559)만으로 프로덕션 그룹(`u$GdZq…`)에 가입할 수 있다. 미지 meshid는 `domain.orphanagentuser` 미설정으로 그룹 생성 불가(:618-634 생성 경로는 관리자 계정이 있어야 함). 가입한 무단 에이전트는 (a)에 따라 다른 장치 메타데이터를 받지 못하며, 실질 영향은 인벤토리 오염·관리자 혼동·그룹 신뢰 훼손(무결성)이다.
- **(d) "자기 장치만 보기" 설정 방법(조사만, 미적용).** ① 테넌트별 장치 그룹 분리 + 사용자 링크를 자기 그룹에만 — 링크 없는 그룹은 나열 단계에서 제외된다(`webserver.js:9734`, `meshuser.js:751/760`). ② 그룹 권한 최소 비트 — `meshuser.js:40-56`의 MESHRIGHT(1 그룹편집, 2 사용자관리, 4 장치관리, 8 원격제어, 16 에이전트콘솔, 32 서버파일, 256 보기전용, 512 터미널금지, 1024 파일금지, 65536 데스크톱금지 등). ③ 장치 단위 링크 `user.links[node._id]`(`meshuser.js:304/344`의 노드 링크 검사 경로). ④ 도메인 키 — `newaccountsrights`(신규 계정 siteadmin 상한, `webserver.js:665`), `newaccountspass`(가입 토큰, :1607), `guestdevicesharing`(계정 없는 보기전용 공유, :4385), `settings.managealldevicegroups`(전 그룹 가시성 슈퍼 권한 화이트리스트, :9747).

### 5.3 결론

- **W1 위험도(현재 구성): 낮음.** (a)로 에이전트 채널의 메타데이터 노출이 성립하지 않고, (b)로 웹 열람은 계정 없이는 닫혀 있으며 계정은 전원 운영자용 최고관리자다. 남는 열린 경로는 (c)의 무단 에이전트 가입이며 이는 기밀성(W1)이 아닌 무결성 항목이다.
- **제안 운영 조치(적용하지 않음, 대기):** `settings.ignoreagenthashcheck`를 `true`→`false`(또는 IP 배열로 스코프). 영향: 서버가 알려진 코어 해시와 맞지 않는 에이전트 연결을 보류/거절한다(해시 불일치 시 연결 보류 경로, `meshagent.js:~526`). 현재 가입 에이전트의 코어 해시가 서버 코어셋에 있으면 무중단이고, 커스텀 코어를 배포 중이면 연결 거절이 가능하므로 1대 장치 선시험을 권한다. 되돌리기: `config.json`을 `config.json.bak-20261103-com2local2`로 복원 + 유닛 재시작.
- **PR-4(계정별 설치 토큰)와의 관계:** PR-4 토큰은 Chat 계층 검증이라 MeshCentral의 가입 게이트를 대체하지 않는다. `ignoreagenthashcheck=true`인 동안은 토큰 유무와 무관하게 meshid만으로 에이전트 가입이 가능하므로, 토큰 도입 전에 해시체크 스코프 정리(위 제안) 또는 MeshCentral 네이티브 그룹 초대 코드(`agentinvitecodes=true` + 그룹 `invite.codes`, `webserver.js:2202-2210`) 채택이 선행돼야 한다.

## 6. 진행 표

| PR | 내용 | 상태 |
|----|------|------|
| PR-1 (B-1) | 본 문서 병합 + 설치 화면 경계 안내 | 문서는 #6695로 병합, 화면 안내 문구는 별도 진행 |
| PR-2 (B-2) | presence 영수증 소유 계정 기록 + 노드 전역 조회 소유자 검증 | **완료 — PR-2 #6717** |
| PR-3 (B-3) | legacy 맵 폴백 종료 스위치(`ORACLE_MESH_LEGACY_MAP_LANE`) + 소유 링크 점검 스크립트(`tools/cto/check_pc_owner_links.py`) | **완료 — PR-3 #6718** (스위치 off 전환은 §4 확인 순서 ①~⑥ 후 운영에서) |
| PR-4 (C-1) | 계정별 설치 토큰 | 대기 |
| PR-5 (C-2) | MeshCentral 메타데이터 가시성 점검(운영 작업) | **점검 완료 — 결과 §5** (운영 조치 1건 제안·대기: §5.3) |

## 7. 미결·보고 사항

- MeshCentral 가시성 점검(PR-5)은 2026-11-03 완료(§5): 현재 구성에서 계정 없는 에이전트가 다른 장치 메타데이터를 볼 경로는 없고, 웹 열람은 계정 필요(셀프가입 차단). 남은 열린 경로는 `settings.ignoreagenthashcheck=true`로 인한 무단 에이전트 가입이며, 운영 조치 제안은 §5.3에 기록(적용 대기, 소유자 승인 후).
- 페어링 코드 전달 경로가 화면 복사 외에 있는지(메신저 전달 등)는 운영 관행 확인 필요(W3 완화 전제).
- 본 문서는 코드 변경을 포함하지 않는다. 모든 파일:줄 근거는 2026-11-02 main(09b4b473f) 기준 실제 소스에서 확인했다.

### 7.1 MeshCentral 가입 게이트 비교·추천 (운영 작업 대기, 본 PR 미적용)

PR-4의 계정 토큰은 Chat 계층 검증이므로 MeshCentral 가입 자체를 막지 못한다(§5.3). `settings.ignoreagenthashcheck=true`가 남아 있는 동안 meshid를 아는 바이너리는 그대로 그룹에 가입할 수 있다. 아래는 그 게이트를 닫는 두 수단의 비교이며, **어느 것도 본 PR에서 적용하지 않았다.**

**(a) MeshCentral 네이티브 그룹 초대 코드 vs 우리 설치 토큰**

| 항목 | MeshCentral 그룹 초대 코드(`agentinvitecodes=true` + 그룹 `invite.codes`, `webserver.js:2202-2210`) | PADIEM 설치 토큰(`padiem_install_token`, PR-4) |
|------|------------------------------------|------------------------------------|
| 검사 주체 | MeshCentral 서버가 에이전트 가입 시점에 검사 | Chat 서버가 페어링·claim 시점에 검사 |
| 막는 것 | meshid만 아는 임의 바이너리의 그룹 가입(무단 가입) | 제3자 PC가 남의 계정에 링크되는 방향(W3), 유출 토큰의 재사용 |
| 범위 | 그룹 단위, 만료·사용 횟수 제한 | 계정 단위, 페어링 코드 1건에 1:1, 만료·폐기·재발급 |
| 설치 URL 인자 | MeshCentral 초대 코드 인자(별도) | `padiem_install_token`(별도 — 두 인자는 서로 대체가 아니다) |
| 기존 3대 영향 | 없음(이미 가입됨, 재설치 불필요) | 없음(기존 링크는 검사 생략, §4 확인 순서) |

토큰과 초대 코드는 검사 지점이 다르므로 **함께 쓰는 것이 맞고, 서로를 대체하지 않는다.** 초대 코드는 가입을 실제로 닫고, 토큰은 Chat 계층에서 누가 언제 어떤 계정으로 설치했는지를 추적·폐기한다.

**(b) `ignoreagenthashcheck=false` 전환 시 기존 3대 유지 판정 방법**

- **무엇과 무엇을 비교하는가:** ① 컴1에 배포된 `C:\Program Files\PADIEM\MeshAgent.exe`의 코어 해시 ② 컴2 MeshCentral 서버가 `ignoreagenthashcheck=false`에서 요구하는 코어 해시 집합(`meshagent.js:526` 부근의 해시 확인 경로, `:2178`이 그 바이패스). ②에 ①이 포함되어야 기존 에이전트 연결이 유지된다.
- **왜 위험한가:** 현재 배포본은 태깅된 커스텀 빌드(2026-10-28)다. 커스텀 코어 해시가 서버 기본 코어셋에 없으면 전환 순간 기존 3대가 연결 거절된다. 즉 "해시 불일치 시 연결 보류" 경로가 운영 장애로 나타날 수 있다.
- **서버 쪽 확인은 컴2 레인 몫:** 서버 코어셋 조회·등록(필요 시)·`config.json` 변경은 컴2 레인이 수행하고, 본 문서는 판정 절차만 남긴다.

**추천안과 적용 순서 (운영 작업 대기)**

1. (완료, 본 PR) Chat 계층 토큰으로 W3 차단·추적. MeshCentral 무변경.
2. (운영 대기) `ignoreagenthashcheck` 스코프 정리 전에 위 (b)로 코어 해시 포함 여부를 판정한다. 포함되면 전환이 무중단 후보다.
3. (운영 대기) 전환은 **1대 선시험**으로 한다: 컴2(테스트 PC) 1대를 전환 후 재연결·10분 관찰 → 컴1(대표 PC) → CGI-1 순. 되돌리기는 `config.json.bak-20261103-com2local2` 복원 + 유닛 재시작(§5.3).
4. (운영 대기) 가입 자체를 닫는 경로는 (a) 그룹 초대 코드다. `agentinvitecodes=true`와 그룹 `invite.codes`를 설치 URL에 붙이는 방안을 별도 운영 작업으로 검토한다(우리 토큰은 계정 추적·폐기용으로 유지).

**토큰 적용 범위(비대칭 고지).** 검토 중인 EXE 설치는 리뷰된 바이너리라 재빌드 없이 에이전트 이름 조립을 바꿀 수 없다. 따라서 EXE 레인은 토큰을 **에이전트 이름에 넣을 수 없고**, 개인화된 다운로드 URL에만 토큰이 실린다(MeshCentral은 이 인자를 가입 시 읽지 않는다). 이 비대칭 때문에 서버 검사는 다음처럼 계층화했다.
- PowerShell 설치 파일 레인: 이름에 토큰이 실리므로 관찰 claim이 **제시된 토큰**을 검증한다.
- EXE 레인: 제시 토큰이 없으므로 관찰 claim은 **바인딩된 토큰의 상태**(존재·미폐기·미만료)를 검증한다.
- POST claim: `install_token`이 있으면 정확히 일치해야 하고, 없으면 바인딩 상태를 검사한다. 토큰 행이 없는 레거시 코드와 이미 링크된 `(user_id, mesh_node_id)`는 검사하지 않는다(기존 동작 그대로).
