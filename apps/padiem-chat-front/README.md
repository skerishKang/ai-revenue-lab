# padiem-chat-front 운영 설정

운영값 변경 후에는 `wrangler.toml`의 `[vars]`와 운영 변수 계약 시험을 함께 갱신한다. `wrangler.toml`에 선언된 `[vars]` 값은 `--keep-vars`로 보호되지 않으며 같은 이름의 운영값을 덮어쓴다.

`node --test test/worker.test.mjs`는 2026-11-01 확인한 비밀 제외 운영 변수 기준값과 설정 파일을 대조한다. 현재 운영값을 직접 대조할 때는 비밀을 제외한 변수만 JSON 객체로 `PADIEM_FRONT_LIVE_VARS_JSON`에 전달한다. 기준값 시험만 통과한 것은 이후 운영값의 변경 여부를 실시간으로 확인했다는 뜻이 아니다.

## 요청별 마감 변수 (2026-11-06)

| 변수 | 기본값 | 대상 |
| --- | --- | --- |
| `UPSTREAM_TIMEOUT_MS` | 8000 | 일반 쓰기(저장·설정·파일·계정 등) |
| `API_READ_TIMEOUT_MS` | 30000 | 일반 API 읽기, `/oauth/*` |
| `ORCHESTRATION_TIMEOUT_MS` | 60000 | 답변 생성 경로(버퍼형 JSON) |
| `APPS_AI_TIMEOUT_MS` | 65000 | `POST /api/apps/ai` |
| `AUTH_CALLBACK_TIMEOUT_MS` | 30000 | `GET /auth/shared/callback` |
| `AUTH_WRITE_TIMEOUT_MS` | 30000 | `/api/auth/*` 쓰기(로그인 등) — OAuth 교환·JWKS 검증·정체성 RPC 를 기다린다 |
| `TUS_UPLOAD_TIMEOUT_MS` | 180000 | tus 업로드(PATCH/POST) |
| `MCP_TIMEOUT_MS` | 180000 | `POST /api/mcp` |

`AUTH_WRITE_TIMEOUT_MS` 는 로그인 쓰기가 정체성 RPC 지연(`resolve_or_create_product_link`, 3일간 52건이 5초 초과)으로 잘리는 문제(#504, 쿠키 없는 504)를 막기 위해 신설했다. #6957 의 효과가 측정되면 이 값을 재조정한다.
