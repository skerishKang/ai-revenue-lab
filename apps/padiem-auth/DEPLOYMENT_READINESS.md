# padiem-auth 배포 준비 — 초안

현재 NOT READY. 승인 없이 배포·DNS·Secrets·콘솔 설정을 변경하지 않는다. 새로운 지문이 처음 등장할 때에만 같은 Cloudflare 계정의 기존 `padiem-control-plane-identity` 서비스 바인딩을 호출한다. 기존 지문 로그인·refresh는 자체 JS Durable Object에서만 처리하며 Chat Worker를 거치지 않는다. 운영 바인딩·실제 계정 연속성은 미검증이다. 기존 identity authority는 Python Worker/DO다.

필요한 이름: padiem-auth Secret `GOOGLE_CLIENT_SECRET`, `PADIEM_AUTH_ES256_PRIVATE_JWK`, `PADIEM_AUTH_IDENTITY_HMAC_KEY`, `PADIEM_AUTH_REFRESH_ENCRYPTION_KEY`; 설정 `GOOGLE_CLIENT_ID`, `PADIEM_AUTH_SIGNING_KID`, `PADIEM_AUTH_JWKS`, `PADIEM_AUTH_CLIENTS` (제품별 콜백 URI·공개 클라이언트 검증키). 러브트리 Pages Secret `LOVETREE_AUTH_STATE_KEY`, `LOVETREE_AUTH_CLIENT_PRIVATE_JWK`; 설정 `LOVETREE_AUTH_CLIENT_KID`, `LOVETREE_SHARED_AUTH_ENABLED` (기본 OFF). COM2 러브트리에도 `LOVETREE_SHARED_AUTH_ENABLED` 기본 OFF가 필요하다. 원문은 읽거나 기록하지 않는다. 지문키의 복구와 키 교체는 별도 검증 전 금지. 서명 공개키는 새 키 게시 → 서명 전환 → 15분 표 만료 및 캐시 전파 이후 옛 키 제거.

## 지연 이관과 옛 권위 은퇴
일괄 이관은 하지 않는다. 기존 권위에는 Google sub가 아닌 비가역 지문만 있으므로 기존 권위 표만으로 sub를 복원할 수 없다. `migrate_identity.py`는 옛 SHA-256 기반 격리 SQLite 대조 실험을 보관한 것으로, 현재 HMAC 지문과 호환되지 않으며 운영 경로에서 실행하지 않는다.
처음 로그인한 검증 sub에 대해 기존 권위가 돌려준 canonical ID를 새 HMAC 지문과 연결한다. 이후 동일 계정은 기존 권위를 읽지 않는다. 활성 사용자는 기존 사용자의 로그인 또는 유효 세션 기록과 새 매핑을 개인정보·지문 값 노출 없이 개수와 일치 여부로 대조한다. 은퇴 전 대조 도구와 실제 검증 경로는 미구현이다. 30일 refresh가 유효한 사용자만 대조해도 장기 미접속자가 나중에 복귀할 수 있으므로, 활성 사용자 완료만으로 전체 계정의 연속성을 보장하지 않는다. 모든 기존 Google 계정의 매핑 대조 또는 미이관 복귀자를 기존 ID로 복구하는 검증된 대안을 확보하기 전 옛 권위를 은퇴하지 않는다. 새 계정 생성 정본은 현재 기존 권위이고, 전환과 역이관·충돌 처리의 별도 검증 뒤에만 padiem-auth로 옮긴다.

## 1단계 범위 밖
계정 차단·해제 관리 기능, 옛 권위 발신과 은퇴는 CTO 결정으로 이번 단계에서 구현하지 않는다. 기존 차단·발신 초안은 보관하며 운영에서 켜지 않는다. 전역 차단·해제는 1단계에서 제공한다고 주장하지 않는다.

## 1단계 켜기 점검표
- [ ] 정확한 SHA에서 테스트와 CI 확인; 별도 Worker에 대한 기존 배포 게이트 재사용 가능 여부는 UNKNOWN. 기존 정식 배포 체계와 동등한 검증·승인 게이트 준비 후 CTO 승인으로 실행한다.
- [ ] Charliekant 계정과 `padiem.net` 존의 Workers 배포·Custom Domain 연결 권한 및 `auth.padiem.net` 기존 충돌 확인. 확인 전 상태 UNKNOWN.
- [ ] 새 Worker의 Durable Object·기존 identity authority 서비스 바인딩 및 위 Secret 이름과 공개키 설정을 승인된 절차로 준비. 값은 보고하지 않는다.
- [ ] `PADIEM_AUTH_CLIENTS`에 제품 ID `lovetree-4-0`와 서비스 콜백 `https://lovetree-4-0.pages.dev/auth/callback`, 서비스의 공개 인증키를 정확히 등록. 이 주소가 실제 운영 앞단인지 DNS·서비스 담당자가 사전 확인한다.
- [ ] 대표가 Google Cloud `padiem-danjion`의 Padiem Production OAuth 클라이언트에 `https://auth.padiem.net/oauth/google/callback` 한 줄 추가. 다른 URI는 유지한다.
- [ ] 새 경로 OFF로 먼저 배포하고 합성 검증, 기존 사용자 공통 ID·작업 공간 일치 및 로그인·갱신·로그아웃 확인. 별도 탭과 Web Locks 미지원 환경을 시험한다.
- [ ] 켤 때 padiem-auth 경로별 `cpuTime`, outcome/1101/1102/5xx, 지연 및 로그인·갱신 성공률을 tail로 확인한다. 문제가 생기면 Pages와 COM2의 `LOVETREE_SHARED_AUTH_ENABLED`를 OFF로 되돌리고 기존 로그인으로 확인한다. 새 경로만 사용하던 사용자는 재로그인이 필요할 수 있다.

갱신은 이전 refresh의 동시 재요청에 30초 유예를 둔다. 짧은 지연이나 응답 유실에서 동일한 다음 표를 반환하기 위한 시간이며, 이 기간에 이전 토큰을 가진 주체도 같은 결과를 받을 수 있다. 클라이언트 비대칭 인증이 필요하고 서버 저장 결과는 AES-GCM으로 암호화한다. 직전 토큰만 유예하며 30초 경계 이후 또는 더 오래된 토큰 재사용 시 해당 세션을 폐기한다.

Cloudflare 계정은 Charliekant. 배포는 저장소의 정식 게이트 체계에 맞춘 새 Worker 전용 게이트와 exact SHA, 환경·바인딩 baseline, 승인 문구 및 사전 읽기 검사를 설계해야 한다. 게이트의 기존 재사용 가능성·계정의 Workers 및 Durable Objects 배포 권한, Zone에서 `auth.padiem.net` Custom Domain 연결 권한은 UNKNOWN. DNS·Custom Domain 배치 전 기존 호스트 충돌을 확인한다. 아무 명령도 실행하지 않는다.

대표는 실제 주소·계정 확인과 승인 뒤 Google Cloud `padiem-danjion`의 Padiem Production OAuth 클라이언트에 승인된 리디렉션 URI `https://auth.padiem.net/oauth/google/callback` 한 줄을 추가한다. 기존 URI는 유지한다.

러브트리 전환은 기본 OFF 스위치, 실계정 소유권 대조 및 롤백을 준비한다. CTO 승인 후 운영 tail에서 경로별 `cpuTime`, outcome/1101/1102/5xx, 지연 및 로그인 성공률을 관찰한다. 임계값·관찰 시간은 사전 합의하며 이상 시 옛 경로로 되돌린다. 현재 CPU는 미측정이다.
