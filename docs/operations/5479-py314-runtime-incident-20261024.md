# #5479 — Cloudflare Python 3.14 런타임 전환 시도 및 복구 인고(auto-mign) 기록 (2026-10-24)

통칭: 3.14 런타임 전환 장애·복구 증거 정리. 관련 이슈 #5479, #5664. 선행 #5732.

## 1. 타임라인 (모두 2026-10-24 UTC)

| 시각(UTC) | 사건 | 근거 |
|---|---|---|
| ~07:35 | 격리 CI 레인 1차: 3.14 부팅 성공, pylock 재생성 누락으로 계약 실패 | run 40071360420 |
| ~07:44 | pylock 재생성 커밋(b7cab7530) | PR #5733 |
| ~07:48 | 격리 CI 레인 2차: **`ok 3.14 kdf=c-path-absent kdfasync=ok tz=ok`** — 3.14 부팅·WebCrypto 바이트 동일성·IANA tz·4케이스 PASS | run 40075476703 |
| ~07:5x | PR #5733 병합(66e8adbc) | GitHub |
| ~08:0x | 보호 배포 run 40076096543 SUCCESS — 운영 3.14 전환 | GitHub |
| 08:09:58 | 운영 인증 E2E: 가입 → 비JSON 500 | Workers tail traceback |
| 08:10:00 | 로그인 → 비JSON 500 | 동일 |
| 08:10:02 | 재설정 요청 → 비JSON 500 | 동일 |
| ~08:1x | 긴급 롤백 시도(run 40077161401) — **실패**: 기록된 이전 버전 없음 | GitHub |
| ~08:2x | revert PR #5736 병합(e4a1c81f) | GitHub |
| ~08:5x | 복구 배포 run 40078483333 SUCCESS — **운영 3.13 복구** | GitHub |
| 복구 후 | 인증 오류 비JSON 500 → 정상 JSON 복귀; 타 흐름 가입/로그인/재설정확정 ok; NoGilError cluster 3.13에서도 관측 | Workers tail |

## 2. 최초 실패 위치·원인 (확정)

- 위치: `app/password_kdf.py:156` — `subtle.deriveBits(params, key, dklen * 8)`
- 예외: `pyodide.ffi.JsException: NotSupportedError: Pbkdf2 failed: iteration counts above 100000 are not supported (requested 220000).`
- 인고: Workers **WebCrypto PBKDF2 구현의 반복 횟수 상한 100,000** vs 저장 자격증명 형식 `pbkdf2_sha512$220000$`(220,000회). 3.14 스냅샷은 `_hashlib`이 없어 C 경로가 없음 → 저장 해시 검증 경로가 3.14에서 구조적으로 부재.
- 왜 격리 레인이 못 잡았나: 프로브의 `kdfasync=ok`는 2,000회 저반복 바이트 동일성 검증이었다. → 프로브에 실알고리즘 220k 케이스 추가(본 PR).

## 3. 복구

- 설계된 `rollback_production_code` 모드는 **`previous_version_id` 디스패치 입력이 비어 실패** — 배포가 이전 버전 ID를 기록하지 않음(§5).
- 대체 복구: revert PR #5736(e4a1c81f) → 보호 배포(run 40078483333)로 3.13 복구. 저장 계정·해시·권한 데이터 변경 없음.

## 4. 3.14 대안 조사 (220k 저장 해시 무변경 검증)

| 대안 | 근거 | 판단 |
|---|---|---|
| WebCrypto `deriveBits` 220k | 런타임 상한 100k (운영 traceback) | 불가 |
| WebCrypto 100k×체크 분할 | PBKDF2의 U_i 체인은 API로 재개 불가(수학적 비동치) | 불가 |
| 순수 파이썬 PBKDF2(HMAC-SHA512, `hashlib.sha512` C 프리미티브 + copy-state) | 로컬 CPython 3.11 기준 220k = **0.49초**, 고정 벡터·C 구현과 바이트 동일. workerd 실측은 프로브 `kdfbench` 케이스로 진행(본 PR) + 3.14 레인 증거 필요 | **유력 — 실측 대기** |
| Pyodide 번들 `cryptography`(45.0.5/47.0.0) `PBKDF2HMAC`(OpenSSL) | 두 스냅샷 모두 패키지 내장 확인(pyodide-lock). 실런타임 동작·번들 영향은 증거 브랜치에서 검증 예정 | 유력 — 실측 대기 |
| C `_hashlib` 복원 | Cloudflare/Pyodide 스냅샷 의존 — 상류 문의 사항 | 대기 |

결론 보류 원칙 준수: "불가능" 판단은 위 실측(격리 레인 3.13/3.14 `kdfbench` 결과) 후에만.

## 5. 롤백 게이트 결함 (별도 항목)

- 원인: `rollback_production_code` 모드가 `previous_version_id`를 **디스패치 입력**으로만 요구(`test -n "${PREVIOUS_VERSION_ID}"`), 배포 작업은 이를 어디에도 기록하지 않음 → 즉시 롤백 시 수동 조회 필요, 기록 부재로 실패.
- 최소 수정안:
  1. `deploy-production-code` 작업의 readonly 스냅샷 단계에서 `READONLY_ACTIVE_VERSION`을 `$GITHUB_STEP_SUMMARY`에 `PRE_DEPLOY_ACTIVE_VERSION`으로 기록(현재 evidence 단계는 `unknown`으로만 출력).
  2. rollback 모드의 오류 메시지에 "최근 deploy run summary의 PRE_DEPLOY_ACTIVE_VERSION 사용" 안내 추가.
  3. (선택) rollback 모드가 입력이 비면 최근 deploy summary 조회 스크립트로 자동 제안 — 위험도 낮은 읽기 전용.
- 배포 게이트 파일은 보호 대상이므로 본 PR에는 미포함, 별도 PR로 진행.

## 6. 증거 파일

- 격리 3.14 레인: run 40075476703 (`ok 3.14 kdf=c-path-absent kdfasync=ok tz=ok`)
- 3.14 운영 배포: run 40076096543 / 실패 traceback: Workers tail (08:09–08:10 UTC)
- 롤백 실패: run 40077161401 / 복구 배포: run 40078483333
- 복구 후 auth 정상: 로그인 401(JSON), 타 흐름 register/login/reset/confirm ok
