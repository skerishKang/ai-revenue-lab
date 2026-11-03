# B61 공통 로그인 및 동기화 설계

작성일: 2026-11-04
범위: 로그인·로그아웃과 독서 기록 동기화 계약. 동기화는 `STORYMEMORY_SYNC_ENABLED=true`와 D1 준비가 함께 완료되기 전까지 켜지지 않는다.

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

| 데이터 | 현재 로컬 위치 | 2단계 동기화 범위와 위치 |
|---|---|---|
| 독서 위치·이어 읽기 | `storymemory.readerProgress.*`, `storymemory.readerResume.*`, 통합 스냅샷의 `progress` | D1 `storymemory_sync_records`의 `progress` 항목. 작품·책·장·페이지·시각·이어 읽기를 사용자별로 저장 |
| 하이라이트·밑줄·주석 | 정확 locator 저장소 `storymemory.annotations.v1`, 호환 주석 `storymemory.annotations.v2` | 같은 D1 표의 `annotation` 항목. 위치, 선택 구간, 사용자가 표시한 문구와 표시 메모를 저장 |
| 사용자가 직접 작성한 일반 메모 | `storymemory.userMemories.v1` 중 `kind=note` | 같은 D1 표의 `note` 항목. 메모 본문은 계정 간 격리하며 로그에 넣지 않음 |
| 책갈피 | 정확 locator 저장소 `storymemory.annotations.v1`의 `kind=bookmark` | 같은 D1 표의 `bookmark` 항목. 로컬 북마크 메모 복제본은 별도 메모로 중복 전송하지 않음 |
| 사용자 Memory·AI Memory, Recall·고정 항목 | `storymemory.userMemories.v1`, `storymemory.recallState.v1`, `storymemory.contextEntityLedger.v1`, `storymemory.pinnedEntities.v1` | 이번 2단계에서 제외. 후속 범위로 남기며 별도 `memories`·`recall_items` 저장은 하지 않음 |

이번 구현은 Pages `_worker.js`의 `/api/sync/*`를 거쳐 D1 바인딩 `STORYMEMORY_DB`를 사용한다. 브라우저는 access token을 보내지 않으며 서버가 HttpOnly 세션 쿠키의 padiem-auth ES256 표를 JWKS로 확인하고, 검증된 `sub`로 모든 쿼리를 제한한다. Neon REST와 기존 Neon 소유자 표는 이 경로에서 사용하지 않는다. D1 스키마는 `apps/storymemory/migrations/0001_storymemory_reading_sync.sql`에만 추가했으며 원격 D1에 적용하지 않았다.

동기화에서 제외할 값: 인증 쿠키/표, 이메일, 화면 위치·필터 같은 임시 UI 설정, 콘텐츠 본문 캐시, 동기화 본문을 담은 로컬 대기열, 기기 로컬 로그. 기존 설치 ID는 충돌 판정용 `device_id` 헤더로만 보내며, 신규 안정 레코드 ID는 불투명한 난수로 만든다. 이미 로컬에 남은 설치 ID 접두 레코드 ID는 동의 이전에서 불투명 ID로 교체한다. AI 대화와 AI Memory·Recall은 이번 범위에서 동기화하지 않는다.

## 첫 로그인 때 로컬 데이터 이전

첫 로그인은 인증만 수행한다. 동기화 기능이 켜져 있으면 “이 기기의 기록을 계정에 옮길까요?” 화면에서 독서 위치, 주석·일반 메모, 책갈피 범위를 고르고 명시적으로 시작한다. 동기화 동의는 계정과 기기 조합으로 D1에 저장해 다른 계정의 브라우저 기록이 자동 업로드되지 않게 한다.

1. 현재 기기 백업을 만들 수 있게 하고 원본 localStorage를 읽기 전용으로 보존한다.
2. 로그인한 공통 계정 `sub`로 B61 서비스 저장소에 접근을 제한한다. 이메일이나 표시 이름으로 기존 Neon 계정을 병합하지 않는다.
3. 로컬 원본은 읽기 전용으로 유지하고 stable client record ID 기준으로 전송한다. 중단·네트워크 실패 시 본문은 로컬 원본에서 다시 읽고, 대기열에는 레코드 ID와 revision만 저장한다.
4. D1이 없거나 준비되지 않았으면 503 `동기화 준비 중`으로 응답하고 로컬 기능은 계속 작동한다. 일부 전송 뒤 취소·실패해도 로컬 원본을 지우지 않으며 재시도는 멱등으로 처리한다.
5. 전송 완료 후 서버 스냅샷을 내려받아 적용하고, 이후 해당 기기에서 선택한 범위만 조용히 동기화한다. 오프라인 변경은 레코드 ID 대기열에 두고 연결 복구 시 다시 읽어 전송한다.

