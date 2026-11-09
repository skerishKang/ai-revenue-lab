# #7078 세션 로컬 검증 설계 (2026-11-09)

- 상태: 설계 문서 (운영 코드·설정 변경 없음). 대표 결정(2026-11-09): 보류 해제·최우선.
  PC 명령 지연의 주원인이 요청마다의 Cloudflare identity 왕복(거점 LAX, 호출당 약 400ms)으로 확인됨.
- 범위: Chat 요청 시점 세션 확인(`session_revocation_guard`) 대체 + 이메일(비밀번호) 로그인 padiem-auth 이전.
  서버 은퇴·RPC 25개 중 19개(계정·테넌트·커넥터 권위)는 범위 밖(2026-11-07 결정).
- 읽은 근거: 이슈 #7078 본문·코멘트, `docs/standards/AUTH_STANDARD.md` §9 이후, 아래 표의 코드 위치만 필요 구간 읽음.
  경로별 호출 수는 11-09 계측(쪽의 RPC 계측 #7274, 세션 캐시 300초 #7191, 폐기 캐시 통합 #7284) 기준으로 센다.
  코드 기준 시점: `main` @ `0856358b2` (#7284).

## 0. 확인된 사실 (전제)

- Chat은 인증된 모든 쿠키 요청마다 `apps/padiem-chat/app/session_revocation_guard.py:180`
  `resolve_verdict()`에서 쿠키의 canonical 세션 id(`sid`)를 `control_plane_identity_authority.resolve_auth_session`
  (`control_plane_identity_worker.py:389`, DO `identity_authority_worker.py:298`,
  저장소 `identity_authority_durable.py` `resolve_auth_session`)으로 확인한다.
  미확인(권한 없음·면제 경로 `/auth/google/callback`·`/auth/android/confirm`·`/api/auth/logout`,
  `session_revocation_guard.py:71`)이면 guard는 inert다.
- 7일 7,736회 guard 확인 중 권위 상향은 420건(평균 ~1.2s, 이슈 점검 기준). 대표 측정(11-09)은 호출당 약 400ms.
  캐시 적용: `SqliteAuthValidationCache`(`auth_validation_cache.py:111`, 세션 행 기본 300초,
  `PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS`, 만료 전 백그라운드 갱신 `get_or_load_ahead` #7191) +
  `CachedIdentityAuthority`(`identity_call_cache.py:75`, `resolve_auth_session` 300초 #7284).
  성공만 캐시, 거부·오류는 저장하지 않는다. 이 호스트의 폐기 이벤트는 즉시 무효화한다.
- Google 로그인은 이미 padiem-auth(`auth.padiem.net`, JWKS `/.well-known/jwks.json`,
  `worker.mjs:291`) + Chat `shared_login_flow`로 전환 완료.
  이메일(비밀번호) 로그인은 Chat 직접 처리 `auth_routes.py:834 password_login` (7일 126회),
  현재는 padiem-auth가 `POST /internal/password-verify`로 역으로 Chat에 검증 요청을 보낸다
  (`worker.mjs:407`, Chat 내측 `passwordRpcOrigin`).
- padiem-auth access 표는 이미 ES256·15분(`access-token.mjs:2`, `worker.mjs:559,572`).
  Chat/북AI의 로컬 검증 라이브러리는 이미 있다: `packages/padiem-auth-verify/verify.py:30 Verifier`
  (고정 issuer·JWKS URL, 캐시 300초), JS판 `verify.mjs`, 북AI `public/bookai-auth-verify.mjs:2`.

## 1. 경로별 identity 호출 표 (현재)

| 경로 | 요청당 identity 호출 (method) | 코드 위치 | 캐시 적용 여부 |
| --- | --- | --- | --- |
| Chat 일반 요청 (보호 API, 브라우저 쿠키) | `resolve_auth_session` ×1 (`sid` 기준) | guard `session_revocation_guard.py:209` → `control_plane_identity_worker.py:389` | 있음: SQLite 세션 캐시 300초(#7191) + `CachedIdentityAuthority` 300초(#7284). 캐시 적중이면 0회 상향. 미적중이 LAX 왕복 (~400ms~1.2s) |
| PC 명령 턴 (채팅 턴·파일/브라우저 lane) | `resolve_current_auth_session` ×1 + `resolve_connector_owner_scope` ×1 + B54 `resolve_current_b54_canonical_session`(내부 `resolve_current_auth_session`) ×1 → 최대 ×3 | `chat_pc_drive.py:374 _resolve_chat_owner:406` + `:518` + `:444`; 소유 경로 `oracle_mesh_read_return_routes.py:4532,4555,5475` | 부분 있음: `CachedIdentityAuthority` 60초(`identity_call_cache.py:75`). 턴 내 중복은 1회로 합쳐지나 턴 간(60초 초과)은 재호출. PC 폴링(`/internal/chat/engine-pc-files`)은 매 폴링마다 재호출됨 |
| Claw (자동화·커넥터·MCP) | `resolve_current_b54_canonical_session` ×1 (+ 경우에 따라 `resolve_product_user_for_subject` ×1, `resolve_connector_owner_scope` ×1) | `b54_canonical_session.py:212` → authority `:244`; `claw_automation_owner_resolution.py:461`; `mcp_oauth.py:603,630` | B54/current은 `CachedIdentityAuthority` 60초. `product_user`는 과정 캐시 60초(§3). MCP OAuth(`/oauth/authorize`)는 옛 경로 30회/7일(점검 기준) |
| 북AI | 옛 identity `resolve_*` 0회. 이미 padiem-auth 토큰을 JWKS 로컬 검증 | `apps/bookai/public/bookai-auth-verify.mjs:2` (JWKS fetch `:13`), `packages/padiem-auth-verify/verify.mjs` | JWKS 캐시. 정본 모델 — 변경 대상 아님 |
| 로그인 — Google | padiem-auth 교환·refresh (신규 경로). 구 전화면 `bridge_trusted_product_auth` → `resolve_or_create_product_link` ×1 + `establish_auth_session` ×1 (+ B54 ×1) | `auth_routes.py:359 _write_identity_shadow_after_login` (호출 `:538`), `worker.py:332,367` | 없음 (로그인 시 1회성). 7일 `/auth/shared/start 39·/callback 30·/refresh 406` / `/auth/google/* 56·6` 중 신규 성공 19건 |
| 로그인 — 이메일(구: Chat 직접) | `resolve_or_create_product_link` ×1 + `establish_auth_session` ×1 (+ B54 ×1) + shadow 저장 | `auth_routes.py:834 password_login:924`, `establish_b54...:418` | 없음. 7일 126회. padiem-auth 경유 시 내부 `/internal/password-verify` 579회(점검 기준)가 뒤집혀 Chat→padiem-auth 1회 |
| 로그아웃 | `revoke_auth_session` ×1 (해당 `sid` 하나만) | `auth_routes.py:1256 logout` → `:957 _revoke_canonical_session:978` | 없음. guard 면제 경로이므로 guard 비용 0. 7일 15회 |
| 비밀번호 변경(로그인 상태) | `revoke_auth_session` ×1 + `revoke_all_auth_sessions` ×1 (best-effort) | `auth_routes.py:1003 password_change:1061,1072` | 없음. 폐기 성공 시 양 캐시 무효화 |
| 비밀번호 재설정 | `revoke_all_auth_sessions` ×1 (strict) | `auth_routes.py:1178 password_reset_confirm:1227` | 없음. 미확인 시 비번 미변경(재시도) |
| 계정 탈퇴 | `remove_product_link` ×1 (+ 세션 폐기 포함) + Chat 사용자 삭제 | `account_deletion.py` (호출부), `worker.py:608 finalizeAccountDeletion`, DO `identity_authority_durable.py` | 없음. tombstone 확정 후 `identityIsDeleted`(`worker.mjs:621`)로 refresh·재로그인 거부 |

비고:
- 위에 없는 닿지 않는 경로: `authority_factory.py`는 COM2 미배포 소스(운영 미사용).
  `lovetree-auth-caller/worker.mjs`는 러브트리 세션 폐기·handoff 중계로 옛 권위를 호출하나
  2026-10-29 이후 신규 handoff 행 0건(점검 기준).
- 계측 기준(11-09): RPC 계측(#7274, `journal_identity_rpc`)으로 method별 ms·성공/거부를 셈.
  guard 7,736회 중 상향 420건이 대부분 비용이다. 캐시가 300초(#7191) + #7284 때처럼
  일반 요청 캐시와 같은 창이 되면 상향률만 낮아지고, 캐시 만료·무효화 시 여전히 400ms+가 턴에 남는다.

## 2. 새 방식 — padiem-auth 짧은 토큰의 Chat 로컬 검증

### 2.1 원칙 (AUTH_STANDARD §0·§4·§8과 정합)

- padiem-auth가 ES256 서명 `access` 표를 발급한다. 이미 구현됨:
  `iss=https://auth.padiem.net`, `aud=<제품 id>`, `sub`, `account_id`(`sub_…`),
  `sid`(세션 id), `iat`, `exp=iat+900`, `token_use=access`.
- Chat은 매 요청마다 identity 권위에 묻지 않고 JWKS(`https://auth.padiem.net/.well-known/jwks.json`)로
  **로컬 검증**한다. 이미 있는 검증기를 재사용한다:
  `packages/padiem-auth-verify/verify.py:30 Verifier(audience="b62", cache_seconds=300)` —
  `alg=ES256`만, `kid` 대조, `iss·aud·token_use·exp` 검사, `exp ≤ iat+900`.
  Chat 내부에서는 이 검증 결과를 `(user_id=account_id 매핑, sid, 만료)`로 변환해
  `current_user_id()`·`session_verdict` 자리에 꽂는다.
- 기존 HMAC 세션 쿠키(`auth.py:109 create_session_token`, `sid` 클레임 `:123`, 수명 7일
  `config.py:143`)는 전환 기간 병행한다. guard의 대체가 아니라 대체를 **포함**하는 별도 검증기가
  기존 guard와 짝을 이루면 (§4 단계 1 그림자) 불일치를 잴 수 있다.

### 2.2 수명·갱신 주기 후보 (추천)

| 후보 | access 수명 | 갱신 | 장점 | 단점 |
| --- | --- | --- | --- | --- |
| A (추천) | 15분 (표준값 그대로, `access-token.mjs:2`) | Chat이 만료 전에 padiem-auth `/token` refresh 호출(30일 회전형 refresh, §8·§10 30초 유예). 프론트 `session-retry` 이미 있음 | 표준·북AI·러브트리 동일 규약. JWKS 캐시(300초)와 정합. 시계 차이 5분 흡수(§5) | 타 제품 폐기의 최악 지연 최대 15분(§2.3) |
| B | 10분 | refresh 시점만 5분 앞당김 | 지연 10분 | 표준과 어긋남, 이득 작음 |
| C | 5분 | refresh 빈도 3배 | 지연 5분 | refresh 상향 3배, 갱신 실패 재로그인 증가 |

- 추천: **A**. 수명·갱신 주기는 표준(§8)대로 두고, 지연을 줄이는 축은 "수명을 짧게"
  가 아니라 "Chat이 refresh를 선제·조용히 수행"하는 쪽이다. Chat `shared_login_flow.refresh`
  (`shared_login_flow.py:395`)가 이미 refresh→신규 access 교환을 한다.
  서버 측에서는 만료 5분 전 백그라운드 갱신을 guard의 refresh-ahead(#7191)와 같은 패턴으로 둔다.

### 2.3 폐기 — 갱신 때 확인 + 즉시 끊어야 하는 경우

기본: **갱신 때 확인**. refresh는 padiem-auth에서 수행되므로
`worker.mjs:520 exchangeCode`/`rotate`가 차단·탈퇴·폐기된 세션을 거부한다.
이미 발급된 access는 만료까지 로컬 유효하므로, "15분 안에"가 상한이다
(§4 "최대 차단 지연은 15분"과 일치).

즉시 끊어야 하는 경우(로그아웃·비밀번호 변경·탈퇴·관리자 차단)에 대한 선택지는 둘 중 하나다:

| 방안 | 동작 | 비용 | 추천 |
| --- | --- | --- | --- |
| (i) 짧은 TTL (추천) | access 15분 + 같은 호스트 폐기 시 즉시 캐시 무효화. 별도 푸시 없음 | 없음. 표준대로 | **이 문서의 추천.** 이미 있는 무효화 인프라(`invalidate_auth_cache`)가 이 몫을 한다 |
| (ii) 폐기 목록 푸시 | padiem-auth가 폐기 시 Chat(및 각 제품)에 무효화 요청 푸시 | DO→제품 푸시 경로·재전송·감시·구독 키 신규 구축. §9 경고("발신·내구성 있는 재전송과 실패 감시가 연결되기 전에는 15분 안에 차단이 반영된다고 주장하지 않는다")가 바로 이 경우 | 표준 감시·재전송이 갖춰지기 전까지는 채택하지 않는다. 필요해지면 별도 설계 후 추가 |

즉, 폐기는 **"갱신 때 확인 + 같은 호스트 즉시 무효화 + 15분 상한"**이 기본이다.
푸시는 지금 만들지 않는다.

### 2.4 경우별 최악 지연 (폐기 후 끊기는 시각)

"0"은 이 요청의 응답까지, "이후"는 같은 호스트의 다음 요청부터를 뜻한다. 타 제품 = 다른 제품에서 수행된 폐기.

| 사건 | 이 호스트(Chat)에서 수행 | 타 제품에서 수행 |
| --- | --- | --- |
| 로그아웃(그 브라우저) | 0초: 쿠키 제거 + `revoke`→access 즉시 무효(같은 `sid` 폐기 경로, `auth_routes.py:957`). 새 access 없음 | 15분: 남은 access 만료까지 유효. refresh 시도 시 거부 |
| 비밀번호 변경 | 0초(같은 호스트): `revoke`+`revoke_all` 후 access 폐기. `password_change:1061,1072` | 15분 (refresh 시 거부). 단, 변경 직후 기존 refresh도 무효이므로 그 논의 refresh는 실패 |
| 비밀번호 재설정(링크) | 0초: `revoke_all strict` 후 비번 변경(`password_reset_confirm:1227`) | 15분 |
| 탈퇴 | 0초: `finalizeAccountDeletion` + tombstone(`worker.mjs:608`) 후 refresh 거부 + Chat 무효화 | 15분까지 유효. 단, tombstone 확정 후 refresh·재로그인은 거부(`identityIsDeleted:621`). refresh가 15분 주기여도 이 수명을 넘지 않는다 |
| 관리자 차단(`account-block`) | 0초(같은 호스트 경유 시): `worker.mjs:278 setAccountStatus` + 무효화 | 15분: 차단 표식 후 refresh 거부(`setAccountStatus`→`rotate` 검사). 푸시를 하지 않으므로 15분 상한 |

구 guard와 비교: 구 guard의 타 제품 폐기 최악은 300초(캐시 창)와 같다.
새 방식은 같은 호스트 즉시(0초) + 타 제품 15분이다.
§9의 "15분 안에 차단이 반영된다고 주장하지 않는다"는 푸시를 주장하지 않는다는 뜻이며,
이 설계는 refresh-거부 경로를 실제로 연결하므로 "refresh 시도 시 0초, 발급분은 최대 15분"으로 명시한다.
즉시 반영이 꼭 필요하면 그때 푸시(방안 ii)를 별도 추진한다.

## 3. 사라지는 호출과 남는 호출

### 3.1 새 방식으로 사라지는 것

| 사라지는 호출 | 대체 | 비고 |
| --- | --- | --- |
| 요청마다 `resolve_auth_session` (§715) | access 로컬 검증(§2). JWKS 캐시 300초 | PC 턴·Claw의 세션 확인분도 이 자리를 대체하면 사라진다(§3.2 제외) |
| 로그인 시 구 `resolve_or_create_product_link`+`establish_auth_session` (B62·B54) | padiem-auth `resolveAccount`(`worker.mjs:617`) + access 발급 | 단, `resolveAccount` 내부가 여전히 옛 권위를 부를 수 있다(§5·§9). Chat 측 호출은 사라지나 권위 자체는 유지 |
| 로그아웃·비번 변경·재설정 시 구 `revoke_*` (Chat→옛 권위) | padiem-auth 세션 폐기(`/token` revoke·refresh 거부) + 로컬 무효화 | refresh 거부 경로가 갖춰지면 대체 가능. Chat→권위 직접 호출은 사라진다 |

### 3.2 남는 호출 (토큰 직접 검증 뒤에도 남음)

| 남는 호출 | 왜 남는가 | 코드 위치 | 처리 방안 |
| --- | --- | --- | --- |
| `resolve_product_user_for_subject` (주제→제품 사용자 매핑, 역방향) | access의 `account_id/sub`와 Chat `usr_…`를 잇는 다리. access만으로 Chat 소유자 ID를 못 만든다 | `control_plane_identity_worker.py:486`, DO `identity_authority_durable.py:1289`, 호출 `mcp_oauth.py:630`, `oracle_mesh_read_return_routes.py:4532,5475`, 부캐시 `identity_call_cache.py:178` | **긴 캐시 + 변경 시 무효화 (추천).** §3.3 |
| `resolve_connector_owner_scope` (PC lane owner 범위) | 파일·데스크톱 소유권(`account_ref/workspace_ref`)은 토큰에 없음 | `chat_pc_drive.py:518`, `control_plane_identity_worker.py:593` | 현행 동작 유지: 60초 `CachedIdentityAuthority` + 같은 호스트 폐기 시 즉시 무효화. 토큰의 `account_id`로 대체 가능한 범위는 단계 3에서 검토 |
| `resolve_current_auth_session` (PC 턴·Claw B54) | "지금 활성 세션"은 토큰의 `sid`와 다름. B54 제품 범위(`b54`)는 토큰 aud와 분리 | `chat_pc_drive.py:406`, `b54_canonical_session.py:212,244` | access 검증이 `sid`를 주면 PC 턴의 세션 존재 확인은 토큰으로 대체 가능. B54는 제품 스코프가 달라 별도 유지. PC 턴은 토큰 검증 + 60초 캐시로 단계적 대체 |
| `resolve_connector_workspace/context/enrollment`, `issue_google_connect_ticket`, 테넌트·멤버십 RPC (19개) | 커넥터 권위. §1대로 서버에 남음 | `identity_authority_worker.py` DO 메서드, `claw_connector_enrollment_routes.py` | 그대로 유지. 범위 밖 |
| padiem-auth `resolveAccount` 내 `resolve_or_create_product_link` | 첫 로그인 매핑(§9: 최초 검증 로그인에서만). `worker.mjs:617` | `worker.mjs:617,632` | 남음. "매 로그인마다" → "최초·미매핑 시만"으로 이미 좁혀졌으나 `b62` 처리로 로그인마다 닿을 수 있다(점검 기준). §5 항목 |

### 3.3 `resolve_product_user_for_subject` 처리안 (TO 지시 반영)

- 11-09 22시 측정: identity 호출 중 가장 잦고 느림 — 20분 n=27, TTFB 중앙 911ms(LAX).
  토큰 직접 검증 뒤에도 남는 호출이므로 이 RPC가 다음 병목이 된다.
- 현재 캐시: 프로세스 캐시 60초(`control_plane_identity_worker.py` `_product_user_cache`, #3247 역방향)
  + `CachedIdentityAuthority` 60초(`identity_call_cache.py:178`).
  무효화: `resolve_or_create_product_link` 성공 시 해당 쌍 삭제, `remove_product_link` 성공 시 삭제.

**추천: 긴 캐시 + 변경 시 무효화.** COM2 사본(동기화)은 이보다 비용과 정합 부담이 크다
(동기화 프로토콜·순서·복구 신규 구축). 기존 캐시 구조(성공만 저장, 쓰기 시 무효화)를
오히려 늘리는 쪽이 변경이 작다.

| 항목 | 값 |
| --- | --- |
| 캐시 TTL (추천) | 300초 → 추후 계측 보고 900초 상한까지 허용. `CachedIdentityAuthority`의 60초 cap을 이 키에만 300초로 분리(#7284의 세션 300초와 동일 창) |
| 키 | `(product_id, canonical_subject_id)` — 토큰의 `account_id`에서 파생. 성공만 저장, 거부·없음은 저장하지 않음(다음 호출이 재시도) |
| 저장소 | 기존 프로세스 캐시 + `auth_validation_cache`의 account-link 테이블(§§). 두 층을 한 창(300초)으로 통일해 만료 이유가 하나로 정리되게 한다 |
| 장애 정책 | 미적중·만료 시 권위 호출 (비용 400ms+). 만료된 답을 계속 쓰지 않는다. 권위 불가 시 fail closed(기존) |

무효화가 필요한 사건:

| 사건 | 무효화 동작 | 근거 |
| --- | --- | --- |
| 제품 연결 생성·재결합 (`resolve_or_create_product_link` 성공) | 해당 `(product_id, canonical_subject_id)` 삭제 후 다음 호출에서 재해결 | 역방향 캐시는 같은 키를 쓰는 생성자가 무효화(`worker.py` 역방향 캐시 주석) |
| 제품 연결 제거 (`remove_product_link` 성공 — 탈퇴·연결 해제 포함) | 해당 키 삭제 | 제거는 역방향 조회가 유일하게 바꾸는 경로 |
| 소유 이전 (소유자 변경·250줄급 재지정) | 기존 키 삭제 + 새 키는 다음 호출에서 해석. `expected_canonical_subject_id` 불일치 시 `identity_conflict`로 중단(`worker.mjs:617`) | 소유 이전은 연결 생성/제거에 포함되므로 별도 RPC가 없음. 자동 병합하지 않음(§2) |
| 계정 차단·탈퇴 확정 (tombstone) | 해당 사용자 전체 무효화 (`invalidate_auth_cache` 사용자 단위, `identity_call_cache.py:107`) | 캐시가 차단/탈퇴를 늦추지 않게 |
| 멤버십·역할 변경 (`assign/revoke_tenant_membership`, 관리자) | 세션·소유 범위 캐시는 별도 무효화. 이 키는 영향 없음(제품 사용자는 안 바뀜) | 영향 없는 사건은 무효화하지 않음 — 과도한 무효화가 911ms 호출을 되살린다 |

## 4. 단계와 각 단계의 바뀌는 것

### 단계 1 — 그림자 모드 (불일치 기록, 사용자 영향 없음)

- 하는 일: Chat이 padiem-auth access를 **병행 검증**한다. 기존 guard(`resolve_auth_session`)는
  여전히 인증을 결정하고, 새 로컬 검증은 **기록 전용**이다. 불일치(새 검증은 유효인데 guard는 거부,
  또는 반대)만 구조화 로그로 남긴다. 하루 불일치 0건을 확인한다.
- 바뀌는 파일: `apps/padiem-chat/app/shared_auth_adapter.py`에 병행 검증 훅 1개 추가,
  `session_revocation_guard.py`에 읽기 전용 비교 주입 (판정 로직 무변경).
  JWKS 캐시는 `Verifier`(300초) 재사용. `identity_call_cache.py`·`auth_validation_cache.py` 무변경.
- 서비스: Chat만. padiem-auth·identity Worker 배포 없음.
- 배포 순서: PR 머지 → COM2 Chat 재배포 1회(그림자 플래그 OFF 기본 → ON). 사용자에게 보이는 동작 없음.
- 되돌리기: 플래그 OFF → 재시작. 데이터·토큰 변경 없음.
- 확인: 그림자 로그 `shadow_mismatch=0` 24시간 유지. JWKS fetch 실패·`kid` unknown 0건.
  `/auth/status`의 `session_state` 분포가 그림자 전과 동일.

### 단계 2 — 스위치 전환 (즉시 되돌리기 가능)

- 하는 일: 인증 결정을 새 로컬 검증으로 바꾼다. `session_revocation_guard`는 그대로 두되
  **스위치 OFF면 구 경로, ON이면 새 경로**로 결정한다. guard의 `resolve_auth_session` 호출은
  스위치 ON에서는 생략하고, access 만료·서명 오류·`kid` unknown은 거부(재로그인 유도)한다.
- 바뀌는 파일: `session_revocation_guard.py` (스위치 분기), `shared_auth_adapter.py` (새 검증 본체),
  `auth_validation_cache.py` + `identity_call_cache.py` (새 캐시 창 = JWKS 캐시와 같은 300초),
  `local_cpython.py` (스위치 환경값 배선). 그 외 라우트 무변경.
- 서비스: Chat만. 배포는 `PADIEM_CHAT_LOCAL_VERIFY_ENABLED=false(기본) → true` 순.
- 되돌리기: 스위치 OFF → 구 guard 즉시 복귀. 이미 새 access만으로 로그인한 사용자는
  롤백 후 구 로그인이 필요할 수 있음을 고지한다(§6과 같은 원칙).
- 확인: 전환 후 24시간 `/auth/status` 서명 상태 분포, 503 `session_authority_unavailable` 0건,
  refresh 406권 유지, PC 턴의 identity ms 감소(§1 계측). 롤백 1회 시험.

### 단계 3 — 이메일 로그인 padiem-auth 이전

- 하는 일: Chat의 `password_login`(`auth_routes.py:834`)을 끈다(스위치). 이메일 로그인은
  padiem-auth(`worker.mjs:347 /login/password`)가 받아 Chat `POST /internal/password-verify`
  (`worker.mjs:407`)로 검증하고, access를 발급한 뒤 Chat은 콜백으로 세션을 만든다
  (Google과 같은 흐름). Chat의 직접 검증(`find_password_credential`+`verify_password_async`)은
  내측 RPC 전용으로 남거나 단계 3 후 제거한다.
  이후 `_write_identity_shadow_after_login`(`auth_routes.py:359`)의 B62·B54 생성은
  padiem-auth `resolveAccount`(`worker.mjs:617`)의 매핑으로 대체되고, Chat 측 2회 RPC는 사라진다.
- 바뀌는 파일: `apps/padiem-chat/app/auth_routes.py` (`password_login` 스위치·내측 RPC),
  `apps/padiem-auth/worker.mjs` (`password_login` 허용·gate), `local_cpython.py`(배선).
  `password_change`·`password_reset_confirm`의 `revoke*`는 padiem-auth 세션 폐기로 교차 적용한다.
- 서비스 순서: Chat(내측 검증 ready) → padiem-auth 재배포(`--keep-vars`, 키 재생성 금지, §11)
  → Chat 스위치 ON. 역순 금지.
- 되돌리기: Chat 스위치 OFF → Chat 직접 로그인 복귀. 이메일로만 가입한 사용자는 그 사이
  발급된 padiem-auth 세션이 필요할 수 있다.
- 확인: `/api/auth/password/login` 126회/주 → 0회, `/internal/password-verify` 유지,
  신규 이메일 로그인 성공률·잠금 정책 동일. `session_config` 수명 7일은 access 15분+refresh로 대체된다.

## 5. 위험 목록

| 위험 | 내용 | 대응 |
| --- | --- | --- |
| 시계 차이 | COM2·Cloudflare·클라이언트 시계 차가 `iat/exp`를 어긋낸다. 구 쿠키는 Chat 비밀만으로 만료 판정 | `Verifier`는 `iat>now` 거부. 허용 여유(leeway)는 5분 이내로 제한한다. 그림자 모드에서 시계 차이로 인한 불일치를 먼저 잰다. 허용 여유를 5분 초과로 늦추면 지연이 그만큼 늘어난다(§2.4) |
| JWKS 갱신·캐시·키 교체 | §8 순서(새 공개키 게시 → 캐시 전파 확인 → 서명 전환 → 만료+캐시 후 구키 제거). 잘못된 순서는 전원 거부 | 캐시 300초 + `kid` unknown 시 1회 강제 재조회(`verify.py:37`). 키 교체 전 새 키를 JWKS에 먼저 올리고 300초 이상 확인한 뒤 전환한다. 키 유출은 긴급 교체(사전 배포 불가) |
| 컴2와 Cloudflare front 양쪽 검증 | 앞단 `padiem-chat-front/worker.mjs`는 브라우저→COM2 중계이며 자체 인증을 하지 않는다. COM2 Chat이 로컬 검증을 담당한다. 북AI·러브트리 등 다른 제품은 이미 JWKS/refresh 경로를 쓴다 | Chat은 `aud=b62`만 검증. 다른 제품의 access(`aud=b61` 등)는 `aud` 불일치로 거부된다. front는 토큰을 쪼개지 않는다 |
| Claw·북AI 등 다른 제품 | Claw(B54)는 제품 스코프(`b54`)가 분리되어 있어 B62 access로 대체할 수 없다. 북AI는 이미 로컬 검증이라 영향 없음. 러브트리는 handoff 경로(handoff 0건, 점검 기준) | Claw는 B54 세션을 유지하고 B62 access는 병행 사용. 북AI·러브트리는 이 단계에서 무변경 |
| 기존 세션 쿠키 이전 | 구 HMAC 쿠키(7일 수명, `sid` 유무 혼합)와 새 access+refresh 세션의 감별 | 전환 기간에 HMAC 쿠키와 access를 둘 다 허용하되 credential 유형을 분리한다(§6). 한쪽의 실패로 다른 쪽을 우회하지 않는다. 구 쿠키는 만료까지만 인정하고, `sid` 없는 구 쿠키는 guard 대상 밖(기존 동작) |
| 탈퇴 tombstone(#7207)과의 관계 | `finalizeAccountDeletion`(`worker.mjs:608`) 후 `identityIsDeleted`로 refresh·재로그인 거부. Chat 삭제(`account_deletion.py:584`)와 같은 트랜잭션성이 아닌데, 순서가 엉키면 삭제된 계정이 refresh를 통과한다 | tombstone 확정을 refresh 거부보다 먼저 둔다(`worker.mjs:191` 주석 순서). `recordAccountChatUsers`·Chat 삭제는 tombstone 이후. §3.3 무효화 표에 "tombstone 확정 시 사용자 전체 무효화" 포함 |
| padiem-auth `b62` 로그인마다 옛 권위 호출 | §9는 "최초 검증 로그인에서만"이나 코드는 제품을 `b62`면 매번 닿을 수 있음(점검). 전환 전에도 상향이 남는다 | 단계 1 그림자에서 로그인 시점의 권위 호출 빈도를 잰다. 단계 3에서 `resolveAccount`의 "최초·미매핑 시만" 분기를 좁힌다. 없으면 컴2가 꺼져도 로그인이 죽는다는 원칙(§0)과 충돌한다 |
| 그림자 비교가 못 잡는 차이 | 그림자는 guard의 `resolve_auth_session` 결과와 새 검증의 access 결과를 비교한다. 둘 다 Chat 요구가 만든 access라서, 생략된 쪽의 원천(권위·발급) 결함은 보인다. 그러나 만료·아력 즉시 반영 같은 **시간 차이**는 그림자에서 안 보일 수 있다 | §2.4의 최악 지연은 그림자가 아니라 스모크로 확인한다: 폐기 후 refresh 시도·다른 제품 폐기 후 access 잔여 |

## 6. 관계 표 (왜 새 방식이 표준과 맞는지)

- §0 "데이터 서버는 padiem-auth가 발급한 로그인 표를 JWKS로 스스로 검증한다, 매 요청 묻지 않는다" —
  정확히 이 설계다. §1의 guard가 그 "매 요청 묻는" 부분이다.
- §4 "서비스는 JS·Python 공통 라이브러리로 서명·알고리즘 허용 목록·발급자·audience·시각·토큰 유형을 요청마다 로컬 검사" —
  `Verifier`가 이미 그러하다. "이미 발급된 표는 만료 전 로컬 검증상 유효하므로 즉시 전역 무효화는 보장하지 않는다" —
  §2.4 최악 지연이 그 문서와 일치한다.
- §8 "access ES256 15분, refresh padiem-auth 단독 30일·사용 시 교체, 재사용 탐지 시 세션 전체 폐기" —
  §2.2 후보 A가 그대로다.
