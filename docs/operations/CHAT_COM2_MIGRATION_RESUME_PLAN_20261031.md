# Chat 본체 컴2 이전 재개 계획 (2026-10-31)

```text
DOC_ROLE=CHAT_COM2_MIGRATION_RESUME_PLAN
STATUS=계획·조사 (구현·설치·전환·배포 없음)
ISSUE=#5115 (COM2 이전 추적)
기준 main=a7d0630c7 (Draft: Chat common login authorization flow, #6282)
```

## 0. 대표 결정과 이 문서의 범위

2026-10-31 대표 결정으로 Chat 본체의 컴2 이전을 재개한다. 경계는 다음과 같다.

| 구분 | 내용 |
| --- | --- |
| Cloudflare에 남김 | 도메인·DNS·HTTPS·cloudflared 터널 입구, 정적 화면 파일·Pages, padiem-auth(공통 로그인), 봇 차단, R2(컴2 백업용) |
| 컴2로 옮김 | Chat API 본체(Python, B14 포함), D1 데이터, 신원기관 Worker, 크론·예약 작업 |
| 이전 범위에서 빠짐 | 로그인 인증 자체 — padiem-auth가 맡는다 |

이 문서는 실행 계획과 대조 결과만 담는다. 설치·기동·전환·배포·운영 자산 변경은 각 권한 소유자가 별도 승인 아래 수행하며, 이 문서의 머지는 그 승인이 아니다. 2026-10-30 보류 당시 초안·리허설 자료는 지우지 않고 이 문서가 갱신 위치를 지정한다.

## 1. 보관 자료 목록과 현재 main 대조 판정

판정 기준: **그대로**(현재 main에서 여전히 유효) / **손봄**(기준이 낡아 갱신 필요) / **버림**(방침 변경으로 채택하지 않음).

### 1.1 닫힌 Draft PR 3건 (2026-10-30 닫힘)

| 위치 | 내용 | 마지막 갱신 | 판정 |
| --- | --- | --- | --- |
| Draft PR #6190 · 브랜치 `astra4/chat-com2-cutover-plan-20261029` · `docs/operations/CHAT_COM2_CUTOVER_PLAN_20261029.md` | 전환 계획 초안: 동결·최종 export·plan/load/verify·도메인 전환·30분 관찰·핸드백 원복. 10-29 리허설(170.89초, 80표 3,308행, 불일치 0) 기록 | 2026-10-30T10:03Z | **손봄** — 스키마 기준이 076/077·078인데 현재 main은 079. 큐가 com2 정본이 되고 파일 레인이 가동돼 "제외 소유 표"와 객체 경로가 달라졌다. padiem-auth 공통 로그인으로 세션·재로그인 절이 무효 |
| Draft PR #6197 · 브랜치 `astra4/chat-handback-options-20261029` · `docs/operations/CHAT_COM2_HANDBACK_OPTIONS_20261029.md` | 되돌리기 선택안 (가) 기준 스냅숏 대비 PK 변경분 / (나) 관찰 중 쓰기 동결 유지 | 2026-10-30T10:03Z | **손봄** — (가)는 채택 권고 유지. (나)는 **버림**(고객 쓰기 창 전체 동결은 운영 불가). (가)에 D1 게이트 원자성·R2 객체 원복이 빠져 있다 |
| Draft PR #6202 · 브랜치 `astra4/com2-pc-coupling-design-20261029` · `docs/operations/CHAT_COM2_PC_COUPLING_DESIGN_20261029.md` | PC 연결·WSS·queue split-brain·동결 종료 증명·추가 위험(GET 쓰기 폴백) 설계 | 2026-10-30T10:03Z | **손봄** — queue split-brain 절은 `PC_QUEUE_BACKEND=com2` 전환 완료로 닫혔다. WSS·동결 증명·GET 쓰기 분류는 그대로 유효 |

### 1.2 저장소에 남아 있는 설계·런북·꾸러미

