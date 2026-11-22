# 다음 Chat 운영 배포 전 점검 (2026-11-18)

- 기준 운영 SHA: `4b8a3df14` (2026-11-18 04:38 KST, 마이그레이션 124까지)
- 대조 대상: `origin/main` = `503255544` (점검 시점 fetch 기준)
- 범위: 읽기·로컬 확인만. 운영 배포·운영 DB 조회/쓰기·운영 로그인은 하지 않았다.
- 절차 근거: `deploy/chat-release/README.md`, `deploy/chat-release/release_chat.ps1`, `deploy/host-com2/deploy_from_main.sh`, `docs/operations/PC_CONNECT_EXE_20261028.md`

## 1. 4b8a3df14..origin/main 머지 목록 (35건)

### 화면

| PR | 한 줄 제목 | 운영에 바뀌는 것 | 배포 뒤 확인 |
| --- | --- | --- | --- |
| #7997 | #7187 7차 옅은 안개 흰색 토큰화 | 정적 CSS | 5테마 대조 |
| #7993 | #7187 6차 짙은 남 잉크 색 토큰화 | 정적 CSS | 5테마 대조 |
| #7961 | 사이드바 최근 대화 대비·계정 단추 한 칸 | 정적 CSS/JS | 사이드바 5테마·좁은 폭 |
| #7980 | #7187 4차 패널면 씻김 색 토큰화 | 정적 CSS | 5테마 대조 |
| #7963 | T1 C2 history.css 바탕 색 토큰화 | 정적 CSS | 대화 화면 5테마 |
| #7959 | #7187 반투명 글자색 토큰화 | 정적 CSS | 5테마 대조 |
| #7949 | #7187 반투명 백색 토큰화 | 정적 CSS | 5테마 대조 |
| #7947 | Chat history timeline | 정적 JS | 대화 화면 타임라인 |
| #7946 | AI 명예회원 소개를 받은함 상세에 표시 | 정적 JS + 마이그레이션 126 | 상세 화면·행 없을 때 |
| #7945 | 공용 로그인 화면 튜토리얼 4단계 소스 | 정적 자산 | 로그인 전 튜토리얼 |
| #7988 | 발행한 새 소식 출처만 바로잡는 옵션 | 새 소식 도구 | 9·11번 출처 dry-run → --apply → 화면 |

### PC 연결·도구

| PR | 한 줄 제목 | 운영에 바뀌는 것 | 배포 뒤 확인 |
| --- | --- | --- | --- |
| #7990 | 세션 실패 이력으로 '명령 준비 안 됨' 표시 | 정적 JS + 컴2 저장소 | 운영(큐 저장소)에서는 판정 조회가 거절돼 늘 '알 수 없음' → 효과 없음(해 없음). '연결됨' 그대로가 정상. 실제 판정은 #7987 둘째 PR 뒤 |
| #7986 | 드라이브 루트·없는 경로 구분, 도구 스키마 정리 | 컴2 MCP 서버·엔진 | 루트·없는 경로·offset |
| #7984 | 한글 경로·한글 검색어 실패 수정 | 컴2·엔진·PC 명령 | 서피스 한글 왕복 |
| #7971 | 설치 파일 10분 안내·만료 다시 받기 | 정적 JS + 서버 헤더 | 카드·모달·안내 창 |
| #7966 | 이미 설치된 PC에서 갱신 설치 시 에이전트 교체 | exe 자산 코드 | 서피스 갱신 설치 |
| #7964 | 내 컴퓨터 카드 안내 창 → 설치 흐름 | 정적 JS | Claw 안내 창 |
| #7970 | B54 세션 만료 재로그인 안내 오류 분리 | 컴2 오류 코드 | 세션 만료 안내 |

### 리팩터링

| PR | 한 줄 제목 | 운영에 바뀌는 것 | 배포 뒤 확인 |
| --- | --- | --- | --- |
| #7996, #7992, #7985, #7983, #7979, #7951, #7948 | T2 B7 1~10차 전달 함수 등록부 이동 | 정적 JS 구조 | 기존 화면 회귀 없음 |
| #7989, #7972, #7969 | #7187 색 토큰·PC 실행 전달 함수 | 정적 CSS/JS | 5테마 대조 |

### CI·시험·기타

