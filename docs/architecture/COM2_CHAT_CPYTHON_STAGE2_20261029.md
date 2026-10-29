# 컴2 이전 2단계 — Chat을 일반 CPython으로 로컬 기동 (2026-10-29)

```text
DOC_ROLE=COM2_CHAT_CPYTHON_STAGE2
STATUS=구현·검증 완료 (이 문서의 PR), 모델 실서비스 호출은 범위 밖
ISSUE=#5573
RELATED=PR #6115 (공용 SQLite D1 facade), PR #6125 (facade batch + 테스트 셈 수렴)
검증 PC: 이 저장소 워크트리, Windows / CPython 3.13.7 / uvicorn(프로젝트 의존)
```

## 1. 이 단계가 답하는 질문

Cloudflare Worker(workerd/Pyodide) 없이, 일반 CPython(uvicorn) 하나로
가입 → 로그인 → 대화 목록 → 일반 채팅 1회가 로컬에서 도는가? 도는 것과 안 도는
것의 경계는 어디인가? 컴2(일반 서버 호스트)로 옮길 때 무엇이 남는가?

## 2. 실행 방법

```bash
python tools/run_chat_local_cpython.py --port 8773            # mock 모델(기본)
# B14 실모델은 Owner 승인 엔드포인트가 환경에 있을 때만:
PADIEM_CHAT_B14_BASE_URL=... python tools/run_chat_local_cpython.py --runtime-mode b14
```

- 데이터는 `apps/padiem-chat/local_dev_data/` (Git 관리 밖): `chat.sqlite3`(WAL),
  `objects/`(디스크 R2), `session_secret`(부트마다 재사용 — 재시작해도 쿠키가 유지된다).
- 스크립트가 명시적 로컬 플래그 `PADIEM_LOCAL_DEV=1`과 루프백 기본값
  (`http://127.0.0.1:포트`, password 인증, Cookie Secure off, Web off)을 설정한다.
- 다른 PC의 편집형 설치에 import가 하이재킹되는 것을 막는 경로 고정은
  `lane_pytest.py`와 같은 방식이다.

## 3. 검증 결과 — 되는 것 / 안 되는 것

`/health`의 바인딩 플래그와 실제 HTTP 호출로 확인한 상태(2026-10-29, mock 런타임):

| 항목 | 상태 | 근거 |
|---|---|---|
| 서버 기동 (uvicorn + create_app) | 되는 것 | `GET /` 200 text/html, `/health` status ok |
| 가입 | 되는 것 | `POST /api/auth/password/register` 200 + 세션 쿠키 |
| 로그인(별도 클라이언트) | 되는 것 | `POST /api/auth/password/login` 200 |
| 세션 유지(재시작 포함) | 되는 것 | 서버 재기동 후 같은 쿠키로 `/api/auth/status` authenticated=true |
| 대화 목록 | 되는 것 | `/api/conversations` 빈 목록 → 대화 1건 표시 |
| 일반 채팅 1회 (mock) | 되는 것 | `/api/chat/stream` SSE: delta 1 + done, `chat_…` id 반환 |
| 한글 저장·읽기 | 되는 것 | UTF-8 body 저장 후 목록 제목·본문 왕복 확인 |
| 대화 상세·프로젝트 목록 | 되는 것 | `/api/conversations/{id}`, `/api/projects` 200 |
| 클로 실행 목록 | 되는 것(빈 상태) | `/api/claw/runs` ok, 엔진 어댑터 미구성 |
| Google OAuth | 안 되는 것(설계상 off) | methods.google=false — Control Plane 바인딩·외부 리다이렉트 필요, password 모드 권장 |
| 웹 검색/딥리서치/이미지 생성 | 안 되는 것 | `web_tools_ready=false` — 프로바이더 off가 mock 기본값 |
| 커넥터 WSS(Web Claw 연결) | 안 되는 것 | 워커 레인(worker.py fetch 선두) 전용, ASGI 라우트에 없음 |
| 크론 자동화·Telemetry 운영 익스포트 | 안 되는 것 | workerd 스케줄러/그라파나 채널 전용 |
| B14 실모델 | 미활성(가능) | `--runtime-mode b14` + Owner 승인 `PADIEM_CHAT_B14_BASE_URL` 필요 — 모델 결정은 Owner 소유라 이 실행에서는 켜지 않았다 |
| Drive/PDF 렌더러/보이스 STT 등 서비스 바인딩 8종 | 안 되는 것(fail-closed 유지) | 바인딩 부재 시 기존 503 경로 그대로 |

