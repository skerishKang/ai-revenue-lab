# 외부 알림·메일 채널 점검 기록 (2026-11-02)

범위: #6460 3번, #4389(공통 알림 Telegram·Discord·메일)·#4871(커넥터 권한) 잔여.
문서 톤: 코드와 실제 시험으로 확인한 것만 적는다. 값은 이름만, 비밀 값 없음.
PR-D·PR-T는 이미 #6594·#6595로 처리되어 이 문서 범위 밖.

## 1. 메일 (Resend)

### 코드 경로

| 발송 | 위치 | 호출 |
|---|---|---|
| 비밀번호 재설정 메일 | `apps/padiem-chat/app/password_reset_delivery.py` (`ResendEmailDelivery.send`) | `POST https://api.resend.com/emails` |
| B66 가입 알림 메일 | `apps/padiem-chat/app/b66_signup_notifications.py` (email 채널) | `POST https://api.resend.com/emails` |

두 경로 모두 `Authorization: Bearer <키>` 헤더 하나, JSON 본문
`{from, to:[...], subject, text}`. 재설정 메일 제목은
`[PADIEM] 비밀번호 재설정 안내`, 가입 알림 제목은 `[B66] 신규 회원가입 알림`.

### 환경변수 이름 (이름만 — 컴2/Cloudflare Worker Secrets 또는 Secrets Store 슬롯)

해석 순서는 `app/worker_config.py`의 `MAIL_API_KEY_BINDING_NAMES` /
`MAIL_FROM_BINDING_NAMES` — 첫 번째로 읽히는 쌍이 재설정·가입 알림 양쪽에 함께 쓰인다.

| 용도 | 이름 |
|---|---|
| API 키 1순위 | `B66_ALERT_RESEND_API_KEY` |
| API 키 2순위 | `PADIEM_CHAT_PASSWORD_RESET_RESEND_API_KEY` |
| API 키 3순위 | `PADIEM_RESEND_API_KEY` |
| 발신 주소 1순위 | `B66_ALERT_EMAIL_FROM` |
| 발신 주소 2순위 | `PADIEM_CHAT_PASSWORD_RESET_EMAIL_FROM` |
| 발신 주소 3순위 | `PADIEM_RESEND_EMAIL_FROM` |
| 가입 알림 수신 주소 (쉼표 최대 10개) | `B66_ALERT_EMAIL_TO` |

### 키가 없을 때 사용자에게 보이는 것

- 재설정 요청 라우트(`POST /api/auth/password/reset/request`,
  `app/auth_routes.py`의 `password_reset_request`): 전송 수단이 없으면
  **503 `password_reset_delivery_unavailable`**과 함께
  "비밀번호 찾기 메일을 현재 보낼 수 없습니다. 잠시 후 다시 시도해 주세요." —
  제공자 오류 원문·키·스택은 어디에도 노출되지 않고, 가짜 "발송됨" 응답도 없다
  (`tests/test_5441_password_reset.py`가 고정).
- B66 가입 알림: 키/수신 주소가 없으면 email 채널 자체가 등록되지 않고,
  알림 실패가 로그인 응답에 영향을 주지 않는다(`deliver_after_signup`이 예외를 삼킴).
- 이벤트는 outbox에 남아 채널이 생기면 재시도된다(`retry_pending`).

### 시험 (모의 — 실제 발송 없음, `httpx.MockTransport` 주입)

- 기존: `tests/test_5441_password_reset.py`(라우트 503·재설정 요청 1건),
  `tests/test_5441_password_reset_mail_credential.py`(Resend HTTP 계약·자격 해석 순서),
  `tests/test_b66_admin_membership.py`(3채널 영수증·중복 방지, 설정 없음=가짜 성공 없음).
- 신규 `tests/test_notify_channels_20261102.py`: Resend 요청 1건 형식(Bearer·본문 키 검증),
  제공자 401 → 실패 1건·예외 없음, 형식이 틀린 자격은 채널 미등록·호출 0건,
  email 채널 없으면 Resend 호출 없음, 알림기 붕괴가 로그인을 깨지 않음,
  시크릿이 페이로드에 복사되지 않음. **9건 전부 통과.**

## 2. Telegram · Discord 알림 (B66 가입/문의 알림 레인)

### 환경변수 이름 (이름만)

| 용도 | 이름 | 형식 제약 (코드가 검증) |
|---|---|---|
| Telegram 봇 토큰 | `B66_ALERT_TELEGRAM_BOT_TOKEN` | `<봇아이디>:<토큰>` (예: `123456:AA…`) |
| Telegram 채팅 ID | `B66_ALERT_TELEGRAM_CHAT_ID` | `-?[0-9]+` |
| Discord 웹훅 URL | `B66_ALERT_DISCORD_WEBHOOK_URL` | `https://discord.com/api/webhooks/<숫자>/<토큰>` |

### 발송 경로와 실패 처리

- 마이그레이션 037 큐(outbox) → `B66SignupNotifier.notify_one`이 채널별 1회 발송 →
  채널별 영수증 기록(중복 발송 없음) → 전 채널 처리 후 완료. 실패는 카운트만
  늘리고 예외를 밖으로 내보내지 않는다.