## 여러 기기 충돌

- 레코드 ID와 소유자 ID가 같고 내용이 같으면 중복으로 취급한다.
- 독서 위치는 같은 작품·판본 안에서 가장 먼 읽기 위치를 knowledge ceiling으로 유지한다. 이어 읽기 위치는 그 작품의 마지막 변경 시각을 기준으로 별도로 선택한다. 작품·판본이 다르면 병합하지 않는다.
- 주석·일반 메모·책갈피는 서버 revision으로 stale edit를 찾는다. 서로 다른 기기의 같은 항목 내용이 달라졌으면 timestamp와 device ID로 대표본을 고르고 다른 쪽은 `conflictOf`가 있는 충돌 사본으로 남긴다. 사용자는 충돌 사본을 일반 기록처럼 확인·편집·삭제할 수 있다.
- 삭제는 동기화 tombstone으로 전파해 오프라인 기기가 오래된 값을 되살리지 않게 한다. 삭제 시각과 revision을 보존하고 보존 기간이 정해지기 전 tombstone을 제거하지 않는다.
- client timestamp만 신뢰하지 않는다. 서버 revision으로 stale edit를 판별하고, 충돌이 확인된 경우 `(client_updated_at, device_id)` 순서로 대표본을 정한다. 독서 위치는 같은 항목의 furthest chapter/page를 되돌리지 않으며 이어 읽기 위치는 이 순서로 결정한다.

## 로그아웃 및 계정 탈퇴

- 로그아웃은 현재 공통 로그인 세션만 폐기한다. localStorage의 독서 위치·메모·Memory·북마크는 삭제하거나 다른 계정에 이동하지 않는다. 브라우저 동기화 대기열의 ID·hash·revision은 비우고, 다른 계정은 그 계정·기기 조합의 전송 범위 확인 전 로컬 기록을 업로드하지 않는다.
- #6773의 공통 탈퇴 흐름은 서비스별 연결 해제와 데이터 삭제 확인을 순서대로 처리한다. 현재 B61은 #6773 수신 대상이 아니며 이번 단계에서는 탈퇴 RPC를 추가하지 않는다.
- B61 삭제 수신기는 `POST /internal/account-delete`에서 `STORYMEMORY_ACCOUNT_DELETE_RPC_SECRET`로 #6773 v2 HMAC, 요청 시각, service UUID, operation UUID, 엄격한 JSON 계약을 검증한다. 처리 완료 영수증에는 service/operation UUID, 계정 ID의 SHA-256, 상태·시각만 남긴다. 해당 계정의 D1 동기화 레코드와 기기별 동기화 설정을 원자적으로 삭제하고, 반복 요청은 새 데이터를 다시 지우지 않도록 멱등 처리한다.
- 공통 탈퇴는 브라우저가 오프라인인 기기의 localStorage와 사용자가 내려받은 백업 파일을 원격으로 지울 수 없다. 탈퇴 화면에서 이 한계를 알리고, 세션이 남아 있는 기기에서는 로컬 데이터 정리 선택을 제공한다. 원격 탈퇴 성공을 모든 기기·백업의 삭제로 표시하지 않는다.

## 동기화를 켜는 순서

1. Cloudflare Pages에 D1 데이터베이스를 만든다.
2. `apps/storymemory/migrations/0001_storymemory_reading_sync.sql`을 D1 migration으로 적용한다.
3. Pages 프로젝트 `storymemory-padiem`에 `STORYMEMORY_DB` 바인딩을 추가한다.
4. Pages secret `STORYMEMORY_ACCOUNT_DELETE_RPC_SECRET`을 공통 탈퇴 RPC 서명 설정과 맞춰 넣는다. padiem-auth 등록/클라이언트 키는 로그인 표준의 별도 설정값을 사용한다.
5. 관련 계약·다중 기기·탈퇴 수신 시험이 통과한 뒤 Pages 변수 `STORYMEMORY_SYNC_ENABLED=true`로 켠다. 기본값은 off다.

이 변경은 원격 D1 적용, 바인딩, secret 설정, 스위치 변경, 배포를 수행하지 않는다. Memory·Recall 동기화는 후속 단계다.
