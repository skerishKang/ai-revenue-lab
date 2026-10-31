# Chat 컴2 엔진·B14 설정 이름 목록 (2026-10-31)

컴2 스테이징 `.env`에 넣을 **이름만** 정리한 문서입니다. 값은 여기에 쓰지 않습니다.
`deploy/host-com2/chat/` 아래 파일은 컴2 레인 영역이므로 이 문서는 이름 목록만 제공합니다.

## 포트 (CTO 결정)

| 서비스 | 주소 |
| --- | --- |
| Chat 호스트 | `127.0.0.1:8798` |
| P01 엔진 정본 | `127.0.0.1:8811` |
| B14 정본 (Linux) | `127.0.0.1:8789` |
| 스테이징 Chat | `127.0.0.1:8801` |
| 스테이징 큐 | `127.0.0.1:8830` |
| 파일 레인 | `127.0.0.1:8788` |

## Chat 호스트 (.env)

| 이름 | 값의 형태 |
| --- | --- |
| `PADIEM_CHAT_CPYTHON_HOST` | `1` |
| `PADIEM_CHAT_PUBLIC_BASE_URL` | `https://…` (호스트 모드는 https 필수) |
| `PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN` | `http://127.0.0.1:8811` |
| `PADIEM_CHAT_LOCAL_P01_CALLER_ID` | 엔진 신원 레지스트리에 등록된 호출자 ID |
| `PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL` | 호출자 자격 증명 값 |
| `PADIEM_CHAT_ORCHESTRATION_ENABLED` | `true` (#6392가 이 스위치로 브리지를 조립) |
| `PADIEM_CHAT_LOCAL_DATA_DIR` | 선택. 미설정 시 앱 폴더의 `local_dev_data` |
| `PADIEM_CHAT_SESSION_SECRET` | 세션 서명 값 |
| `PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN` / `..._SECRET` | 크론 tick 게이트에 필요 |
| `PC_QUEUE_BACKEND` / `PC_QUEUE_ORIGIN` / `PC_QUEUE_SERVICE_SECRET_FILE` | 큐를 쓸 때만 |

## 엔진 호스트 (.env)

| 이름 | 값의 형태 |
| --- | --- |
| `PADIEM_ENGINE_CPYTHON_HOST` | `1` (`PADIEM_LOCAL_DEV`와 동시 설정 금지) |
| `P01_HOST` | `127.0.0.1` (루프백만 허용) |
| `P01_PORT` | `8811` |
| `PADIEM_ENGINE_LOCAL_B14_ORIGIN` | `http://127.0.0.1:8789` |
| `PADIEM_ENGINE_LOCAL_DB` | 멱등성 SQLite 파일 경로 |
| `PADIEM_ENGINE_CALLER_ID` | Chat이 보내는 호출자 ID와 같은 값 |
| `PADIEM_ENGINE_CALLER_SECRET` | Chat이 보내는 자격 증명과 같은 값 |
| `PADIEM_ENGINE_ALLOWED_APPS` | `padiem-chat` (쉼표 구분 다중 허용) |
| `PADIEM_B14_SERVICE_PROOF_SECRET` | 선택. B14 호출 증명 서명 값(32자 이상). 없으면 증명 헤더 없이 호출 |

`B14_UPSTREAM_MODE`·`B14_UPSTREAM_URL`은 서비스 바인딩 대신 HTTPS로 B14를 부를 때만 씁니다.
이번 호스트 구성은 기본값(`binding`)을 그대로 두고 `PADIEM_ENGINE_LOCAL_B14_ORIGIN`으로 바인딩 목적지만 바꿉니다.

## 확인 상태

2026-10-31 기준, 위 이름으로 엔진 호스트를 띄우면 Chat 턴은 `run_started → context_prepared → run_failed`로 끝나고
합성 B14는 호출되지 않습니다(`error_code=upstream_unavailable`). 엔진이 B14 외에 추가로 요구하는 바인딩은
아직 확인되지 않았습니다(추측 기재 금지). 확인 대상: `worker._engine_services_for_env`가 호스트에서 바인딩 분기를 타는지,
`CloudflareB14ServiceBindingTransport`가 `https://b14.internal` 검증을 통과하는지.
