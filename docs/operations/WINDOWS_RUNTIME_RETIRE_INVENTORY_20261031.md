# Windows 릴리스 런타임 은퇴 인벤토리 (2026-10-31)

```text
DOC_ROLE=WINDOWS_RUNTIME_RETIRE_INVENTORY
STATUS=조사 (코드 수정·호스트 조회·서비스 변경 없음)
TRACKER=#5115
BASE_MAIN=19c76ccad (#6405)
METHOD=저장소 전체 소스 검색 (코드·설정·스크립트·워크플로·문서·cloudflared ingress 예시)
```

대상은 컴2 이전이 끝난 뒤 내릴 Windows 릴리스 런타임 `18764`·`18717`·`18731`입니다. 이 문서는 **저장소가 아직 그 포트에 의존하는 지점**을 전부 적고, 각 지점에 컴2 대체가 있는지 판정합니다. 컴1·컴2의 실제 Windows 서비스·스케줄러는 조회하지 않았습니다.

## 1. 요약

| 포트 | 무엇인가 | 컴2 대체 포트 | 상태 |
| --- | --- | --- | --- |
| `18764` | Chat·Claw API (`b62-chat-api`, Windows PowerShell 릴리스, `runtime=b14`) | 스테이징 Chat `8801` / 운영 Chat `8798` | **대체 있음** |
| `18717` | B14 Router (Windows 릴리스, DPAPI secret-store 경유) | B14 `8789` (Linux, `b14.padiem.net`, CTO 결정 10-31) | **대체 있음** |
| `18731` | P01 Engine (Windows 릴리스, 정본 아님) | P01 `8811` (Linux/WSL systemd, CTO 결정 10-31) | **대체 있음** |

참조 파일 36건 중 실질 참조 31건, 나머지 5건은 잠금 파일의 해시 문자열 안에서 우연히 일치한 오탐입니다(§2.4).

세 포트 모두 **서비스 자체의 대체는 이미 정해졌고 꾸러미도 있다**는 뜻입니다. 은퇴를 막는 것은 포트가 아니라 그 포트를 가리키는 **운영 도구·스케줄러·터널 매핑**이며, §3·§4에 따로 모았습니다.

## 2. 포트별 참조

### 2.1 `18764` — Chat·Claw API

| 참조 파일 (위치) | 무엇을 하나 | 컴2 대체 | 상태 |
| --- | --- | --- | --- |
| `scripts/ops/com2_runtime.py:9,74` (`COMPONENTS`, `CONTRACTS["b62"]`) | Windows 감독기의 구성 요소 정의·health 계약 | `deploy/host-com2/chat/padiem-chat-com2.service`(8798)·`health.py`·`deploy/host-com2/restart-policy` | 대체 있음(도구 자체는 은퇴 대상) |
| `scripts/ops/com2_tunnel.py:36-37` (`PUBLIC_SERVICES` chat/claw) | 공개 ingress 렌더러의 chat·claw origin | `deploy/host-com2/chat/cloudflared-chat-com2.example.yml` → `8798` (hostname은 `chat-com2.padiem.net`) | **판단 필요** — 최종 공개 `chat.padiem.net` → COM2 매핑 예시는 저장소에 없음 |
| `scripts/ops/tests/test_com2_runtime.py:83,88` | 위 감독기 시험 | 같은 도구 시험 | 도구와 함께 은퇴 |
| `scripts/ops/tests/test_com2_tunnel.py:31,32,100` | 위 렌더러 시험 | 같은 도구 시험 | 도구와 함께 은퇴 |
| `apps/padiem-chat/tests/test_5115_cookie_secure.py:108,137` | 시험 픽스처 `base_url` (쿠키 Secure 판정) | 포트 무관 값(8798/8801로 바꿔도 시험 의미 동일) | 대체 있음(시험 유지) |
| `docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md` | 10-19 런타임 기록·감독기·터널 문서 | 이 문서가 은퇴 시점을 기록 | 문서 갱신 대상 |
| `docs/operations/COM2_B62_GENERATION_BINDING_20261019.md` | 18764 세대 바인딩 기록(`production_bound=false`) | — | 문서 갱신 대상 |
| `docs/operations/COM2_HOST_FACTS_20261026.md` | Windows/WSL 리스너 목록 | — | 문서 갱신 대상 |
| `docs/operations/CHAT_COM2_MIGRATION_PLAN_ADDENDUM_20261031.md` | 18764 ↔ 8798 관계 판정 | — | 문서 갱신 대상 |

