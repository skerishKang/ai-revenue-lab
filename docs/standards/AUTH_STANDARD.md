# PADIEM 공통 인증 표준 — 설계 초안
상태: CTO 설계 승인 (2026-10-29). 구현·배포·도메인·콘솔 등록은 아직 없음. 기존 운영 경로는 유지한다.

## 1. 인증 경계
padiem-auth는 Cloudflare JS/TS Worker로 유일한 Google OAuth 로그인 및 공통 로그인 표 발급 권위다. Python Worker와 COM2에 공통 인증을 두지 않는다. Firebase·Neon 등 외부 인증을 쓰지 않는다. 기존 공통 계정 데이터와 사용자 연결은 이관·검증하며 별도 계정 정본으로 갈라지지 않는다.

## 2. 계정
검증한 Google issuer와 sub가 Google 계정의 유일한 식별 근거다. 이메일은 신원 병합 기준이 아니다. 다른 인증 방식은 기존 로그인 후 명시적 연결만 허용하며 이번 구현 범위 밖이다. 새 표의 sub는 Google sub에 연결된 기존 canonical 계정 ID이며 기존 canonical subject, Chat usr_, LoveTree workspace 소유자와의 매핑을 저장·검증한다. 기존 소유자 ID를 섣불리 바꾸지 않는다. 이관 대조(기존 계정·서비스별 연결·데이터 소유권·충돌·중복)와 중단/복구 절차가 선행 조건이다. 충돌은 자동 병합하지 않고 중단해 보고한다.

## 3. OAuth 및 허용 목록
Google 클라이언트는 padiem-danjion의 Padiem Production 하나. 설계상 확정 Google callback URI는 https://auth.padiem.net/oauth/google/callback 이다. 이는 새 서비스가 사용할 목표 계약값이며 도메인 소유·DNS·라우팅·가용성과 콘솔 등록 여부는 UNKNOWN: 사전 검증 및 CTO 운영 승인 전 콘솔 변경 금지. 기존 oauth.padiem.net은 다른 Google 연동에 쓰이는 경로로 이 주소로 대체하지 않는다. 기존 클라이언트/프로젝트도 운영 확인이 필요하다. 기존 리디렉션 URI를 전환 중 지우지 않는다.
padiem-auth가 state·nonce·PKCE S256을 생성/검증하고 Google ID token 서명·issuer·audience·expiration·nonce·sub를 검증한다. 돌아갈 서비스 callback은 product ID별 등록된 HTTPS URI와 정확히 일치해야 한다. next는 서비스 내부 상대 경로로 제한하고 외부 URL·우회 표기를 거부한다. OAuth 에러, state·nonce 위조/만료/재사용, open redirect를 시험한다.

