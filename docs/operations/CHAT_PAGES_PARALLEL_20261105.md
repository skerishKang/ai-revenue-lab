# Chat을 pages.dev로 병행 서비스 (#6850)

대표 결정 2026-11-05 06:24: **`chat.padiem.net`은 그대로 두고 pages.dev 주소를
병행 운영한다.** 근거는 2026-11-05 실측 — 같은 파일을 `*.pages.dev`로 서빙하면
ICN에서 응답하고(콜드 0.081s / 웜 0.033s), `padiem.net` 존은 이 회선에서 LAX로
떨어져 첫 바이트가 0.78s다.

## 구성

| 항목 | 값 |
|---|---|
| Pages 프로젝트 | `padiem-chat` → `https://padiem-chat.pages.dev` |
| 실행 모드 | Pages advanced mode (`_worker.js`) |
| 프록시 코드 | `apps/padiem-chat-front/worker.mjs` **그대로** (복사해서 배포) |
| 정적 자산 | `apps/padiem-chat/static` (Pages가 직접 서빙) |
| origin | `https://chat-com2.padiem.net` (기존 터널, 변경 없음) |
| 시크릿 | `PADIEM_COM2_EDGE_SECRET` — 프런트 Worker와 **같은 값** 필요 |

`apps/padiem-chat-pages/build.mjs`가 `dist/`를 만들고, `_worker.js`는
`./_worker/worker.mjs`를 재내보내기만 한다. 프록시 구현은 한 벌뿐이다.

## 왜 시크릿이 같은 값이어야 하나

COM2는 edge proof를 강제한다(무서명 요청 403 확인). Pages에서 COM2로 가는
요청도 같은 HMAC 서명을 실어야 하므로, 프런트 Worker에 설정된
`PADIEM_COM2_EDGE_SECRET`과 동일한 값이 Pages 프로젝트에 있어야 한다.
Worker 시크릿은 다시 읽을 수 없으므로, 값을 가진 운영자가 한 번 설정한다.

## 로그인 (#6259 표준 유지)

* 인증 권위는 여전히 `padiem-auth` 하나다. Google에 등록된 리디렉션 URI는
  `https://auth.padiem.net/oauth/google/callback` 하나로 그대로다 — 서비스
  콜백은 Google이 아니라 `padiem-auth`가 검증한다.
* 쿠키는 호스트 단위이므로 주소마다 로그인이 따로다:
  * `chat.padiem.net` → `https://chat.padiem.net/auth/shared/callback`
  * `padiem-chat.pages.dev` → `https://padiem-chat.pages.dev/auth/shared/callback`
* `apps/padiem-auth/wrangler.toml`의 클라이언트 `b62` `redirect_uris`에 두 URI가
  모두 등록돼 있다.
* Chat은 `PADIEM_CHAT_PUBLIC_BASE_URLS`(쉼표 구분, https 루트만)에 있는
  호스트에 한해 **요청 호스트의 콜백**을 만든다(`x-forwarded-host` 기준).
  목록에 없는 호스트는 언제나 정본 콜백으로 떨어진다.
* 같은 이유로 same-origin 가드는 `public_base_url` + `public_base_urls`의
  정확한 오리진만 통과시킨다. 정본 `chat.padiem.net` 동작은 그대로다.

## 바뀌지 않는 것

* `chat.padiem.net` 라우트·프런트 Worker·터널·COM2는 손대지 않는다.
* MCP 커넥터(`https://chat.padiem.net/api/mcp`)와 그 OAuth 메타데이터는 그대로다.
  Pages 쪽도 같은 프록시 코드라 `/api/mcp`는 동일하게 COM2로 전달된다.
* 요금제 변경 없음. Pages 프로젝트와 배포만 추가된다.

## 배포 절차

1. `node apps/padiem-chat-pages/build.mjs`
2. 미리보기: `npx wrangler pages deploy dist --project-name padiem-chat --branch <preview-branch>`
3. 미리보기 주소에서 확인(정적 자산·`/health`·게스트 답변)
4. 운영: 같은 명령에 `--branch main` → `https://padiem-chat.pages.dev`

## 되돌리기

Pages 프로젝트를 삭제하거나 배포를 이전 것으로 되돌린다. `chat.padiem.net`은
건드리지 않았으므로 정본 경로에는 영향이 없다.