## 4. 구조 — 무엇을 재사용하고 무엇을 새로 두지 않았나

- **create_app 단일 권한**: `worker.py`와 이 엔트리포인트는 같은
  `app/app_factory.create_app`을 조립한다. 차이는 바인딩 공급원뿐이다
  (D1→`SqliteD1`, R2→`LocalDiskR2`). 두 번째 앱 팩토리·두 번째 스토어 계층은 없다.
- **facade 수렴**: D1 문장 표면은 #6115의 `app/d1_sqlite.py`가 공용 위치다.
  Chat이 쓰는 `batch()`를 추가(#6125)하고, 테스트에 흩어져 있던 같은 계통
  SQLite 셈 3개(3580/4072/lovetree 하네스)를 그 facade로 수렴했다.
  mesh-queue는 `run/first/all`만 쓰므로 동작 불변(전체 20/20 통과).
- **마이그레이션**: `migrations/` 001~076(75개)을 파일명 순서로 SQLite에
  적용하고 자체 장부(`padiem_local_migration_ledger`)에 기록한다. wrangler의
  `d1_migrations` 장부는 건드리지 않는다. 재실행 시 재적용 0건 확인.
- **R2 디스크 어댑터**: 스토어들이 실제로 호출하는 `put/get/delete`만 구현
  (`list/head`는 앱 코드에서 쓰이지 않음을 grep으로 확인). 객체 모양은
  `_read_r2_object_bytes` 계약(`.body`/`.size`/`arrayBuffer()`)을 따른다.
  키는 서버 생성 정규 id이고, 어댑터가 `..`/절대경로/드라이브 문자를 거부한다.
- **로컬 플래그의 경계** (`PADIEM_LOCAL_DEV`):
  - 값은 `1`/`true`만 참. 오타는 에러로 떨군다(조용한 무효화 금지).
  - 켜져도 http를 허용되는 호스트는 `127.0.0.1`/`localhost`/`::1`뿐 —
    `http://example.com`은 플래그가 있어도 거부된다.
  - `PADIEM_CHAT_PUBLIC_BASE_URL` 정규화(config.py)와 same-origin 가드의
    기대 오리진(same_origin_guard.py)이 **같은 규칙**을 공유한다.
  - Worker 바인딩 경로(`app/worker_config.py`)는 `Settings.from_values`를
    이 플래그 없이 호출하므로 프로덕션에서는 구조적으로 항상 False.
    검증 규칙 자체는 무변경(기본값에서 전과 동일 경로).
- **엔트리포인트 가드**: `app/local_cpython.build_app()`은 플래그 없이 호출되면
  `ConfigError`로 조립을 거부한다. Cloudflare 배포는 `worker.py`/`app.main`을
  그대로 쓰고, 이 모듈을 import하는 경로는 없다.

## 5. 전수 목록 요약 (세부 근거는 조사서 `.tmp/cpython-inventory.md`)

Workers/Pyodide 전용 요소와 로컬 처리:

| 요소 | 로컬 처리 |
|---|---|
| `worker.py`(WorkerEntrypoint·`import asgi/js`) | 미로드 — uvicorn이 ASGI 수행 |
| `httpx_compat` | CPython에서는 실제 httpx 자동 분기(무대체) |
| WebCrypto KDF | hashlib 경로 자동 선택(기존 코드) |
| D1 바인딩 | `SqliteD1`(facade) |
| R2 바인딩 | `LocalDiskR2` |
| 서비스 바인딩 8종·secrets_store·vars | 미구성 = 기존 fail-closed 그대로; env는 `Settings.from_env`가 동일 이름 수신 |
| WebSocket 커넥터 레인 | 로컬 미동작(범위 밖, fail-closed) |
| cron·waitUntil | 미사용(기본 off) |
| [assets] | `create_app`의 StaticFiles 마운트(기존) |
| KV | 미사용(없음) |

## 6. 컴2에서 띄울 때 필요한 것 (다음 단계)

1. **엔드포인트 소유권**: `PADIEM_CHAT_PUBLIC_BASE_URL`을 실제 호스트(TLS 종단)로 —
   컴2 호스트 모드는 `PADIEM_CHAT_CPYTHON_HOST=1`(https 공개 오리진 필수,
   `PADIEM_LOCAL_DEV`와 동시 설정 금지)로 켠다. 배포 꾸러미·런북은
   `deploy/host-com2/chat/`, `docs/operations/CHAT_COM2_RUNBOOK.md`.
2. **B14 연결**: Owner 승인 엔드포인트·바인딩. 모델/프로바이더 결정은 Owner 소유
   (`MODEL_CHANGE_OWNER_APPROVAL_POLICY`) — 이 문서가 선택을 대체하지 않는다.
3. **커넥터 WSS가 필요하면**: uvicorn 사이드카(별도 프로세스·별도 포트) 또는
   ASGI WebSocket 레인 설계. 현재 커넥터 게이트웨이는 worker.py 전용이다.
   broker/device 레인은 **Stage 2-C**(com2 이전 단계, `docs/architecture/
   COM2_CONTROL_PLANE_RPC_INGRESS_20261029.md` §5)로 옮긴다 — 그 전까지 fail-closed.
4. **마이그레이션 운영**: 장부가 wrangler가 아니라면 컴2 적용 절차(실행 시점·
   롤백)를 배포 정책 안에서 별도 결정.
5. **Telemetry/Cron**: 컴2에서 필요 확정 시 OS 스케줄러/별도 워커 프로세스로 분리.
6. **인증 운영**: password 모드는 로컬 검증용 동작 확인. Google/OAuth·canonical
   identity는 Control Plane 바인딩이 있는 호스트에서의 검증이 남았다.

## 7. 안전 경계

- 프로덕션 Cloudflare 경로(worker.py, wrangler.toml, 배포 스크립트) 무변경.
- 로컬 변경은 전부 명시적 플래그·별도 엔트리포인트 뒤.
- DB·세션 키·objects 폴더는 gitignore(`apps/padiem-chat/local_dev_data/`).
  session_secret은 로컬 생성 값이며 출력되지 않는다.
- 검증: 집중 pytest(test_local_cpython.py 10건 — 플래그 경계 포함 최종단),
  facade 회귀(test_d1_sqlite_batch.py 4건), mesh-queue 20건, 3476 가드 34건.
  이 문서는 위 표의 실제 HTTP 확인과 같은 세션의 결과다.

## 8. 병행 운영 비교 계획 — Cloudflare 경로 vs 컴2 경로

목적: 병행 운영 중 두 경로가 **같은 시나리오**에서 어떤 응답 시간·실패율을 보이는지
측정해, 3단계 전환 판단의 근거를 만든다. 이 절은 측정 **방법**이며 결과 수치가 아니다.

### 8.1 비교 쌍과 시나리오

| 시나리오 | 정의(두 경로 동일) | 요청 |
|---|---|---|
| S1 로그인 | 가입된 계정으로 `POST /api/auth/password/login`, 세션 쿠키 획득 | 응답 200 + 쿠키 |
| S2 대화 목록 | `GET /api/conversations` (계정당 대화 20건 시드 고정) | JSON 200 |
| S3 채팅 1턴 | `POST /api/chat/stream` 일반 텍스트 1문장, SSE 종료까지 | first-delta 시간 + total |
| S4 PC 읽기 | 연결된 PC의 파일 목록 1회 + 작은 텍스트 1개 읽기 | 200 + 본문 크기 일치 |

- 호스트: `chat.padiem.net`(Cloudflare) / `chat-com2.padiem.net`(컴2). 계정·데이터는
  경로별로 **분리 시드**한다(같은 이메일을 두 호스트에 만들지 않는다).
- 모델: 1차 비교는 mock(`PADIEM_CHAT_RUNTIME_MODE=mock`)로 고정 — 경로 자체의
  지연을 잰다. B14 실모델은 별도 시리즈로 라벨링해 기록하고 mock 수치와 섞지 않는다
  (모델 선택은 Owner 소유이므로 이 계획이 모델을 정하지 않는다).
- S4 전제: 컴2 PC 레인은 서비스 바인딩 표의 broker RPC가 열린 뒤에만 측정 가능하다.
  열리기 전에는 결과표에 `NOT_MEASURED reason=pc_lane_unbound`로 남긴다 — 0으로
  채우거나 생략하지 않는다.

### 8.2 실행 방법(동일 스크립트·동일 페이로드)

1. 계정 시드: 경로별 1개 계정, 대화 20건(제목·본문 고정), 첨부 없음.
2. 워밍업 5회(버리는 표본) 후, 시나리오마다 **50회 연속**, 하루 3개 창
   (09:00·13:00·21:00 KST)에 반복. 총 2 호스트 × 4 시나리오 × 150 요청.
3. 각 요청은 독립 httpx 클라이언트 세션, 리다이렉트 미추종, 타임아웃 30초(S3는
   120초). Origin/쿠키는 그 호스트 자신의 값만 사용한다(교차 사용 금지).
4. 기록(JSONL, 1줄 1요청): `ts, host, scenario, status, ttfb_ms, total_ms,
   bytes, error_code, run_id`. 토큰·쿠키·본문·이메일 원문은 기록하지 않는다.
5. 집계: 시나리오·호스트별 p50/p95/p99, 실패율(= 비2xx + 타임아웃 + 본문 검증 실패),
   오류 분류표(HTTP 코드/예외 클래스). S3는 first-delta와 total을 따로 낸다.
6. 판정 보조 지표: 5xx 비율, 429 비율, S1 성공률, S3 완주율(SSE `done` 수신 비율).
   수용/기각 기준은 이 단계에서 정하지 않는다 — CTO·Owner가 결과표를 보고 정한다.

### 8.3 편향 통제

- 두 경로를 **같은 시간 창 안에서 교차** 측정(호스트 A 25회 → B 25회 → A 25회 …)해
  시간대 효과를 상쇄한다.
- 측정 PC는 한 대, 유선, VPN 미사용. Cloudflare 경로는 엣지 위치 영향을 받으므로
  측정 PC 위치를 기록한다.
- 시드 데이터는 두 경로에서 동일 파일에서 생성(제목 길이·본문 크기 동일).
- 각 창의 첫 요청은 워밍업으로 제외. 실패 요청도 분모에 포함한다(빼지 않는다).

### 8.4 결과표 템플릿(3단계 계획 문서에 붙인다)

```text
scenario | host | n | ok | fail% | p50 | p95 | p99 | note
S1 login | cf   | 150 | … | … | … | … | … |
S1 login | com2 | 150 | … | … | … | … | … |
...
S4 pc-read | com2 | — | NOT_MEASURED reason=pc_lane_unbound
```

측정 산출물은 이 저장소의 보고 경로 정책(GITHUB_REPORT_HANDOFF_POLICY)에 따라
수치·분류만 남기고 원문 로그·쿠키는 남기지 않는다.

## 9. 3단계 — Chat 본체 데이터(D1 전체) → 컴2 SQLite

```text
도구=tools/chat_d1_migration.py (stdlib only) / 리허설=로컬·CI (프로덕션 D1 미접근)
실제 export·적재·전환=Qoder가 컴2에서, CTO 창 승인 후
```

### 9.1 도구

| 명령 | 하는 일 |
|---|---|
| `plan --source EXPORT --target CHAT_DB` | 읽기 전용 비교: 표별 `OK(건수)`/`EXCLUDED_OWNED`/`MISSING_IN_TARGET`/`SCHEMA_MISMATCH`, 원천 장부(`d1_migrations`) 열거. 쓰기 없음 |
| `load …` | **전 표를 한 트랜잭션으로** 교체 적재. 사전 검증(표 존재·열 일치·PK 존재)에서 하나라도 어긋나면 **아무것도 쓰지 않고** 거부. 성공 시 `chat_migration_runs/summary/snapshot`(행 해시) 기록, 건수·해시만 출력 |
| `verify --target [--source]` | 기록된 run과 현재 target을 재계산 대조(표별 `OK`/`DRIFT`), `--source` 지정 시 원천 export도 대조(`SOURCE_DRIFT`) — 적재 후 바뀐 행이 있으면 종료 코드 3 |
| `export --live --out` | 역방향: 컴2 DB의 **비소유 표**만 담은 핸드백용 읽기 전용 사본(+표별 건수·해시 요약) |

**소유 표(덮어쓰지 않음):** 큐가 진실인 `oracle_mesh_dispatch`·`mesh_device_presence`·`pc_pairing_codes`·`pc_device_links`, broker(Stage 2-C) `local_agent_*`, 그리고 장부/도구 표. D1 export에 남아 있어도 적재 대상이 아니다 — 이중 쓰기 금지.

### 9.2 리허설 결과 (로컬·CI, 마이그레이션 001–077로 만든 D1 대역 + 합성 300행)

| 리허설 | 결과 |
|---|---|
| export→plan→load→verify | PASS, 표 80·20,005행 기준 **load 0.61초(≈32.7k행/초), verify 0.22초** (로컬 SSD, 20k 메시지 벤치) |
| 적재 후 원천 한 행 변조 | `verify --source`가 `SOURCE_DRIFT`로 **거부(종료 3)** |
| target 열 불일치·PK 없는 표 | **쓰기 0으로 전체 거부** (bookkeeping 표조차 생성 안 함) |
| 큐 소유 표 | target의 `device.com2.queue` 행 보존, D1 쪽 행은 미적재 |
| 역방향 export | 비소유 표만, 표별 건수·해시 요약 포함 |

### 9.3 쓰기 중지 창

- 방법: 컴2 Chat에 **유지보수 모드**(센티널 파일) — 읽기(GET/HEAD)는 그대로, 변경 요청(POST/PUT/PATCH/DELETE)은 503 `maintenance` "잠시 점검 중". 플래그는 재시작 없이 켜고 끈다. (구현: `app/maintenance_mode.py`, env `PADIEM_CHAT_MAINTENANCE_SENTINEL` — 파일 존재 여부를 요청마다 검사)
- 순서: ① 쓰기 중지(센티널) ② 최종 D1 export(읽기 전용) ③ `plan` ④ `load` ⑤ `verify`(원천 포함) ⑥ 쓰기 재개 ⑦ 대표 시나리오 스모크.
- 소요 산정: `초 ≈ 행수 ÷ 20,000 × 2(안전계수) + verify(≈load의 1/3)`. 100만 행이면 약 2~3분(컴2 실측으로 대체). 실제 행 수는 Qoder의 export 보고서가 채운다.
- 원복: 창 실패 시 `export --live`로 컴2 변경분을 핸드백 → D1 재적재(Qoder 경로) → 장부 해시 대조 → 쓰기 재개. D1은 창 전까지 무변경이므로 최후 수단은 "컴2 적재 폐기 + 쓰기 재개"다.

### 9.4 Qoder 인계 절차

1. CTO 창 승인 후, 컴2에서 Chat 쓰기 중지(센티널 파일 배치) — 헬스/읽기 유지 확인.
2. 승인된 경로로 D1 export(읽기 전용 SQLite 파일) 생성. 계정·토큰·행 내용은 채팅/로그에 남기지 않는다.
3. `python tools/chat_d1_migration.py plan --source <export> --target /mnt/d/padiem/chat-com2/chat.sqlite3` → `SCHEMA_MISMATCH`/`MISSING_IN_TARGET` 0 확인.
4. `load` → 출력된 RUN·TABLES·ROWS·ELAPSED만 보고. 이어서 `verify --target … --source <export>`가 `PASS`인지 확인.
5. 쓰기 재개 → 대표 시나리오(로그인·목록·채팅 1회) 스모크. 실패 시 §9.3 원복 순서.
6. 보고: RUN id, 표/행 수, load·verify 초, refuse가 났다면 `CHAT_MIGRATION_REFUSED reason=…`(내용 없음).
