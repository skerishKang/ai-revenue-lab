# Stage 2-C 상세 설계 — broker/device 레인의 컴2 이전 (2026-10-29)

```text
DOC_ROLE=COM2_BROKER_STAGE2C_DESIGN
STATUS=설계만 (구현 없음). 착수는 Qoder 큐 전환 30분 관찰 결과를 본 CTO 결정.
ISSUE=#5573
RELATED=COM2_CONTROL_PLANE_RPC_INGRESS_20261029.md §5, PR #6121(queue_store_proxy), PR #6135(큐 배포)
```

## 1. 범위 — 큐에 흡수되지 않은 것만

COM2 큐가 이미 진실인 것: `oracle_mesh_dispatch`(생성·클레임·갱신·취소·완료), `pc_pairing_codes`, `pc_device_links`, `mesh_device_presence`. Chat은 `queue_store_proxy`로 그 표들을 큐에 묻는다.

Stage 2-C 대상(현재 `padiem-local-agent-broker-state` DO 전용):

| 레인 | RPC | 현재 보증 |
|---|---|---|
| 기기 HTTP/세션 | `handle_device_http`, `open_session`, `authenticate_device_session`, `terminal_command_result` | 세션·자격증명은 해시로만 저장, 원문 비저장, 재생/시퀀스 규칙 |
| 등록(enrollment) | `issue_enrollment_challenge`, `verify_enrollment_bootstrap`, `redeem_enrollment`, `gateway_bootstrap_rpc`, `recovery_verdict`, `install_pairing_schema` | 일회용 challenge·부트스트랩·동의 경계 |
| 읽기 | `read_verified_file_text`, `device_directory`, `read_office_artifact_part`, `installed_execution_profile`, `android_saf_profile(s)` | owner 스코프 투영, 자격증명 미노출 |
| 명령 material | `enqueue_command_with_material`, `store/resolve_command_material` | material 만료·ack/rotate/revoke 시 즉시 purge |

목표는 "같은 RPC 이름·같은 응답 봉투"를 컴2의 단일 프로세스 + SQLite에서 제공하는 것이다. 새 권한을 만들지 않는다.

## 2. 컴2 구성 (CTO 확정 2026-10-29)

