# B66 회원·등급·가입 알림 관리자 — 운영 게이트 (2026-10-11)

## 구현 범위

- 관리자: 검증된 Google subject에서 유도된 서버 user ID + 운영에서만 지정하는 `B66_ADMIN_GOOGLE_EMAIL` 확인. password_credentials가 있는 동일 이메일 계정은 관리자 불가. 클라이언트 이메일 문자열로 승인 금지.
- 회원: 신규 가입 시 migration 037 trigger로 `pending, FREE` 및 가입 알림 outbox 생성. 기존 계정은 `approved, FREE` 로 초기화하여 CGI 운영을 유지한다.
- 관리자 API: 세션 기반 조회·승인·정지·티어 권한, compare-and-swap revision 및 D1 변경 감사. 클라이언트가 임의 tier/email/actor를 제시해도 권한 근거가 될 수 없다.
- 모델: 관리자는 B14 소유자 허용 및 실제 등록된 모델 중에서 FREE/PLUS/PRO/MAX 허용 목록을 선택. 새로운 B14 route, fallback, Max 경로를 임의로 만들지 않는다. 허용 모델 목록과 서버 정책을 승인한 뒤 Worker `B66_MEMBERSHIP_ENFORCED=enabled` 를 별도로 켜야 사용 제한이 효력을 가진다.
- 알림: 가입 이벤트가 D1 outbox에 남는다. 채널별 성공 영수증을 저장한다. 설정되지 않은 채널은 전송 불가·대기 상태를 정확히 표시한다. Telegram/Discord/Resend 이메일 수신 내용은 '새 가입' 안내만 포함하며 회원 이메일/문서/키는 포함하지 않는다. 네트워크 수신 후 영수증 저장 전 장애에서는 중복 전송이 가능(at-least-once).
- 웹: 관리자 Google 로그인 확인 시 프로필 메뉴에 관리자 페이지 버튼만 노출. 실제 API는 별도로 관리자 재검증하며, 비권한 사용자에게 회원 명단을 반환하지 않는다.

## 운영 적용 순서 (아직 실행하지 않음)

1. **PADIEM** Cloudflare 계정의 정확한 `PADIEM_CHAT_DB` 식별 및 백업. 다른 조직(CharlieKant)의 DB가 아닌지 확인. 스키마 `apps/padiem-chat/migrations/037_b66_admin_memberships.sql` 수동 1회 적용.
2. PADIEM Chat backend Worker 배포와 B66 Pages admin 페이지/프록시 배포. 두 앱의 exact-main SHA와 세션 쿠키 검증.
3. 관리자 본인 Google 계정으로 로그인 → admin/me true; 동일 이메일 password·다른 Google·비로그인은 false/403 확인. 운영 기존 CGI 회원은 approved 상태와 원래 모델 호출이 유지돼야 한다.
4. 관리자에서 모델 등급별 B14 등록 목록을 저장. Free/Plus/Pro/Max 정책 준비, 신규 합성 QA 가입 → pending → 승인 → 모델 허용/차단 테스트.
5. 그 후에만 Worker `B66_MEMBERSHIP_ENFORCED=enabled` 를 켜고 관리자가 모델 정책 active를 승인. 문제가 있으면 flag/active를 OFF로 원복.
6. 원하는 알림 채널만 서버 secret binding에 설정한다. Telegram: `B66_ALERT_TELEGRAM_BOT_TOKEN` + `B66_ALERT_TELEGRAM_CHAT_ID`; Discord: `B66_ALERT_DISCORD_WEBHOOK_URL`; 메일: `B66_ALERT_RESEND_API_KEY` + 인증된 `B66_ALERT_EMAIL_FROM` + `B66_ALERT_EMAIL_TO` (수신 주소를 반드시 명시적으로 지정). 채팅/GitHub에는 토큰을 남기지 않는다.
7. 합성 QA 가입으로 실제 알림 수신을 확인하고 관리자에서 발송 실패 이벤트 재전송 확인. 고객 실운영 데이터·권한은 오너 승인 전 수정하지 않는다.

## 검증

`python E:\b66-admin-direct-tests-261011.py`: SQLite D1/관리자 위조 차단/승인 이력/모델 정책/알림/HTTP 테스트.
`python E:\b66-admin-browser-qa-261011.py`: PC·모바일 관리자 모의 계정 시각 QA.
`node reference/business-66-padiem-quote-v1/tests/run-b66-contracts.cjs --tests`: B66 66개 계약 테스트.

B14 #2107의 전역 라우팅/공급업체/Max 활성화는 **별도 HOLD** 유지. 이 브랜치는 B66 전용 관리 경계만 변경한다.
