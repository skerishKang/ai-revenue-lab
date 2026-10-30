# Chat 공통 계정 대조 준비 (2026-10-30)

## 현재 상태

- 대조 경로는 기본 미등록이며 명시적으로 시험 흐름이 주입될 때만 등록된다. Chat 운영 배포·설정 변경은 하지 않았다.
- 서버는 기존 Chat 인증 세션 및 super-admin 권한을 확인하고 공통 표를 검증한 뒤 identity authority의 b62 역방향 조회 결과와 비교한다. 결과는 MATCH / MISMATCH / UNKNOWN만 표시한다. 실제 대표 계정의 결과는 UNKNOWN이다.
- Cloudflare Secrets Store에 새 항목 `PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK`, `PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY`를 만들었다. 값은 접근하거나 출력하지 않았다. Worker에는 아직 바인딩하지 않았다.
- 공개키와 유일한 콜백 `https://chat.padiem.net/_test/auth/account-comparison/callback` 등록은 #6273에서 준비했다. 해당 PR은 아직 미머지다. 인증 서버 재배포 시 `--keep-vars`를 사용하고 인증 서버의 기존 서명·지문 키를 재생성하지 않는다.

## 운영 시험 전에 필요한 것

1. #6273을 승인된 경로로 머지하고 인증 서버에 배포한 뒤 기존 JWKS kid, 러브트리 로그인과 허용 목록 밖 거절을 확인한다.
2. #6267의 검증 라이브러리를 Chat Worker 빌드에 포함하고, JWKS를 Python Worker의 fetch 호환 경계로 비동기 수신하도록 연결한다. 현재 공통 Python 검증기는 기본 urllib 소켓 경로여서 Worker에서 실사용을 확인하지 못했다. 일반 Python HTTPX의 소켓 경로도 Worker에서 사용할 수 없어 Chat의 `httpx_compat`를 사용한다.
3. 두 Secrets Store 항목을 Chat Worker 설정에 바인딩하고 요청 시 비동기 `.get()`으로 가져오는 구성, 기본 OFF 스위치와 인증 흐름 생성 코드를 연결한다. private key·state key는 로그·응답·브라우저 저장소·최상위 스냅숏에 넣지 않는다. 다른 레인의 배포와 충돌하지 않게 CTO가 정한 배포 시점까지 적용하지 않는다.
4. 대표의 현재 Chat 세션이 플랫폼 super-admin인지 기존 역할 확인 경로로 검사한다. 실제 권한은 미확인이다. 권한이 없거나 확인 불가면 UNKNOWN이며 임의로 권한을 부여하지 않는다.
5. 격리된 Python Worker 환경에서 서명·공개키 갱신·코드 교환·identity binding·권한 및 기본 OFF, 쿠키/state/PKCE를 검증한다. CPython 합성 시험과 Worker fetch 호환 계층을 가짜 JS fetch로 구동한 시험은 통과했다. 실제 Pyodide에서 활성화된 대조 흐름의 E2E는 미검증이며 현재 PR의 Worker 계약 CI는 별도 결과를 확인한다.
6. CTO가 Chat 게이트 배포 시점을 정하면 정확한 SHA로 배포하고, 대표의 기존 Chat 세션과 공통 로그인으로 시험한다. 일치 결과만 Chat 전환 준비의 통과로 간주한다. 불일치 또는 UNKNOWN에서는 전환을 멈추고 데이터를 합치지 않는다.

## 시험 종료 후 정리 목록

- 러브트리 #93은 미머지로 닫았다. 운영 main에 미리보기 전용 라우트 예외와 진단 코드는 없다.
- 인증 서버 `PADIEM_AUTH_CLIENTS`에 러브트리 미리보기 콜백과 미리보기 공개키가 아직 있다. 운영 키와 같은 클라이언트 ID에 함께 연결돼 있으므로, 미리보기 시험 종료를 확인한 뒤 별도 변경으로 제거한다. 그때 운영 콜백과 운영 공개키는 유지하고 `--keep-vars`로 배포해 운영 로그인을 재검증한다.
- 러브트리 시험 미리보기 환경의 전용 개인키·상태 키·기타 비밀은 삭제하지 않았다. 실제 제거 여부와 시점은 별도 결정한다.
