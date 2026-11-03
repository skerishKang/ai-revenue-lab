# B62/Chat 로그인 세션 → 커넥터 enrollment 동의 브리지 리뷰 (2026-11-04)

결정: 승인. `REVIEWED_CONNECTOR_ENROLLMENT_LOGIN_PRODUCTS`에 `b62`를 추가한다.
근거 이슈: #6666 / #6717 (MCP pc_shell·pc_list가 owner-scope RPC의 제품 관문 (e)에서 거절).
결정자: CTO (컴2로컬2 분석 보고 #6666 후속 기준).

## 1. Chat 세션이 만들어지는 로그인 경로

1. MCP 커넥터(대표의 Claude 연결)가 Chat의 OAuth 레이어에 등록된다
   (`/oauth/register` 201, `/oauth/authorize` 302 — padiem-chat 저널 실측).
2. 커넥터가 `/auth/shared/start` → padiem-auth(PADIEM_AUTH) 로그인 →
   `/auth/shared/callback`에서 코드 교환 → Control Plane identity authority가
   canonical subject·tenant을 해석하고 `establish_auth_session`으로
   **product_id="b62"** 정식 세션을 발급한다(저널 shared_login_timing identity_rpc_ms 실측).
3. 세션 스냅샷은 Chat 호스트가 Control Plane identity authority에서
   `resolve_current_auth_session(product_id="b62", product_user_id=uid)`으로 재해석한다
   (chat_pc_drive.py `_resolve_chat_owner`). 클라이언트가 세션 값을 만들거나 가져갈 수 없다.

## 2. 같은 사용자임이 보장되는 경로

- 커넥터 토큰의 소유자(uid, usr_… 축)와 브라우저 세션의 subject는 **같은 Control Plane
  identity authority의 같은 canonical subject**에서 내려온다. 클라이언트가 subject를
  공급하는 경로는 없다(브라우저 쿠키·커넥터 토큰 모두 권위 세션 조회로만 해석).
- owner-scope RPC(`resolve_connector_owner_scope`)도 호출자가 session_id만 공급하고
  authority가 세션→subject→tenant을 해석하므로, 응답의 owner_subject_id는
  항상 세션 본인의 것(#6796)이다. 타인 subject가 섞일 경로가 없다.
- 세션·멤버십은 매 요청 authority에서 재해석된다(만료·폐기·비활성 즉시 반영).

## 3. 위험과 막는 장치

| 위험 | 막는 장치 |
|---|---|
| 웹 세션이 PC 등록 동의를 연다(피싱·CSUF) | 동의 grant는 명시 UI 확인 + confirmation_version + CSRF 절차를 유지(rpc:200-207), owner-scope 조회는 읽기만 |
| 만료·폐기 세션 통과 | 관문 (b): effective_state가 active가 아니면 거절(매 요청 재해석) |
| 비-human/서비스 주체 | 관문 (c): subject_type USER만 |
| tenant 없음·비-owner | 관문 (d) + membership_role OWNER만(rpc:75) |
| 여러 PC·미페어링 장치 | #6792: intent 장치는 소유자의 활성 pc_device_link 중 본인 것만 |
| 커넥터 토큰 누출 | 토큰은 MCP 전용 스코프이고 PC 명령은 서명된 내부 경로(X-Claw-Engine proof)로만 |
| b54 세션 부재 | #6800의 b54 필수 해석을 제거해 의존성을 끊었다 — b54 링크가 없어도 MCP 동일 사용자는 동작 |

## 4. 유지되는 기존 계약

- B66/Quote와 Engine은 여전히 각자의 브리지 리뷰가 필요하다(정책 문서).
- 제품 세션만으로 P01 READ/WRITE 권한이 생기지 않는다
  (CONNECTOR_REGISTRATION_GRANTS_P01_READ/WRITE = False 불변).
- enrollment 동의 자체는 여전히 명시적 소유자 확인 절차를 거친다.

## 5. 참조
- #6666 / #6717 / #6800 (b54 세션 해석 시도와 그 한계)
- PR #6792 (커넥터 토큰 소유자 + 활성 pc_device_links 우회 — 본 리뷰로 정식 경로화)
- connector_enrollment_owner_policy.py (정책 본문)
