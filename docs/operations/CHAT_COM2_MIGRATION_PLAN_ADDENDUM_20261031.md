# Chat COM2 이전 계획 보충 — Windows 릴리스 런타임 관계와 테스트 범위 (2026-10-31)

```text
DOC_ROLE=CHAT_COM2_MIGRATION_PLAN_ADDENDUM
STATUS=계획 보충 (실행·설치·전환·운영 조회 없음)
TRACKER=#5115 (2026-10-31 재개)
PARENT=docs/operations/CHAT_COM2_MIGRATION_RESUME_PLAN_20261031.md
```

이 문서는 상위 계획(#6354)을 대체하지 않는다. 상위 계획이 다루지 않은 두 가지를 보충한다: ① 컴2에 이미 올라가 있는 **Windows 릴리스 런타임**과 계획의 CPython Chat(8798)·broker(8799)의 관계, ② 전환 후 **테스트·기준선 범위**의 변동.

## 1. 컴2에 이미 있는 Windows 릴리스 런타임 (10-19 기록)

이 절의 모든 값은 저장소 문서 기록이며, 이 PR은 호스트에 접속해 현재 상태를 조회하지 않았다.

| 구성 | 포트(127.0.0.1) | 기동 수단 | 근거 |
| --- | --- | --- | --- |
| Chat·Claw API (`b62-chat-api`) | `18764` | `b62-chat-api/start-b62-release.ps1`, B14 런타임 연결 | `COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md` |
| B14 Router | `18717` | `infrastructure/start-b14-release.ps1`, DPAPI secret-store 경유 | 같은 문서 |
| P01 Engine | `18731` (Windows 릴리스, 정본 아님) | `p01-ai-engine/start-p01-local.ps1`, 내부 실행 경계 | 같은 문서 |
| P01 Engine 정본 | `8811` (Linux/WSL systemd) | `deploy/host-com2/p01/padiem-p01.service.example` | **2026-10-31 CTO 결정**, `CPYTHON_P01_ENGINE_TRANSPORT_20261031.md` |

- 설치 위치: `D:\PADIEM-Servers\b62-chat-api` 계열(런타임·백업·secret-store). 감독기·터널 렌더러는 `D:\padiem-cloudflare-com2\scripts\ops\com2_runtime.py`·`com2_tunnel.py`.
- 스케줄: `PADIEM-Local-AI-OnLogon`·`PADIEM-Local-AI-Watchdog`(5분), `PADIEM-COM2-D1-R2-Sync`(매일 04:20).
- Tunnel 매핑(렌더 기준): `chat`/`claw` → `127.0.0.1:18764`만 공개 후보, `b14`(18717)·`p01`(18731)은 내부 전용으로 공개 매핑 시 거부.
- `18764` `/health`는 `app=padiem-chat`, `runtime=b14`를 보고한다(2026-10-19 기록). 즉 **같은 제품 코드**다.
- 데이터: `D:\PADIEM-Servers\b62-chat-api\runtime\generation-store\current_generation.json`가 활성 산출물을 선택하며, 기록된 시드는 `d1_tables=57`, `production_bound=false`다(`COM2_B62_GENERATION_BINDING_20261019.md`).

## 2. 관계 판정 — 같은 제품, 다른 호스트, 정본은 아직 하나가 아니다

| 질문 | 판정 | 근거 |
| --- | --- | --- |
| 18764와 계획의 CPython Chat(8798)은 같은 것인가 | **아니다.** 같은 `padiem-chat` 코드를 서로 다른 호스트·런타임으로 띄운 두 인스턴스다. 18764는 Windows 네이티브 PowerShell 릴리스, 8798은 WSL2 Ubuntu systemd + `app.local_cpython`(호스트 모드) | `COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md`, `docs/architecture/COM2_CHAT_CPYTHON_STAGE2_20261029.md`, `deploy/host-com2/chat/` |
| 데이터 정본은 무엇인가 | **18764는 정본으로 선언된 적이 없다.** generation pointer가 고른 읽기 시드(57표, `production_bound=false`)를 쓰는 결합 런타임이다. 계획의 8798은 검토된 마이그레이션 장부(현재 001–079)와 `/mnt/d/padiem/chat-com2/chat.sqlite3`를 쓴다 | `COM2_B62_GENERATION_BINDING_20261019.md`, `apps/padiem-chat/migrations/` |
| 계획은 18764를 어떻게 다루어야 하는가 | ③ D1 전환(쓰기 정지 창)까지 **현행 유지**, 창에서 18764에 새 쓰기가 있는지 확인한 뒤 은퇴 판단. 8798과 18764가 동시에 쓰기 정본이 되는 상태를 만들지 않는다 | 상위 계획 §4-③, #6202 split-brain 표 |
| B14는 어느 쪽인가 | 후보가 **둘**이다: Windows `18717`(10-19 릴리스 라우터)과 Linux `8789`(`B14_COM2_RUNBOOK`의 `b14.padiem.net`). 계획의 방향(B14도 컴2)을 따르며, 정본은 **2026-10-31 CTO 결정으로 Linux `8789`(`b14.padiem.net`)**로 확정됐다(Windows `18717`은 정본 후보에서 제외) | `B14_COM2_RUNBOOK.md`, `COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md` |
| P01은 어느 쪽인가 | 후보가 **둘**이었다: Windows `18731`(10-25 릴리스)과 Linux 루프백(계획의 8798이 부를 upstream). **2026-10-31 CTO 결정으로 Linux(WSL) systemd `127.0.0.1:8811`이 정본**이다. B14 `8789`와 같은 근거다: COM2 운영 서비스가 이미 WSL/systemd에 있고, Windows 릴리스 프로세스는 로그온 세션·드라이브 마운트에 묶인다. Windows `18731`은 은퇴 판단 대상이며 공개 매핑 대상이 아니다 | `deploy/host-com2/p01/`, `CPYTHON_P01_ENGINE_TRANSPORT_20261031.md` |
| P01 미결 항목 | 호스트 쪽은 끝났다: 8798의 엔진 전송(루프백 HTTP, #6382)과 8811 꾸러미. 남은 것은 **엔진의 CPython ASGI 진입점이 이 저장소에 없다는 점**이다(Worker `worker.py`·Windows `start-p01-local.ps1`만 존재). 꾸러미는 `asgi.py`가 없으면 `p01_asgi_entry_missing`으로 거부하고 기동하지 않는다 | `deploy/host-com2/p01/README.md` |
| 메시(Oracle) | **이번 범위 밖.** 메시·브로커 상태는 별도 레인이며 이 계획의 ①②③④⑤ 어디에도 포함하지 않는다 | 상위 계획 §0 |

**결론 3줄**

1. 18764는 계획의 8798과 같은 제품의 **다른 호스트 인스턴스**이며, 데이터 정본이 아니라 generation pointer가 고른 시드를 쓰는 결합 런타임이다.
2. 전환 대상 정본 후보는 계획의 8798(검토된 001–079 장부)로 유지하고, 18764는 ③ 창에서 쓰기 발생 여부를 확인한 뒤 은퇴 판단한다.
3. B14 후보는 18717(Windows)과 8789(Linux)로 갈려 있었고, **2026-10-31 CTO 결정으로 Linux `8789`(`b14.padiem.net`)가 정본**이다. Windows `18717`은 은퇴 판단 대상이며 이 문서는 결정을 기록만 한다.
4. P01도 같은 날 **Linux(WSL) systemd 루프백 `8811`이 정본**으로 결정됐다. 8798→8811 호출은 #6382의 루프백 전송 설정 이름을 쓰고, 꾸러미는 `deploy/host-com2/p01/`이다. 설치·기동은 하지 않았다.

## 3. 테스트 범위 — 전환 후 은퇴 / 새로 필요

### 3.1 전환 후 필요 없어지는 것 (은퇴·축소 대상)

정확한 파일 목록은 ⑤-1 정리 PR에서 CI 인벤토리와 대조해 확정한다(이 문서는 범주와 근거만 고정한다).

| 범주 | 예 | 은퇴 조건 |
| --- | --- | --- |
| 바인딩 기준선 | `.github/binding_baselines/padiem-chat.json` (82개 항목 = vars 41 + secret_text 15 + secrets_store 14 + service 7 + d1·r2·assets·browser·version_metadata 5) | ⑤-1에서 assets·browser·version_metadata만 남기고 재리뷰 |
| Worker 배포·바인딩 계약 | `apps/padiem-chat/wrangler.toml` 및 connector-acceptance 변형의 변수·서비스·Secrets Store 선언, wrangler 기반 배포·드라이런 검사 | 정적·입구 전용 Worker로 축소된 배포가 검증된 뒤 |
| workerd/Pyodide 전용 계약 | `worker.py` Service Binding 전송체·`import asgi`/`js` 경로 검사, Pyodide CPU·콜드스타트 프로브, `test_3989_b62_worker_probe_parallel.py` 계열 | COM2 런타임 e2e가 같은 계약을 덮은 뒤 |
| D1 플랫폼 한도 계약 | D1 전용 상한·게이트 검사(예: 대화 검색 LIKE 바이트 한도 #6329, D1 마이그레이션 게이트) | COM2 SQLite 장부(001–079) 운영이 확정된 뒤. 검증 자체는 삭제가 아니라 COM2 계약으로 대체 |
| Worker 크론 | `scheduled()` 자동화 tick 관련 검사 | ⑤-2에서 COM2 타이머가 대체한 뒤 |

유지 대상: `same_origin_guard`·세션 가드·소유자 스코프·요청 텔레메트리처럼 **ASGI 앱 계약**인 검사는 런타임과 무관하므로 그대로 둔다.

### 3.2 COM2 런타임에 새로 필요한 것

| # | 테스트 | 덮는 위험 | 단계 |
| --- | --- | --- | --- |
| 1 | 스테이징 기동 스모크: `check_config.py` 1, loopback health 200, `CHAT_COM2_CONFIG_READY=1` | 호스트 모드 기동·설정 누락 | ① |
| 2 | 크론 진입 계약: 호스트 모드 허용·로컬 모드 유지·동시 설정 거부 (코드 PR #6356에서 선행 완료) | scheduled 레인 도달 불가 | ① |
| 3 | D1 사본 검증: `plan`에서 `SCHEMA_MISMATCH`/`MISSING_IN_TARGET` 0, `load`→`verify` 불일치 0, 소유 표 미적재, 079 스키마 기준 | 스키마 드리프트·이중 쓰기 | ①·③ |
| 4 | 주요 경로 e2e: padiem-auth 로그인 → `/api/auth/status` → 대화 목록 → `/api/chat/stream` 1턴 → 파일 티켓+텍스트 읽기 → Claw 실행 목록(fail-closed 표현 포함) | 전환 후 주 경로 회귀 | ①·④ |
| 5 | 쓰기 정지 창 도구: 센티널로 변경 요청만 503, 읽기 유지, 재개 | 창 중 데이터 변동 | ②·③ |
| 6 | 원복 리허설: 핸드백 plan/apply/verify + 객체 원복, 롤백도 차동 테스트 통과 | 되돌리기 실패 | ③·④ |
| 7 | 백업·복원: `VACUUM INTO` + integrity_check + 행 수 대조 후 rotate | 백업이 복원 불가 | ① |
| 8 | 호스트 모드 경계: https 공개 오리진 필수, `PADIEM_LOCAL_DEV` 동시 사용 금지 | loopback 허용이 호스트로 유출 | ① |

## 4. 이 문서가 주장하지 않는 것

- 컴2 호스트에 접속해 18764·18717·18731의 **현재** 가동·설정·데이터를 확인하지 않았다. §1의 값은 2026-10-19 저장소 기록이다.
- 18764와 8798 중 어느 쪽이 더 최신 데이터를 가졌는지 판정하지 않았다. ③ 창의 쓰기 확인 전에는 알 수 없다.
- B14 정본을 고르지 않는다. 2026-10-31 CTO 결정(Linux `8789`, `b14.padiem.net`)을 기록할 뿐이고, 8789의 현재 가동 상태는 확인하지 않았다.
- P01 정본도 같은 원칙이다. 2026-10-31 CTO 결정(Linux/WSL `8811`)을 기록하고 꾸러미를 추가했을 뿐, 8811 서비스는 설치·기동하지 않았고 엔진의 CPython ASGI 진입점은 아직 저장소에 없다.
- 메시(Oracle) 레인은 범위 밖이며 이 문서가 상태를 판단하지 않는다.