### 2.2 `18717` — B14 Router

| 참조 파일 (위치) | 무엇을 하나 | 컴2 대체 | 상태 |
| --- | --- | --- | --- |
| `scripts/ops/com2_runtime.py:8,73` (`COMPONENTS`, `CONTRACTS["b14"]`) | Windows 감독기 구성 요소 정의·health 계약 | `deploy/host-com2/b14/padiem-b14.service.example`(`B14_PORT=8789`)·`health.py` | 대체 있음 |
| `scripts/ops/com2_tunnel.py:41` (`INTERNAL_SERVICES["b14"]`) | 공개 매핑 거부 목록 | `deploy/host-com2/b14/cloudflared-config.example.yml` → `b14.padiem.net` = `8789` | 대체 있음 |
| `scripts/ops/tests/test_com2_runtime.py:85,90`, `scripts/ops/tests/test_com2_tunnel.py:35` | 위 두 도구 시험 | 같은 도구 시험 | 도구와 함께 은퇴 |
| `docs/operations/B14_FREE_ROLLOUT_REPO_WIDE_STATUS_2026-10-18.md` | 18717 교체 보류 기록 | 10-31 CTO 결정(8789) | 문서 갱신 대상 |
| `docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md` | B14 18717 프로세스·계약 기록 | — | 문서 갱신 대상 |
| `docs/operations/COM2_HOST_FACTS_20261026.md`, `docs/operations/CHAT_COM2_MIGRATION_PLAN_ADDENDUM_20261031.md` | 리스너 목록·정본 판정 | — | 문서 갱신 대상 |

### 2.3 `18731` — P01 Engine

| 참조 파일 (위치) | 무엇을 하나 | 컴2 대체 | 상태 |
| --- | --- | --- | --- |
| `scripts/ops/com2_runtime.py:10,75` (`COMPONENTS`, `CONTRACTS["p01"]`) | Windows 감독기 구성 요소·health 계약 | `deploy/host-com2/p01/`(`8811` systemd, `check_config.py`, `health.py`) | 대체 있음 |
| `scripts/ops/com2_tunnel.py:42` | 공개 매핑 거부 목록 | `8811`은 공개 노출 없음(같은 규칙 유지) | 대체 있음 |
| `deploy/host-com2/p01/README.md`, `install.sh:6`, `start.sh:3` | “Windows 18731은 건드리지 않는다” 경계 문구 | 8811 정본 | 문구 갱신 대상 |
| `deploy/host-com2/p01/tests/test_p01_packaging.py:113,157` | 유닛에 18731이 박히지 않았는지 검사 | 같은 검사 유지 | 대체 있음 |
| `apps/padiem-ai-engine/tests/test_local_engine_asgi.py:98` | `P01_PORT=18731` 기본값 → 18731 바인딩 | `asgi.py`는 설정 포트를 따름(8811) | 대체 있음(값만 다름) |
| `apps/padiem-chat/tests/test_local_p01_engine_transport_261031.py:56,153-171,370-457` | 루프백 전송 시험의 예시 origin | 같은 시험이 8811에도 적용 | 대체 있음(값만 다름) |
| `docs/operations/CPYTHON_P01_ENGINE_TRANSPORT_20261031.md:76,80,98` | 18731을 임시 upstream으로 본 기록 | 10-31 결정(8811) | 문서 갱신 대상 |
| `scripts/ops/tests/test_com2_runtime.py:84,89` | 감독기 시험 | 같은 도구 시험 | 도구와 함께 은퇴 |
| `docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md`, `COM2_HOST_FACTS_20261026.md`, `CHAT_COM2_MIGRATION_PLAN_ADDENDUM_20261031.md` | 기록 문서 | — | 문서 갱신 대상 |

`apps/padiem-ai-engine/asgi.py`와 `app/local_runtime.py`는 현재 main에 있습니다(파일 존재 확인). 즉 8811이 실행할 CPython 진입점은 저장소에 있고, 10-31 보충 문서의 “진입점 없음” 항목은 해소됐습니다. 이 인벤토리에서 그 진입점의 조립 내용은 다시 검증하지 않았습니다.

### 2.4 오탐 (실제 포트 참조 아님)

