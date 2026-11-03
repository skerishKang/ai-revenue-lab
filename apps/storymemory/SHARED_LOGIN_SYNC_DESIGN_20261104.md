# B61 공통 로그인 및 동기화 설계

작성일: 2026-11-04
범위: 로그인·로그아웃 연결과 동기화 설계. 이 문서만으로 원격 동기화가 켜지지 않는다.

## 로그인 연결

- 공통 로그인 권위는 `padiem-auth`다. 앱은 Google OAuth를 직접 수행하지 않는다.
- B61은 Pages Advanced Mode의 `public/_worker.js`가 `/auth/*` 경로를 처리한다. 이 배포 모드에서 `functions/`는 실행되지 않으므로 Pages Functions 파일을 추가하지 않는다.
- 로그인은 state와 PKCE S256을 만들고 암호화한 단기 state 쿠키에 보관한 뒤 `https://auth.padiem.net/login`으로 이동한다. 콜백은 서비스 서버 측에서 private_key_jwt로 `/token`을 호출하고 ES256 access 표를 공개 JWKS로 확인한다.
- access·refresh 표는 host-only Secure HttpOnly 쿠키에만 둔다. 브라우저 API 응답, localStorage, URL, 로그에 표·이메일·계정 ID를 내보내지 않는다. 화면에는 로그인 여부만 표시한다.
- 로그아웃은 same-origin POST만 허용한다. refresh 표를 padiem-auth `/logout`에 보내 해당 세션을 폐기한 뒤 B61 인증 쿠키를 지운다. 실패하면 성공한 것처럼 보이지 않게 한다.
- `STORYMEMORY_SHARED_AUTH_ENABLED`가 정확히 `true`이고 서비스 서명 키와 state 암호화 키가 준비돼야 로그인 기능이 설정된 것으로 본다. 기본값은 꺼짐이며, 설정이 없으면 현재 localStorage 동작을 유지하고 로그인 버튼을 숨긴다.
- 현재 AI adapter의 상태 `auth: deferred`는 이 로그인 연결로 바뀌지 않는다. AI 요청 인증은 별도 단계에서 구현·검증해야 한다.

### padiem-auth 등록 대기값

기존 `b61` 클라이언트는 BookAI 전용이므로 공유하지 않는다.

| 항목 | 등록/설정 값 |
|---|---|
| 클라이언트 ID 후보 | `b61-storymemory` |
| 정확한 redirect URI | `https://storymemory-padiem.pages.dev/auth/callback` |
| 허용할 공개 키 | B61 전용 ES256 P-256 서비스 공개 JWK. padiem-auth 허용 목록에 공개키와 `kid`만 등록 |
| Pages 변수 | `STORYMEMORY_SHARED_AUTH_ENABLED=true`, `STORYMEMORY_AUTH_CLIENT_KID` |
| Pages Secrets | `STORYMEMORY_AUTH_CLIENT_PRIVATE_JWK`, `STORYMEMORY_AUTH_STATE_KEY` (32바이트 AES-GCM 키의 base64url 표현) |

이번 변경에서는 padiem-auth 등록이나 Pages 변수·Secret 설정을 하지 않는다. 개인키와 state 키 값은 저장소에 넣지 않는다. 설정 전까지 로그인 버튼은 숨겨진다.

## 현재 데이터와 동기화 범위

현재 기록은 브라우저 localStorage가 원본이다. `storymemory.store.v1`은 progress·annotations·memories·recall·entity ledger의 통합 스냅샷이며, 호환/세부 저장 키도 함께 사용한다.

| 데이터 | 현재 로컬 위치 | 향후 동기화 범위와 위치 |
|---|---|---|
| 독서 위치·이어 읽기 | `storymemory.readerProgress.*`, `storymemory.readerResume.*`, 통합 스냅샷의 `progress` | B61 서비스 저장소의 `reader_progress`. 작품·판본·canonical locator·이어 읽기 위치를 사용자별로 저장 |
| 하이라이트·밑줄·메모·책갈피 | `storymemory.annotations.v2` (legacy `v1`도 읽음), 통합 스냅샷의 `annotations` | B61 서비스 저장소의 `annotations`. 원문 전체 대신 현재 계약상 필요한 locator, 범위, 발췌 길이 제한값, 사용자 메모를 기록 |
| 사용자 Memory·AI Memory·북마크 Memory | `storymemory.userMemories.v1`, 통합 스냅샷의 `memories` | B61 서비스 저장소의 `memories`; stable client record ID와 소유자별 unique key 사용 |
| 복습 시각/Recall 상태 | `storymemory.recallState.v1`, `storymemory.contextEntityLedger.v1`, 통합 스냅샷 | 사용자가 만든 복습 상태만 관련 Memory와 묶어 `recall_items`에 동기화. entity ledger는 검색용 파생 상태라 별도 원본으로 동기화하지 않고 서버/클라이언트에서 재구성 |
| 고정 항목 | `storymemory.pinnedEntities.v1` | 사용자가 고정한 항목 중 대상 Memory ID가 안정적으로 연결되는 값만 Memory의 사용자 설정으로 저장 |