- Telegram: `POST https://api.telegram.org/bot<토큰>/sendMessage`
  `{chat_id, text, disable_web_page_preview:true}` — 응답 `ok:true`만 성공.
- Discord: 설정된 웹훅 URL로 `POST {content, allowed_mentions:{parse:[]}}`.
- 제공자 거부·네트워크 오류는 전부 "실패 1건"으로 흡수되고 오류 원문이
  사용자 응답·로그로 새지 않는다. 토큰이 페이로드에 복사되지 않는 것도 시험으로 고정.
- B66 문의(b66_member_inquiries)의 telegram/discord/email은 회신 **선호 채널 표시값**이며
  별도 발송 경로가 아니다.

### Claw 아티팩트 Telegram 전송 (#4389 잔여)

`app/claw_telegram_delivery_host_composition.py` — 봇 토큰·채팅 ID는 Worker 설정이
아니고, Control Plane SEND 권한 + 신뢰된 아웃바운드 바인딩이 생겨야 구성된다.
현재 배포는 fail-closed(구성 없음 → 라우트 거부). **컴2에 넣을 설정 이름 없음.**

## 3. 커넥터 실제 연결 체크리스트 (실연은 하지 않음 — 대표 작업 목록)

### GitHub App (Chat 안에서 연결)

- 코드: `app/github_oauth_routes.py` (`/api/connectors/github/start` →
  `github.com/login/oauth/authorize` → `/api/connectors/github/callback`).
  App ID `5321929`, Client ID는 코드에 고정.
- 대표가 할 일:
  1. GitHub App(5321929) 설정에서 **콜백 URL**이
     `https://<Chat 공개 주소>/api/connectors/github/callback`인지 확인.
  2. App의 **Client secret**을 발급/확인해 Worker 시크릿
     **`PADIEM_GITHUB_APP_CLIENT_SECRET`** 로 등록(코드가 읽는 이름, `worker.py`).
  3. Chat 설정의 연결 화면에서 GitHub 연결 시작(사용자-to-서버 OAuth) —
     권한 범위는 GitHub App 측 설정을 따른다(#4871의 WRITE 확장은 별도 이슈).
  4. 상태 확인: `/api/connectors/github/status` 200.

### Gmail / Drive (Control Plane 소유 — Chat은 상태만 읽음)

- 코드: `app/connector_workspace_truth.py` — Identity Authority가 워크스페이스를
  확인하면 Google OAuth 권위(B-0 `workspace_connector_state`)가 Gmail/Drive 사용
  가능 상태를 대답한다. Chat은 이 bounded 상태만 투영하고 OAuth를 직접 하지 않는다.
- 대표가 할 일:
  1. Control Plane 쪽에서 **Google 계정 연결(OAuth 동의)** — Gmail/Drive 스코프 동의.
  2. Chat Worker 바인딩 `GOOGLE_OAUTH_STATE_SERVICE`가 그 권위를 가리키는지 확인
     (없으면 커넥터 상태는 fail-closed).
  3. 확인: Chat `/api/connectors/status`에서 gmail/drive가 usable로 보이는지.

## 4. 컴2 (Cloudflare Worker)에 넣을 설정 이름 목록 — 값 없음

```
B66_ALERT_RESEND_API_KEY
PADIEM_CHAT_PASSWORD_RESET_RESEND_API_KEY
PADIEM_RESEND_API_KEY
B66_ALERT_EMAIL_FROM
PADIEM_CHAT_PASSWORD_RESET_EMAIL_FROM
PADIEM_RESEND_EMAIL_FROM
B66_ALERT_EMAIL_TO
B66_ALERT_TELEGRAM_BOT_TOKEN
B66_ALERT_TELEGRAM_CHAT_ID
B66_ALERT_DISCORD_WEBHOOK_URL
PADIEM_GITHUB_APP_CLIENT_SECRET
```

(메일 키·발신 주소 3쌍은 우선순위 목록 — 한 쌍만 있어도 재설정·가입 알림 모두 동작.)

## 5. 대표가 할 일 (순서)

1. **Resend**: 계정 발급 → 발신 도메인 인증 → API 키 발급.
2. 키·발신 주소를 위 표의 이름으로 Cloudflare Worker 시크릿 등록(1쌍 이상).
3. **Telegram**: 봇 생성 → 토큰·채팅 ID 발급 → 등록. **Discord**: 웹훅 발급 → 등록.
4. 확인: 비밀번호 찾기 1건 실제 수신 + B66 가입 알림 1건 수신(채널별).
5. **GitHub App**: 콜백 URL 확인 → client secret 등록 → Chat에서 연결 1회.
6. **Gmail/Drive**: Control Plane에서 Google 연결(OAuth 동의) → Chat 커넥터 상태 확인.
7. Telegram 아티팩트 전송(#4389 잔여)은 Control Plane SEND 권한 이슈가 먼저다 —
   이 문서의 Worker 설정과 무관.