| 위치 | 내용 | 마지막 갱신 | 판정 |
| --- | --- | --- | --- |
| `docs/architecture/COM2_CHAT_CPYTHON_STAGE2_20261029.md` | CPython 단일 프로세스 기동 검증(가입·로그인·대화·mock 채팅), D1→SQLite facade, R2 디스크 어댑터, 병행 비교 계획 §8, D1 이전 도구 §9 | 2026-10-29 | **손봄** — §9가 001–077 기준. §8 비교 시나리오는 S4(PC 읽기) 전제가 broker 미개방. `app/local_cron.py`가 `PADIEM_LOCAL_DEV=1`을 요구해 컴2 호스트 모드(`PADIEM_CHAT_CPYTHON_HOST=1`)와 **동시 사용 불가** — 크론 이전의 실제 차단 항목 |
| `docs/architecture/COM2_CHAT_SERVICE_BINDINGS_20261029.md` | 서비스 바인딩 8종 대체표, proof 계약(v1), Google OAuth 병행 호스트 절차, WSS·cron 원인 | 2026-10-29 | **손봄** — 그 뒤 파일 레인(HTTP 터널 + 티켓 시크릿)과 큐(HTTPS origin + 서비스 시크릿)가 실제로 붙어 대체표가 8종→10종이 됐다. B14는 `B14_UPSTREAM_MODE=https`로 이미 닫혔다 |
| `docs/architecture/COM2_CONTROL_PLANE_RPC_INGRESS_20261029.md` | identity/google-state 대상 `POST /internal/rpc/<method>` + v1 proof 입구 설계, allowlist 9+1, broker는 Stage 2-C로 이연 | 2026-10-29 | **그대로** — 대상 입구는 구현돼 있고 기본 꺼짐 상태다. 배포·비밀 배치가 남은 실행 항목 |
| `docs/architecture/COM2_BROKER_STAGE2C_DESIGN_20261029.md` | broker Stage 2-C design | 2026-10-29 | Valid design; #6162 already implements broker service and state. See BROKER_GAP_TABLE_20261031.md for remaining gaps. |
| `docs/architecture/COM2_MIGRATION_INVENTORY_20261025.md` | Worker 22개·워크플로 235개 전수 정적 목록, 서비스·D1·R2·KV·DO·Secrets Store 이름, "인증만 Cloudflare" 분류 | 2026-10-25 | **손봄** — 기준 main `ac24435`. 이후 큐·파일 레인·padiem-auth·스테이징 Worker가 추가돼 목록이 부분적으로 낡았다. 인증 분류는 10-31 결정(신원기관 이전, 로그인은 padiem-auth)으로 갱신 필요 |
| `docs/operations/CHAT_COM2_FRONT_RUNBOOK.md` · `CHAT_COM2_RUNBOOK.md` · `deploy/host-com2/chat/` | 앞단 구성, 설치(비기동)·health·백업·터널 꾸러미, systemd 유닛 5종, `check_config.py` | 2026-10-29 | **손봄** — 설치 꾸러미는 재사용 가능. `local_cron.py` 게이트 결함(위), 로그인 경로가 padiem-auth로 바뀐 점, 마이그레이션 079 반영 필요 |
| `docs/architecture/FILE_LANE_COM2_MIGRATION_20261026.md` · `docs/architecture/BINARY_ATTACHMENT_VIA_COM2_FILE_LANE_20261030.md` | 파일 레인 이전 설계와 Chat 연결(티켓·텍스트 읽기) | 2026-10-30 | **그대로** — 이미 가동. Chat 이전 시 `PADIEM_CHAT_FILE_LANE_ORIGIN`·티켓 시크릿을 com2 env로 옮기는 항목만 추가 |
| `docs/operations/STAGING_MINIMAL_20261030.md` · `PADIEM_AUTH_UPDATE_GATE_PLAN_20261029.md` | 최소 스테이징 격리안, padiem-auth 갱신·롤백 게이트 | 2026-10-30 / 10-29 | **그대로** — 스테이징 1단계의 입력으로 그대로 쓴다 |
| `docs/operations/COM2_PC_DISPATCH_QUEUE_CUTOVER_20261029.md` · `COM2_EXECUTOR_QUEUE_SWITCH_20261030.md` · `COM2_BOOT_RECOVERY_RUNBOOK.md` | 큐 전환·실행기 전환·부팅 복구 절차 | 2026-10-30 | **그대로** — 큐 lane은 이 계획의 선행 조건이며 이미 전환됐다 |

