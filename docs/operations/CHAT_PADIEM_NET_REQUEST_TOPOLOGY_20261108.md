# chat.padiem.net 요청 경로 위상 — 어디를 고치면 어디를 배포하나 (2026-11-08)

```text
DOC_ROLE=CHAT_PADIEM_NET_REQUEST_TOPOLOGY
STATUS=코드·실측 확정 / 배포 절차 변경 없음 (사고 재발 방지용 대응표)
RELATED=docs/operations/CHAT_COM2_FRONT_RUNBOOK.md, docs/architecture/COM2_CHAT_SERVICE_BINDINGS_20261029.md
경계: 시크릿·토큰 값은 일절 없다. 이름과 "같은 값이어야 함 / 달라도 됨" 구분만 다룬다.
```

## 0. 한 줄 요약

chat.padiem.net은 Cloudflare Worker **padiem-chat-front**(`apps/padiem-chat-front/wrangler.toml:1-21`)이 받는다. 정적 자산은 front의 `[assets]`(=`../padiem-chat/static`)가 직접 서빙하고(`apps/padiem-chat-front/wrangler.toml:14-16`, `worker.mjs:257-262`), 나머지 전부는 `FRONT_ORIGIN`(`https://chat-com2.padiem.net`, 같은 wrangler.toml `[vars]`)으로 프록시한다. Python Worker `padiem-chat`은 서비스 바인딩 폴백(읽기 전용, `worker.mjs:221-223`)이고, 컴2 `deploy_from_main.sh`는 **API 코드만** 반영한다 — **정적 자산은 front 재배포에서만 바뀐다.** 컴2 배포만으로 화면 수정이 미반영된 #7100·#7102 사고와, D1→컴2 이관 링크의 봉인 키 불일치 #7118 사고가 모두 이 위상에서 나왔다.

## 1. 요청 흐름 (경로별 1줄)

공통: front는 요청을 바꾸지 않는 순수 프록시다 — 본문·상태코드·헤더(다중 Set-Cookie)·SSE·WebSocket을 그대로 통과시키고(`apps/padiem-chat-front/worker.mjs:4-12`), 전달 직전 에지 프루프 헤더 `x-padiem-edge-at/id/tls/proof`를 덧붙인다(`apps/padiem-chat-front/edge-proof.mjs:24-30` — HMAC v1 = `["v1", method, pathname, at, id, tls]`, 시크릿 `PADIEM_COM2_EDGE_SECRET`, TLSv1.2/1.3 요건, 쿼리 문자열 제외). 컴2는 `EdgeProofMiddleware`(`apps/padiem-chat/app/com2_edge_middleware.py:35`)에서 검증해 `EDGE_VERIFY path=… result=ok|reject` 한 줄을 남기고 거절은 403이다(`/health` 면제).

