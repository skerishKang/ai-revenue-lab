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
   https면 플래그 없이 동작하므로 `PADIEM_LOCAL_DEV`는 켜지 않는다.
2. **B14 연결**: Owner 승인 엔드포인트·바인딩. 모델/프로바이더 결정은 Owner 소유
   (`MODEL_CHANGE_OWNER_APPROVAL_POLICY`) — 이 문서가 선택을 대체하지 않는다.
3. **커넥터 WSS가 필요하면**: uvicorn 사이드카(별도 프로세스·별도 포트) 또는
   ASGI WebSocket 레인 설계. 현재 커넥터 게이트웨이는 worker.py 전용이다.
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
- 검증: 집중 pytest(test_local_cpython.py 6건 — 플래그 경계 포함 최종단),
  facade 회귀(test_d1_sqlite_batch.py 4건), mesh-queue 20건, 3476 가드 34건.
  이 문서는 위 표의 실제 HTTP 확인과 같은 세션의 결과다.
