# padiem-auth 배포 준비 — 초안

현재 NOT READY. 승인 없이 배포·DNS·Secrets·콘솔 설정을 변경하지 않는다. 서비스 바인딩은 같은 Cloudflare 계정의 기존 `padiem-control-plane-identity` 서비스로 향하며 Chat Worker를 거치지 않는다. 운영에서 바인딩 가능 여부·권한·실제 계정 일치와 기존 데이터 연속성은 미검증이다. 기존 identity authority는 Python Worker/DO다. padiem-auth 로그인 경로는 JS지만 이 기존 RPC 의존성을 CTO 표준의 Python Worker 금지와 어떻게 조화할지 검토가 필요하다.

필요한 값의 이름: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PADIEM_AUTH_ES256_PRIVATE_JWK` (padiem-auth Secret만), `PADIEM_AUTH_SIGNING_KID`, `PADIEM_AUTH_JWKS`, `PADIEM_AUTH_CLIENTS` (제품별 콜백 URI·공개 클라이언트 검증키). 원문은 읽거나 기록하지 않는다. 공개키 게시 → 서명 전환 → 15분 토큰 만료 및 캐시 전파 이후 옛 키 제거.

Cloudflare 계정은 Charliekant. 배포는 저장소의 정식 게이트 체계에 맞춘 새 Worker 전용 게이트와 exact SHA, 환경·바인딩 baseline, 승인 문구 및 사전 읽기 검사를 설계해야 한다. 게이트의 기존 재사용 가능성·계정의 Workers 및 Durable Objects 배포 권한, Zone에서 `auth.padiem.net` Custom Domain 연결 권한은 UNKNOWN. DNS·Custom Domain 배치 전 기존 호스트 충돌을 확인한다. 아무 명령도 실행하지 않는다.

대표는 실제 주소·계정 확인과 승인 뒤 Google Cloud `padiem-danjion`의 Padiem Production OAuth 클라이언트에 승인된 리디렉션 URI `https://auth.padiem.net/oauth/google/callback` 한 줄을 추가한다. 기존 URI는 유지한다.

러브트리 전환은 기본 OFF 스위치, 실계정 소유권 대조 및 롤백을 준비한다. CTO 승인 후 운영 tail에서 경로별 `cpuTime`, outcome/1101/1102/5xx, 지연 및 로그인 성공률을 관찰한다. 임계값·관찰 시간은 사전 합의하며 이상 시 옛 경로로 되돌린다. 현재 CPU는 미측정이다.
