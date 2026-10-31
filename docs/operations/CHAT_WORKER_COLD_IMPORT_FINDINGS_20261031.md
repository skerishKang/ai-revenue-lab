# Chat Worker 콜드 import 경량화 — 측정 결과와 결론 (2026-10-31)

**상태: 기록용. 머지하지 않음.**

CTO 결정(2026-10-31): 브랜치 `perf/chat-worker-cold-import-261031`의 변경은 PR/머지 대상이 아니다. Cloudflare Python Worker는 배포 시 최상단(top-level) import를 실행해 메모리 스냅샷에 담고, 요청 시점에는 그 스냅샷을 로드한다. 최상단 import 비용은 요청 CPU에 계상되지 않으므로, import를 함수 안으로 옮기면 요청 시점 CPU가 오히려 늘어난다. 로컬 측정 효과도 노이즈 범위(−44 ms)였다.

결론 한 줄: **최상단 import는 스냅샷으로 처리되어 요청 CPU와 무관 — 지연 import 금지.**

---

## 1. 측정 대상 변경 (기록용)

| 파일 | 변경 |
| --- | --- |
| `packages/padiem-ai-core/padiem_ai_core/__init__.py` | 60여 개 서브모듈을 최상단에서 즉시 import하던 것을 `_LAZY_SUBMODULE_EXPORTS`(이름 → 서브모듈) 선언 + 모듈 `__getattr__` 기반 지연 해석으로 전환. `__all__` 내용·순서 유지, `__dir__` 추가 |
| `apps/padiem-chat/worker.py` | cron 레인(`claw_automation*`, `kagent.claw_automation*`), 앱 빌드 전용 컴포지션(로컬 접근/드라이브 업로드/텔레그램 전달/문서 파서/격리 파서), B14 응답 상한 상수를 각각 첫 사용 지점으로 이동 |
| `apps/padiem-chat/app/claw_local_task_result_composition.py` | 브로커 권한 상수를 함수 내부 import로 이동 |
| `packages/padiem-ai-core/tests/test_package_root_*.py`, `tests/test_package_lazy_exports.py`, `apps/padiem-chat/tests/test_worker_cold_import_contract.py` | 지연 표면 계약과 isolate import 경계 계약 테스트 |

측정 명령(로컬 Windows CPython, `-X importtime`):

```text
python -X importtime -c "import worker"   # isolate import 상당
python docs/evidence/chat-worker-cold-import-261031/measure_cold.py  # import + 앱 빌드 + 첫 요청
```

## 2. 상위 import 표 (self time, µs)

`worker` import 한 번을 각각 별도 프로세스에서 측정한 단일 실행 결과다. 두 실행은 Python 콜드 import 분산 때문에 모듈별 순위가 흔들린다.

### 2-1. 변경 전 (`importtime-before.txt`)

| # | 모듈 | self µs |
| --- | --- | --- |
| 1 | `kagent.ops_contracts` | 25,129 |
| 2 | `starlette.websockets` | 19,377 |
| 3 | `app.main` | 17,640 |
| 4 | `kagent.claw_automation` | 15,499 |
| 5 | `kagent.telegram_contracts` | 14,660 |
| 6 | `_socket` | 14,419 |
| 7 | `padiem_ai_core.document_normalization` | 14,397 |
| 8 | `padiem_control_plane.padiem_routing_profile_admin` | 13,200 |
| 9 | `_sqlite3` | 12,360 |
| 10 | `padiem_control_plane.contact_verification` | 11,220 |

### 2-2. 변경 후 (`importtime-after.txt`)

| # | 모듈 | self µs |
| --- | --- | --- |
| 1 | `app.b14_upstream_composition` | 41,145 |
| 2 | `padiem_ai_core.document_normalization` | 26,416 |
| 3 | `kagent.ops_contracts` | 23,129 |
| 4 | `kagent.p01_adapter` | 19,424 |
| 5 | `padiem_ai_core.pdf_markdown` | 18,252 |
| 6 | `padiem_ai_core.slack_capability` | 16,863 |
| 7 | `kagent.claw_memory` | 15,312 |
| 8 | `padiem_ai_core.connectors` | 14,593 |
| 9 | `padiem_ai_core.calendar_capability` | 14,340 |
| 10 | `padiem_ai_core.drive_capability` | 13,843 |

