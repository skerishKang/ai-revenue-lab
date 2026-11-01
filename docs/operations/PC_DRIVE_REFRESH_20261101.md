# PC 드라이브 목록 자동 갱신 (#6460)

범위: 코드·모의 시험·브랜치 push. 실제 Windows PC, 운영 서비스, DB에는 적용하지 않았다.

## 운영 경로

1. 기존 Windows MeshAgent 안에 읽기 전용 메모리 watcher를 멱등 설치한다.
   `WM_DEVICECHANGE`가 목록을 갱신하고 30초 비교가 이벤트 미지원·누락과 여유 공간 변경을 보완한다.
   드라이브 이름·종류·여유 공간·전체 용량만 읽는다.
2. 컴2의 기존 Mesh executor가 별도 background loop에서 활성·일시정지되지 않은 pairing 기기만 조회한다.
   기존 MeshCentral Agent Console 인증으로 watcher 결과를 읽고, 인증 서버가 붙인 node ID와 요청 식별자를 확인한다.
   재접속·agent core 재시작 뒤 다음 조회에서 watcher가 다시 설치된다.
3. 변경된 전체 목록을 기존 `X-Oracle-Mesh-Secret` 채널로 운영 큐 **8797**에 보고한다.
   PC에는 큐의 비밀을 전달하지 않는다. 실패한 전송은 다음 주기에 다시 보낸다.
4. 큐가 현재 pairing을 재확인하고 서버 수신 시각을 붙여 `mesh_device_drives`에 저장한다.
5. Chat **8798**의 기존 소유자별 기기 목록 API가 큐 내부 RPC로 목록을 읽는다.
   기존 PC 선택기에서 각 기기 아래 이름·종류·여유 공간을 표시한다.

장치 이벤트는 PC 메모리 목록을 즉시 갱신한다. 컴2 보고는 다음 30초 조회 주기와 조회 소요 시간 뒤 반영되며,
열려 있고 보이는 선택기 화면도 30초마다 읽는다. 지속 연결을 통한 즉시 화면 push는 아니다.
창을 닫거나 탭을 숨기면 화면 조회를 중단한다. 갱신 대기 중 기존 PC 선택은 유지한다.

Broker 8799를 사용하지 않는다. 드라이브 목록은 표시용 읽기 메타데이터이며,
기존 파일 권한·허용 폴더·실행 하네스는 변경하지 않는다.

## 계약과 저장

- `POST /api/claw/connector/mesh-reads/drives/targets`: 기존 executor 채널 인증, 빈 JSON 요청.
  현재 active/unpaused pairing의 기기 ID만 반환한다. 사용자 ID·허용 폴더는 반환하지 않는다.
- `POST /api/claw/connector/mesh-reads/drives`: 같은 인증. 요청은 `device_id`, `drives`만 허용한다.
  각 드라이브는 `path`, `name`, `kind`, `free_bytes`, `total_bytes`를 가진다.
  종류는 `fixed/removable/network/cdrom/ramdisk/unknown`, 모르는 용량은 `null`이다.
- migration **086_mesh_device_drives.sql**: 기기당 최신 전체 스냅샷과 `received_at`.
  성공적으로 관측된 `[]`는 전체 제거다. 조회 불가는 빈 목록으로 저장하지 않는다.
- `GET /api/claw/local-access/devices`: 기존 세션과 소유권 검증을 통과한 기기에만
  `drives`, `drivesUpdatedAt`, `drivesStatus`를 붙인다. 다른 사용자의 기기는 조회하지 않는다.
- 마지막 확인 시각은 마지막 변경 보고의 서버 수신 시각이다. 과거 목록을 온라인 여부나 새 권한으로 해석하지 않는다.

## 컴2 반영 참고 (이번 작업에서는 실행하지 않음)

새 비밀·환경 변수는 없다. 기존 `ORACLE_MESH_QUEUE_ORIGIN`, `ORACLE_MESH_MESHCTRL_JS`,
`ORACLE_MESH_LOGIN_USER`, `ORACLE_MESH_PASSWORD_FILE`, `ORACLE_MESH_URL`,
`ORACLE_MESH_CHANNEL_SECRET_FILE`을 재사용한다.
큐 origin이 설정된 기존 executor 시작 경로에서 보고기를 자동 시작한다.
MeshCentral의 기존 운영 계정에는 대상 PC의 기존 RemoteControl·AgentConsole 권한이 필요하다.
권한이 없거나 PC가 끊기면 마지막 목록을 보존하고 새 성공으로 표시하지 않는다.

CTO가 머지한 뒤 컴2 담당 레인이 기존 설치 절차로 같은 revision의 큐·Chat·executor를 반영한다.
큐의 schema 적용 목록에 086이 포함되어 있고, Chat의 기존 migration loader도 086을 읽는다.
Windows에 별도 파일·예약 작업·서비스·비밀을 설치하지 않는다.

## 시험 범위

- 모의 Windows 장치 이벤트와 30초 fallback: 초기 목록, USB 추가·제거, 용량 변경, 조회 실패, 재설치 멱등성.
- Mesh 콘솔 응답: 서버 node ID·요청 식별자 결합, 보호된 stdin 자격증명, 실패 조회 생략.
- 변경 보고·재전송, active pairing 대상 제한, 8797 인증, command watchdog와 분리.
- 실제 큐 route → migration 086 SQLite → 실제 내부 RPC → 세션 Chat API → 실제 화면 JS 통합.
- 다른 사용자·미인증·해제된 기기 격리, 빈 목록·미보고·조회 장애 구분, 선택 유지와 화면 30초 갱신.

실제 Windows 장치 연결·운영 배포 시험은 이 코드 작업의 결과에 포함하지 않는다.

관련 시험은 중복을 제외해 301개 통과했다. 자동 갱신 중 PC 선택 유지 회귀시험을 포함한다.
Node 문법 검사와 `git diff --check`도 통과했다.

사용한 공식 구현 계약:

- [MeshCentral meshcore.js](https://github.com/Ylianst/MeshCentral/blob/adce1ec488dc884ce947ea4e4808e6a520609b17/agents/meshcore.js):
  콘솔 권한 검사, eval 반환값 JSON 직렬화, `msg/console` 응답.
- [MeshCentral webserver.js](https://github.com/Ylianst/MeshCentral/blob/adce1ec488dc884ce947ea4e4808e6a520609b17/webserver.js),
  [meshuser.js](https://github.com/Ylianst/MeshCentral/blob/adce1ec488dc884ce947ea4e4808e6a520609b17/meshuser.js):
  인증된 서버 node ID 부여와 계정 domain 전달.
- [MeshAgent win-message-pump.js](https://github.com/Ylianst/MeshAgent/blob/26846b1c7f0841d71938f6bebc96eef5a947d217/modules/win-message-pump.js),
  [ILibDuktape_fs.c](https://github.com/Ylianst/MeshAgent/blob/26846b1c7f0841d71938f6bebc96eef5a947d217/microscript/ILibDuktape_fs.c):
  Windows 장치 메시지와 native 드라이브 목록 필드.

## 브랜치 출발점

요청된 `origin/feat/pc-agent-drives-261101`은 fetch·원격 조회에서 발견되지 않았다.
별도 `feat/pc-agent-tray-drives-261101`에는 트레이 변경만 있었다.
이 때문에 main `6b180fa569cb7befc6f6280236ada8b252ad2401`에서 요청된 이름의 브랜치를 만들었고,
작업 중 규칙 문서만 갱신한 main `429a7f11`을 fast-forward로 반영했다.
선행 드라이브 비교 코드를 이어받았다고 주장하지 않는다.
