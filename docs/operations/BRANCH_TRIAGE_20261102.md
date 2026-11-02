# 브랜치 정리 결과 — 2026-11-02

기준: clone한 main은 `c188eb38`이고 분류를 확정한 시점의 `origin/main`은 `375293567`이다(2026-11-02). 조사 중 #6697·#6698·#6699가 main에 들어왔고, 대상 브랜치와 관련된 것은 #6697 하나다(아래 A에 머지로 기록). 삭제 직전에 `origin/main`을 다시 확인해 삭제 대상 204개가 여전히 고유 커밋 0인지 검증했다.

대상은 main에 머지되지 않았고 마지막 커밋이 2026-10-25 이후인 원격 브랜치 406개다. dependabot 등 자동 브랜치는 제외했다.

## 요약

| 분류 | 개수 | 원격 삭제 |
|---|---:|---:|
| A 대체됨 | 374 | 204 |
| B 살릴 것 | 12 | 0 |
| C 버릴 것 | 20 | 0 |
| 합계 | 406 | 204 |

- A 204개는 고유 커밋이 0(`git cherry` 결과에 `+` 없음)이라 원격에서 지운다.
- 나머지 A 170개는 squash 병합이나 중간 브랜치 병합으로 patch-id가 달라 고유 커밋처럼 보인다. 내용은 main에 있지만 지시대로 보존한다.
- B·C는 지우지 않는다.

## 판정 방법

- 대상 선정: `git branch -r --no-merged origin/main` ∩ `git for-each-ref` 마지막 커밋 2026-10-25 이후. dependabot 등 자동 브랜치 제외 → 406개.
- 고유 변경: `git diff origin/main...<branch> --stat`(3점 diff, merge-base→branch)와 `git cherry origin/main <branch>`(`+` = main에 없는 patch, `-` = main에 있는 patch).
- 같은 내용이 main에 있는지: 연결 PR의 상태·base·닫힌 사유를 확인하고, 브랜치가 추가한 줄(25자 이상)을 `origin/main:<path>` 본문과 대조했다. 파일이 main에 없으면 고유 작업으로 본다.
- 삭제 조건: A 중 `git cherry` 결과에 `+`가 하나도 없는 브랜치. 고유 커밋이 있는 A, B, C는 지우지 않는다.

## B — 살릴 것

| 브랜치 | 남은 일 | 크기 |
|---|---|---|
| `astra4/auth-bootstrap-error-reporting-20261029` | 배포 도구 stderr 보존과 비밀 마스킹(`redactDiagnostics`)을 현재 main 기준으로 다시 올린다. #6243은 대체 PR 없이 닫혔고 변경은 main에 없다. | S |
| `astra4/identity-notifier-stage-later-20261029` | `identity_account_block_notifier` 모듈·시험(982줄)을 main에 올리고 계정 차단 알림 연결 지점을 정한다. | M |
| `feat/b61-shared-auth-sync-261101` | 익명 동기화 데이터 경계 시험을 통합 브랜치에 포함해 올린다. | S |
| `feat/b61-v11-backup-261101` | 백업·복원과 익명 동기화 경계를 통합 브랜치와 함께 올린다. 복원 할당량 실패 처리 확인이 남아 있다. | M |
| `feat/b61-v11-integration-261101` | StoryMemory 1.1 스택의 통합 브랜치다. 백업·설정·문구 변경을 한 PR로 올려 브라우저 시험 후 머지한다. | M |
| `feat/b61-verse-lookup-261101` | 성경 구절 참조 검증과 시험을 올린다. | S |
| `fix/b61-memory-current-main-261101` | 최신 main 베이스의 같은 변경이다. relevance 브랜치와 중복이므로 이쪽 하나만 채택해 올린다. | S |
| `fix/b61-memory-relevance-261101` | 무관한 기억·미래 항목 숨김 변경을 올린다. `fix/b61-memory-current-main`과 같은 변경이므로 최신 베이스 하나만 채택한다. | S |
| `fix/b61-mobile-qa-261101` | 모바일 페이지 넘김 조작 복구를 올린다. | S |
| `fix/b61-reader-settings-main-261101` | 읽기 설정·키보드 접근 4커밋(94줄)을 올린다. `fix/b61-reading-settings`의 상위 집합이다. | S |
| `fix/b61-reading-settings-261101` | `fix/b61-reader-settings-main`과 같은 변경의 옛 베이스다. 그 브랜치를 채택하고 이 브랜치는 참고용으로 둔다. | S |
| `fix/b61-service-copy-261101` | 독자 안내 문구·출처 라벨 정리 3커밋을 올린다. | S |

StoryMemory 1.1 10개 브랜치는 한 스택이다. `feat/b61-v11-integration-261101`을 정본으로 삼고, 그 위에 백업·기억·모바일·읽기 설정·문구 변경을 합쳐 올린다. `fix/b61-memory-relevance-261101`와 `fix/b61-memory-current-main-261101`, `fix/b61-reading-settings-261101`와 `fix/b61-reader-settings-main-261101`는 각각 같은 변경의 다른 베이스이므로 최신 베이스 하나만 채택한다.

### StoryMemory 1.1 통합 완료 — #6703

최신 main(`01990c73e`)에서 `feat/b61-v11-261103`을 만들어 위 8개 브랜치를 차례로 합치고 #6703으로 squash 머지했다(머지 SHA `3c4bf4e65`). 아래 10개 브랜치는 이 통합에 모두 반영되어 원격에서 삭제했다.

`feat/b61-v11-integration-261101`, `feat/b61-v11-backup-261101`, `feat/b61-shared-auth-sync-261101`, `feat/b61-verse-lookup-261101`, `fix/b61-memory-current-main-261101`, `fix/b61-memory-relevance-261101`, `fix/b61-mobile-qa-261101`, `fix/b61-reader-settings-main-261101`, `fix/b61-reading-settings-261101`, `fix/b61-service-copy-261101`

통합 확인: StoryMemory 단위·브라우저 시험 전체와 390·1440 백업·복원·익명 동기화·읽기 설정·페이지 넘김, 복원 할당량 실패 롤백 시험을 통과했다. 배포는 하지 않았다.

### astra4 인증 브랜치 2개 처리 완료 — #6705 · #6706

B 목록의 astra4 두 브랜치를 최신 main 기준으로 다시 올려 머지했고, 원본 브랜치는 원격에서 삭제했다.

- `astra4/auth-bootstrap-error-reporting-20261029`: 배포 도구 stderr 보존과 비밀 마스킹(`redactDiagnostics`)을 `apps/padiem-auth/bootstrap-deploy.mjs`에 다시 올렸다. 생성 비밀값(원문·JSON 이스케이프·URI 인코딩·개인키 `d`)과 `CLOUDFLARE_API_TOKEN`·`CLOUDFLARE_ACCOUNT_ID`가 진단 출력에 남지 않는 시험을 포함했다. #6705 머지 SHA `83651e73b`.
- `astra4/identity-notifier-stage-later-20261029`: `identity_account_block_notifier` 모듈과 시험을 올렸다. 현재 main의 계정 차단 경로는 `apps/padiem-auth/worker.mjs:73-85`와 `apps/padiem-auth/state.mjs:52-58`이고, 알림은 그 경로로 전달하는 호출자 쪽에 연결했다. 연결 지점은 `packages/padiem-control-plane/identity_authority_worker.py:9`의 named entrypoint 하나이며 기본 RPC 표면은 바꾸지 않았다. #6706 머지 SHA `66227244d`.

두 PR 모두 배포는 하지 않았다.

## C — 버릴 것

| 브랜치 | 이유 |
|---|---|
| `astra4/chat-com2-cutover-plan-20261029` | #6190 종료. 대표 결정(2026-10-30) "Chat 본체 컴2 이전 보류"에 따라 닫힌 초안이다. |
| `astra4/chat-handback-offline-20261029` | #6200 종료. Chat 컴2 이전 보류 결정에 따라 닫힌 오프라인 리허설 초안이다. |
| `astra4/chat-handback-options-20261029` | #6197 종료. Chat 컴2 이전 보류 결정에 따라 닫힌 선택지 비교 초안이다. |
| `astra4/chat-ledger-bootstrap-20261029` | #6196 종료. Chat 컴2 이전 보류 결정에 따라 닫힌 장부 채택 초안이다. |
| `astra4/chat-local-cpu-measurement-20261029` | #6211 종료. Chat 컴2 이전 보류 결정에 따라 닫힌 측정 초안이다. |
| `astra4/chat-migration-ledger-20261029` | #6192 종료. Chat 컴2 이전 보류 결정에 따라 닫힌 읽기 전용 대조 도구다. |
| `astra4/chat-pyproxy-nogil-audit-20261029` | #6225 종료. Chat 컴2 이전 보류 결정에 따라 닫힌 정적 조사다. |
| `astra4/chat-snapshot-route-plan-20261029` | #6215 종료. Chat 컴2 이전 보류 결정에 따라 닫힌 라우트 분리 초안이다. |
| `astra4/chat-worker-cpu-20261029` | #6208 종료. Chat 컴2 이전 보류 결정에 따라 닫힌 예약 실행 import 지연 실험이다. |
| `astra4/chat-worker-freeze-20261029` | #6194 종료. Chat 컴2 이전 보류 결정에 따라 닫힌 쓰기 동결 초안이다. |
| `astra4/chat-worker-vendor-trim-20261029` | #6217 CTO 종료. 기대 효과가 스냅숏 크기 축소뿐이고 pywrangler 꾸러미 구조 변경이 필요해 추진하지 않는다. |
| `astra4/com2-pc-coupling-design-20261029` | #6202 종료. Chat 컴2 이전 보류 결정에 따라 닫힌 연결 설계 초안이다. |
| `astra4/lovetree-shared-google-identity-20261029` | #6232 종료. 2026-10-30 padiem-auth 공통 로그인 표준으로 대체된 이전 설계다. |
| `astra4/migration-trigger-guard-20261029` | #6195 종료. Chat 컴2 이전 보류 결정에 따라 닫힌 트리거 안전 이전 초안이다. |
| `feat/5318-owner-model-usage-console` | #5863 CLOSED(2026-10-30, main 충돌 장기 방치)이고 이슈 #5318도 2026-10-31 종료됐다. 변경은 main에 없다. |
| `feat/5573-limits-web-xlsx-071-gate` | #5878 CLOSED. 웹 XLSX 상한은 이후 1GiB tus 업로드 경로로 해결됐다. |
| `feat/5895-util-revise-draft-261028` | 2026-11-01 Chat 유틸 메뉴 통합으로 축사·SNS·회의정리 도구가 `apps/padiem-council-apps`로 이동했다. 이 브랜치가 고치던 Chat 안의 초안 편집 화면은 main에 없다. 기능이 필요하면 council 앱에서 새로 만든다. |
| `ops/5643-retire-legacy-mesh-tunnel-261029` | #6214 CLOSED이고 이슈 #5643도 2026-10-30 종료됐다. 아카이브 방향이 폐기됐다. |
| `perf/chat-worker-cold-import-261031` | 마지막 커밋이 "기록용·머지 안 함"이라고 밝힌 측정 기록 브랜치다. PR이 없다. |
| `test/tus-hardening-261101` | main이 공용 `static/tus-upload.js`로 tus를 자체 구현했다. 외부 벤더 클라이언트 방식은 채택되지 않았다. |

## A — 대체됨 (374개)

`삭제` 열이 `삭제`인 브랜치가 원격에서 지운 대상이다.