| PR | 한 줄 제목 | 운영에 바뀌는 것 | 배포 뒤 확인 |
| --- | --- | --- | --- |
| #7982 | full pytest 를 main push·야간에도 실행 | CI만 | 없음 |
| #7968 | #7814 엔진 PC 호출표 골든 갱신 | 시험만 | 없음 |
| #7950 | 권위 계정 열쇠 읽기 RPC 스위치 ON | 워커 설정 | Control Plane 헬스 |
| #7940 | S37 BYOK 키 확인 상한 공유 D1 카운터 | 마이그레이션 125 + 컴2 | 제한 동작 |
| #7952 | 배포마다 새 소식 쓰기 규칙 문서화 | 문서 | 새 소식 절차 준수 |

## 2. 운영 영향 있는 것

### 마이그레이션

| 번호 | 파일 | 내용 | 되돌림 | 예상 행 수 |
| --- | --- | --- | --- | --- |
| 125 | `apps/padiem-chat/migrations/125_byok_probe_windows.sql` | 소유자별 BYOK 탐색 시도 횟수를 담는 `byok_probe_windows` 표 생성. 키·요청 본문·로그는 저장하지 않음 | `CREATE TABLE IF NOT EXISTS`라 되돌리려면 `DROP TABLE byok_probe_windows` 수동 실행(데이터 소실). 저장소에 down 파일 없음 | 소유자 × 시간 창 수. 운영 DB 조회 금지로 미측정 |
| 126 | `apps/padiem-chat/migrations/126_ai_tester_intro.sql` | AI 명예회원 계정만의 짧은 소개(`ai_tester_intro`) 표 생성. `users(id)` 참조, 삭제 연쇄 | 동일하게 수동 DROP. down 파일 없음 | AI 명예회원 수만큼(초기 0행), 운영 미조회 |

적용 순서: 파일 번호 순서대로 **125 → 126**. 두 파일 모두 멱등(`IF NOT EXISTS`)이며 기존 표에 데이터를 넣지 않는다.

### 새 환경변수·설정·워커

- `packages/padiem-control-plane/wrangler.identity-authority.jsonc`: `CONTROL_PLANE_CONNECTOR_ACCOUNT_KEY_RPC_ENABLED: "true"` 추가. 읽기 전용 RPC 스위치이며 쓰기 RPC는 `false` 유지. Control Plane 워커 배포 필요.
- 컴2 앱: `mcp_gateway_*`, `oracle_mesh_read_return_routes.py`, `pc_pairing_connect_exe_asset.py`, `byok_probe_limit.py`, `ai_tester_intro_store.py`, `pc_command_ready_store.py` 변경.
- 프런트: `apps/padiem-chat/static/` 아래 다수(새 `pc-command-ready.js`, `pc-install-deadline.js` 포함).
- exe: `docs/operations/PC_CONNECT_EXE_20261028.md`와 `pc_pairing_connect_exe_asset.py`의 `CONNECT_EXE_SHA256 = 223999a4…3441df`는 main에서도 동일. 자산·문서 지문은 `release_chat.ps1` step 5에서 고정 SHA의 정적 자산 sha256으로 대조된다.

## 3. 배포 절차와 롤백

### 정상 배포 순서 (`deploy/chat-release/README.md`)

1. `git fetch origin` 후 배포 SHA 고정(`-Sha`, 기본 main).
2. 컴2 OPS 체크아웃에서 `deploy_from_main.sh <sha> --apply` 실행, `chat:PASS`/`chat:SKIP` 요구. 배포 요약의 `file-lane` 항목은 네 상태 중 하나다: 소스 변경 없음+건강 `PASS`, 소스 변경 없음+실패 `FAIL`(보고만, 게이트 통과), 소스 변경+건강 `INSTALL_PENDING`(게이트 통과), 소스 변경+실패 `FAIL`(게이트 중단). `STAGE_ONLY`는 `SKIP reason=STAGE_ONLY`. 파일 레인 소스가 바뀐 배포는 설치기를 자동 실행하지 않고 보고에 `FILE_LANE_INSTALL=APPROVAL_REQUIRED` 한 줄을 남긴다 — 별도 승인 단계에서 `deploy/host-com2/file-lane/install.sh`를 실행한 뒤 `INSTALL_PENDING`이 해소된다.
3. 화면 Worker `padiem-chat-front`: 이전 Version ID 기록 → `npx wrangler deploy --keep-vars`.
4. pages 거울: `node build.mjs` → `npx wrangler pages deploy`.
5. `/health`·`/privacy` 200, 정적 자산 sha256 대조, 도메인 확인. 실패 시 기록된 Version으로 자동 롤백.
6. 첫 실행은 `-DryRun`, 10분 내 재실행은 `-Force`.

