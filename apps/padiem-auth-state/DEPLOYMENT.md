# padiem-auth-state 배포 예시

이 문서는 설치 예시다. 실제 설치·서비스 등록·Worker 배포·비밀 설정·데이터 이전은 이 PR에서 수행하지 않는다. 실제 주소·IP·비밀 값·계정 정보는 문서에 기록하지 않는다.

## 전제 조건

- Node.js 22 이상. `node:sqlite`를 사용하므로 Node.js 24 LTS를 권장한다.
- 상태 전용 SQLite 파일을 저장할 디렉터리와 서비스 사용자.
- 기존 컴2 터널 뒤에 서비스를 노출할 수 있는 구성.
- identity Worker에 auth-state 전용 v2 ingress 두 개가 코드로 배포되어 있고, 전용 비밀이 각각 설정되어 있어야 한다.
  - `PADIEM_AUTH_STATE_IDENTITY_RPC_SECRET`
  - `PADIEM_AUTH_STATE_DELETION_RECORD_RPC_SECRET`
- Worker↔컴2 상태 RPC에는 별도 `AUTH_STATE_SECRET`을 사용한다. 세 비밀은 서로 다른 값이어야 한다.

## 환경 파일

`deploy/auth-state.env.example`을 복사해 값은 운영 절차로 채운다. 예시 파일에는 값이 없다.

- `PADIEM_AUTH_STATE_DB`: 상태 전용 SQLite 파일 경로.
- `PADIEM_AUTH_STATE_HOST`, `PADIEM_AUTH_STATE_PORT`: 터널이 연결할 로컬 리스너.
- `PADIEM_AUTH_STATE_IDENTITY_RPC_ORIGIN`, `PADIEM_AUTH_STATE_DELETION_RECORD_ORIGIN`: identity Worker의 HTTPS origin.
- `PADIEM_AUTH_STATE_IDENTITY_RPC_SECRET`, `PADIEM_AUTH_STATE_DELETION_RECORD_RPC_SECRET`: 각 전용 문의 비밀.
- `PADIEM_AUTH_ACCOUNT_ISSUER_MODE`, `PADIEM_AUTH_EMAIL_RECOVERY_ENABLED`, `PADIEM_AUTH_PASSWORD_FIND_ENABLED`, `PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED`: Worker의 기존 기능 스위치와 같은 값.

컴2 환경 파일에는 기존 Chat 비밀번호 RPC 비밀과 identity HMAC 키를 넣지 않는다. `completeEmailRecovery`와 삭제 후 Chat 정리는 Worker가 기존 비밀로 수행한다.

## 설치 예시

1. 승인된 절차로 이 디렉터리의 파일을 설치한다. 저장소를 복제해 테스트를 실행하거나 운영 호스트에서 전체 작업 트리를 백업하지 않는다.
2. `deploy/auth-state.env.example`을 바탕으로 환경 파일을 만들고 소유자·권한을 제한한다.
3. `deploy/padiem-auth-state.service.example`을 systemd 유닛으로 설치한다. 설치 경로와 Node 실행 파일은 실제 배포 절차에 맞춘다.
4. SQLite 파일은 서비스 사용자만 읽고 쓸 수 있게 한다. WAL 모드와 `busy_timeout`은 서비스가 시작 시 설정한다.
5. 서비스를 시작하고 `systemctl is-active`와 저널의 값 없는 단계 로그만 확인한다. 본문·헤더·비밀·계정 식별자는 로그에 남기지 않는다.

## 백업

- SQLite WAL 상태를 포함하는 정합성 있는 백업이 필요하다. 서비스 중단 후 SQLite 백업 도구로 복제하거나, 온라인 백업 API를 사용한다.
- 파일만 복사할 경우 WAL 체크포인트와 데이터베이스 파일을 같은 시점에 보존해야 한다. `-wal`·`-shm` 파일을 누락한 복사본은 복구 본문으로 사용하지 않는다.
- 백업 대상은 상태 SQLite와 환경 파일의 키 목록·메타데이터다. 비밀 값과 데이터베이스 본문을 저장소·로그·PR에 올리지 않는다.
- 기존 컴2 백업 흐름에 이 서비스의 정합성 있는 백업 단계를 추가하는 작업은 실제 설치 단계에서 수행한다.

## Worker 전환

Worker 환경은 다음과 같이 선택한다. 기본값은 DO다.

```text
AUTH_STATE_BACKEND=do
AUTH_STATE_BACKEND=com2
AUTH_STATE_URL=<https-origin>
AUTH_STATE_SECRET=<shared-secret>
```

`com2`를 선택하면 DO 바인딩을 호출하지 않는다. 컴2 네트워크 오류·비성공 응답·잘못된 응답은 즉시 실패하며 DO로 자동 전환하지 않는다.

운영 전환 전에는 DO와 컴2 중 하나에만 쓰기를 허용해야 한다. 컴2에 쓰기가 발생한 뒤에는 저장소가 갈라질 수 있으므로, 데이터 이전·검증·전환 계획 없이 환경 변수만 되돌리지 않는다.

## 검증

설치 후 실제 전환 전에 최소한 다음을 확인한다.

- 서명 오류·시각 오차·nonce 재전송이 거절된다.
- 동일 1회용 코드의 동시 교환은 하나만 성공한다.
- 동일 갱신 토큰의 동시 회전은 30초 재시도 계약을 지킨다.
- identity 전용 문은 세 메서드만, 삭제 기록 문은 한 메서드만 허용한다.
- 컴2 실패 시 Worker가 DO를 호출하지 않는다.