## 3. 전/후 측정 (cumulative import time, µs)

| 대상 | 변경 전 | 변경 후 | 증감 |
| --- | --- | --- | --- |
| `worker` (isolate import 전체) | 1,864,448 | 1,600,078 | **−264,370 (−14.2%)** |
| `padiem_ai_core` 패키지 루트 | 272,903 | 1,918 | −270,985 |
| `app.main` | 411,641 | 483,167 | +71,526 (실행 간 분산) |
| `app.app_factory` | 390,760 | 466,146 | +75,386 (실행 간 분산) |
| `kagent.claw_automation` | 73,870 | 59,859 | −14,011 (앱 팩토리 경유로 여전히 로드됨) |

추가 관찰:

- 지연 해석으로 줄어든 것은 `padiem_ai_core` 루트의 즉시 import다. `worker` 전체 감소분(−264 ms)의 대부분이 여기서 나온다.
- `worker.py`에서 첫 사용 지점으로 옮긴 cron/빌드 모듈 중 `kagent.claw_automation`은 `app.app_factory` 경유로 import 그래프에 남아 있다. isolate import에서 완전히 벗어난 것이 아니다.
- `app.main`/`app.app_factory` 누적 시간은 오히려 늘었는데, 같은 코드의 두 단일 실행을 비교한 값이라 방향을 해석할 수 없다.
- `measure_cold.py`(import → 앱 빌드 → 첫 요청 `/health`, `/api/auth/status`, `/api/files/capabilities`)의 종합 차이는 **−44 ms**로, 로컬 실행 분산 범위 안이다. 이 스크립트의 원본 실행 출력은 이 브랜치에 보존되어 있지 않아 수치만 기록한다.

## 4. 결론

1. **Cloudflare Python Worker에서 최상단 import 비용은 요청 CPU가 아니다.** 배포 시 top-level 실행 후 메모리 스냅샷을 만들고, 콜드 스타트는 그 스냅샷을 로드한다. import를 함수 본문으로 옮겨도 요청당 CPU가 줄지 않고, 오히려 그 함수가 처음 실행되는 요청이 import 비용을 부담한다.
2. 따라서 **지연 import를 성능 개선으로 취급하지 않는다.** 콜드 import 단축은 로컬 인터프리터 지표이며, 요청 지연으로 이어지지 않는다.
3. `padiem_ai_core` 루트 표면은 `__all__` 계약이 넓어 지연화 이득이 로컬에서만 관측됐다. 이 변경은 머지하지 않고 기록만 남긴다.
4. 다시 이 주제를 다룰 경우의 판단 기준은 isolate import 시간이 아니라 **실제 요청 CPU 시간과 스냅샷 크기**다.

참고 지연 import가 여전히 정당한 경우: 요청 경로에 절대 들어가지 않는 무거운 선택 의존성(선택 패키지 부재 시 오류 메시지 분기 등). 이번 브랜치의 변경은 그 범주가 아니다.

## 5. 참고 링크

- Cloudflare Changelog, *Python cold start improvements* (2025-12-08) — 배포 시 top-level 실행 후 메모리 스냅샷 캡처, 콜드 스타트에서 스냅샷 로드:
  <https://developers.cloudflare.com/changelog/post/2025-12-08-python-cold-start-improvements/>
- Cloudflare Blog, *Python Workers redux: fast cold starts, packages, and a uv-based workflow* (2025-12-08):
  <https://blog.cloudflare.com/python-workers-advancements>
- 보존 산출물: `docs/evidence/chat-worker-cold-import-261031/` (`measure_cold.py`, `importtime-*.txt` 원본 로그)