| 경로 | 처리 |
|---|---|
| 정적 파일(`/`, `/static/*`, 단일 세그먼트 js·css·이미지·폰트; GET/HEAD) | front `[assets]`가 직접 서빙 — 컴2 미경유(`worker.mjs:257-262`) |
| `/api/mcp`(POST) | 프록시 → 컴2(MCP 전용 타임아웃, `worker.mjs:284`) |
| `/api/orchestration`, `/api/orchestration/resume`, `/api/chat`, `/api/chat/stream`, `/api/claw/general`, `/api/claw/manual-intake/*`, `/api/b66/ai/chat`(POST) | 프록시 → 컴2, 답변 8경로 60s 전체 예산 + TTFB/총시간 로그(`worker.mjs:42-50, 283-329`) |
| `/api/connectors/*` | 프록시 → 컴2(일반 읽기/쓰기 예산; github status·callback 포함 — #7118의 503도 이 경로) |
| `/api/auth/*` 쓰기, `/auth/shared/callback` | 프록시 → 컴2(로그인 쓰기 30s 예산, `worker.mjs:269-271`) |
| Google OAuth 콜백 `/auth/google/callback` | 일반 프록시 → 컴2(redirect URI는 호스트 `PADIEM_CHAT_PUBLIC_BASE_URL` 파생, `apps/padiem-chat/app/auth.py:322-325`) |
| GitHub OAuth 콜백 `/api/connectors/github/callback` | 일반 프록시 → 컴2(redirect_uri는 호스트 공개 오리진 파생, `apps/padiem-chat/app/github_oauth_routes.py` start) |
| `/oauth/*`, `/.well-known/oauth-*` | 정적 분기에서 제외 + 읽기 예산으로 프록시(`worker.mjs:255-257`) |
| WebSocket 업그레이드 | 프록시가 그대로 통과(`worker.mjs:276`) |
| `/health` | 프록시 → 컴2(읽기 헬스 캐시 판정에 사용, `worker.mjs:274, 335-343`) |
| 컴2 무응답/타임아웃/5xx 시 | 읽기: `FALLBACK_MODE=service`면 Python Worker(`CHAT_WORKER` 바인딩), `static`이면 503 안내 / 쓰기: `COM2_CANONICAL=writes`면 **항상 503** — 정본 보호로 Python 폴백 금지(`worker.mjs:347-351`, 런북 §1) |

타임아웃은 헤더 수신까지만 적용되고 헤더 이후 스트림은 끊지 않는다(SSE/긴 응답 보호, 런북 §1).

## 2. "어디를 고치면 어디를 배포하나"

| 변경 파일 | 필요한 배포 | 근거 |
|---|---|---|
| `apps/padiem-chat/app/**`(API 로직) | ① 컴2 `deploy_from_main.sh <main-sha>`(주 담당) ② B62 Python Worker 폴백 정합성: `b62-production-code-deploy-gate` workflow_dispatch(`deploy_production_code`) | `deploy/host-com2/README.md:14,41`, `.github/workflows/b62-production-code-deploy-gate.yml:112-146` |
| `apps/padiem-chat/static/**`(화면·locale) | **padiem-chat-front 재배포**(`wrangler deploy`, apps/padiem-chat-front 체크아웃에서; 새 static이 포함된 SHA로) — 컴2 배포만으로는 미반영 | front `wrangler.toml:14-16`([assets]=`../padiem-chat/static`), 런북 §2-3 |
| `apps/padiem-chat-front/**`(프록시·폴백·타임아웃·env) | padiem-chat-front 재배포; Custom Domain 이동·`COM2_CANONICAL` 변경은 런북 절차(승인 창) | 런북 §2 |
| `packages/padiem-control-plane/google_oauth_worker.py` | `b54-google-oauth-state-production-redeploy`(workflow_dispatch + 확인 문구) | 해당 워크플로 |
| `packages/padiem-control-plane/identity_authority_worker.py` | `b54-control-plane-identity-production-redeploy` | 해당 워크플로 |
| `apps/padiem-ai-engine/**`(P01) | 컴2 P01 실행 레인(`deploy/host-com2/p01/install.sh --apply`) | `deploy/host-com2/p01/install.sh:89-97` |
| `deploy/host-com2/**`(유닛·checker·installer) | 컴2 실행 레인(installer) | `deploy/host-com2/README.md` |

주의: 컴2 체크아웃의 `apps/padiem-chat/static/`은 어떤 공개 경로로도 서빙되지 않는다(front `[assets]`가 유일한 정적 출처). Python Worker의 `[assets]`(`.b66-worker-src/static`)는 Custom Domain이 `padiem-chat`으로 되돌아간 원복 상태에서만 공개 표면이 된다.

## 3. 양쪽(Worker·컴2)에 걸리는 비밀·콜백 (이름만, 값 금지)

**같은 값이어야 하는 것** — 어긋나면 이관 데이터 해독 실패(#7118) 또는 검증 거부:

| 이름 | Worker 쪽 | 컴2 쪽 | 같아야 하는 이유 |
|---|---|---|---|
| `PADIEM_CHAT_SESSION_SECRET` | `apps/padiem-chat/wrangler.toml:287` `[secrets].required` | 컴2 `.env`(check_config 32자 검사) | GitHub 토큰 봉인 키 파생(#7118 원인), 세션 쿠키 서명 — 이관 데이터와 폴백 경로 모두 |
| `PADIEM_COM2_EDGE_SECRET` | padiem-chat-front Worker secret | `PADIEM_COM2_EDGE_SECRET_FILE` 파일 내용(0600, 32자 이상) | 에지 프루프 HMAC 검증(`edge-proof.mjs:12`, `local_cpython.py:776-784`) |
| `PADIEM_CHAT_CUSTOM_KEY_SECRET` | `[secrets].required`(wrangler.toml:287) | 컴2 `.env` | 커스텀 자격증명 봉인(이관 데이터) |
| `PADIEM_CHAT_GOOGLE_CLIENT_ID`/`_CLIENT_SECRET` | `_CLIENT_SECRET`은 `[secrets].required`(wrangler.toml:287) | 컴2 `.env.example:8-9` | 같은 Google OAuth 클라이언트를 양쪽이 쓰는 경우(Owner 결정) 값 동일 |
| `PADIEM_GITHUB_APP_CLIENT_SECRET` | `[secrets]`(wrangler.toml:147-149) | 컴2 `.env`(#7101) | 같은 GitHub App 재사용 시 동일(봉인 자체는 session_secret 파생) |

**달라도 되는 것(예)** — 단, 표의 파급 확인 후: `PADIEM_CHAT_PUBLIC_BASE_URL`(콜백 오리진을 결정 — Google/GitHub 콘솔 등록값과 일치해야 함), `FRONT_ORIGIN`·`FALLBACK_MODE`·`COM2_CANONICAL`(front 전용), `PC_QUEUE_SERVICE_SECRET`·B14/P01 계열(호스트 레인), `PADIEM_PUSH_VAPID_*`(발신 주체 쪽 값), `PADIEM_CHAT_QUOTA_SALT`(이관 해시 데이터 정합성 확인 전에는 동일 유지 권장).

**콜백(등록처):**

| 콜백 | 등록처 |
|---|---|
| Google: `https://chat.padiem.net/auth/google/callback`, `https://chat-com2.padiem.net/auth/google/callback` | Google Cloud 콘솔 승인된 리다이렉트 URI(호스트 `PADIEM_CHAT_PUBLIC_BASE_URL`이 가리키는 오리진 포함) |
| GitHub: `https://chat.padiem.net/api/connectors/github/callback` | GitHub App Authorization callback URL(front가 프록시하므로 공개 오리진 1개면 충분) |
| Google state edge: `https://oauth.padiem.net/v1/google/callback` | state Worker 배포 시 `GOOGLE_OAUTH_REDIRECT_URI`(워크플로가 주입) |

## 4. 오늘의 두 사고 매핑

- **#7100·#7102(화면 미반영)**: static 변경 → 컴2 배포(`deploy_from_main.sh`)로는 front `[assets]`가 갱신되지 않음 → §2의 2행. static PR 머지 후에는 front 재배포가 배포의 완결이다.
- **#7118(이관 링크 미사용)**: D1→컴2 이관 행의 봉인 키 불일치 → §3의 `PADIEM_CHAT_SESSION_SECRET` 동일값 요건. 이미 갈라진 봉인은 재연결(save upsert)로만 회수된다(#7118의 200 재연결 필요 응답).