| 브랜치 | 마지막 커밋 | 고유 커밋 | 규모 | 근거 | 삭제 |
|---|---|---|---|---|---|
| `astra4/6282-worktree-snapshot-261030` | 2026-10-30 `17cabc978` Kilo — Preserve earlier local login worktree snapshot [skip ci] | +29/−0 | 31개 / +1643−3 | PR 없음 · 내용 main 확인 |  |
| `astra4/auth-bootstrap-jwks-20261029` | 2026-10-29 `026055d0d` skerishKang — Expose public JWKS during auth bootstrap | +0/−1 | 2개 / +19−0 | #6241 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `astra4/auth-callback-diagnostics-20261030` | 2026-10-30 `a2817bae9` skerishKang — Keep only stage and status in auth diagnostics | +14/−0 | 6개 / +97−28 | #6260 MERGED(base main) · 병합 후 커밋 없음 |  |
| `astra4/auth-preview-config-20261030` | 2026-10-30 `4301c9a10` skerishKang — Configure PADIEM auth LoveTree preview client | +0/−1 | 1개 / +4−0 | #6256 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `astra4/chat-compare-auth-client-20261030` | 2026-10-30 `fb5103db8` skerishKang — Test the Chat comparison callback and public key | +2/−0 | 2개 / +14−1 | #6273 MERGED(base main) · 병합 후 커밋 없음 |  |
| `astra4/chat-login-callback-261030` | 2026-10-30 `4a2520c12` Kilo — Allow Chat common login callback | +0/−1 | 2개 / +5−2 | #6295 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `astra4/chat-shared-auth-prep-20261030` | 2026-10-30 `82e31bd85` skerishKang — Include reviewed comparison bindings in inventory contract | +26/−0 | 23개 / +1098−0 | #6267 MERGED(base main) · 병합 후 커밋 없음 |  |
| `astra4/chat-worker-init-singleflight-20261029` | 2026-10-30 `2069405df` skerishKang — Update Worker composition contract tests for single-fligh… | +4/−0 | 12개 / +854−713 | #6223 MERGED(base main) · 병합 후 커밋 없음 |  |
| `astra4/lovetree-direct-google-design-20261029` | 2026-10-29 `4a8954afa` skerishKang — docs: define PADIEM shared authentication standard | +0/−1 | 2개 / +63−0 | #6231 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `astra4/lovetree-production-auth-20261030` | 2026-10-30 `d0453e503` skerishKang — Test production client registration | +2/−0 | 2개 / +21−1 | #6269 MERGED(base main) · 병합 후 커밋 없음 |  |
| `astra4/padiem-auth-deploy-gate-20261029` | 2026-10-29 `e3ba97d28` skerishKang — Run exact-head deployment gate checks | +3/−1 | 1개 / +135−0 | #6238 MERGED(base main) · 병합 후 커밋 없음 |  |
| `astra4/padiem-auth-domain-gate-20261029` | 2026-10-29 `498cbca7e` skerishKang — Add guarded auth custom-domain activation | +0/−1 | 3개 / +243−0 | #6244 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `astra4/padiem-auth-gate-account-check-20261029` | 2026-10-29 `cbadedde0` skerishKang — Fix auth gate account check and bootstrap secrets over st… | +0/−1 | 3개 / +84−4 | #6240 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `astra4/padiem-auth-verifiers-20261029` | 2026-10-29 `5c54d8f1b` skerishKang — Add shared JS and Python access token verification | +0/−1 | 5개 / +181−0 | #6237 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `astra4/padiem-auth-worker-20261029` | 2026-10-29 `0e2fb9738` skerishKang — Add opt-in PADIEM auth worker | +0/−1 | 14개 / +915−0 | #6233 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `central/b64-d1-binding-987` | 2026-10-26 `6a12062fe` Hermes Agent — fix(b64): bind provisioned income D1 database #987 | +0/−1 | 1개 / +1−1 | #5840 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/5359-engine-d1-apply-gate` | 2026-10-30 `9c4a24270` Kilo — feat(5359): add guarded engine D1 apply workflow | +4/−0 | 11개 / +505−1 | #6293 MERGED(base main) · 병합 후 커밋 없음 |  |
| `chore/5359-engine-d1-apply-gate-261030` | 2026-10-30 `6aee103c0` Kilo — test(5359): enforce read-only D1 queries and inspect inbo… | +3/−0 | 5개 / +408−1 | #6290 MERGED(base main) · 병합 후 커밋 없음 |  |
| `chore/5359-engine-d1-apply-gate-v2` | 2026-10-30 `5941370f7` Kilo — fix(5359): inspect inbound references via schema SQL | +0/−1 | 2개 / +47−50 | #6292 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/5734-remove-ooxml-capacity-caps-261026` | 2026-10-26 `3b677f0e3` Kilo Bot — test(5734): state what the Chat reader refuses now, and w… | +3/−0 | 8개 / +122−86 | #5862 MERGED(base main) · 병합 후 커밋 없음 |  |
| `chore/5734-stage2-b14-response-ceilings-261026` | 2026-10-26 `9918f4619` Kilo Bot — Merge remote-tracking branch 'origin/main' into chore/573… | +0/−1 | 3개 / +20−11 | #5879 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/5734-stage2-ooxml-xlsx-residue-261026` | 2026-10-26 `25321bc50` Kilo Bot — test(5734): move the Core document canary pin with the co… | +10/−0 | 29개 / +539−251 | #5876 MERGED(base main) · 병합 후 커밋 없음 |  |
| `chore/5734-stage2-parser-report-char-check-261026` | 2026-10-26 `e2250fedf` Kilo Bot — Merge remote-tracking branch 'origin/main' into chore/573… | +0/−1 | 2개 / +35−11 | #5880 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/5734-stage2-pdf-caps-261026` | 2026-10-26 `e08c25f27` Kilo Bot — chore(5734): stop refusing a PDF for its length | +3/−0 | 8개 / +144−70 | #5869 CLOSED → #5876(스택) |  |
| `chore/5734-stage2-text-document-caps-261026` | 2026-10-26 `53c504842` Kilo Bot — chore(5734): keep the guarded word out of the Core docume… | +6/−0 | 22개 / +380−196 | #5874 CLOSED → #5876(스택) |  |
| `chore/5734-stage2-xlsx-caps-261026` | 2026-10-26 `50e1a2096` Kilo Bot — chore(5734): pin the canaries to the bytes a checkout pro… | +2/−0 | 4개 / +90−30 | #5867 CLOSED → #5876(스택) |  |
| `chore/5895-rename-repo-baseline-diff-counts-261027` | 2026-10-27 `f7d1cdb73` astra1 — ops(4318): name the repo-vs-baseline binding diff apart f… | +0/−1 | 4개 / +41−3 | #5962 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/5895-retire-per-migration-d1-gates-261027` | 2026-10-27 `d976162e2` skerishKang — chore(5895): keep the two gate tests surviving workflows … | +2/−0 | 59개 / +11−14510 | #5921 MERGED(base main) · 병합 후 커밋 없음 |  |
| `chore/astra-2-canary-repin-261026` | 2026-10-26 `572c028ac` skerishKang — chore(canary): re-pin document_normalization.py after #58… | +0/−1 | 2개 / +8−2 | #5837 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/leftover-pr-b-chat-dead-symbols-261029` | 2026-10-29 `8f16c542b` skerishKang — chore(chat): 죽은 심볼·alias·상한 이름을 걷어내고 main.py 재수출을 실제 소비자만… | +0/−1 | 14개 / +68−173 | #6245 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/leftover-pr-c-country-261029` | 2026-10-29 `6ee887d9d` skerishKang — test(council): 저장 문서의 country는 유지하고 chat 본문 키에서만 country를… | +3/−0 | 5개 / +39−69 | #6246 MERGED(base main) · 병합 후 커밋 없음 |  |
| `chore/leftover-pr-d-packages-engine-261029` | 2026-10-30 `fcba4d426` skerishKang — chore(leftover): PR-D 고아 모듈과 호환 재수출, 임의 상한을 제거한다 | +0/−1 | 34개 / +79−4874 | #6252 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/leftover-pr-e-hidden-switching-261029` | 2026-10-30 `7a143803a` skerishKang — chore(chat): 숨은 슬래시 등급 전환과 제공자 능력 행을 지운다 | +0/−1 | 13개 / +144−222 | #6253 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/leftover-pr-g-tier-registry-cas-261029` | 2026-10-30 `6f81c820a` skerishKang — style: 새로 넣은 tier 주석 2줄을 LF로 써서 diff whitespace gate를 통과시… | +1/−1 | 7개 / +30−801 | #6249 MERGED(base main) · 병합 후 커밋 없음 |  |
| `chore/leftover-pr-h-dead-ui-261030` | 2026-10-30 `e7d1c2557` skerishKang — chore(ui): 죽은 스킬 패널과 거짓 준비 중 안내를 화면에서 지운다 | +0/−1 | 8개 / +57−93 | #6248 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/leftover-pr-i-empty-promises-261030` | 2026-10-30 `37fdc225e` skerishKang — chore(ui): 빈 형식 안내와 꺼질 수 없는 연결 카드를 지운다 | +0/−1 | 5개 / +23−15 | #6250 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/leftover-pr-j1-dead-exports-261030` | 2026-10-30 `947debccc` skerishKang — chore: 쓰이지 않는 브라우저 전역 셋과 등급 문구 튜플을 지운다 | +0/−1 | 6개 / +35−21 | #6255 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/leftover-pr-k-task-modes-261029` | 2026-10-29 `5d070e0fe` skerishKang — feat(chat): 작업 모드 6종을 명부에서 지우고 서버가 미지 값으로 거절하게 한다 (C1) | +0/−1 | 6개 / +48−91 | #6247 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/leftover-pr-l-copy-labels-261030` | 2026-10-30 `6dd6d469b` skerishKang — fix(ui): Google 계정 링크를 내비게이션 허용 목록에 넣고 등급 알약 테스트 라벨을 새 라벨… | +2/−0 | 14개 / +60−25 | #6254 MERGED(base main) · 병합 후 커밋 없음 |  |
| `chore/leftover-pr-m-state-cap-261029` | 2026-10-30 `06c56b8b9` skerishKang — fix(chat): 32KiB 상태 상한을 형제 모듈과 같은 1MiB로 맞춘다 (B6) | +0/−1 | 2개 / +21−3 | #6251 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/pc-queue-switch-chat-261030` | 2026-10-30 `b9014ec59` zwork — feat(5573): PC 작업 대기열 전환 설정을 Chat에 선언한다 | +0/−1 | 2개 / +19−2 | #6261 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `chore/remove-chat-mode-remnant-261029` | 2026-10-29 `2d3d49ccd` skerishKang — qa(chat): 사후 인증 QA와 5785 하니스에서 mode를 요구하던 자리에 부존재 단언을 넣는다 | +4/−0 | 60개 / +409−462 | #6234 MERGED(base main) · 병합 후 커밋 없음 |  |
| `ci/3595-generic-pipeline` | 2026-10-29 `dc8f8058e` Kilo — ci(3595): 수집된 테스트 전부가 돌았는지 세어서 검사한다 | +2/−0 | 5개 / +123−8 | #6189 MERGED(base main) · 병합 후 커밋 없음 |  |
| `ci/b62-target-sha-input-guard-261029` | 2026-10-29 `dea3ec237` skerishKang — chore: 머지 상태 재계산을 위한 빈 커밋 (코드 변경 없음, 스쿼시 시 main에 남지 않음) | +0/−2 | 32개 / +2003−311 | #6209 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `ci/nightly-main-full-suite-phase2-261031` | 2026-10-31 `3c75134f2` skerishKang — ci: nightly round 2 — fix padiem_ai_core setup gaps and a… | +1/−0 | 1개 / +41−0 | PR 없음 · 내용 main 확인 |  |
| `design/5967-parliament-cinematic-261027` | 2026-10-28 `2d5e8e143` Kilo — fix(5967): lead every country's font stack with a shipped… | +9/−0 | 28개 / +2770−0 | #5974 MERGED(base main) · 병합 후 커밋 없음 |  |
| `design/6011-parliament-overseas-themes` | 2026-10-28 `3fda951cf` Kilo — Merge remote-tracking branch 'origin/main' into design/60… | +4/−0 | 8개 / +1286−315 | #6030 MERGED(base main) · 병합 후 커밋 없음 |  |
| `design/6421-parliament-final` | 2026-10-28 `7a9bbd115` Kilo — design(#6040): bring licensed parliament photos to the ov… | +0/−1 | 16개 / +77−34 | #6041 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `design/council-workspace-261031` | 2026-10-31 `78b318a18` Kilo — design(council): refine workspace layouts | +1/−0 | 6개 / +85−4 | #6393 CLOSED → #6622 |  |
| `diag/5573-astra-2-core-invoke` | 2026-10-26 `96c4e002a` skerishKang — test(5573): import diagnostics from its declared submodul… | +2/−0 | 7개 / +221−39 | #5855 MERGED(base main) · 병합 후 커밋 없음 |  |
| `docs/0f-pc-lessons-261026-astra1` | 2026-10-26 `697a270b2` skerishKang — docs(0F,5573): encode the 10-26 lessons — acceptance cove… | +0/−1 | 2개 / +27−2 | #5857 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/2002-memory-rag-inventory-261030` | 2026-10-30 `aed722e86` ccmkbs-web — docs(2002): 현황 집계 표의 이중 계산을 바로잡는다 | +2/−0 | 1개 / +213−0 | #6326 MERGED(base main) · 병합 후 커밋 없음 |  |
| `docs/2505-desktop-origin-scope-261026` | 2026-10-26 `a6ef63778` Hermes Agent — docs(ui): clarify desktop-only shared origin scope | +0/−1 | 1개 / +1−1 | #5847 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/3595-acceptance-matrix` | 2026-10-29 `6395cdb19` Kilo — docs(3595): 수용 항목을 현재 main과 하나씩 대조한 표를 남긴다 | +0/−1 | 2개 / +121−0 | #6188 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/3595-state-080-design` | 2026-10-29 `5287cb817` Kilo — fix(3595): 근거 JSON에서 임의 바이트 상한을 빼고 유효성만 본다 | +2/−0 | 3개 / +328−0 | #6193 MERGED(base main) · 병합 후 커밋 없음 |  |
| `docs/4139-native-process-lane-261029` | 2026-10-29 `20ac4a0b6` astra1 — docs(4139): the read-only probe that answers the two ques… | +2/−0 | 2개 / +513−0 | #6227 MERGED(base main) · 병합 후 커밋 없음 |  |
| `docs/5093-com2-restore-drill-261030` | 2026-10-30 `b9504fb3e` Kilo — docs(5093): document COM2 backup restore drill | +0/−1 | 1개 / +18−0 | #6287 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/5573-backup-bytes-not-links` | 2026-10-29 `9d19929d8` Kilo Bot — docs(5573): a backup is bytes - the host's executor "back… | +0/−1 | 1개 / +24−1 | #6180 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/5573-file-lane-install-fingerprint` | 2026-10-29 `08985037d` Kilo Bot — docs(5573): how the file lane should be installed, and ho… | +1/−0 | 1개 / +92−0 | #6181 MERGED(base main) · 병합 후 커밋 없음 |  |
| `docs/5799-speech-capture-261030` | 2026-10-30 `1f26c0af5` ccmkbs-web — docs(5799): 축사 화면 실측 캡처와 유틸 4종 비교표 | +0/−1 | 30개 / +1377−0 | #6317 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/5881-com2-binary-attachments-261030` | 2026-10-30 `dc4891f9d` astra1 — docs(5881): design binary attachment parsing through COM2… | +0/−1 | 1개 / +29−0 | #6321 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/5881-executor-queue-switch-261030` | 2026-10-30 `fb6bbc6c9` Kilo Bot — docs(ops): the executor half of the queue switch, prepare… | +0/−1 | 1개 / +184−0 | #6262 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/5881-postmortem-complete-261031` | 2026-10-31 `c1217b2ce` ccmkbs-web — docs(5881): 컴2 큐 전환 사후 기록에 전환 완료 절을 더한다 | +0/−1 | 1개 / +65−16 | #6333 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/5881-queue-oracle-failover-gap-261030` | 2026-10-30 `5a96d1a48` Kilo — docs(5881): analyze the Oracle-failover gap when the com2… | +0/−1 | 1개 / +186−0 | #6271 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/5895-operating-policy-one-page-summary-261027` | 2026-10-27 `56c611778` PADIEM AI LOCAL — docs(5895): let the one-page summary win over the body it… | +2/−0 | 1개 / +39−0 | #5961 MERGED(base main) · 병합 후 커밋 없음 |  |
| `docs/5895-owner-decision-pc-scope-261028` | 2026-10-28 `6155976e7` astra1 — docs(5895): record the 2026-10-28 owner decisions as tech… | +0/−1 | 2개 / +11−6 | #6002 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/5895-policy-conflict-sections-cleanup` | 2026-10-27 `0825f324a` astra1 — docs(5895): close the summary's conflict-section line to … | +2/−0 | 1개 / +7−18 | #5964 MERGED(base main) · 병합 후 커밋 없음 |  |
| `docs/5895-roadmap-installer-mesh-record-261028` | 2026-10-28 `24d5649b6` astra1 — docs(5895): mark the installer doc superseded and record … | +0/−1 | 2개 / +16−0 | #6009 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/5895-scope-resume-util-b66-261028` | 2026-10-28 `b5d8a4678` astra1 — docs(5895): resume Util and B66 scope as beta core (2026-… | +0/−1 | 2개 / +5−5 | #6003 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/5967-design-originals-archive-261030` | 2026-10-30 `e9708f82e` Kilo — docs(5967): archive the four original design concept PNGs… | +0/−1 | 7개 / +68−2 | #6268 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/6305-minimal-staging-20261030` | 2026-10-30 `f28f96f43` Hermes Agent — docs: record staging auth decision | +2/−0 | 1개 / +44−0 | #6310 MERGED(base main) · 병합 후 커밋 없음 |  |
| `docs/b14-runbook-and-inventory-261027` | 2026-10-27 `b1432a8ee` PADIEM AI LOCAL — docs(5784): retire the inventory rows that pointed at the… | +2/−0 | 2개 / +6−13 | #5918 MERGED(base main) · 병합 후 커밋 없음 |  |
| `docs/b64-auth-reconciliation-20261029` | 2026-10-29 `79a9b61f6` skerishKang — docs(b64): reconcile independent identity and shared auth… | +0/−1 | 1개 / +43−0 | #6094 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/browser-agent-lessons-tinyfish-20261027` | 2026-10-27 `8c410e8c7` skerishKang — docs: record TinyFish browser agent failures and recovery… | +0/−1 | 1개 / +41−0 | #5969 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/com2-host-facts-20261026` | 2026-10-26 `aa6211aab` skerishKang — docs(ops): record COM2 host facts and prepared landing ar… | +0/−1 | 1개 / +74−0 | #5891 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/com2-tunnel-runbook-20261026` | 2026-10-26 `28c8f8909` skerishKang — docs(ops): add COM2 tunnel preparation and Owner token ha… | +0/−1 | 1개 / +42−0 | #5892 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/cto-status-evening-261030` | 2026-10-30 `7b7e939e8` Kilo — docs(ops): 10-30 저녁 CTO 현황과 공통 인증 표준 현황 갱신 | +0/−1 | 2개 / +60−2 | #6309 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/file-lane-com2` | 2026-10-26 `c73f1c0c4` PADIEM AI LOCAL — docs(file-lane): record the COM2 file-lane decision and t… | +0/−1 | 2개 / +52−0 | #5883 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/leftover-classification-261029` | 2026-10-29 `ec6feb354` skerishKang — docs(leftover): A1·C9의 인용 수를 실측으로 정정한다 — skills 소비처는 테스트 … | +5/−0 | 1개 / +178−0 | #6235 MERGED(base main) · 병합 후 커밋 없음 |  |
| `docs/mvp-beta-principles` | 2026-10-26 `a504ef223` Kilo — docs(policy): 0G MVP/베타 운영 원칙 + 마스터 체크리스트 문서 (#5885) | +0/−1 | 2개 / +48−0 | #5886 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/pc-queue-com2-followup-261030` | 2026-10-30 `ceef026ae` opencode — docs(5881): record the confirmed cause of the 19:09 retest | +0/−1 | 1개 / +23−11 | #6313 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `docs/pc-queue-com2-postmortem-261030` | 2026-10-30 `81e5b1687` opencode — docs(5573): apply CTO review corrections to the COM2 post… | +2/−0 | 1개 / +179−0 | #6307 MERGED(base main) · 병합 후 커밋 없음 |  |
| `engine-b14-full-regression-5678` | 2026-10-27 `a1c8c1dfb` skerishKang — ci(5678): record the two new main-push jobs in the pinned… | +2/−0 | 3개 / +183−0 | #5960 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/2824-isolated-parser-authority-261025` | 2026-10-26 `3af0162e5` Kilo Bot — fix(2824): drop the canary and health edits main already … | +7/−0 | 33개 / +3851−253 | #5817 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/2833-scheduler-injection-seam` | 2026-10-30 `f6e2b9886` Kilo — feat(2833): 스케줄러에 store·identity·discovery 주입 seam을 연다 | +0/−1 | 2개 / +229−23 | #6213 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/3180-saved-pc-form` | 2026-10-29 `5fc9fdccf` Kilo — fix(3180): 종류 칸은 표 끝에 붙여 기존 제공 게이트 계약을 그대로 지킨다 | +2/−0 | 14개 / +1040−44 | #6184 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/3186-new-quote-paths` | 2026-10-29 `69b58a707` Kilo — test(3186): 비활성 파일 경로와 살아 있는 두 경로를 DOM 스텁으로 고정한다 | +2/−0 | 4개 / +269−7 | #6198 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/3595-gate-independence` | 2026-10-29 `3766ca64e` Kilo — fix(3595): 게이트마다 다른 것을 재게 하고, 같은 비교를 두 이름으로 세지 않는다 | +0/−1 | 3개 / +382−52 | #6191 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/4139-idle-poll-backoff-261029` | 2026-10-30 `0d3477737` astra1 — test(4139): the idle suite defines its own stub port inst… | +3/−0 | 3개 / +497−5 | #6212 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/4139-lighter-poll-beat-261029` | 2026-10-30 `a753d61ae` astra1 — test(4139): the beat suite defines what it needs instead … | +2/−0 | 4개 / +405−3 | #6219 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/4139-mesh-process-lane-261029` | 2026-10-30 `4efeab4f9` Kilo Bot — feat(4139): the stop takes the shape the observed agent a… | +2/−0 | 3개 / +894−3 | #6230 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/4434-claw-excel-pc-roundtrip-261025` | 2026-10-26 `b222da096` Kilo Bot — docs(4434): name the two remaining integration points pre… | +15/−0 | 19개 / +6929−1383 | #5835 CLOSED → #5994 |  |
| `feat/4434-office-chunk-web-return-261026` | 2026-10-26 `bf072dcb4` PADIEM UI 통합 LOCAL — docs(4434): record the owner-facing Office output read th… | +2/−0 | 4개 / +629−17 | #5850 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/4434-xlsx-revision-producer-261026` | 2026-10-26 `ff200ff13` Kilo Bot — test(4434): answer the revision routes end to end and ref… | +17/−0 | 26개 / +8446−1392 | #5852 CLOSED → #5994 |  |
| `feat/4727-native-tool-integration-261026` | 2026-10-26 `390ee1af0` Kilo Bot — test(4727): make a timed-out tool run a fact the model ca… | +5/−0 | 20개 / +2564−62 | #5856 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5093-offsite-d1-generation-261029` | 2026-10-29 `dfb18647e` skerishKang — feat(5093): 오프사이트 백업이 D1 세대를 먼저 지키고 대상별 상태를 나눈다 | +0/−1 | 8개 / +944−114 | #6220 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-adopt-target-account` | 2026-10-28 `e05e801e5` skerishKang — test(5573): let the email-target adoption see its second … | +2/−0 | 3개 / +314−83 | #5990 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5573-broker-skeleton-261029` | 2026-10-29 `d675c978f` skerishKang — test(5573): the broker CI installs pytest-asyncio for the… | +2/−0 | 20개 / +1140−7 | #6162 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5573-chat-com2-deploy-261029` | 2026-10-29 `a7df934ce` skerishKang — feat(5573): the COM2 Chat parallel-host package, install … | +0/−1 | 17개 / +958−0 | #6144 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-drive-root-default` | 2026-10-27 `67e3c20f5` Kilo Bot — feat(5573): a linked PC works over its whole local drives… | +0/−1 | 6개 / +329−53 | #5981 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-limits-b14-2of3-261026` | 2026-10-26 `bd4d033fb` skerishKang — feat(limits): 2/3 B14 provider write 120s and pool 60s | +0/−1 | 6개 / +12−10 | #5875 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-limits-chat-3of3-261026` | 2026-10-26 `717a5d75b` skerishKang — refactor(limits): move remaining web XLSX upload ceiling … | +4/−0 | 37개 / +226−79 | #5877 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5573-limits-core-engine-rules-261026` | 2026-10-26 `87f5dc04f` skerishKang — test(limits): align consumer fixtures and preflight with … | +2/−0 | 61개 / +232−106 | #5872 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5573-one-click-pc-install` | 2026-10-28 `4526f6c6e` Kilo Bot — feat(5573): one click hands out the install file that pai… | +0/−1 | 9개 / +583−88 | #5998 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-pc-link-lane-node-card` | 2026-10-27 `084df4507` Kilo Bot — fix(5573): address a linked PC by the deployment's Mesh r… | +0/−1 | 3개 / +174−0 | #5951 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-pc-link-pause-resume-261027` | 2026-10-27 `d81360cc9` skerishKang — Merge remote-tracking branch 'origin/main' into feat/5573… | +3/−0 | 11개 / +499−46 | #5982 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5573-pc-pair-handoff-without-link` | 2026-10-27 `1148bc58d` Kilo Bot — feat(5573): issue the pairing tag even when the installer… | +0/−2 | 7개 / +328−49 | #5930 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-pc-pair-install-wrapper` | 2026-10-27 `2f46eb88e` Kilo Bot — fix(release): name the one declared-but-unserved variable… | +2/−0 | 9개 / +540−8 | #5919 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5573-pc-pairing-admin-adopt` | 2026-10-27 `55a89687b` Kilo Bot — fix(5573): make a repeat adoption a read, not a rewrite | +2/−0 | 5개 / +308−0 | #5943 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5573-pc-pairing-beat-4c` | 2026-10-27 `1148bc58d` Kilo Bot — feat(5573): issue the pairing tag even when the installer… | +0/−2 | 7개 / +328−49 | #5925 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-pc-pairing-card-pr3` | 2026-10-27 `d1faf2b49` Kilo Bot — feat(5573): pair a PC from the computer card the account … | +0/−1 | 4개 / +633−0 | #5907 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-pc-pairing-directory-pr2` | 2026-10-27 `10200f865` Kilo Bot — feat(5573): send PC file work to the account's own linked… | +0/−1 | 8개 / +644−32 | #5906 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-pc-pairing-pr1` | 2026-10-26 `3166683f0` Kilo Bot — feat(5573): pair an account to its own PC with a one-time… | +0/−1 | 9개 / +1867−0 | #5894 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-pc-pairing-tag-claim` | 2026-10-27 `0c4d03ecf` Kilo Bot — feat(5573): claim a PC from the tag its installer stamped | +0/−1 | 8개 / +1216−692 | #5914 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5573-retire-keyword-admit-ledger-261026-astra1` | 2026-10-26 `f0f4f7e2f` skerishKang — docs(5573): no-deadline PC lane design; note keyword entr… | +0/−1 | 5개 / +132−2 | #5866 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5608-meeting-activity-book-261027` | 2026-10-27 `a5afcb79b` skerishKang — feat(5608): persist the activity book and arrange the rec… | +0/−1 | 3개 / +260−39 | #5935 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5728-sns-flow-verify-261027` | 2026-10-27 `a82c6dbb0` skerishKang — feat(5731): store past speeches as pickable style referen… | +0/−1 | 4개 / +79−1 | #5932 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5728-sns-photo-restore-local1` | 2026-10-27 `6bfbe7447` skerishKang — feat(5728): restore the saved SNS draft text with its pla… | +0/−1 | 3개 / +169−17 | #5924 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5784-b14-com2-asgi-261026` | 2026-10-27 `cf231f887` PADIEM AI LOCAL — fix(5784): declare the B14 routes through the supported R… | +4/−0 | 18개 / +1257−63 | #5897 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5784-b14-com2-deploy-261026` | 2026-10-26 `ee5fed46e` skerishKang — docs(5784): record the COM2 deploy bundle PR number on th… | +2/−0 | 9개 / +532−1 | #5901 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5784-b14-upstream-switch-261026` | 2026-10-27 `46115982d` PADIEM AI LOCAL — Merge remote-tracking branch 'origin/main' into feat/5784… | +5/−0 | 18개 / +964−33 | #5900 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5784-engine-b14-https-body-headroom-261026` | 2026-10-27 `00414d327` PADIEM AI LOCAL — Merge remote-tracking branch 'origin/main' into feat/5784… | +5/−1 | 4개 / +226−19 | #5902 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5786-councillor-cta` | 2026-10-29 `f8bd5242f` Kilo — fix(#5786): 헤더 CTA를 세션 답으로 페인트하고 320px 옆밀림을 제거한다 | +0/−1 | 4개 / +65−0 | #6175 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5786-councillor-nav-and-touch` | 2026-10-29 `dc32390eb` Kilo — feat(#5786): 의원 페이지에 이동표, 44px 터치 하한, 바로 아래 붙는 앵커 | +0/−1 | 6개 / +348−11 | #6172 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5791-com2-diag-summary-20261030` | 2026-10-30 `11aae341e` Kilo — fix(5791): collect WSL signals using root and report jour… | +2/−0 | 3개 / +312−0 | #6284 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5805-glass-mobile-header` | 2026-10-30 `133ab1f93` Kilo — test(5805): verify mobile header scroll and reduced motio… | +3/−0 | 38개 / +1078−0 | #6274 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5824-b14-user-credential-pr3a-261027` | 2026-10-27 `ecea2acda` skerishKang — feat(5824): accept a user credential on the B14 lane with… | +0/−1 | 14개 / +1996−72 | #5913 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5824-byok-detect-register-261026` | 2026-10-26 `2ad541ea3` skerishKang — feat(byok): detect and verify provider keys before owner-… | +0/−1 | 5개 / +288−3 | #5887 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5824-byok-paste-key-ui-261026` | 2026-10-26 `515d9e3f9` skerishKang — feat(byok): add paste-key registration and a verified pro… | +0/−1 | 5개 / +217−10 | #5889 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5881-chat-file-lane-reference-load-261027` | 2026-10-27 `db842f257` skerishKang — feat(5881): load a COM2 reference onto the Engine instead… | +2/−0 | 8개 / +1131−3 | #5912 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5881-engine-file-lane-window-261027` | 2026-10-27 `e8c75fb21` skerishKang — docs(5881): record the saved text counter in the lane fil… | +3/−0 | 9개 / +1007−23 | #5909 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5885-d1-migrate-gate-261027` | 2026-10-27 `7d9e91a8a` skerishKang — ops(5895): replace per-migration D1 gates with one genera… | +0/−1 | 3개 / +1788−0 | #5915 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5895-b66-pc-excel-form-261028` | 2026-10-28 `57ad0fac6` skerishKang — feat(5895): the quote screen fills the owner's own Excel … | +0/−1 | 9개 / +1190−1 | #6045 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5895-gate-plan-file-lists-261027` | 2026-10-27 `2fb4066c6` astra1 — feat(5895): name the plan's apply, seed and wide-destruct… | +0/−1 | 2개 / +67−0 | #5949 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5895-legacy-hwp-file-lane-261028` | 2026-10-29 `c1c13fe77` zwork — test(5895): carry the hwp dependency into its own contrac… | +2/−0 | 17개 / +757−14 | #6087 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5895-pc-cancel-and-partial-find-261028` | 2026-10-28 `d7e39b520` skerishKang — feat(5895): a long search no longer holds the PC, and the… | +0/−1 | 10개 / +1005−78 | #6031 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5895-pc-file-exchange-part-261028` | 2026-10-28 `5d6048d91` skerishKang — fix(5895): the save button keeps the touch-target floor t… | +3/−0 | 9개 / +2767−2 | #6012 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5895-predelegate-approval-tools-261028` | 2026-10-28 `70a565b04` astra1 — test(5994-align): remove the hark private-ledger suite wi… | +4/−0 | 15개 / +134−741 | #6007 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5895-remove-caps-2nd-261028` | 2026-10-28 `22ea75fea` astra1 — test(5895-A): align the executor fidelity tests with no b… | +3/−0 | 8개 / +119−157 | #6054 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5895-remove-caps-C-261028` | 2026-10-29 `8c48a72f2` zwork — fix(5895-C): the D1 row bound is the only ceiling a saved… | +2/−0 | 14개 / +80−36 | #6081 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5895-remove-caps-D-261028` | 2026-10-29 `faa5d6c26` zwork — feat(5895-D): folder lists, guidance lines and rosters ar… | +0/−1 | 8개 / +57−20 | #6096 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5895-remove-work-volume-caps-261028` | 2026-10-28 `e84e1c5e3` astra1 — feat(5895): lift the time caps in the tool spec and mesh … | +0/−1 | 7개 / +54−23 | #5995 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/5895-staged-chat-rollout-261028` | 2026-10-28 `09e255375` astra1 — test(5895): count the shared smoke once per lane, twice o… | +4/−0 | 6개 / +308−48 | #6035 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5895-util-pc-reference-261028` | 2026-10-28 `fa363a330` skerishKang — fix(5895): ask whether a PC is linked when the screen is … | +2/−0 | 13개 / +624−14 | #6039 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/5937-council-same-origin-entry` | 2026-10-27 `0700e1152` Kilo — Merge remote-tracking branch 'origin/main' into feat/5937… | +7/−0 | 18개 / +1179−120 | #5944 MERGED · 병합 후 커밋 보존 |  |
| `feat/5972-councillor-v2` | 2026-10-28 `047b9d6ca` Kilo — feat(5972): apply the official photography and correct th… | +19/−0 | 166개 / +5106−420 | #5979 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/6046-country-label` | 2026-10-28 `e8b991066` Kilo — feat(#6046): carry a content-country label through the co… | +0/−1 | 6개 / +193−2 | #6052 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/6046-country-meta` | 2026-10-28 `38636a625` Kilo — fix(#6046): pass the country filter only when a filter wa… | +7/−0 | 13개 / +178−46 | #6053 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/6061-parliament-rule-mapping-261028` | 2026-10-28 `52e1a7c64` Kilo — fix(#6061): separate the decree from the Assembly Act in … | +2/−0 | 8개 / +1330−0 | #6062 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/6063-councillor-mobile-crop-261028` | 2026-10-28 `1956c3ec6` Kilo — fix(#6063): keep the councillor pages' CRLF line endings | +2/−0 | 11개 / +285−8 | #6067 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/6064-parliament-design-mobile-261028` | 2026-10-28 `a33c922f8` Kilo — fix(parliament): keep the mobile header row monotonic and… | +0/−1 | 5개 / +172−1 | #6071 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/6065-cinematic-ui` | 2026-10-29 `65aa64612` Kilo — feat(#6065): 시안의 첫 화면을 운영 UI에 세운다 — 국가 4 × 스타일 5, 20조합 실측 | +0/−1 | 42개 / +2533−75 | #6222 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/6065-council-ui-integration-261028` | 2026-10-28 `3148f19f7` Kilo — fix(council): reflow the mobile header instead of squeezi… | +2/−0 | 5개 / +265−2 | #6079 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/6065-s1-header-nav-skin-261028` | 2026-10-28 `47c55c707` Kilo — feat(council): give the production header the design's vo… | +0/−1 | 8개 / +167−21 | #6083 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/6065-s2-card-archive-261029` | 2026-10-29 `19aaef3e2` Kilo — feat(council): give the tool cards the design frame and w… | +0/−1 | 9개 / +230−8 | #6088 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/6065-s3-editor-skin-261029` | 2026-10-29 `adbd22982` Kilo — feat(council): give the three editors the design's field … | +0/−1 | 6개 / +208−23 | #6095 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/6065-s4-auth-archive-261029` | 2026-10-29 `cc766eaa6` Kilo — merge: 최신 main(4139·5573·util #6098/#6099/#6093)을 S4 레인에 … | +0/−1 | 7개 / +191−27 | #6103 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/6065-s5-live-verification-261029` | 2026-10-29 `69983617a` Kilo — docs(council): record the S5 authenticated run and the pr… | +4/−0 | 8개 / +637−2 | #6114 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/6199-util-edit-stored` | 2026-10-30 `752d85bee` Kilo — feat(6199): 예전 축사·SNS 글을 고쳐 쓰기로 다시 열어 편집·저장한다 | +0/−1 | 10개 / +551−40 | #6205 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/6305-staging-worker-20261030` | 2026-10-30 `8bda8fc11` Hermes Agent — ci(6305): identify staging deployment workflow | +7/−0 | 6개 / +299−0 | #6311 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/b14-registry-declared-openai-adapter` | 2026-11-02 `afca5e6d4` Kilo — feat(b14): declare OpenAI-compatible providers and retire… | +1/−0 | 12개 / +1211−66 | #6697 MERGED(2026-11-02, 조사 중) · 브랜치는 이후 삭제됨 |  |
| `feat/b14-upstream-switch` | 2026-10-26 `4baf56a83` PADIEM AI LOCAL — Merge commit '3a81f88a0' into feat/b14-upstream-switch | +3/−0 | 12개 / +529−37 | #5899 CLOSED → #5900 |  |
| `feat/b62-file-lane-origin-var-declaration-261027` | 2026-10-27 `c4fd33abf` PADIEM AI LOCAL — feat(b62): declare the COM2 file-lane origin as an empty … | +0/−1 | 2개 / +17−6 | #5933 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b62-file-lane-ticket-secret-declaration-261027` | 2026-10-27 `b325f7701` PADIEM AI LOCAL — ops(b62): keep the reviewed baseline at the set productio… | +2/−0 | 3개 / +27−10 | #5923 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/b64-admin-email-binding-6001-261028` | 2026-10-28 `2d93a682a` Kilo Bot — ops(b64): keep the gate comment out of the deployment-com… | +2/−0 | 3개 / +99−5 | #6010 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/b64-ads-txt-987-261028` | 2026-10-28 `40f13fc29` Kilo Bot — feat(b64): serve the ads.txt lines ayeT checks for the B6… | +0/−1 | 3개 / +102−0 | #6029 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-auth-dedupe-5987-261029` | 2026-10-29 `a02000af4` Kilo Bot — refactor(b64): keep one constant-time compare in the cred… | +0/−1 | 1개 / +2−7 | #6097 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-authority-parity-5864-261027` | 2026-10-27 `d7f786579` Kilo Bot — feat(b64): resolve identity through the Control Plane aut… | +0/−1 | 12개 / +860−112 | #5954 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-ayet-contract-alignment-987-261028` | 2026-10-28 `d1a00f376` Kilo Bot — fix(b64): align the ayeT postback with the published prov… | +0/−1 | 6개 / +360−160 | #6000 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-ayet-s2s-987-261028` | 2026-10-28 `c36a6ffbe` Kilo Bot — feat(b64): connect the ayeT reward postback to the Worker… | +0/−1 | 10개 / +1026−4 | #5999 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-brand-independence-987-261027` | 2026-10-27 `c1b0be306` Kilo Bot — feat(b64): drop the PADIEM sub-service appearance from th… | +0/−1 | 22개 / +155−78 | #5970 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-browse-empty-filter-state-6074-261029` | 2026-10-29 `04fd9b856` Kilo Bot — fix(b64): a filter that finds nothing is not a supply out… | +0/−1 | 3개 / +96−3 | #6100 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-consumer-completion-987-261027` | 2026-10-27 `c44411587` Kilo Bot — fix(b64): stop unconfirmed payouts from reading as realis… | +0/−1 | 19개 / +259−24 | #5946 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-deploy-gate-987-261027` | 2026-10-27 `9cbc3fabc` Kilo Bot — ops(b64): add the dispatch-only production deploy gate fo… | +0/−1 | 3개 / +772−0 | #5950 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-google-reuse-5987-261027` | 2026-10-27 `2a12c65c6` Kilo Bot — feat(b64): reuse the proven Google login on B64's own cli… | +0/−1 | 13개 / +1524−96 | #5989 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-google-secret-binding-5987-261028` | 2026-10-28 `8a9930d20` Kilo Bot — ops(b64): bind B64's Google OAuth client through the revi… | +0/−1 | 4개 / +290−23 | #5993 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-independent-identity-987-261027` | 2026-10-27 `ed2199007` Kilo Bot — test(b64): keep the mid-request income storage 503 check … | +2/−0 | 41개 / +1844−2059 | #5966 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/b64-korean-typography-6001-261028` | 2026-10-28 `a9f65a110` Kilo Bot — style(b64): put B64's Korean screens on one type scale (#… | +0/−1 | 3개 / +72−40 | #6006 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-pretendard-webfont-6077-261028` | 2026-10-28 `f2094358c` Kilo Bot — fix(b64): ship the Pretendard the design tokens already n… | +0/−1 | 102개 / +1140−3 | #6080 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-super-admin-6001-261028` | 2026-10-28 `feb883e4a` Kilo Bot — feat(b64): give B64 its own operator authority and a read… | +0/−1 | 8개 / +786−1 | #6005 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b64-ui-triplename-6074-261028` | 2026-10-28 `b3a7a623b` Kilo Bot — fix(b64): stop the pipeline screen printing its own name … | +0/−1 | 2개 / +21−2 | #6076 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/b66-pc-form-entry-261028` | 2026-10-28 `743187262` skerishKang — feat(5895): a linked PC reaches the quote screen without … | +0/−1 | 2개 / +41−1 | #6056 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/beta-ux-structure-261029` | 2026-10-29 `42b270664` zwork — feat(util): the speech 참고 글 lane leads its form, and the … | +0/−1 | 57개 / +1060−28 | #6108 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/chat-file-lane-reference` | 2026-10-26 `17d4a8b9a` skerishKang — feat(chat): add signed COM2 file tickets and reference at… | +0/−1 | 19개 / +527−12 | #5893 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/connector-install-guide-261102` | 2026-11-02 `42332783d` Kilo — docs(chat): PC 연결 프로그램 설치 안내를 실제 동작과 함께 싣는다 (#6659 2) | +0/−2 | 8개 / +1361−2 | PR 없음 · 고유 커밋 0 | 삭제 |
| `feat/connector-lane-watch-261029` | 2026-10-29 `e36db52e4` astra1 — fix(#82): the watch's own guard checks executable lines, … | +2/−0 | 5개 / +730−7 | #6140 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/connector-release-2-261102` | 2026-11-02 `2656b0d0f` skerishKang — Merge branch 'main' into feat/connector-release-2-261102 | +2/−0 | 6개 / +142−7 | #6673 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/connector-watch-cf-codes-261029` | 2026-10-29 `c5f1a5e4e` astra1 — feat(#82): the health read names which way the worker fai… | +0/−1 | 2개 / +99−9 | #6152 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/connector-watch-com2-branch-261029` | 2026-10-29 `7df968a44` astra1 — feat(#82): after the cutover the watch follows the live s… | +0/−2 | 9개 / +518−10 | #6156 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/council-apps-base` | 2026-10-27 `adc54120d` Kilo — fix(5927): declare the util scope the #5916 execution bou… | +2/−0 | 16개 / +2214−0 | #5929 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/council-apps-ui-ux` | 2026-10-27 `0ed305705` Kilo — feat(5927): complete council apps SNS photo restore/delet… | +0/−1 | 5개 / +850−32 | #5939 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/council-pc-import-261102` | 2026-11-02 `e5d2a0eb8` skerishKang — Merge branch 'main' into feat/council-pc-import-261102 | +5/−0 | 16개 / +1642−40 | #6620 CLOSED → #6630 |  |
| `feat/council-pc-save-binary-261101` | 2026-11-02 `5d2374dc8` skerishKang — Merge branch 'main' into feat/council-pc-save-binary-2611… | +4/−0 | 10개 / +785−27 | #6607 CLOSED → #6630 |  |
| `feat/file-lane-com2-skeleton` | 2026-10-26 `f4e6bfce1` skerishKang — feat(file-lane): add signed disk-backed COM2 file service… | +0/−1 | 12개 / +1063−0 | #5888 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/file-lane-parser-phase2` | 2026-10-26 `0775dc5dc` skerishKang — test(5881): pin the additive Core parser budget and retai… | +2/−0 | 19개 / +485−66 | #5904 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/long-turn-progress` | 2026-10-26 `86bfebd1d` PADIEM AI LOCAL — feat(5573): show elapsed time on a long turn and keep the… | +0/−1 | 5개 / +243−1 | #5890 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/mesh-session-command-lane-261029` | 2026-10-29 `be9b51343` astra1 — feat(#82): a dispatch can run on its own terminal session… | +0/−1 | 2개 / +456−4 | #6163 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/padiem-apps-integration-contract-261027` | 2026-10-27 `8e8a8efb3` Kilo — feat(apps): state the app-to-platform contract as one che… | +0/−1 | 4개 / +659−0 | #5936 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/pc-cancel-ends-the-pc-process` | 2026-10-28 `62ddceab8` Kilo Bot — test(5573): the #6044 write scope has to stay one line on… | +2/−0 | 6개 / +373−12 | #6059 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/pc-computer-use-261102` | 2026-11-02 `e8c902615` Kilo — Merge remote-tracking branch 'origin/main' into feat/pc-c… | +1/−1 | 5개 / +849−1 | #6660 CLOSED → #6662 |  |
| `feat/pc-computer-use-3-261102` | 2026-11-02 `55d6303fa` Kilo — test(pc): 루프 값 무기록 시험의 날짜 민감 픽스처를 고친다 | +6/−1 | 18개 / +1732−68 | #6665 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/pc-connect-card-redesign-261029` | 2026-10-29 `344783103` zwork — feat(5573): the computer connection finishes on the first… | +0/−1 | 17개 / +2147−268 | #6110 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/pc-connect-exe` | 2026-10-28 `9a812e0c3` Kilo Bot — fix(5573): the agent is registered with -install, from a … | +3/−0 | 14개 / +2992−15 | #6066 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/pc-content-search-261101` | 2026-11-01 `6d9f78dbd` Kilo — feat(6460): search PC file names and text contents in the… | +1/−0 | 12개 / +1164−30 | #6513 CLOSED → #6554 |  |
| `feat/pc-write-move-delete-5573` | 2026-10-28 `e7796c029` skerishKang — test(5573): drop the assertion a refused write already se… | +9/−0 | 14개 / +1133−38 | #5994 MERGED(base main) · 병합 후 커밋 없음 |  |
| `feat/pc-write-scope-chat-6044` | 2026-10-28 `548dd3996` skerishKang — Merge remote-tracking branch 'origin/main' into feat/pc-w… | +0/−1 | 11개 / +396−16 | #6047 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/pdfmd-pc-import-save-6012` | 2026-10-28 `7f4c36fe9` skerishKang — Merge remote-tracking branch 'origin/main' into feat/pdfm… | +0/−1 | 3개 / +271−3 | #6043 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/prf-b457-removal-261030` | 2026-10-31 `5cc395c3d` skerishKang — fix(designer): DESIGNER_B14_MODEL_ID 미설정 시 b14/auto 대신 설정… | +7/−1 | 90개 / +748−2697 | #6265 MERGED · 병합 후 커밋 보존 |  |
| `feat/queue-lane-status-261029` | 2026-10-29 `0003387d3` astra1 — feat(#82): the queue serves the lane-status read, behind … | +0/−1 | 2개 / +192−3 | #6155 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/tail-path-cpu-stats-261029` | 2026-10-30 `b675a6fb9` zwork — feat(tail): 경로별 cpuTime p50/p95/max·outcome 표와 3일 보존 정제 캡… | +0/−1 | 3개 / +170−4 | #6218 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `feat/ui-page-contract-phase2-261026` | 2026-10-26 `d3210d1f1` PADIEM UI 통합 LOCAL — Merge origin/main (the shared-origin step, #5843) into th… | +4/−0 | 14개 / +317−114 | #5844 CLOSED → #5846 |  |
| `feat/util-save-status-261030` | 2026-10-30 `ca07a48b3` skerishKang — feat(5783): 저장 실패를 탭 안 상태 줄로 말하고 회의정리에도 고쳐 쓰기를 연다 | +0/−1 | 5개 / +546−82 | #6257 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/2544-marker-rederive-261029` | 2026-10-29 `6acb1f6d6` skerishKang — fix(2544): live-content marker 7개를 지금 main의 600s 예산으로 재도출… | +0/−1 | 3개 / +48−34 | #6221 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/2824-com2-binary-attachment-chat-261030` | 2026-10-30 `6e26c5830` astra1 — test(2824): verify file lane browser attachment flow | +4/−0 | 10개 / +143−45 | #6322 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/2824-intake-safety-gaps-261030` | 2026-10-30 `92fd727b1` Kilo — test(engine): re-pin the frozen-source canary for the #28… | +2/−0 | 10개 / +749−10 | #6316 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/2824-mobile-fallback-marker-261026` | 2026-10-26 `8df2c7ac2` skerishKang — fix(2824): let the mobile hosted fallback resolve its own… | +0/−1 | 4개 / +79−0 | #5859 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/2824-parser-binding` | 2026-10-26 `43b2035a5` Hermes Agent — fix(2824): activate private parser service binding throug… | +0/−1 | 4개 / +78−1 | #5865 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/2952-owner-scope-audit-261030` | 2026-10-30 `83c9c3494` Kilo — fix(2952): a stored document is opened by the user who mi… | +2/−0 | 15개 / +926−149 | #6318 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/2952-task-owner-required-261031` | 2026-10-31 `e2e9622ce` Kilo — test(2952): 배경 실행 스텁도 소유자 필수 조회 서명에 맞춘다 | +2/−0 | 10개 / +369−226 | #6337 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/4816-call-screen-m4-261031` | 2026-10-31 `a4f36d80d` Kilo — feat(4816): M4 통화 화면에 턴별 전사 이력·경과 시간·탭 종료 시 세션 폐기를 넣는다 | +0/−1 | 9개 / +479−4 | #6330 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/4816-waveform-icon-visible-261030` | 2026-10-31 `3b77322fb` Kilo — Merge remote-tracking branch 'origin/main' into fix/4816-… | +0/−1 | 19개 / +1016−183 | #6328 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/4976-pdf-broken-xref-recovery-261026` | 2026-10-26 `57b888043` skerishKang — fix(4976): move the Engine canary pin for the changed Cor… | +2/−0 | 4개 / +131−6 | #5851 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5479-longpoll-wait` | 2026-10-28 `0b3dd17ad` skerishKang — fix(5479): cap the executor long-poll at five seconds on … | +0/−1 | 3개 / +44−2 | #6057 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5479-request-scope-task-cleanup-261028` | 2026-10-29 `74ccc49e4` zwork — fix(5479): request-scoped async work ends with the reques… | +0/−1 | 3개 / +192−115 | #6086 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5553-astra-2-mesh-presence` | 2026-10-26 `8c93a4a47` skerishKang — fix(5553): record presence for Mesh-only devices and carr… | +0/−1 | 15개 / +760−54 | #5868 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5561-real-waveform-261026` | 2026-10-26 `f258ccd6d` Hermes Agent — fix(5561): keep original HTML line endings in waveform ch… | +2/−0 | 1개 / +1−1 | #5841 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5561-voice-waveform-face-261026` | 2026-10-26 `025856822` PADIEM CGI LOCAL 1 — fix(5561): move the waveform face by attribute and keep t… | +0/−1 | 2개 / +107−26 | #5839 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5573-astra-2-argumentless-drives-261026` | 2026-10-26 `38f150a29` skerishKang — fix(5573): invoke the drives tool for argument-less tool … | +0/−1 | 5개 / +99−10 | #5842 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5573-astra-2-drive-decision-final` | 2026-10-26 `c54eb4aa4` skerishKang — test(5573): preserve heartbeat opt-in for PC stream failu… | +2/−0 | 2개 / +286−16 | #5845 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5573-astra-2-step-selection-logs` | 2026-10-26 `966f65bff` skerishKang — fix(5573): execute argument-less PC tool calls directly i… | +0/−1 | 3개 / +75−7 | #5848 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5573-astra-2-stream-errors` | 2026-10-26 `7c03b89a5` skerishKang — fix(5573): render orchestration stream error records inst… | +0/−1 | 3개 / +143−19 | #5873 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5573-chat-drive-dispatch` | 2026-10-26 `49da53211` skerishKang — fix(5573): let Chat tool-turn runs dispatch PC drive quer… | +0/−1 | 6개 / +172−36 | #5858 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5573-drive-path-arguments` | 2026-10-28 `f8f200bb5` Kilo Bot — fix(5573): accept a granted drive as the PC path argument | +0/−1 | 4개 / +217−14 | #5991 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5573-pc-command-utf8-base64-envelope` | 2026-10-27 `e5d0b3c1a` Kilo Bot — fix(5573): carry the PC's reply as a UTF-8 Base64 envelope | +0/−1 | 6개 / +227−46 | #5971 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5573-pc-pairing-not-ready` | 2026-10-26 `c595effcd` Kilo Bot — fix(5573): answer "not ready" until pairing migration 072… | +0/−1 | 2개 / +127−40 | #5903 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5573-queue-backup-dir-owner` | 2026-10-30 `5893254f7` Kilo Bot — fix(5573): the installer gives the backup directory to th… | +0/−1 | 2개 / +11−0 | #6236 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5573-queue-compat-response` | 2026-10-30 `68742b86e` skerishKang — fix(5573): include safe exception kinds in queue diagnost… | +4/−0 | 7개 / +266−34 | #6279 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5573-queue-ua-261030` | 2026-10-30 `bdf8274ba` zwork — fix(5573): 큐 호출이 엣지 봇 차단(1010)에 걸리지 않게 자신의 UA를 보낸다 | +0/−1 | 2개 / +19−1 | #6270 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5573-second-pc-nameable` | 2026-10-28 `a45f15089` Kilo Bot — feat(5573): a linked PC is named by Windows first and ren… | +2/−0 | 16개 / +751−33 | #6011 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5574-grounding-fake-signature` | 2026-10-28 `a646df5bc` Kilo Bot — test(6046): every grounding fake takes the two keywords t… | +2/−0 | 4개 / +14−8 | #6084 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5643-retire-tunnel-layer-261030` | 2026-10-30 `ea1c4eac8` Kilo — fix(5643): retire the COM1 mesh tunnel layer from the mes… | +0/−1 | 14개 / +313−2731 | #6276 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5881-copy-state-cli-argv` | 2026-10-30 `6797a31df` Kilo Bot — fix(5881): copy_state.py takes the command line the runbo… | +0/−1 | 2개 / +33−1 | #6266 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5881-file-lane-reason-codes-261031` | 2026-10-31 `3d99940a3` kilo — fix(5881): 파일 레인이 Core의 상수 사유 코드를 허용 목록으로만 통과시킨다 | +0/−1 | 3개 / +230−3 | #6338 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5881-queue-moment-boundary` | 2026-10-30 `ced95ff11` Kilo Bot — fix(5881): the door coerces every instant it is given, an… | +0/−1 | 7개 / +353−10 | #6291 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5881-queue-request-log` | 2026-10-30 `1881766c1` Kilo Bot — feat(5881): the store door can say it was knocked on, in … | +0/−1 | 6개 / +226−4 | #6278 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5881-queue-schema-ledger` | 2026-10-30 `b1c0d53ea` Kilo Bot — fix(5881): the queue applies each migration once, so a re… | +0/−1 | 3개 / +435−4 | #6281 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5881-read-deadline` | 2026-10-30 `24299aafc` Kilo Bot — fix(5881): 실행기가 PC 읽기에 대기 시간을 넘기지 않아 모든 읽기가 거부되던 문제 | +0/−1 | 5개 / +381−10 | #6327 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5881-result-pin-read` | 2026-10-30 `521d2eb42` Kilo Bot — test(5881): import the seam helper where the double is bu… | +5/−0 | 7개 / +525−63 | #6315 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5881-run-ownership` | 2026-10-30 `cddc70456` Kilo Bot — fix(5881): 결과 저장은 dispatch 표를 더 이상 D1에서 다시 읽지 않는다 | +1/−1 | 6개 / +742−68 | #6303 MERGED · 병합 후 커밋 보존 |  |
| `fix/5881-watchdog-exit-wiring` | 2026-10-30 `6a8014c1a` Kilo Bot — docs(5881): the runbook quotes the door's five fields, no… | +2/−0 | 3개 / +80−2 | #6283 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5895-apply-job-arg-audit-261027` | 2026-10-27 `b282ff830` astra1 — fix(5895): hand the apply classify the column detail the … | +0/−1 | 2개 / +129−1 | #5959 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5895-apply-probes-ledger-before-classify-261027` | 2026-10-27 `b78cdc17e` astra1 — fix(5895): probe the ledger fresh before classify in the … | +0/−1 | 2개 / +61−4 | #5956 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5895-d1-gate-premutation-guard-261027` | 2026-10-27 `c72239433` skerishKang — fix(5895): parse a wrangler response around its banner | +2/−0 | 3개 / +68−6 | #5922 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5895-d1-gate-reads-by-command-261027` | 2026-10-27 `8b9d5573e` skerishKang — fix(5895): read and write Chat D1 through the query API, … | +1/−0 | 3개 / +96−12 | #5928 CLOSED → #5945·#5959 |  |
| `fix/5895-d1-gate-split-snapshot-blocks-261027` | 2026-10-27 `a9ecd601e` astra1 — fix(5895): read the gate with one --command execute per q… | +2/−0 | 3개 / +289−78 | #5945 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5895-exact-main-ancestor-path-261027` | 2026-10-27 `dc6287d37` PADIEM AI LOCAL — fix(5895): widen the released paths to the bundle the gat… | +2/−0 | 10개 / +316−8 | #5957 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5895-gate-bookmark-key-261027` | 2026-10-27 `51c695776` astra1 — fix(5895): read the recovery bookmark from result.bookmark | +0/−1 | 3개 / +77−7 | #5953 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5895-long-wait-stream-keepalive-261027` | 2026-10-27 `d42c48b82` PADIEM AI LOCAL — fix(5895): keep a long turn's stream warm, and recover it… | +0/−1 | 7개 / +210−10 | #5968 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5895-oracle-mesh-dispatch-lease-261028` | 2026-10-28 `b49f482bc` skerishKang — fix(5895): an executor claim is a lease, so a lost respon… | +0/−1 | 5개 / +367−45 | #5997 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5895-p01-cross-app-completion-261028` | 2026-10-28 `49332c4e3` astra1 — fix(5895): project a pre-delegated P01 completion in the … | +5/−0 | 9개 / +157−38 | #6042 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5895-pairing-mock-every-fixture-261027` | 2026-10-27 `97287ca91` PADIEM AI LOCAL — ops(5895): answer the whole PC pairing surface in both br… | +0/−1 | 2개 / +24−12 | #5980 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5895-pc-lane-pending-on-stream-loss-261027` | 2026-10-27 `b846ecf58` PADIEM AI LOCAL — test(5895): cut the stream in the pending fix's fail-clos… | +2/−0 | 3개 / +63−4 | #5976 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5895-pc-long-wait-progress-261027` | 2026-10-27 `5b9194248` skerishKang — fix(5895): release the waiting line when the PC run stops… | +4/−0 | 8개 / +485−5 | #5983 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5895-smoke-login-diagnostics-261028` | 2026-10-28 `4ea918f7a` astra1 — ops(5895): name the login status and server code on a ref… | +0/−1 | 2개 / +34−0 | #5992 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5895-worker-import-time-js-261028` | 2026-10-28 `76999c173` skerishKang — fix(5895): the Worker stops reading JS while it is still … | +0/−1 | 3개 / +178−30 | #6034 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5906-pc-context-no-link` | 2026-10-27 `369eb850c` Kilo Bot — fix(release): review the served binding set that is answe… | +2/−0 | 5개 / +89−17 | #5911 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/5942-book-draft-kept` | 2026-10-27 `f1fdff30f` Kilo — fix(5942): keep the saved book draft on screen after the … | +0/−1 | 3개 / +27−2 | #5958 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5942-book-persistence` | 2026-10-27 `56097490d` Kilo — fix(5942): persist the activity book and reopen it on re-… | +0/−1 | 4개 / +302−41 | #5955 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/5997-lease-renewal-261028` | 2026-10-28 `b51f4dffc` skerishKang — fix(5997): a running command keeps its claim, so a long P… | +0/−1 | 6개 / +347−1 | #6051 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/6027-mobile-hero-portrait` | 2026-10-28 `b530c7412` Kilo — fix(6027): keep the mobile hero portrait whole and give t… | +0/−1 | 1개 / +9−3 | #6028 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/6044-main-red` | 2026-10-28 `d33f450e0` skerishKang — test(6044): pin the account line by its meaning, not its … | +0/−1 | 1개 / +4−1 | #6058 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/6046-select-floor-scope` | 2026-10-28 `ec0a3cada` Kilo — fix(#6046): scope the language-select touch target to nar… | +1/−0 | 2개 / +29−21 | #6078 CLOSED → #6079 |  |
| `fix/6046-util-auto-grounding` | 2026-10-28 `624b9385f` Kilo — fix(#6046): put the language select and record checkbox o… | +2/−0 | 5개 / +303−4 | #6075 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/6065-country-list-refresh` | 2026-10-29 `914f4c53b` Kilo — fix(council): make the stored lists follow the content co… | +0/−1 | 5개 / +200−5 | #6139 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/6127-auth-status-unavailable-state` | 2026-10-29 `3b3fa897e` Kilo — fix(council): re-ask a status read that produced no answe… | +2/−0 | 5개 / +280−16 | #6136 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/6209-claw-smoke-gate-normalized-sha-261029` | 2026-10-29 `7adadb4d3` skerishKang — fix(6209): chat 테스트가 실제로 읽는 게이트 3개만 CI 경로에 넣고 CI 범위 정책을 함… | +2/−0 | 3개 / +23−3 | #6239 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/6222-b62-gate-duplicate-steps-261029` | 2026-10-29 `eb723cc3e` skerishKang — fix(ci): retain exact-sha guard in single source-contract… | +0/−1 | 1개 / +0−1 | #6226 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/6223-init-wait-bounds-261030` | 2026-10-30 `98333fc35` skerishKang — fix(6223): 초기화 대기에 상한을 두고 hang된 시도는 스스로 정산해 다음 요청이 재시도하게 … | +0/−1 | 2개 / +129−5 | #6275 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/84-channel-refusal-leg` | 2026-10-30 `1adb5645e` Kilo Bot — feat(84): a refusal names the server it asked, and the wa… | +0/−1 | 5개 / +249−10 | #6272 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/admission-error-code-log-261102` | 2026-11-02 `0b6797812` skerishKang — feat(6679): log the closed rpc method and error code on a… | +0/−1 | 1개 / +10−5 | #6680 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/astra1-b14-auto-no-return-261030` | 2026-10-31 `1169c73ac` skerishKang — merge main (pypdf CI fix #6308) into #6280 branch | +34/−1 | 170개 / +975−3081 | #6280 MERGED (중간 브랜치) → #6265로 main 반영. `test_b14_auto_removed_guard.py`가 main에 있다. |  |
| `fix/astra1-designer-model-required-261030` | 2026-10-31 `5616b0434` skerishKang — fix: retire remaining B14 auto references and prevent the… | +8/−1 | 271개 / +6486−3385 | #6277 MERGED (중간 브랜치) → #6265로 main 반영. |  |
| `fix/b14-info-telemetry-timeout-261026` | 2026-10-26 `22fd24153` skerishKang — fix(b14): keep info-level operations logs and swallow tel… | +0/−1 | 4개 / +81−3 | #5870 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/b14-malformed-upstream` | 2026-10-26 `b9c8dac53` skerishKang — fix(b14): log malformed upstream reason/shape, tolerate G… | +0/−1 | 15개 / +400−187 | #5884 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/b62-auth-history-pairing-read-in-page` | 2026-10-29 `d6de1b7b0` zwork — fix(b62): answer the account-session pairing read inside … | +0/−1 | 2개 / +52−17 | #6085 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/b62-deploy-signed-in-smoke` | 2026-10-28 `5647587b3` Kilo Bot — fix(b62): prove the signed-in Chat path after a productio… | +0/−1 | 3개 / +314−0 | #6032 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/b62-repo-binding-authority` | 2026-10-26 `e77072b37` skerishKang — fix(b62): use live activation prerequisites only for hist… | +7/−1 | 33개 / +1049−3143 | #5898 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/b62-reviewed-four-vars-20261030` | 2026-10-30 `5f61300ce` Hermes Agent — fix(b62): review four existing production vars | +0/−1 | 1개 / +16−0 | #6320 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/b62-rollback-binding` | 2026-10-28 `55ecbb9b0` Kilo Bot — fix(b62): a rollback is not gated by the baseline of the … | +0/−1 | 2개 / +132−2 | #6033 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/b62-staged-smoke-identity` | 2026-10-28 `c800758f5` Kilo Bot — fix(b62): give the staged signed-in proof the identity it… | +0/−1 | 3개 / +57−0 | #6036 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/b64-deploy-parity-pipefail-5950` | 2026-10-27 `e66c8224c` skerishKang — fix(b64): consume full HTTP parity streams under pipefail | +0/−1 | 1개 / +10−10 | #5952 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/b64-form-post-origin-null-5987-261028` | 2026-10-28 `32367f845` Kilo Bot — fix(b64): accept the Origin a browser actually sends on a… | +0/−1 | 2개 / +200−4 | #5996 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/b64-join-503-5978-261027` | 2026-10-28 `31df506a9` Kilo Bot — Merge remote-tracking branch 'origin/main' into fix/b64-j… | +1/−0 | 5개 / +143−92 | #5985 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/b64-mobile-tap-targets-6074-261029` | 2026-10-29 `7f0fa4ef2` Kilo Bot — fix(b64): give the secondary mobile links a 24px tap targ… | +0/−1 | 2개 / +52−2 | #6101 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/b64-reward-insert-conflict-987-261029` | 2026-10-29 `ad73a1aee` Kilo Bot — fix(b64): a duplicate reward-event create reported a stor… | +0/−1 | 2개 / +86−2 | #6122 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/b64-secondary-contrast-5822-261029` | 2026-10-29 `2a54e0ac0` Kilo Bot — fix(b64): lift the secondary text tokens to WCAG AA in bo… | +0/−1 | 3개 / +109−3 | #6111 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/chat-fetch-exception-observability-20261030` | 2026-10-30 `268deccd3` Kilo — fix(chat): log safe fetch failure stages | +0/−1 | 2개 / +176−55 | #6300 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/chat-pc-correlation-20261030` | 2026-10-30 `0a83fc034` Hermes Agent — fix(chat): correlate runs without browser ids | +3/−0 | 5개 / +178−6 | #6306 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/chat-search-like-50-bytes-261031` | 2026-10-31 `3fe6197c5` ccmkbs-web — fix(chat): 대화 검색이 D1 LIKE 50바이트 한도를 넘지 않게 한다 | +0/−1 | 2개 / +126−32 | #6329 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/ci-hidden-import-audit-261030` | 2026-10-30 `cd6319b40` skerishKang — docs(operations): add CI path-filter dependency audit tab… | +0/−1 | 1개 / +131−0 | #6314 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/connector-approval-copy-261029` | 2026-10-29 `8d7320e87` zwork — test(connector): 가이드 문구 고정을 런타임 사실(범위·백업·발송 1회 확인) 계약으로 갱신 | +2/−0 | 8개 / +42−37 | PR 없음 · 내용 main 확인 |  |
| `fix/connector-watch-canary-ceiling-261029` | 2026-10-29 `6aa099b9e` astra1 — fix(#82): assert the job token by name, not by an express… | +2/−0 | 3개 / +289−42 | #6129 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/connector-watch-lane-status-261029` | 2026-10-29 `afa6b8f5b` astra1 — feat(#82): the lane reports its own waiting and working c… | +0/−1 | 6개 / +453−1 | #6134 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/connector-watch-read-secret-261029` | 2026-10-29 `620070da2` astra1 — fix(#82): the watch reads with its own secret, never the … | +0/−1 | 4개 / +229−18 | #6145 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/core-ci-pypdf-5568-261030` | 2026-10-30 `70f37772f` Kilo — fix(ci): install pypdf for Core test collection | +0/−1 | 2개 / +3−0 | #6308 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/council-cache-and-nav-261101` | 2026-11-01 `91cffdf69` zwork — fix(council): 정적 자산 내용 해시 버저닝 + 시안(04) 상단 메뉴·검색 반영 | +1/−0 | 10개 / +832−16 | #6574 CLOSED → #6578 |  |
| `fix/council-first-visit-no-login-261029` | 2026-10-29 `307442bf7` skerishKang — test(council): expect deferred login on first visit while… | +5/−0 | 4개 / +11−10 | #6229 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/council-meeting-reopen-261102` | 2026-11-02 `352ecfbf8` Kilo — merge: main 동기화 — 헤니스 deepText 관례와 자산 해시 지도를 새로 굽는다 | +1/−0 | 0개 / +0−0 | #6669 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/council-mobile-legibility-261102` | 2026-11-02 `b16f5637f` Kilo — Merge remote-tracking branch 'origin/main' into fix/counc… | +1/−0 | 5개 / +277−2 | #6640 CLOSED → #6642 |  |
| `fix/councillor-good-news-261101` | 2026-11-01 `dc0985ccb` Kilo — fix(councillor): 득표율·미확인 SNS·방어적 안내 문구 제외 (대표 요청) | +3/−0 | 17개 / +524−210 | PR 없음 · 내용 main 확인 |  |
| `fix/designer-b14-model-config-261030` | 2026-11-01 `b0630f7f7` astra1 — fix(designer): DESIGNER_B14_MODEL_ID 미설정 시 b14/auto 대신 설정… | +0/−1 | 3개 / +24−13 | PR 없음 · 고유 커밋 0 | 삭제 |
| `fix/engine-d1-count-scope-261030` | 2026-10-30 `0a5195593` Kilo — fix(engine): bound D1 apply row counts to migration tables | +0/−1 | 2개 / +25−49 | #6302 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/engine-d1-inspection-http-261030` | 2026-10-30 `1f1b0fb57` Kilo — fix(engine): exclude reserved D1 metadata from row invent… | +0/−1 | 2개 / +60−2 | #6297 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/file-lane-binding-baseline-261030` | 2026-10-30 `415c6e7a5` astra1 — fix(b62): review the file lane ticket binding in the base… | +0/−1 | 1개 / +4−0 | #6304 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/github-gate-baseline-2-261101` | 2026-11-01 `8b4188109` zwork — test(gates): 2차 — POSIX 스코핑, jq 환경, stale 기대값, playwright… | +2/−0 | 19개 / +211−76 | #6585 CLOSED → #6609 → #6630 |  |
| `fix/github-gate-baseline-261101` | 2026-11-01 `351007879` zwork — test(gates): main 기준 게이트 시험의 Windows·오염 원인별 정리 (1차) | +1/−0 | 10개 / +136−38 | #6576 CLOSED → #6609 → #6630 |  |
| `fix/github-gate-baseline-3-261101` | 2026-11-02 `aaefae283` skerishKang — Merge branch 'main' into fix/github-gate-baseline-3-261101 | +4/−0 | 25개 / +260−80 | #6609 CLOSED → #6630 |  |
| `fix/identity-e2e-product-set` | 2026-10-28 `2fc2e09e6` Kilo Bot — test(5963): the identity e2e fixture takes its product se… | +0/−1 | 2개 / +7−1 | #6072 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/legacy-chat-request-422` | 2026-10-30 `9b8f455d9` Hermes Agent — test(chat): update retired mode rejection expectations | +2/−0 | 9개 / +104−14 | #6301 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/limits-quick-5-261102` | 2026-11-02 `8350b0ba4` skerishKang — Merge branch 'main' into fix/limits-quick-5-261102 | +1/−0 | 11개 / +85−11 | #6608 CLOSED → #6630 |  |
| `fix/mesh-health-authority-261030` | 2026-10-30 `fa4799a70` Kilo — fix(mesh): align startup and alerts with remote health | +0/−1 | 4개 / +151−1 | #6298 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/mesh-line-probe-default-off-261029` | 2026-10-29 `4b3fe2398` astra1 — fix(#6106): the console probe ships off until the shell l… | +0/−1 | 4개 / +115−11 | #6183 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/nogil-waituntil-proxy-release-261030` | 2026-10-30 `607aed30f` skerishKang — fix(6225): waitUntil에 넘긴 PyProxy를 배경 작업 정산 뒤 해제한다 | +0/−1 | 2개 / +111−10 | #6264 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/pc-agent-install-align-261028` | 2026-10-29 `97cb47e8a` zwork — fix(5573): a host without Program Files still reaches its… | +2/−0 | 6개 / +475−52 | #6093 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/pc-card-honest-states-261031` | 2026-10-31 `4d8af6402` ccmkbs-web — fix(chat): 내 컴퓨터 카드가 읽지 못한 상태를 연결 안 됨으로 말하지 않게 한다 | +0/−1 | 3개 / +76−5 | #6331 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/pc-chip-honest-states-261031` | 2026-10-31 `709df83a2` ccmkbs-web — fix(chat): 컴포저 칩이 읽지 못한 상태에서 연결하기를 내밀지 않게 한다 | +0/−1 | 3개 / +36−4 | #6334 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/pc-connect-exe-mesh-url` | 2026-10-28 `c9c9d65fe` Kilo Bot — fix(5573): the connect program keeps a mesh link's @ inst… | +0/−1 | 4개 / +494−378 | #6082 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/pc-failed-run-terminal-20261030` | 2026-10-31 `3de5685d1` Hermes Agent — test(chat): match optional PC read timeout contract | +4/−0 | 8개 / +112−13 | #6325 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/pc-line-blockage-claim-gate-261029` | 2026-10-29 `af89c51fe` astra1 — docs(4139): the console-kill path needs a new client, and… | +2/−0 | 11개 / +687−17 | #6113 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/pc-line-blockage-selfheal-261029` | 2026-10-29 `a7cd9f496` astra1 — docs(4139): what MeshCentral can and cannot do in parallel | +2/−0 | 6개 / +1291−40 | #6106 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/pdfmd-first-paint-261102` | 2026-11-02 `94f8c1736` ccmkbs-web — fix(chat): PDF→Markdown 첫 화면은 확인 중으로 그리고 잠김은 답 뒤에 말한다 | +6/−1 | 21개 / +1409−193 | PR 없음 · 내용 main 확인 |  |
| `fix/queue-parity-fixture-clock-261029` | 2026-10-29 `985872c51` astra1 — test(#82): the parity fixture stages its dispatch from th… | +0/−1 | 1개 / +7−1 | #6148 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/stt-chat-binding-report-261030` | 2026-10-30 `3e32abc13` astra1 — test(stt): align Chat binding report with shared auth | +0/−1 | 1개 / +3−0 | #6299 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/time-anchor-ops-tests-261029` | 2026-10-29 `e57726aca` skerishKang — test(ops): 24h/240h stale 테스트의 앵커를 now로 바꾸고 scripts/ops를 … | +0/−1 | 2개 / +35−1 | #6224 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/tus-d4-concurrency-261102` | 2026-11-02 `107f8833e` skerishKang — Merge branch 'main' into fix/tus-d4-concurrency-261102 | +2/−0 | 2개 / +786−49 | #6670 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/ui-shared-first-screen-origin-261026` | 2026-10-26 `b2bfb864a` PADIEM UI 통합 LOCAL — test(ui): keep the #5014 guard on the brand sheet's verti… | +2/−0 | 8개 / +180−47 | #5843 MERGED(base main) · 병합 후 커밋 없음 |  |
| `fix/util-sns-meeting-form-order-261030` | 2026-10-30 `9e80798d8` ccmkbs-web — fix(5783): SNS·회의정리 폼이 요소를 붙이는 순서 때문에 만들어지지 않던 문제 | +0/−1 | 4개 / +65−5 | #6319 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `fix/windows-local-test-env-261030` | 2026-10-30 `bb0056156` astra1 — test(chat): configure cross-app subprocess paths in conft… | +4/−0 | 8개 / +67−5 | #6294 MERGED(base main) · 병합 후 커밋 없음 |  |
| `inspect/6421-final-scan` | 2026-10-28 `4a29eaad0` Kilo — feat(#6046): carry a content-country label through the co… | +0/−2 | 8개 / +212−2 | #6044 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `integrate/5844-page-contract-261026` | 2026-10-26 `4bcca37d5` PADIEM UI 통합 LOCAL — test(ui): point the sidebar and meeting contracts at the … | +2/−0 | 14개 / +317−114 | #5846 MERGED(base main) · 병합 후 커밋 없음 |  |
| `integration/4434-central-261026` | 2026-10-26 `4e3539dca` Hermes Agent — fix(4434): avoid multiline nested f-string on Python 3.11 | +20/−0 | 29개 / +9076−1409 | #5854 CLOSED → #5994 |  |
| `local/5785-util-execution-boundary-261027` | 2026-10-27 `8626bd0e7` Kilo — fix(util): keep the pinned tail literal of the browser fi… | +2/−0 | 7개 / +181−34 | #5916 MERGED(base main) · 병합 후 커밋 없음 |  |
| `local/b64-auth-final-987` | 2026-10-26 `f1911861c` Hermes Agent — docs(b64): confirm Plan A session auth — Plan B cannot id… | +0/−1 | 1개 / +48−0 | #5849 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `local/b64-authority-987` | 2026-10-26 `297813c96` Hermes Agent — feat(b64): authenticate through the Control Plane identit… | +3/−0 | 12개 / +1036−94 | #5864 CLOSED |  |
| `local/b64-prod-connect-987` | 2026-10-26 `80daf8d37` Hermes Agent — docs(b64): close runbook gaps — mutation origin var, rout… | +2/−0 | 3개 / +108−2 | #5838 MERGED(base main) · 병합 후 커밋 없음 |  |
| `local/b64-prod-final-987` | 2026-10-26 `b6755046f` skerishKang — fix(b64): correct secret activation shell pipeline | +3/−0 | 4개 / +445−0 | #5853 MERGED(base main) · 병합 후 커밋 없음 |  |
| `lovetree-auth-caller-261027` | 2026-10-28 `f2e556aa3` skerishKang — Merge pull request #5984 from skerishKang/lovetree-login-… | +0/−0 | 0개 / +0−0 | #5977 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `lovetree-authority-caller-261027` | 2026-10-28 `e53c4bc58` skerishKang — Merge pull request #5977 from skerishKang/lovetree-auth-c… | +0/−0 | 0개 / +0−0 | #5965 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `lovetree-identity-registration-261027` | 2026-10-28 `6a8bd5b20` skerishKang — Merge pull request #5965 from skerishKang/lovetree-author… | +0/−0 | 0개 / +0−0 | #5963 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `ops/5573-queue-service-secret-baseline` | 2026-10-30 `1cececb19` Kilo Bot — ops(5573): approve the queue's service secret as a review… | +0/−1 | 1개 / +4−0 | #6216 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `ops/5700-astra-2-chat-observability` | 2026-10-26 `a8e23fd5c` skerishKang — test(5700): isolate the deploy contract from Chat runtime… | +2/−0 | 3개 / +151−2 | #5861 MERGED(base main) · 병합 후 커밋 없음 |  |
| `ops/5881-queue-to-d1-backfill-261031` | 2026-10-31 `dbfee89ca` PADIEM Astra1 — feat(5881): prepare offline queue dispatch rollback export | +0/−1 | 3개 / +332−0 | #6332 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `ops/5895-pc-connector-canary-261028` | 2026-10-28 `d99be3703` skerishKang — ops(5895): measure the whole PC turn and prove the stream… | +2/−0 | 3개 / +896−0 | #6004 MERGED(base main) · 병합 후 커밋 없음 |  |
| `ops/b62-binding-attach-gates-retire-261027` | 2026-10-27 `49cd65ba2` PADIEM AI LOCAL — test(voice-stt): follow the two Chat bindings #5898 decla… | +2/−0 | 14개 / +19−3735 | #5910 MERGED(base main) · 병합 후 커밋 없음 |  |
| `ops/b62-browser-qa-pairings-fixture-261027` | 2026-10-27 `557b78d7d` PADIEM AI LOCAL — ops(b62): answer the PC pairing read in the two Chat brow… | +0/−1 | 2개 / +18−0 | #5917 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `ops/b62-rollback-recover-active-bindings-261026` | 2026-10-26 `82ecf4450` PADIEM AI LOCAL — ops(b62): let rollback recover from a failed latest versi… | +0/−1 | 5개 / +513−9 | #5871 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `ops/b64-independent-auth-activation-20261027` | 2026-10-27 `cb936ba9e` skerishKang — chore(b64): remove unused activation-gate parser stub | +2/−0 | 1개 / +124−0 | #5975 MERGED(base main) · 병합 후 커밋 없음 |  |
| `ops/connector-watch-com2-261029` | 2026-10-29 `c0409d302` astra1 — ops(#82): a COM2 timer that watches what only the host ca… | +0/−1 | 7개 / +511−0 | #6141 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `ops/file-lane-com2-packaging` | 2026-10-26 `cfd14ff93` skerishKang — fix(5881): avoid Windows reserved COM2 checkout path | +2/−0 | 9개 / +538−0 | #5896 MERGED(base main) · 병합 후 커밋 없음 |  |
| `perf/edge-replay-sync-261102` | 2026-11-02 `26f16d7af` skerishKang — Merge branch 'main' into perf/edge-replay-sync-261102 | +2/−0 | 5개 / +570−12 | #6610 CLOSED → #6630 |  |
| `perf/identity-rpc-keepalive-261102` | 2026-11-02 `33b82c623` skerishKang — Merge branch 'main' into perf/identity-rpc-keepalive-2611… | +1/−0 | 4개 / +358−10 | #6614 CLOSED → #6630 |  |
| `perf/outbound-keepalive-sweep-261102` | 2026-11-02 `812200e82` Kilo — ci: PR #6671 전체 검사 재실행 — 구헤드 적색은 이관 전 실행 (트리 변화 없음) | +4/−1 | 8개 / +621−41 | #6671 CLOSED → #6619 |  |
| `perf/queue-proxy-keepalive-261102` | 2026-11-02 `7601a802d` Kilo — ci: PR #6672 전체 검사 재실행 — 구헤드 적색은 이관 전 실행 (트리 변화 없음) | +5/−1 | 10개 / +790−42 | #6672 CLOSED → #6619 |  |
| `test/5573-pc-endpoint-contract-261026-astra1` | 2026-10-26 `b7f51018e` skerishKang — test(5573): contract — every PC endpoint accepts a Chat t… | +0/−1 | 1개 / +119−0 | #5860 MERGED(squash) · 고유 커밋 0 | 삭제 |
| `test/5783-util-g5-end-to-end` | 2026-10-30 `f5fef191a` skerishKang — test(5783): rebase에 맞춰 chat 요청 계약 어설션을 util 키로 갱신한다 (#623… | +2/−0 | 3개 / +556−3 | #6228 MERGED(base main) · 병합 후 커밋 없음 |  |
| `test/account-isolation-2-261101` | 2026-11-02 `752a02846` skerishKang — Merge branch 'main' into test/account-isolation-2-261101 | +1/−0 | 3개 / +381−0 | #6580 CLOSED → #6630 |  |
| `wip/bookai-auth-attack-261102` | 2026-11-02 `d00fee3fa` Kilo — wip(bookai): 로그인·기록 저장 공격 시험 작성 중 — env 주입·hostile token … | +1/−0 | 1개 / +302−0 | PR 없음 · 내용 main 확인 |  |
| `wip/bookai-pass-261102` | 2026-11-02 `d94e6e347` Kilo — merge: main 동기화 — MARKUP_TEXT 정적 스캔 진화분을 유지하고 주석 재작성은 그대로… | +1/−1 | 1개 / +2−1 | #6674 MERGED(base main) · 병합 후 커밋 없음 |  |
| `wip/chat-multi-attach-261102` | 2026-11-02 `4c9170e98` skerishKang — wip(chat): 첨부 여러 개 — 통합 시험·documents 보강 (전체 스위트 26 실패 분류 … | +2/−0 | 16개 / +1002−165 | PR 없음 · 내용 main 확인 |  |
| `wip/chat-multi-attach-261102-b` | 2026-11-02 `9bdb452c1` ccmkbs-web — wip(chat): 첨부 여러 개 — 화면 핀 시험 갱신 중 (아스트라9 크레딧 소진, CTO 보관 커… | +3/−0 | 21개 / +1020−172 | PR 없음 · 내용 main 확인 |  |
| `wip/connector-release-261102` | 2026-11-02 `30fd0c75c` skerishKang — wip(kagent): 커넥터 새 버전 — 실행기 봉투 20MB 변경·시험 수정 중 (아스트라8 크레딧… | +1/−0 | 2개 / +55−13 | PR 없음 · 내용 main 확인 |  |
| `wip/council-pc-import-261102` | 2026-11-02 `8a5d0c0ee` zwork — wip(council): 축사·SNS 내 PC에서 예전 글 가져오기 — 공용 부품 accept 옵션·c… | +7/−0 | 21개 / +2357−60 | PR 없음 · 내용 main 확인 |  |
| `wip/legacy-hwp-rebase-261102` | 2026-11-02 `25631837c` zwork — wip(6126): main 위 rebase 후 tus 경로 충돌 정리 중 (아스트라8 크레딧 소진, … | +2/−0 | 20개 / +1001−152 | PR 없음 · 내용 main 확인 |  |
| `wip/pc-batch-exec-2-261102` | 2026-11-02 `1b4183ca3` Kilo — wip(pc): 묶음 실행 PC lane 연결 작업 중 — origin/main 병합 + pc_remo… | +3/−0 | 12개 / +460−24 | PR 없음 · 내용 main 확인 |  |

## 원격 삭제 목록

`git cherry origin/main <branch>` 결과에 `+`가 없는 A 브랜치 204개다. 삭제 직전에 같은 조건을 다시 확인했다.

- `astra4/auth-bootstrap-jwks-20261029`
- `astra4/auth-preview-config-20261030`
- `astra4/chat-login-callback-261030`
- `astra4/lovetree-direct-google-design-20261029`
- `astra4/padiem-auth-domain-gate-20261029`
- `astra4/padiem-auth-gate-account-check-20261029`
- `astra4/padiem-auth-verifiers-20261029`
- `astra4/padiem-auth-worker-20261029`
- `central/b64-d1-binding-987`
- `chore/5359-engine-d1-apply-gate-v2`
- `chore/5734-stage2-b14-response-ceilings-261026`
- `chore/5734-stage2-parser-report-char-check-261026`
- `chore/5895-rename-repo-baseline-diff-counts-261027`
- `chore/astra-2-canary-repin-261026`
- `chore/leftover-pr-b-chat-dead-symbols-261029`
- `chore/leftover-pr-d-packages-engine-261029`
- `chore/leftover-pr-e-hidden-switching-261029`
- `chore/leftover-pr-h-dead-ui-261030`
- `chore/leftover-pr-i-empty-promises-261030`
- `chore/leftover-pr-j1-dead-exports-261030`
- `chore/leftover-pr-k-task-modes-261029`
- `chore/leftover-pr-m-state-cap-261029`
- `chore/pc-queue-switch-chat-261030`
- `ci/b62-target-sha-input-guard-261029`
- `design/6421-parliament-final`
- `docs/0f-pc-lessons-261026-astra1`
- `docs/2505-desktop-origin-scope-261026`
- `docs/3595-acceptance-matrix`
- `docs/5093-com2-restore-drill-261030`
- `docs/5573-backup-bytes-not-links`
- `docs/5799-speech-capture-261030`
- `docs/5881-com2-binary-attachments-261030`
- `docs/5881-executor-queue-switch-261030`
- `docs/5881-postmortem-complete-261031`
- `docs/5881-queue-oracle-failover-gap-261030`
- `docs/5895-owner-decision-pc-scope-261028`
- `docs/5895-roadmap-installer-mesh-record-261028`
- `docs/5895-scope-resume-util-b66-261028`
- `docs/5967-design-originals-archive-261030`
- `docs/b64-auth-reconciliation-20261029`
- `docs/browser-agent-lessons-tinyfish-20261027`
- `docs/com2-host-facts-20261026`
- `docs/com2-tunnel-runbook-20261026`
- `docs/cto-status-evening-261030`
- `docs/file-lane-com2`
- `docs/mvp-beta-principles`
- `docs/pc-queue-com2-followup-261030`
- `feat/2833-scheduler-injection-seam`
- `feat/3595-gate-independence`
- `feat/5093-offsite-d1-generation-261029`
- `feat/5573-chat-com2-deploy-261029`
- `feat/5573-drive-root-default`
- `feat/5573-limits-b14-2of3-261026`
- `feat/5573-one-click-pc-install`
- `feat/5573-pc-link-lane-node-card`
- `feat/5573-pc-pair-handoff-without-link`
- `feat/5573-pc-pairing-beat-4c`
- `feat/5573-pc-pairing-card-pr3`
- `feat/5573-pc-pairing-directory-pr2`
- `feat/5573-pc-pairing-pr1`
- `feat/5573-pc-pairing-tag-claim`
- `feat/5573-retire-keyword-admit-ledger-261026-astra1`
- `feat/5608-meeting-activity-book-261027`
- `feat/5728-sns-flow-verify-261027`
- `feat/5728-sns-photo-restore-local1`
- `feat/5786-councillor-cta`
- `feat/5786-councillor-nav-and-touch`
- `feat/5824-b14-user-credential-pr3a-261027`
- `feat/5824-byok-detect-register-261026`
- `feat/5824-byok-paste-key-ui-261026`
- `feat/5885-d1-migrate-gate-261027`
- `feat/5895-b66-pc-excel-form-261028`
- `feat/5895-gate-plan-file-lists-261027`
- `feat/5895-pc-cancel-and-partial-find-261028`
- `feat/5895-remove-caps-D-261028`
- `feat/5895-remove-work-volume-caps-261028`
- `feat/6046-country-label`
- `feat/6064-parliament-design-mobile-261028`
- `feat/6065-cinematic-ui`
- `feat/6065-s1-header-nav-skin-261028`
- `feat/6065-s2-card-archive-261029`
- `feat/6065-s3-editor-skin-261029`
- `feat/6065-s4-auth-archive-261029`
- `feat/6199-util-edit-stored`
- `feat/b62-file-lane-origin-var-declaration-261027`
- `feat/b64-ads-txt-987-261028`
- `feat/b64-auth-dedupe-5987-261029`
- `feat/b64-authority-parity-5864-261027`
- `feat/b64-ayet-contract-alignment-987-261028`
- `feat/b64-ayet-s2s-987-261028`
- `feat/b64-brand-independence-987-261027`
- `feat/b64-browse-empty-filter-state-6074-261029`
- `feat/b64-consumer-completion-987-261027`
- `feat/b64-deploy-gate-987-261027`
- `feat/b64-google-reuse-5987-261027`
- `feat/b64-google-secret-binding-5987-261028`
- `feat/b64-korean-typography-6001-261028`
- `feat/b64-pretendard-webfont-6077-261028`
- `feat/b64-super-admin-6001-261028`
- `feat/b64-ui-triplename-6074-261028`
- `feat/b66-pc-form-entry-261028`
- `feat/beta-ux-structure-261029`
- `feat/chat-file-lane-reference`
- `feat/connector-install-guide-261102`
- `feat/connector-watch-cf-codes-261029`
- `feat/connector-watch-com2-branch-261029`
- `feat/council-apps-ui-ux`
- `feat/file-lane-com2-skeleton`
- `feat/long-turn-progress`
- `feat/mesh-session-command-lane-261029`
- `feat/padiem-apps-integration-contract-261027`
- `feat/pc-connect-card-redesign-261029`
- `feat/pc-write-scope-chat-6044`
- `feat/pdfmd-pc-import-save-6012`
- `feat/queue-lane-status-261029`
- `feat/tail-path-cpu-stats-261029`
- `feat/util-save-status-261030`
- `fix/2544-marker-rederive-261029`
- `fix/2824-mobile-fallback-marker-261026`
- `fix/2824-parser-binding`
- `fix/4816-call-screen-m4-261031`
- `fix/4816-waveform-icon-visible-261030`
- `fix/5479-longpoll-wait`
- `fix/5479-request-scope-task-cleanup-261028`
- `fix/5553-astra-2-mesh-presence`
- `fix/5561-voice-waveform-face-261026`
- `fix/5573-astra-2-argumentless-drives-261026`
- `fix/5573-astra-2-step-selection-logs`
- `fix/5573-astra-2-stream-errors`
- `fix/5573-chat-drive-dispatch`
- `fix/5573-drive-path-arguments`
- `fix/5573-pc-command-utf8-base64-envelope`
- `fix/5573-pc-pairing-not-ready`
- `fix/5573-queue-backup-dir-owner`
- `fix/5573-queue-ua-261030`
- `fix/5643-retire-tunnel-layer-261030`
- `fix/5881-copy-state-cli-argv`
- `fix/5881-file-lane-reason-codes-261031`
- `fix/5881-queue-moment-boundary`
- `fix/5881-queue-request-log`
- `fix/5881-queue-schema-ledger`
- `fix/5881-read-deadline`
- `fix/5895-apply-job-arg-audit-261027`
- `fix/5895-apply-probes-ledger-before-classify-261027`
- `fix/5895-gate-bookmark-key-261027`
- `fix/5895-long-wait-stream-keepalive-261027`
- `fix/5895-oracle-mesh-dispatch-lease-261028`
- `fix/5895-pairing-mock-every-fixture-261027`
- `fix/5895-smoke-login-diagnostics-261028`
- `fix/5895-worker-import-time-js-261028`
- `fix/5942-book-draft-kept`
- `fix/5942-book-persistence`
- `fix/5997-lease-renewal-261028`
- `fix/6027-mobile-hero-portrait`
- `fix/6044-main-red`
- `fix/6065-country-list-refresh`
- `fix/6222-b62-gate-duplicate-steps-261029`
- `fix/6223-init-wait-bounds-261030`
- `fix/84-channel-refusal-leg`
- `fix/admission-error-code-log-261102`
- `fix/b14-info-telemetry-timeout-261026`
- `fix/b14-malformed-upstream`
- `fix/b62-auth-history-pairing-read-in-page`
- `fix/b62-deploy-signed-in-smoke`
- `fix/b62-reviewed-four-vars-20261030`
- `fix/b62-rollback-binding`
- `fix/b62-staged-smoke-identity`
- `fix/b64-deploy-parity-pipefail-5950`
- `fix/b64-form-post-origin-null-5987-261028`
- `fix/b64-mobile-tap-targets-6074-261029`
- `fix/b64-reward-insert-conflict-987-261029`
- `fix/b64-secondary-contrast-5822-261029`
- `fix/chat-fetch-exception-observability-20261030`
- `fix/chat-search-like-50-bytes-261031`
- `fix/ci-hidden-import-audit-261030`
- `fix/connector-watch-lane-status-261029`
- `fix/connector-watch-read-secret-261029`
- `fix/core-ci-pypdf-5568-261030`
- `fix/designer-b14-model-config-261030`
- `fix/engine-d1-count-scope-261030`
- `fix/engine-d1-inspection-http-261030`
- `fix/file-lane-binding-baseline-261030`
- `fix/identity-e2e-product-set`
- `fix/mesh-health-authority-261030`
- `fix/mesh-line-probe-default-off-261029`
- `fix/nogil-waituntil-proxy-release-261030`
- `fix/pc-card-honest-states-261031`
- `fix/pc-chip-honest-states-261031`
- `fix/pc-connect-exe-mesh-url`
- `fix/queue-parity-fixture-clock-261029`
- `fix/stt-chat-binding-report-261030`
- `fix/time-anchor-ops-tests-261029`
- `fix/util-sns-meeting-form-order-261030`
- `inspect/6421-final-scan`
- `local/b64-auth-final-987`
- `lovetree-auth-caller-261027`
- `lovetree-authority-caller-261027`
- `lovetree-identity-registration-261027`
- `ops/5573-queue-service-secret-baseline`
- `ops/5881-queue-to-d1-backfill-261031`
- `ops/b62-browser-qa-pairings-fixture-261027`
- `ops/b62-rollback-recover-active-bindings-261026`
- `ops/connector-watch-com2-261029`
- `test/5573-pc-endpoint-contract-261026-astra1`

