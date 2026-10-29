# PADIEM 공통 인증 및 LoveTree 전환 설계 — 초안 (2026-10-29)

이 문서는 기존 LoveTree 직접 Google OAuth 설계를 대체한다. PADIEM 전체 공통 표준은 [AUTH_STANDARD.md](../standards/AUTH_STANDARD.md)다. 구현·배포·운영 설정·Google 콘솔 변경 없음.

## 구조와 검증 순서
padiem-auth는 Cloudflare JS/TS Worker이며 유일한 로그인·서명 권위다. 서비스는 padiem-auth로 이동하고 서비스별 허용 callback으로 받은 1회 코드를 서버에서 PKCE 및 서비스 비대칭 인증으로 교환한다. 서명 표는 서비스가 공개키로 로컬 검증하고 호스트 전용 쿠키로 보관한다. 갱신에서 차단·폐기를 강제한다. 이미 발급된 표는 만료까지 유효할 수 있다. 모든 규칙과 새로운 서비스 연결 5단계는 표준 문서를 따른다.

Google 공통 callback 목표 계약은 https://auth.padiem.net/oauth/google/callback 하나다. 이 주소는 설계값이며 도메인 소유·DNS·경로·콘솔 등록 상태는 UNKNOWN이다. CTO 운영 승인 및 사전 확인 전 대표에게 등록을 요청하지 않는다. 기존 oauth.padiem.net OAuth 연동은 별도 기존 용도이며 변경 대상이 아니다. Padiem Production 클라이언트와 프로젝트의 실제 운영 상태도 확인 전 UNKNOWN이다.

## 현재 구현과 기존 계정 보존
현재 LoveTree Pages 프록시는 JS, 로그인 서비스는 COM2 Node이며 Chat을 경유하는 기존 handoff를 쓴다. 현재 공통 identity authority는 Python Worker/DO이고 Google provider+sub와 기존 제품 링크로 canonical subject를 찾는다. Chat은 Google sub에서 usr_ ID를 만든다. 새로운 padiem-auth가 두 번째 정본을 만들면 데이터가 갈라지므로 기존 Google sub→canonical subject→제품별 ID/소유자 매핑을 새 JS 권위로 이관/대조해야 한다. 성공·충돌·중복·소유자 불일치에는 자동 이메일 병합 없이 중단하도록 설계한다. 실제 기존 데이터 연속성은 아직 검증되지 않았다. 검증 및 감사가 끝날 때까지 기존 권위/경로를 유지한다.

## 이전 초안과 구현 계획
기존 LoveTree 직접 Google provider [lovetree-4.0 #91](https://github.com/skerishKang/lovetree-4.0/pull/91) 및 기존 Python authority 계약 [ai-revenue-lab #6232](https://github.com/skerishKang/ai-revenue-lab/pull/6232)는 새 표준에 맞는 구현이 아니다. 초안 보관하며 머지·배포하지 않는다. 새 작업은 (1) JS padiem-auth와 기존 계정 이관 (2) JS·Python 공개키 검증 라이브러리 (3) LoveTree 서비스 연동 (4) Chat·Claw·견적 연동으로 나눈다. 코드 작성은 이번 설계 보고 이후 지시에 따라 진행한다.

## 전환·검증
러브트리부터 기본 OFF 스위치로 검증하고, 다음으로 Chat에 구 HMAC 쿠키·신규 공개키 검증 표를 병행한다. 기존 사용자 데이터와 동일 계정, 기존 진행 중 로그인, 재사용·위조·만료·PKCE/state·allowlist·키 회전·갱신 거절·롤백을 시험한다. 신규 경로를 끄는 롤백 시 신규 표만 있는 사용자는 재로그인이 필요할 수 있다. padiem-auth 자체 CPU 및 실제 로그인 성능은 미측정이며 10ms 충족이나 장애 해소를 보장하지 않는다.