## 4. 로그인 교환 및 세션
서비스는 OAuth나 Google 비밀을 보유하지 않는다. 서비스가 요청별 state와 PKCE verifier를 안전하게 보관한 뒤 padiem-auth에 보내고, 허용된 서비스 callback으로 일회용 코드를 돌려받는다. callback은 서비스 state를 검증하고 서버 측에서 코드와 verifier를 교환한다. 코드는 제품·정확한 callback·PKCE에 묶고 원자적으로 1회 소비한다. 코드 유효기간은 60초이며 동시 소비와 오류 시 재시작 정책을 시험한다. 교환은 HTTPS이며 공개 웹 클라이언트의 ID나 고정된 주소만으로 신뢰하지 않는다. 서비스별 서명키에 의한 비대칭 클라이언트 인증(private_key_jwt 등)과 키 회전을 설계하고 검증한다. 서비스 간 공유 HMAC 비밀을 사용하지 않는다.
padiem-auth는 ES256 비대칭 서명한 유효 15분의 서비스별 audience 로그인 표를 발급한다. 표에는 issuer, subject, audience, issued-at, expiry, session ID, key ID와 type을 고정하고 키 ID에 따른 공개키만 제공한다. 서비스는 JS 또는 Python 공통 라이브러리로 서명·알고리즘 허용 목록·발급자·audience·시각·토큰 유형을 요청마다 로컬 검사한다. 공개키 안전한 배포, 캐시 및 장애 시 정책, 키 사전 배포·회전·폐기, 키 손상 복구를 구현 전에 확정한다. unknown kid나 검증 오류는 거부한다.
세션 쿠키는 각 서비스 호스트 전용 Secure·HttpOnly·SameSite, 적절한 Path를 사용한다. refresh 자격은 서비스 측 서버 또는 CTO 승인한 host-only HttpOnly 쿠키 보관 및 서비스에 묶인 안전한 갱신·회전·재사용 탐지로 관리하고 브라우저·로그에 노출하지 않는다. 로그아웃·차단은 갱신 거절 및 로컬 쿠키 제거. 이미 발급된 표는 만료 전 로컬 검증상 유효하므로 즉시 전역 무효화는 보장하지 않는다. 최대 차단 지연은 15분이다. 갱신 장애 시 만료 후 재로그인이 필요하다. CSRF·세션 고정·코드 탈취·재사용 시험을 필수로 한다.

## 5. 새 서비스 연결 5단계
1. 제품 ID, callback URI와 공개 인증 키를 padiem-auth 허용 목록에 등록한다.
2. 서비스 로그인 버튼이 padiem-auth로 이동한다.
3. 서비스 서버가 1회 코드를 검증·교환한다.
4. 공통 검증 라이브러리(JS·Python)를 사용해 로그인 표를 로컬 검증한다.
5. 공통 계정 ID와 검증된 기존 소유자 매핑으로 데이터를 연결한다.
두 라이브러리와 상호운용 테스트는 향후 구현물이며 아직 제공되지 않았다.

## 6. 전환 및 되돌리기
순서: 러브트리 → Chat(Claw·견적 포함). 각 단계 신규 경로 기본 OFF, 기존 경로 기본 ON. 러브트리의 진행 중 기존 handoff는 만료까지 기존 방식 처리한다. Chat은 전환 기간에 기존 HMAC 세션과 새 서명 표 모두 허용하며 두 credential 유형을 명확히 분리하고 어느 방식의 실패도 다른 방식으로 우회하지 않는다. 기존 세션을 그대로 인정하되 새 표 발급·기존 계정 연결은 검증된 소유권만 사용한다. 스위치로 신규 진입을 끄고 기존 경로로 되돌린다. 이미 새 표로만 로그인한 사용자는 롤백 후 기존 로그인으로 다시 로그인해야 할 수 있다. 모든 기존 로그인 유지와 새/기존 계정의 동일성은 운영자료 대조 및 E2E 검증 전 UNKNOWN.
공개키 검증·OAuth·1회 코드·state·PKCE·쿠키·기존 세션 양립·계정/데이터 연속성·롤백·키 회전·차단 지연 및 CPU를 검증하고 CTO 승인 후 단계별 배포한다. 이메일·비밀번호 로그인 변경은 범위 밖이다.

## 7. 대표가 할 일
운영 승인과 위 도메인 검증이 끝나면 Google Cloud Console → padiem-danjion → Padiem Production OAuth 클라이언트 → 승인된 리디렉션 URI에 https://auth.padiem.net/oauth/google/callback 한 줄을 추가한다. 기존 URI는 유지한다. 아직 실행하지 않는다.