| 파일 | 이유 |
| --- | --- |
| `reference/business-42-ai-development-control-tower-v1/evidence/source-hashes.json` | sha256 문자열 안의 부분 일치(`…799187641…`) |
| `apps/korean-ai-platform/uv.lock`, `apps/padiem-chat/uv.lock` | 패키지 해시 문자열 안의 부분 일치 |
| `apps/padiem-file-lane/uv.lock`, `deploy/host-com2/file-lane/requirements.txt` | 같은 이유 |

## 3. 서비스·스케줄러·터널 이름 참조

포트 번호 없이 이름으로만 이 런타임에 붙는 지점입니다. 은퇴 시 포트를 내리는 것과 별개로 정리해야 합니다.

| 이름 | 무엇인가 | 저장소 위치 | 컴2 대체 | 상태 |
| --- | --- | --- | --- | --- |
| `PADIEM-COM2-Runtime-Supervisor` | Windows 5분 감독 작업(`com2_runtime.py install-task`) | `scripts/ops/com2_runtime.py:790-855`, `COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md` | systemd 유닛 + `deploy/host-com2/restart-policy` + `boot-recovery/wsl` 자기점검 | 대체 있음 |
| `PADIEM-Local-AI-OnLogon`, `PADIEM-Local-AI-Watchdog` | 5분 시작 스크립트 묶음 `start-local-ai.ps1` 호출 | 문서 2건(`COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md`, `CHAT_COM2_MIGRATION_PLAN_ADDENDUM_20261031.md`)만. 스크립트는 저장소 밖 | 같은 systemd 유닛 묶음 | 대체 있음(폐기 절차 문서 필요) |
| `PADIEM-COM2-D1-R2-Sync` (매일 04:20) | D1·R2 일일 동기화 → 세대 사본 발행 | `scripts/ops/com2_periodic_sync.py`(Windows `schtasks`만 지원), `deploy/host-com2/offsite-backup/offsite.py`가 이 출력을 읽음, `deploy/host-com2/chat/STAGING.md:125` | **없음** — Linux 실행기·타이머가 저장소에 없고 계획 ⑤·⑥에도 없음 | **대체 없음** |
| `PADIEM-Mesh-Tunnel` | Oracle·MeshCentral 터널 (포트 무관) | `docs/operations/COM2_MESH_TUNNEL_RETIREMENT_PLAN_20261029.md` | 별도 계획(10-29) | 범위 밖 |
| cloudflared ingress (Windows 감독기용) | `chat`/`claw`→18764, `b14`→18717, `p01`→18731 | `scripts/ops/com2_tunnel.py` | `deploy/host-com2/chat/cloudflared-chat-com2.example.yml`(8798), `deploy/host-com2/b14/cloudflared-config.example.yml`(8789·8788), `deploy/host-com2/file-lane` | 부분 대체 — 공개 `chat.padiem.net` 최종 매핑 예시 없음 |

`18765`(10-19 세대 후보 검증용 임시 리스너)는 이미 종료됐고 코드·설정 참조가 없어 표에서 제외했습니다. `18554`·`18555`는 `COM2_HOST_FACTS_20261026.md`에 리스너로만 기록되며 이 세 서비스와 무관합니다.

## 4. “대체 없음” 목록과 계획 대조