대상 B61 저장소는 기존 `storymemory` Neon 스키마와 `reader_progress`, `annotations`, `memories`, `recall_items` 계약을 우선 검토한다. 현재 브라우저 adapter는 Neon Auth JWT를 전제로 하므로 padiem-auth 표를 그대로 Neon REST에 전달하지 않는다. 동기화 구현 전에 B61 서버 측 경로가 ES256/JWKS로 표를 검증하고 `sub` 소유권을 강제하도록 연결한다. 기존 Neon 사용자 ID와 공통 계정 `sub`의 소유권 대조 및 RLS/마이그레이션 검증이 끝나기 전에는 쓰기를 허용하지 않는다. 서비스 데이터는 padiem-auth에 저장하지 않는다.

동기화에서 제외할 값: 인증 쿠키/표, 이메일, 설치 ID, 화면 위치·필터 같은 임시 UI 설정, 콘텐츠 본문 캐시, sync cursor/state, 기기 로컬 로그. AI 대화 전문은 Memory로 명시적으로 저장한 항목 이외에는 동기화하지 않는다.

## 첫 로그인 때 로컬 데이터 이전

첫 로그인은 인증만 수행한다. 별도 동기화 단계에서 사용자가 로컬 레코드 수와 전송 범위를 확인하고 명시적으로 시작한 뒤 이전한다.

1. 현재 기기 백업을 만들 수 있게 하고 원본 localStorage를 읽기 전용으로 보존한다.
2. 로그인한 공통 계정 `sub`로 B61 서비스 저장소에 접근을 제한한다. 이메일이나 표시 이름으로 기존 Neon 계정을 병합하지 않는다.
3. 해당 사용자의 원격 상태가 비어 있으면 확인한 로컬 레코드를 stable client ID 기준으로 일괄 업로드한다. 각 레코드와 진행 위치는 재시도해도 중복 생성되지 않게 한다.
4. 원격 데이터가 있으면 양쪽 레코드 ID·수정 시각·revision을 비교한다. 동기화 완료 응답과 복구 가능한 백업을 확인하기 전에는 로컬 원본을 지우지 않는다.
5. 브라우저 저장량·네트워크 제한 때문에 전체 이전이 끝나지 않으면 미완료 상태를 사용자에게 표시하고 다음 로그인에서 이어간다.

## 여러 기기 충돌

- 레코드 ID와 소유자 ID가 같고 내용이 같으면 중복으로 취급한다.
- 독서 위치는 같은 작품·판본 안에서 가장 먼 읽기 위치를 knowledge ceiling으로 유지한다. 이어 읽기 위치는 그 작품의 마지막 변경 시각을 기준으로 별도로 선택한다. 작품·판본이 다르면 병합하지 않는다.
- 메모·Memory·하이라이트가 한 기기에서만 바뀌었으면 변경된 쪽을 적용한다. 두 기기에서 같은 레코드의 본문/선택 구간을 서로 다르게 바꾸면 자동 덮어쓰기 대신 충돌 사본을 남기고 선택을 사용자에게 맡긴다.
- 삭제는 동기화 tombstone으로 전파해 오프라인 기기가 오래된 값을 되살리지 않게 한다. 삭제 시각과 revision을 보존하고 보존 기간이 정해지기 전 tombstone을 제거하지 않는다.
- client timestamp만 신뢰하지 않는다. 서버 수정 시각과 revision을 기준으로 비교하고, 시계 차이/동시 변경은 충돌로 처리한다.

## 로그아웃 및 계정 탈퇴

- 로그아웃은 현재 공통 로그인 세션만 폐기한다. localStorage의 독서 위치·메모·Memory·북마크는 삭제하거나 다른 계정에 이동하지 않는다. 다음 로그인에서도 소유권 확인 전 기존 로컬 데이터를 자동 업로드하지 않는다.
- #6773의 공통 탈퇴 흐름은 서비스별 연결 해제와 데이터 삭제 확인을 순서대로 처리한다. 현재 B61은 #6773 수신 대상이 아니며 이번 단계에서는 탈퇴 RPC를 추가하지 않는다.
- B61 원격 동기화를 구현할 때 #6773 서비스 목록에 B61 삭제 수신기를 추가한다. 해당 계정의 `reader_progress`, `annotations`, `memories`, `recall_items`를 삭제 완료한 뒤에만 서비스 삭제 확인을 반환한다. 실패 시 계정 파기를 진행하지 않고 재시도를 허용한다.
- 공통 탈퇴는 브라우저가 오프라인인 기기의 localStorage와 사용자가 내려받은 백업 파일을 원격으로 지울 수 없다. 탈퇴 화면에서 이 한계를 알리고, 세션이 남아 있는 기기에서는 로컬 데이터 정리 선택을 제공한다. 원격 탈퇴 성공을 모든 기기·백업의 삭제로 표시하지 않는다.

## 검증 전제

동기화를 켜기 전 별도 승인 단계에서 Neon 기존 소유권 대조, B61 저장소의 공통 `sub` 검증, 레코드별 RLS, 재시도/충돌/tombstone, 계정 탈퇴 삭제 수신기, 데이터 내보내기·복원, 다중 기기 E2E를 확인한다. 이 커밋은 해당 원격 동작을 호출하거나 설정하지 않는다.