## 8. CTO 확정 세부값 (2026-10-29)
access는 ES256, 15분. refresh는 padiem-auth에서만 발급·관리하며 30일, 사용 시마다 교체한다. 이전 refresh의 재사용을 감지하면 해당 세션 전체를 폐기한다. refresh 수명 30일의 절대 만료/슬라이딩 정책은 구현 시 명시한다.
공개키 주소는 https://auth.padiem.net/.well-known/jwks.json 이며 kid를 포함한다. 서명 개인키는 padiem-auth Secret에만 둔다. 정상 키 교체 순서는 새 공개키 게시 → 캐시 전파 확인 → 새 키로 서명 전환 → 이전 표의 최대 15분 만료와 캐시 기간을 고려해 옛 공개키 제거. 키 유출 시 일반 교체와 다른 긴급 폐기 정책이 필요하다.
일회 코드와 refresh 회전은 원자적 저장소를 사용한다. Cloudflare 무료 플랜은 SQLite 기반 Durable Objects를 지원하므로 객체별 SQLite transaction을 우선 설계한다. D1 조건부 갱신도 가능하나 refresh 재사용 감지와 세션 전체 폐기를 한 트랜잭션으로 구현하고 동시 요청을 시험해야 한다. 무료 한도 초과 시 실패를 숨기지 않고 인증을 거부한다. 근거: https://developers.cloudflare.com/durable-objects/platform/pricing/ 및 https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/ .

## 9. 지연 이관과 차단 (CTO 2026-10-29)
Google sub 원문은 padiem-auth 저장소에 저장하지 않는다. padiem-auth 전용 Secret 키의 HMAC-SHA256 지문과 공통 canonical account ID를 JS Durable Object SQLite에 저장한다. 최초 검증 로그인에서만 기존 identity authority를 확인하고 이후 알려진 계정 로그인과 모든 refresh에는 그 권위를 호출하지 않는다. 키 손실·교체는 지문 연결을 깨뜨릴 수 있으므로 복구·교체 계획을 검증하기 전 수행하지 않는다.
일괄 이관은 보류: 기존 권위에는 복원 불가능한 HMAC 지문만 있다. 종전 격리 SQLite 도구는 참고 보관이고 운영에 사용하지 않는다. 신규 계정 정본은 기존 권위에서 padiem-auth로 옮기는 별도 단계로 진행하며 이중 쓰기를 피하고 역이관을 검증한다. 옛 권위 은퇴 전 활성 사용자 매핑 대조와 장기 미접속 사용자의 기존 계정 복구 방안을 확인한다. 활성 사용자 완료만으로 모든 계정의 연속성을 보증하지 않는다.
차단·탈퇴는 기존 권위가 전용 서비스 Secret으로 제한된 padiem-auth 관리 경로에 전달한다. padiem-auth는 계정 차단 표식을 기록하고 이후 refresh를 거절한다. Secret 없으면 관리 경로를 등록하지 않고 무단 요청을 거부한다. 발신·내구성 있는 재전송과 실패 감시가 연결되기 전에는 15분 안에 차단이 반영된다고 주장하지 않는다. 전용 서비스 비밀은 관리 호출 인증에만 쓰며 서비스 로그인 표의 서명·검증에 쓰지 않는다.

## 10. 1단계 범위 조정 (CTO 2026-10-29)
러브트리 1단계에서 전역 계정 차단·해제 관리, 옛 권위의 차단 발신 및 권위 은퇴는 범위 밖이다. 기존 초안은 미연결 보관한다. 1단계에서 전역 계정 차단 기능이나 15분 내 전파를 제공한다고 주장하지 않는다. 개별 로그아웃은 기존대로 해당 refresh 세션을 폐기한다.
동시 탭을 위해 직전 refresh 재사용은 30초 이내에 동일한 교체 결과를 반환한다. 단 하나의 이전 토큰에만 적용하고 그 다음 토큰이 이미 사용되었거나 30초가 지나면 재사용으로 해당 세션을 폐기한다. 응답은 padiem-auth 전용 Secret의 AES-GCM으로 저장하고, 서비스별 비대칭 인증을 요구한다. 유예 동안 이전 refresh를 가진 인증된 서비스는 같은 새 표를 받을 수 있다. Web Locks 지원 환경은 탭 간 갱신을 추가로 직렬화한다.