- **별도 서비스 `padiem-broker`**(확정): 큐와 **프로세스·DB를 분리**한다(자격증명 경계). systemd 단일 프로세스, loopback `127.0.0.1:8799`, Cloudflare Tunnel hostname `broker-com2.padiem.net`(가칭)로만 노출. 큐(`:8797`)·파일 레인(`:8788`)·채팅(`:8798`)과 겹치지 않는다.
- **전용 SQLite**(확정): `broker.sqlite3`(WAL, `busy_timeout=5000`, autocommit + 명시 트랜잭션). 큐와 같은 방식의 **일 백업** — `VACUUM INTO` → 사본 `integrity_check`·핵심 표 행 수 검증 통과 후에만 rotate, 보관 정책 동일(7개).
- **호출자 경로**: Chat/Engine/kagent → HTTPS `POST /internal/rpc/<method>` + **v1 service proof**(#6149와 동일 계약). PC 기기 HTTP는 기존 사설 기기 전송 계약 그대로(터널 통과), 세션 인증은 서버 시계 기준.

## 3. 원자성·동시성 — DO `transactionSync` 대응

| DO 특성 | com2 대응 |
|---|---|
| 단일 DO 인스턴스 직렬화 | 프로세스 1개 + `asyncio.Lock`(authority_ref 단위) — systemd가 중복 기동을 막는다(`StartLimit`·ExecCondition) |
| `transactionSync`로 CAS 성공/실패 원자 | `BEGIN IMMEDIATE` … `COMMIT`; 조건부 UPDATE는 `WHERE generation=? AND sequence=?` + `SELECT CHANGES()`(0=패자). 실패 시 전체 ROLLBACK |
| 리스/만료는 서버 시계 | 호출자 시각을 권한 판정에 쓰지 않는다(현행과 동일). 판정용 `now`는 서비스가 1회 채집해 트랜잭션 안에서 고정 |
| material store와 세션 갱신이 한 결정 | enqueue-with-material · ack-purge를 **한 트랜잭션**으로 |

경쟁 조건: 두 호출자가 같은 generation을 회전/소비하면 한쪽만 `changes()==1`, 다른 쪽은 기존과 같은 거절 코드. 차동 테스트(§6)가 이를 실제 소켓 동시 요청으로 잰다.

## 4. 자격증명·비밀

- 기기 자격증명·세션 시크릿: **해시만 저장**(서버 pepper + HMAC/단방향).
- **pepper**(확정): 컴2에서 **1회 생성한 0600 파일**(root 소유, 서비스 사용자 읽기 전용). **DB 백업과 분리 보관** — 같은 백업 묶음/같은 스냅샷 안에 넣지 않는다(백업 유출이 곧 자격증명 검증키 유출이 되지 않도록). 원문은 출력·로그·커밋 금지, 생성 시에도 화면에 쓰지 않는다.
- 원문 자격증명·세션 시크릿·refresh 계열은 DB·로그·응답에 남기지 않는다(현재 DO 플래그와 동일한 계약).
- material(명령 본문)은 별도 표 + `expires_at`, ack/rotate/revoke 시 즉시 삭제, 크기 상한. 백업에도 남지 않도록 purge를 백업 전 스냅샷에 반영(백업은 VACUUM INTO 이후 상태).
- service proof 시크릿은 호출자(Chat)와 같은 값, env 파일 0600. 비밀이 없으면 기동 거부(check_config).

## 5. 전환 순서 (쓰기 권위는 항상 하나)

1. **선행**: Qoder 큐 전환 `QUEUE_BACKEND=com2` 30분 관찰 통과(CTO 판단). 이 설계는 그 뒤에 착수.
2. **Stage A — 읽기 전용 그림자(확정: 100% 비교)**: D1/DO 스냅샷을 `copy_state` 방식으로 `broker.sqlite3`에 복사. **읽기 호출 100%를 com2에서도 실행해 응답을 Cloudflare와 대조하되, 실제 응답은 기존 DO 경로가 돌려준다**(그림자). **불일치 0이 24시간 유지**되면 Stage B로 간다. 쓰기는 계속 Cloudflare.
3. **Stage B — 쓰기 권위 이전(확정: 05:00~06:00 KST 창)**: 새벽 창에서 쓰기 동결 → 최종 스냅샷(해시 장부) → Chat/Engine/kagent의 broker origin을 com2로 전환 → 기기 한 대 페어링/세션/읽기/명령 왕복 스모크. **실행은 Qoder, CTO 승인 후**. 창을 넘기면 자동으로 원복 절차(§6)를 따른다.
4. **Stage C — 관찰**: 이중 쓰기 없음(쓰기 권위는 com2 단일). Cloudflare DO는 **읽기 전용 롤백 경로**로 보존하되 쓰기를 받지 않도록 배포 구성에서 분리.

원칙: **이중 쓰기(dual-write) 금지** — 두 권위가 서로 다른 CAS 결과를 만들 수 있다. 단계 사이는 동결+스냅샷으로 자른다.

## 6. 원복 방법

- Stage A: Chat 설정만 되돌리면 끝(Cloudflare 쓰기 권위 불변). 복사본 폐기.
- Stage B/C: ① 쓰기 동결 → ② com2 `VACUUM INTO` 스냅샷 + 행 해시 장부 → ③ 스냅샷 장부를 D1 복원 도구(방향 반대의 copy)로 재적용 → ④ origin을 Cloudflare로 되돌림 → ⑤ 동결 해제. 장부 해시로 "동결 후 누락 행"을 확인한 뒤에만 해제한다.
- 롤백도 같은 차동 테스트를 통과해야 완료로 본다.

## 7. 필요한 차동 테스트 (같은 벡터, 두 구현)

| 테스트 | 방법 |
|---|---|
| RPC 봉투 동일성 | 고정 벡터(세션 개설/인증/디렉터리/읽기/enrollment/회전)를 DO(인메모리 storage)와 컴2 서비스에 각각 실행, 응답 딥이퀄 |
| CAS 패자 | 두 동시 요청(회전·소비) → 한쪽만 성공, 다른 쪽 기존 거절 코드 |
| 만료 경계 | `expires_at` 1초 전/후, 서버 시계 고정(모듈 시계 pin) — 시한폭탄 금지 |
| purge | ack/rotate/revoke 후 material·세션 행 부재 |
| 재생/시퀀스 | 같은 시퀀스 재전송 거절, 큰 시퀀스 거절 |
| 스코프 | cross-product·cross-workspace 거절, 자격증명/시크릿 응답 미노출 |
| 동시성 | 실제 소켓 2연결 경쟁, `BEGIN IMMEDIATE` 잠금 대기 상한 내 완료 |
| 롤백 리허설 | Stage B 원복 절차를 스테이징에서 1회 수행, 장부 해시 일치 |

## 8. CTO 확정 (2026-10-29)

1. **서비스**: 별도 `padiem-broker` — 큐와 프로세스·DB 분리(자격증명 경계), systemd 단일 프로세스.
2. **DB**: 컴2 전용 SQLite(WAL), 큐와 같은 방식의 일 백업(`VACUUM INTO` + 검증 + 보관).
3. **Stage A**: 읽기 **100%** 그림자 비교, **응답은 기존 DO 경로**. 불일치 0이 **24시간** 유지되면 Stage B.
4. **Stage B**: **05:00~06:00 KST** 창, 실행 **Qoder**, **CTO 승인 후**.
5. **pepper**: 컴2에서 1회 생성한 **0600 파일**, **DB 백업과 분리 보관**(같은 백업 묶음 금지), 원문 출력·로그·커밋 금지.

남은 실행 항목(결정 아님): Stage A 그림자 러너의 배포 위치·로그 보관(숫자만), Stage B 승인 문서 형식.
