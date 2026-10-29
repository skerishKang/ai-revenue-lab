# padiem-auth 배포 준비 — 초안

현재 NOT READY. 승인 없이 배포·DNS·Secrets·콘솔 설정을 변경하지 않는다. 새로운 지문이 처음 등장할 때에만 같은 Cloudflare 계정의 기존 `padiem-control-plane-identity` 서비스 바인딩을 호출한다. 기존 지문 로그인·refresh는 자체 JS Durable Object에서만 처리하며 Chat Worker를 거치지 않는다. 운영 바인딩·실제 계정 연속성은 미검증이다. 기존 identity authority는 Python Worker/DO다.

필요한 값의 이름: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PADIEM_AUTH_ES256_PRIVATE_JWK`, `PADIEM_AUTH_IDENTITY_HMAC_KEY`, `PADIEM_AUTH_ADMIN_SECRET` (모두 해당 비밀은 Secret만), `PADIEM_AUTH_SIGNING_KID`, `PADIEM_AUTH_JWKS`, `PADIEM_AUTH_CLIENTS` (제품별 콜백 URI·공개 클라이언트 검증키). padiem-auth의 지문키는 계정 연결 정본이므로 재발급·소실 시 기존 데이터와 단절될 수 있다. 복구와 키 교체는 별도 설계·검증 전 금지. 원문은 읽거나 기록하지 않는다. 서명 공개키는 새 키 게시 → 서명 전환 → 15분 토큰 만료 및 캐시 전파 이후 옛 키 제거.

## 지연 이관과 옛 권위 은퇴
일괄 이관은 하지 않는다. 기존 권위에는 Google sub가 아닌 비가역 지문만 있으므로 기존 권위 표만으로 sub를 복원할 수 없다. `migrate_identity.py`는 옛 SHA-256 기반 격리 SQLite 대조 실험을 보관한 것으로, 현재 HMAC 지문과 호환되지 않으며 운영 경로에서 실행하지 않는다.
처음 로그인한 검증 sub에 대해 기존 권위가 돌려준 canonical ID를 새 HMAC 지문과 연결한다. 이후 동일 계정은 기존 권위를 읽지 않는다. 활성 사용자는 기존 사용자의 로그인 또는 유효 세션 기록과 새 매핑을 개인정보·지문 값 노출 없이 개수와 일치 여부로 대조한다. 은퇴 전 대조 도구와 실제 검증 경로는 미구현이다. 30일 refresh가 유효한 사용자만 대조해도 장기 미접속자가 나중에 복귀할 수 있으므로, 활성 사용자 완료만으로 전체 계정의 연속성을 보장하지 않는다. 모든 기존 Google 계정의 매핑 대조 또는 미이관 복귀자를 기존 ID로 복구하는 검증된 대안을 확보하기 전 옛 권위를 은퇴하지 않는다. 새 계정 생성 정본은 현재 기존 권위이고, 전환과 역이관·충돌 처리의 별도 검증 뒤에만 padiem-auth로 옮긴다.

## 차단 전파
내부 `/internal/account-block`은 전용 서비스 Secret으로 인증하며 account ID 이외 입력을 받지 않는다. 새 레지스트리에 없는 계정도 차단 표식을 남겨 나중에 가입하는 것을 막는다. 기존 identity authority가 이 경로를 부르는 발신과 실패 시 재시도·감사가 아직 미연결이므로 전역 15분 차단 보장을 주장할 수 없다. 발신·내구성 있는 재시도·누락 감시 및 통합 시험 전 전환 금지.

Cloudflare 계정은 Charliekant. 배포는 저장소의 정식 게이트 체계에 맞춘 새 Worker 전용 게이트와 exact SHA, 환경·바인딩 baseline, 승인 문구 및 사전 읽기 검사를 설계해야 한다. 게이트의 기존 재사용 가능성·계정의 Workers 및 Durable Objects 배포 권한, Zone에서 `auth.padiem.net` Custom Domain 연결 권한은 UNKNOWN. DNS·Custom Domain 배치 전 기존 호스트 충돌을 확인한다. 아무 명령도 실행하지 않는다.

대표는 실제 주소·계정 확인과 승인 뒤 Google Cloud `padiem-danjion`의 Padiem Production OAuth 클라이언트에 승인된 리디렉션 URI `https://auth.padiem.net/oauth/google/callback` 한 줄을 추가한다. 기존 URI는 유지한다.

러브트리 전환은 기본 OFF 스위치, 실계정 소유권 대조 및 롤백을 준비한다. CTO 승인 후 운영 tail에서 경로별 `cpuTime`, outcome/1101/1102/5xx, 지연 및 로그인 성공률을 관찰한다. 임계값·관찰 시간은 사전 합의하며 이상 시 옛 경로로 되돌린다. 현재 CPU는 미측정이다.