합계: **그대로 4 · 손봄 7 · 버림 1**(#6197의 "관찰 중 쓰기 동결 유지" 안).

## 2. 10-30 이후 바뀐 것 — 초안과 충돌하는 지점

| 변경 | 초안에 미치는 영향 |
| --- | --- |
| PC 큐가 컴2 정본(`PC_QUEUE_BACKEND=com2`, `PC_QUEUE_ORIGIN`) | dispatch/pairing/presence의 D1↔큐 split-brain 창은 닫혔다. Chat 이전은 "이미 큐를 쓰는 세 호출자" 전제로 다시 쓴다 |
| 파일 레인 가동(8788, Chat 연결 #6322, 사유 코드 #6338·#6344) | 첨부 원본은 Chat을 거치지 않는다. 이전 후에도 Chat이 파일 레인 origin·티켓 시크릿을 유지해야 하며, R2/로컬 객체 원복 범위에서 첨부 원본은 파일 레인 쪽 정본이다 |
| padiem-auth 공통 로그인(#6295·#6296·#6282·#6312·#6341) | 초안의 "새 세션 서명 비밀로 교체 → 전 사용자 재로그인"은 로그인 권위가 padiem-auth로 옮겨가는 경로와 겹친다. **인증은 이 계획에서 제외**하고, Chat 세션 쿠키는 padiem-auth가 발급한 주체를 받는 형태로 단계 분리한다 |
| 바인딩 기준선(`.github/binding_baselines/padiem-chat.json`, reviewed 2026-10-23, 82개 항목 = vars 41 + secret_text 15 + secrets_store 14 + service 7 + d1 1 + r2 1 + assets/browser/version_metadata 3) | 초안은 기준선 이전 상태를 인용한다. 5단계 정리 시 이 파일이 삭제 대상 목록의 유일한 기준이 된다 |
| 마이그레이션 078·079 추가(`078_project_files_doc_kind`, `079_b66_saved_quote_skill_kind`) | #6190의 076/077 리허설은 현재 스키마가 아니다. plan/load/verify를 079 기준으로 다시 리허설해야 한다 |
| 스테이징(#6305, 큐 8830) | 1단계의 대상 환경이 생겼다. 운영 D1·R2·B14·브로커를 연결하지 않는 조건 그대로 쓴다 |

## 3. 미완성 3개 — 현재 상태와 남은 작업량

### 3.1 broker RPC (PC 기기 세션·등록·읽기)

- **무엇**: `padiem-local-agent-broker-state` DO의 device HTTP·enrollment·session·read·command material RPC 30여 개를 컴2 단일 프로세스 + SQLite로 옮기는 Stage 2-C.
- **Correction**: #6162 already implements broker service, SQLite state, session, material and some differential tests. Queue-owned tables remain separate. See BROKER_GAP_TABLE_20261031.md for evidence and open gaps.
- **남은 작업량**: ① 서비스 골격 + RPC 봉투 ② 상태 표·마이그레이션 ③ 세션·자격증명 해시 검증기 이전 ④ material purge ⑤ CAS 경쟁 테스트 ⑥ 읽기 그림자 러너 ⑦ Stage B 전환·원복 리허설. **PR 3~4개 분량, 가장 큰 레인**.

### 3.2 WebSocket (커넥터 게이트웨이)

- **무엇**: `/api/claw/connector/gateway/session` 업그레이드가 `worker.py` fetch 선두에서 workerd `WebSocketPair`로 갈라지는 레인. uvicorn ASGI 앱에는 그 분기가 없다.
- **지금까지**: 원인 확정, 대체 순서 합의(① broker HTTPS RPC → ② starlette WS 라우트 + 기존 세션 로직 재사용 → ③ 실기기 페어링 검증). 대상 WSS 경로를 기존 Worker로 되돌리는 앞단 분기안은 설계 후보로만 남아 있고, `request.cf` TLS 메타데이터가 앞단 전달에서 유지되는지 미검증이다.
- **남은 작업량**: 3.1 선행 후 WS 라우트 + 양방향 검증 + 실기기 1대. **PR 2개 분량**(구현, 실기기 검증). 앞단 분기 채택 시 +1.

### 3.3 늦은 쓰기(late writes) — 동결 종료 증명

- **무엇**: 동결 후에도 쓰기를 수행하는 경로(GET 쓰기 4종: Google 콜백, LoveTree 시작, GitHub OAuth 시작·콜백 / cron / WebSocket / queue consumer / waitUntil / 외부 producer)와 진행 중 요청 종료를 증명하는 절차.
- **지금까지**: 위험 목록 확정, 10-29에 동결 GET 쓰기 사례 2개 발견, 두 번의 D1 스냅숏 비교(행 수·정렬 해시·`updated_at` 최대값) 방식 합의. **증명 도구·게이트 구현 0건**. isolate 로컬 카운터를 전역 증거로 쓰지 않는다는 원칙만 확정.
- **남은 작업량**: 쓰기 효과 기준 라우트 분류표(읽기/쓰기 GET 구분) → 동결 센티널 + 드레인 대기 + 스냅숏 2회 비교 도구 → 최종 export 전 증거 형식. **PR 2개 분량**.

## 4. 단계별 계획 (완료 기준 · 되돌리기 · 레인 작업)

### ① 컴2 Chat 본체를 스테이징 주소로 기동 + D1 사본 검증

- **완료 기준**: `chat-com2-staging` 주소에서 health 200, 가입·로그인(padiem-auth 스테이징 클라이언트)·대화 목록·mock 채팅 1회·파일 첨부 1회가 동작. 운영 D1 export 사본에 대해 `plan`이 `SCHEMA_MISMATCH`/`MISSING_IN_TARGET` 0, `load`→`verify` 불일치 0을 **079 스키마**로 통과. 인증된 화면은 padiem-auth 경유로 1계정만 확인.
- **되돌리기**: 스테이징 터널·서비스를 멈추고 폐기. 운영 경로 무변경.
- **레인 PR**: ①-1 스테이징 Chat 꾸러미(기존 `deploy/host-com2/chat`에 staging 프로파일·포트 8801 추가) ②-2 `local_cron` 게이트 결함 수정(호스트 모드에서 `PADIEM_LOCAL_DEV` 요구 제거, 명시 플래그로 대체) ③-3 D1 이전 도구를 079 기준으로 재리허설(로컬·CI, 프로덕션 D1 미접근) ④-4 병행 비교 하네스(`CPYTHON_STAGE2` §8 시나리오, S4는 broker 전까지 `NOT_MEASURED`) — **4개**.

### ② 미완성 3개

- **완료 기준**: broker RPC 차동 테스트 전부 통과(봉투 동일성·CAS 패자·만료 경계·purge·재생·스코프·동시성), 읽기 그림자 24시간 불일치 0. CPython에서 PC 페어링→목록→읽기→명령 왕복 1회 실기기 성공. 동결 도구가 쓰기 0을 증명하고 스냅숏 2회 비교를 자동화.
- **되돌리기**: 그림자 단계는 설정만 되돌리면 종료. Stage B 전환은 스냅숏 장부 → D1 재적재 → origin 복귀 순서.
- **레인 PR**: ②-1 broker 서비스 골격 + RPC 봉투 + SQLite 상태 ②-2 세션·자격증명 검증기 이전 + purge + 차동 테스트 ②-3 읽기 그림자 러너(100% 대조, 응답은 기존 DO) ②-4 CPython WebSocket 라우트 + 커넥터 세션 재사용 ②-5 실기기 페어링·왕복 검증(레인 아님, 검증 기록) ②-6 동결·드레인·스냅숏 2회 비교 도구 + 쓰기 효과 기준 라우트 분류 — **5개**(+검증 기록).

### ③ D1 전환 (쓰기 정지 창)

- **완료 기준**: 창 안에서 최종 export → `plan`/`load`/`verify(소스 포함)` 통과, 표·행 수·해시 일치, 소유 표(큐·broker·파일 레인) 미적재 확인. 객체 저장소(로컬 객체 + R2 + 파일 레인 원본) 참조 일관성 대조 통과. 창 종료 후 쓰기 재개 + 대표 시나리오 스모크.
- **되돌리기**: #6197의 (가) — 기준 스냅숏 대비 PK 변경분 핸드백 + D1 게이트 apply/verify + 객체 복원. 객체 복원 전 쓰기 재개 금지.
- **레인 PR**: ③-1 D1 핸드백 게이트(plan/apply/verify, 정확 SHA·확인 문자열·readonly 선행·쓰기 0 실패) ③-2 객체 원복 계획(로컬 객체·R2·파일 레인 원본 대조) ③-3 전환 런북 개정(079·큐·파일 레인 반영, 창 승인 형식) — **3개**.

### ④ 운영 진입을 컴2로

- **완료 기준**: `chat.padiem.net` 앞단이 컴2 Chat으로 GET/POST/SSE를 정상 전달, padiem-auth 로그인·세션 유지, 파일 첨부·B14 채팅 1회, 30분 관찰에서 1101/1102 0건·5xx 비율이 전환 전 동등 기준과 동등 이상. 폴백이 켜져 있으면 쓰기 효과 기준으로 fail-closed 분류(쓰기 GET은 폴백 금지).
- **되돌리기**: 도메인을 Worker로 복귀하고 ③의 핸드백 절차로 컴2 변경분을 D1에 반영한 뒤 쓰기 재개.
- **레인 PR**: ④-1 앞단 라우팅 구성(쓰기 효과 기준 폴백 분류 + 테스트) ④-2 전환 후 관찰·스모크 자동화 ④-3 스테이징에서 원복 리허설 1회 기록 — **3개**.

**④ 전환 방식 = 사용자 지정 도메인 이동 (이번 PR 정정)**: 운영 전환은 tunnel ingress를 바꾸는 방식이 아닙니다. `chat.padiem.net` Custom Domain을 `padiem-chat`(Python Worker)에서 `padiem-chat-front`로 **한 번 이동**하고, front가 서명한 뒤 `FRONT_ORIGIN=https://chat-com2.padiem.net`(tunnel → `127.0.0.1:8798`)으로 전달합니다. 근거: #6400 브랜치(`feat/chat-com2-edge-gate-261031`)의 `apps/padiem-chat-front/wrangler.toml`과 `docs/operations/CHAT_COM2_FRONT_RUNBOOK.md`.

- `deploy/host-com2/**`의 cloudflared 예시에는 `chat.padiem.net` hostname을 두지 않습니다. tunnel이 직접 받으면 front를 건너뛰어 서명 없는 요청이 컴2로 들어옵니다. `deploy/host-com2/chat/tests/test_ingress_public_hostname_guard.py`가 이 금지를 고정합니다.
- tunnel은 지금처럼 `chat-com2.padiem.net` → `127.0.0.1:8798` 하나입니다. 이 hostname·포트가 운영 유닛(`padiem-chat-com2.service`)과 같은지, #6400의 `FRONT_ORIGIN`과 같은지 시험이 대조합니다(#6400이 main에 없으면 skip 사유를 남기고 대기).
- `chat-com2.padiem.net`은 공개 hostname이라 front를 거치지 않고 직접 들어올 수 있습니다. 그 경로는 #6400 `EdgeProofMiddleware`가 막습니다: `GET /health`를 뺀 **모든 http·websocket 요청**이 서명을 요구하고, 검증기는 `GET /api/claw/connector/gateway/session` 외에는 통과시키지 않습니다(그 밖의 경로는 403, WSS는 close 1008).
- 전환·원복은 각각 1회입니다: 런북 §2(도메인 이동) / §3(재이동). 앞단 배포·도메인 이동은 저장소 PR로 실행되지 않습니다.
- 되돌리기: Custom Domain을 `padiem-chat`으로 재이동(1회)하고, 컴2에만 쓰인 데이터는 핸드백으로 D1에 반영한 뒤 쓰기 재개.

### ⑤ Cloudflare Chat Worker를 정적 파일·입구만 남기고 정리

- **완료 기준**: `padiem-chat` Worker에 남는 바인딩이 정적 assets·도메인·버전 메타데이터(및 봇 차단 설정)뿐. `B14_SERVICE`·`PADIEM_CHAT_DB`·`PADIEM_WORKSPACE_FILES`·identity/broker/STT/PDF/OAuth-state 서비스 바인딩·`PADIEM_*` 변수·시크릿이 기준선에서 제거되고, 기준선 파일이 새 상태로 리뷰 갱신. `scheduled()` 핸들러 제거 또는 비활성. R2는 컴2 백업 버킷만 남긴다.
- **되돌리기**: 정리 배포 직전 서빙 버전 ID를 기록해 두고 그 버전으로 롤백. D1은 삭제하지 않고 읽기 전용으로 보존(§#6197 (가)의 원복 경로).
- **레인 PR**: ⑤-1 정적·입구 전용 Worker 축소(바인딩·변수 정리 + 기준선 갱신) ⑤-2 `scheduled()`·크론 lane 제거와 COM2 타이머 활성 절차 ⑤-3 문서 종결(이 계획, 이전 인벤토리, 런북 상태 갱신) — **3개**.

**총 레인 PR 18개** (① 4 · ② 5 · ③ 3 · ④ 3 · ⑤ 3), 별도 검증 기록 2건.

## 5. 컴2 포트 배정

사용 중(변경 금지): `8788` 파일 레인, `8789` B14, `8790` lovetree-api, `8797` 큐, `8830` 스테이징 큐.

| 용도 | 포트 | 근거 |
| --- | --- | --- |
| Chat 운영(본체) | `8798` | 10-29 초안·설치 꾸러미·부팅 복구 프로브가 이미 이 포트를 쓴다 |
| Chat 스테이징 | `8801` | 1단계 대상. `8830` 스테이징 큐와 짝 |
| broker(Stage 2-C) | `8799` | 10-29 CTO 확정 |
| 신원기관 RPC 입구(컴2로 옮길 때) | `8802` | identity/google-state `POST /internal/rpc/<method>` 표면 |
| 앞단 프록시(운영 진입) | `8796` | 4단계에서 도메인을 받는 유일한 입구. 루프백 앱 앞에 둔다 |
| health·백업 타이머 | 포트 없음 | systemd timer |

규칙: 새 서비스는 위 표에 먼저 등록한 뒤 설치한다. 이미 점유된 포트를 협의 없이 재사용하지 않는다(`COM2_HOST_FACTS` 갱신 대상).

## 6. 크론 이전 대상 (현재 Cloudflare 기준)

| # | 현재 위치 | 무엇 | 컴2 대응 |
| --- | --- | --- | --- |
| 1 | `worker.py` `Default.scheduled()` → `run_scheduled_automation_source` | Claw 예약·자동화 tick(유일한 Worker scheduled 레인) | `python -m app.local_cron --once` + systemd timer. 지금은 `PADIEM_LOCAL_DEV` 요구와 identity/P01 미결로 `NOT_CONFIGURED`만 출력 — ①-2에서 게이트 수정, ②·③ 이후 실제 tick |
| 2 | `deploy/host-com2/chat/padiem-chat-com2-health.timer` | loopback health 확인 | 이미 컴2 전용(활성 여부는 설치 시 결정) |
| 3 | `deploy/host-com2/chat/padiem-chat-com2-backup.timer` | `VACUUM INTO` + 검증 + rotate | 동일, 7개 보관 |
| 4 | GitHub Actions schedule | Worker cron과 별개 | 이전 대상 아님 |

`wrangler.toml`에는 `[triggers]`/`crons` 선언이 없다(정적 인벤토리 §2의 "모든 cron 미선언"과 일치). 즉 5단계에서 제거할 Worker 크론은 위 1번 하나다.

## 7. 착수 순서 — 첫 3개 PR

1. **①-2 `local_cron` 게이트 결함 수정** — 컴2 호스트 모드에서 크론 진입이 구조적으로 불가능한 상태를 먼저 없앤다(가장 작고, 다른 단계의 전제).
2. **①-1 스테이징 Chat 꾸러미(포트 8801)** — 1단계 완료 기준의 실행 기반.
3. **③-1 D1 핸드백 게이트(plan/apply/verify) 설계·구현** — 되돌리기 수단이 없으면 ②③ 어느 것도 실행할 수 없다.

## 8. 이 문서가 주장하지 않는 것

- 어떤 설치·기동·전환·배포도 수행하지 않았다. 리허설 수치(170.89초, 80표 3,308행, 불일치 0)는 **10-29 초안의 기록**이며 현재 스키마·현재 데이터로 재측정한 값이 아니다.
- Broker, WSS and freeze proof are not claimed complete. Broker has existing code; its outstanding evidence is in BROKER_GAP_TABLE_20261031.md.
- Cloudflare 운영 계정의 실측(플랜·사용량·서빙 버전)을 새로 조회하지 않았다.
- 모델·공급자 선택은 이 문서가 정하지 않는다(`MODEL_CHANGE_OWNER_APPROVAL_POLICY`).