### 롤백

- 화면(front): `npx wrangler rollback 03a68ba7-7fcb-45e6-a3a8-3ce25426c7d7`
- 컴2 앱: 옛 SHA 로 되돌리기 불가 — `deploy_from_main.sh` 는 origin/main 이 아닌 SHA 를 `SHA_NOT_ORIGIN_MAIN` 으로 거부한다(우회 플래그 없음). revert PR 로만 되돌린다.
- 마이그레이션: 저장소에 자동 down이 없어 125·126을 수동 `DROP TABLE` 해야 한다. 데이터 소실을 막으려면 표를 남기고 코드만 이전 SHA로 되돌리는 편이 안전하다.
- 순서: 화면 롤백 → (필요할 때만) 마이그레이션 수동 처리. 단, 화면과 서버 코드의 10분 안내 헤더가 맞물려 있으므로 화면만 되돌리면 안내 문구가 사라진다.

> 2026-11-19 정정: 배포 당일 실제 롤백에서 두 줄이 틀렸음이 확인됐다. 위 원문(`c17d0603-…`, `deploy_from_main.sh 4b8a3df14 --apply`)은 11-16 자산과 실행 불가능한 명령이었다. 11-18 05시 운영 front 는 `03a68ba7` 이었고, 컴2 앱은 origin/main 위상 때문에 옛 SHA 재배포가 구조적으로 거부된다(`SHA_NOT_ORIGIN_MAIN`). 11-19 롤백에서 front 만 `03a68ba7` 로 되돌렸고 컴2 는 유지했다.

## 4. 배포 뒤 확인 목록

1. USAGE_FLOW 점검.
2. 새 소식 9·11번 출처 수정(#7847): `chat_news_publish.py` dry-run(기본) 출력 확인 → `--apply` → 화면에서 출처 표시 확인.
3. 사이드바(#7961) 5테마 × 1440·390 대조.
4. 서피스에서 민규 PC 재연결.
5. 서피스(또는 컴1)에서 PC 도구 확인: 한글 경로, 한글 검색어, 드라이브 루트, 없는 경로(`pc_path_not_found`), 명령 준비 표시(#7990 은 효과 없음 — '연결됨' 유지가 정상).
6. PC 연결 10분 안내: 카드·모달·Claw 안내 창, 만료 후 다시 받기.
7. Control Plane 새 RPC 스위치 헬스, BYOK 제한 동작.
8. exe 지문 `223999a4…3441df`가 배포 자산과 문서에서 같은지 대조, 서피스 갱신 설치 시 서비스 재등록 확인.

## 5. 열린 PR과 다시 돌릴 부분

| PR | 제목 | 상태 | 머지 뒤 다시 돌릴 것 |
| --- | --- | --- | --- |
| #8000 | locale.js 쓰임새 묶음 분리 | MERGEABLE | 5테마 전체 캡처 |
| #7999 | PC 도우미 준비 상태 관찰(#7987 ①) | MERGEABLE | PC 명령 준비 표시 |
| #7998 | 로그인 창 색 토큰(#7811) | MERGEABLE | 로그인 전 5테마 |
| #7928 | conversation_turn 축소 | Draft | 대화 화면 회귀 |
| #7848 | 처리방침 문장 | Draft | 문서 검토만 |

요청에서 언급된 #7961(사이드바)·#7992(B7 9차)·#7993(#7187 6차)은 이미 이 배포 범위에 머지되어 있다.

## 배포 막는 것

**없음.** 마이그레이션 125·126은 표 생성뿐이고 되돌림은 수동 DROP이며, exe 지문은 main에서 동일하다. 단, Control Plane RPC 스위치 ON과 125 BYOK 카운터는 배포 뒤 항목 7 확인이 필요하다.