| 항목 | 왜 대체가 없는가 | 계획 문서에 있는가 |
| --- | --- | --- |
| `PADIEM-COM2-D1-R2-Sync` (`com2_periodic_sync.py`) | Windows `schtasks` 등록만 지원하고, COM2 쪽 동등 실행기·타이머가 없다. 그런데 `deploy/host-com2/offsite-backup/offsite.py`와 `chat/STAGING.md`의 스테이징 DB 생성이 이 작업이 발행하는 세대 사본을 입력으로 쓴다 | **부분**: `CHAT_COM2_MIGRATION_RESUME_PLAN_20261031.md`는 “D1→COM2 일간 동기화(#5508)”가 있다고 전제하고 스테이징 DB를 그 출력에서 만든다고 적지만, 그 발행기를 COM2로 옮기는 레인 PR은 ①~⑤ 어디에도 없다. 추가 필요 |
| 공개 `chat.padiem.net` → COM2 Chat 최종 tunnel 매핑 | `deploy/host-com2/chat/cloudflared-chat-com2.example.yml`은 `chat-com2.padiem.net`(스테이징)만 정의한다. 운영 hostname을 8798로 옮기는 reviewed 예시·절차가 없다 | **부분**: 계획 §0 “Cloudflare에 남김 = cloudflared 터널 입구”, ⑤ “정적 파일·입구만 남기고 정리”에 방향은 있으나, ingress origin 전환 작업은 PR로 쪼개져 있지 않다. 추가 필요 |
| `PADIEM-Local-AI-OnLogon/Watchdog` 폐기 절차 | 기능 대체(systemd·restart-policy·boot-recovery)는 있으나, 기존 작업을 실제로 내리는 순서·확인 문구는 이 인벤토리에 없다 | 계획에 없음. 은퇴 실행 PR에서 작성 |

나머지 항목(`18764`/`18717`/`18731` 서비스, 감독기, B14·P01·파일 레인 ingress)은 컴2 대체가 저장소에 이미 있습니다.

## 5. 은퇴 전 확인 순서 (제안)

1. ③ D1 전환 창에서 18764에 새 쓰기가 있었는지 확인한다(상위 계획·보충 문서의 조건).
2. `PADIEM-COM2-D1-R2-Sync` 발행기를 COM2 타이머로 옮기고, `offsite-backup`·`STAGING.md`가 새 경로를 읽는지 확인한다.
3. 운영 `chat.padiem.net` ingress를 COM2 Chat(8798)로 돌리는 reviewed 설정을 만들고 offline `ingress validate`를 통과시킨다.
4. 그 뒤에 `PADIEM-Local-AI-OnLogon`·`PADIEM-Local-AI-Watchdog`·`PADIEM-COM2-Runtime-Supervisor`를 중지·해제하고 `18764`·`18717`·`18731` 리스너가 사라졌는지 확인한다.
5. `scripts/ops/com2_runtime.py`·`com2_tunnel.py`는 그 시점에 함께 은퇴 대상으로 표시한다(운영 참조가 끊긴 뒤).

## 6. 확인 상태

- 저장소 소스 검색만 수행했다. 컴1·컴2의 실제 Windows 서비스·예약 작업·리스너는 조회하지 않았다.
- 포트·작업 이름의 현재 가동 상태는 10-19~10-31 저장소 기록 기준이며, 이 문서는 그것을 재측정하지 않았다.
- 코드·설정·워크플로를 수정하지 않았다. 비밀 값은 읽지도 출력하지도 않았다.
- 이 문서의 참조 목록은 아래 기계 판독 블록과 같고, `.github/tests/test_windows_runtime_retire_inventory_261031.py`가 저장소를 다시 검색해 대조한다. 새 참조가 생기면 그 시험이 실패한다.

## 7. 기계 판독 블록

<!-- port-reference-inventory:start -->
PORTS=18764,18717,18731
SKIP=docs/operations/WINDOWS_RUNTIME_RETIRE_INVENTORY_20261031.md
SKIP=reference/business-42-ai-development-control-tower-v1/evidence/source-hashes.json
SKIP=apps/korean-ai-platform/uv.lock
SKIP=apps/padiem-chat/uv.lock
SKIP=apps/padiem-file-lane/uv.lock
SKIP=deploy/host-com2/file-lane/requirements.txt
REF 18764 = apps/bookai/public/content/bible-web/book-EZK-chapter-031.json, apps/bookai/public/content/bible-web/book-GEN-chapter-038.json, apps/bookai/public/content/bible-web/book-ISA-chapter-056.json, apps/bookai/public/content/bible-web/book-JDG-chapter-017.json, apps/bookai/public/content/bible-web/book-JHN-chapter-005.json, apps/bookai/public/content/iliad/book-21.json, apps/padiem-chat/tests/test_5115_cookie_secure.py, apps/storymemory/public/content/bible-web/book-EZK-chapter-031.json, apps/storymemory/public/content/bible-web/book-GEN-chapter-038.json, apps/storymemory/public/content/bible-web/book-ISA-chapter-056.json, apps/storymemory/public/content/bible-web/book-JDG-chapter-017.json, apps/storymemory/public/content/bible-web/book-JHN-chapter-005.json, apps/storymemory/public/content/iliad/book-21.json, docs/operations/CHAT_COM2_MIGRATION_PLAN_ADDENDUM_20261031.md, docs/operations/COM2_B62_GENERATION_BINDING_20261019.md, docs/operations/COM2_HOST_FACTS_20261026.md, docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md, docs/operations/WINDOWS_RUNTIME_RETIRE_RUNBOOK_20261031.md, scripts/ops/com2_runtime.py, scripts/ops/com2_tunnel.py, scripts/ops/tests/test_com2_runtime.py, scripts/ops/tests/test_com2_tunnel.py, scripts/ops/tests/test_windows_runtime_retire_contract.py, scripts/ops/windows_runtime_retire_check.ps1
REF 18717 = apps/bookai/public/content/bible-web/book-1CH-chapter-015.json, apps/bookai/public/content/bible-web/book-1KI-chapter-008.json, apps/bookai/public/content/bible-web/book-1SA-chapter-005.json, apps/bookai/public/content/bible-web/book-1TI-chapter-003.json, apps/bookai/public/content/bible-web/book-ISA-chapter-053.json, apps/bookai/public/content/iliad/book-09.json, apps/bookai/public/content/metamorphoses/book-14.json, apps/storymemory/public/content/bible-web/book-1CH-chapter-015.json, apps/storymemory/public/content/bible-web/book-1KI-chapter-008.json, apps/storymemory/public/content/bible-web/book-1SA-chapter-005.json, apps/storymemory/public/content/bible-web/book-1TI-chapter-003.json, apps/storymemory/public/content/bible-web/book-ISA-chapter-053.json, apps/storymemory/public/content/iliad/book-09.json, apps/storymemory/public/content/metamorphoses/book-14.json, docs/operations/B14_FREE_ROLLOUT_REPO_WIDE_STATUS_2026-10-18.md, docs/operations/CHAT_COM2_MIGRATION_PLAN_ADDENDUM_20261031.md, docs/operations/COM2_HOST_FACTS_20261026.md, docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md, docs/operations/WINDOWS_RUNTIME_RETIRE_RUNBOOK_20261031.md, scripts/ops/com2_runtime.py, scripts/ops/com2_tunnel.py, scripts/ops/tests/test_com2_runtime.py, scripts/ops/tests/test_com2_tunnel.py, scripts/ops/tests/test_windows_runtime_retire_contract.py, scripts/ops/windows_runtime_retire_check.ps1
REF 18731 = apps/bookai/public/content/bible-web/book-ACT-chapter-015.json, apps/bookai/public/content/bible-web/book-ISA-chapter-048.json, apps/bookai/public/content/bible-web/book-ISA-chapter-054.json, apps/bookai/public/content/bible-web/book-REV-chapter-002.json, apps/bookai/public/content/metamorphoses/book-10.json, apps/padiem-ai-engine/tests/test_local_engine_asgi.py, apps/padiem-chat/tests/test_local_p01_engine_transport_261031.py, apps/storymemory/public/content/bible-web/book-ACT-chapter-015.json, apps/storymemory/public/content/bible-web/book-ISA-chapter-048.json, apps/storymemory/public/content/bible-web/book-ISA-chapter-054.json, apps/storymemory/public/content/bible-web/book-REV-chapter-002.json, apps/storymemory/public/content/metamorphoses/book-10.json, deploy/host-com2/README.md, deploy/host-com2/deploy_from_main.sh, deploy/host-com2/p01/README.md, deploy/host-com2/p01/install.sh, deploy/host-com2/p01/start.sh, deploy/host-com2/p01/tests/test_p01_packaging.py, docs/operations/CHAT_COM2_MIGRATION_PLAN_ADDENDUM_20261031.md, docs/operations/COM2_HOST_FACTS_20261026.md, docs/operations/COM2_PRIMARY_RUNTIME_SUPERVISOR_AND_TUNNEL_20261019.md, docs/operations/CPYTHON_P01_ENGINE_TRANSPORT_20261031.md, docs/operations/WINDOWS_RUNTIME_RETIRE_RUNBOOK_20261031.md, docs/research/REUSE_CANDIDATES_20261101.md, scripts/ops/com2_runtime.py, scripts/ops/com2_tunnel.py, scripts/ops/tests/test_com2_runtime.py, scripts/ops/tests/test_com2_tunnel.py, scripts/ops/tests/test_windows_runtime_retire_contract.py, scripts/ops/windows_runtime_retire_check.ps1
<!-- port-reference-inventory:end -->
