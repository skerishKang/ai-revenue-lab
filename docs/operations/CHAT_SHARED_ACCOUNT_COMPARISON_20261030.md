# Chat 공통 계정 대조 준비 (2026-10-30)

## 현재 상태

- 대조 경로는 기본 미등록이며 명시적으로 시험 흐름이 주입될 때만 등록된다. Chat 운영 배포·설정 변경은 하지 않았다.
- 서버는 기존 Chat 인증 세션 및 super-admin 권한을 확인하고 공통 표를 검증한 뒤 identity authority의 b62 역방향 조회 결과와 비교한다. 결과는 MATCH / MISMATCH / UNKNOWN만 표시한다. 실제 대표 계정의 결과는 UNKNOWN이다.
- Cloudflare Secrets Store에 새 항목 `PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK`, `PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY`를 만들었다. 값은 접근하거나 출력하지 않았다. 운영 Worker에는 아직 바인딩하지 않았다. PR에 바인딩·기준선·기본 OFF 스위치를 추가했다.
- 공개키와 유일한 콜백 `https://chat.padiem.net/_test/auth/account-comparison/callback` 등록은 #6273으로 머지됐고 main `4766fdcfe61b8e3c6bb09259288b4a2d0c0a8e8c`를 `--keep-vars`로 인증 서버에 배포했다. b62 시작 302, 러브트리 시작 302, 기존 JWKS kid 유지를 확인했다.

## 운영 시험 전에 필요한 것

1. #6273 인증 서버 등록은 완료했다. 러브트리 미리보기 허용 목록은 대표 계정 비교 뒤 정리한다.
2. ES256 서명·검증은 새 패키지를 추가하지 않고 Workers WebCrypto를 사용한다. 공통 ES256 벡터와 키 회전은 국소 테스트했고 실제 Pyodide 프로브를 CI에 추가했다. CI 결과가 나오기 전에는 실제 Worker 통과로 보지 않는다.
3. PR에 두 Secrets Store 바인딩·게이트 기준선·기본 OFF 스위치·서버 측 흐름 생성을 연결했다. 활성화한 경우에만 비동기 `.get()`으로 비밀을 읽는다. private key·state key는 로그·응답·브라우저 저장소·최상위 스냅숏에 넣지 않는다. CTO가 정한 Chat 배포 시점까지 적용하지 않는다.
4. 대표의 현재 Chat 세션이 플랫폼 super-admin인지 기존 역할 확인 경로로 검사한다. 실제 권한은 미확인이다. 권한이 없거나 확인 불가면 UNKNOWN이며 임의로 권한을 부여하지 않는다.
5. 격리된 Python Worker에서 WebCrypto 서명·공통 검증 벡터를 실제 구동하는 CI 결과를 확인한다. 전체 OAuth 교환·identity binding·운영자 권한을 포함한 실제 활성화 E2E는 배포 전 별도 확인이 필요하다.
6. CTO가 Chat 게이트 배포 시점을 정하면 정확한 SHA로 배포하고, 대표의 기존 Chat 세션과 공통 로그인으로 시험한다. 일치 결과만 Chat 전환 준비의 통과로 간주한다. 불일치 또는 UNKNOWN에서는 전환을 멈추고 데이터를 합치지 않는다.

## 시험 종료 후 정리 목록

- 러브트리 #93은 미머지로 닫았다. 운영 main에 미리보기 전용 라우트 예외와 진단 코드는 없다.
- 인증 서버 `PADIEM_AUTH_CLIENTS`에 러브트리 미리보기 콜백과 미리보기 공개키가 아직 있다. 운영 키와 같은 클라이언트 ID에 함께 연결돼 있으므로, 미리보기 시험 종료를 확인한 뒤 별도 변경으로 제거한다. 그때 운영 콜백과 운영 공개키는 유지하고 `--keep-vars`로 배포해 운영 로그인을 재검증한다.
- 러브트리 시험 미리보기 환경의 전용 개인키·상태 키·기타 비밀은 삭제하지 않았다. 실제 제거 여부와 시점은 별도 결정한다.
