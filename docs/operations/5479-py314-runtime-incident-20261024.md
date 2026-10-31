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
| 순수 파이썬 PBKDF2(HMAC-SHA512, `hashlib.sha512` C 프리미티브 + copy-state) | 격리 3.14 레인 220k = **720ms**, 고정 벡터·C 구현과 바이트 동일 | 대안 보존 (자동 전환 금지) |
| Pyodide 번들 `cryptography`(45.0.5/47.0.0) `PBKDF2HMAC`(OpenSSL) | 격리 3.14 레인 실측: 220k 269ms, 고정 벡터 바이트 동일(§7) | **채택** |
| C `_hashlib` 복원 | Cloudflare/Pyodide 스냅샷 의존 — 상류 문의 사항 | 대기 |

결론 보류 원칙 준수: "불가능" 판단은 위 실측(격리 레인 3.13/3.14 `kdfbench` 결과) 후에만.

> 2026-10-25 갱신: 실측 결과 `cryptography 47.0.0`을 채택했다. 구현·검증 상세는 §7.

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
- 3.14 + cryptography 격리 실측: run 40105508694 `B62 Worker/Pyodide contract` job
  (`B62_WORKER_KDF_BENCH={"pure_ms": 720, "cryptogr_ms": 269, "cryptogr_identity": "true"}`)

## 7. 채택 구현 (2026-10-25)

### 7.1 결정

- KDF 제공자: **Pyodide 번들 `cryptography` 47.0.0 (`PBKDF2HMAC`, OpenSSL)**.
- 저장 자격증명 형식·반복 횟수·회원 데이터 변경 없음: `pbkdf2_sha512$220000$...` 그대로.
- Worker 의존성에 `cryptography==47.0.0` + `cffi==2.0.0`을 **메인 의존성**으로 추가한다
  (Pyodide v314 wasm 휠 정확 핀, `cffi` 2.1.1은 wasm 휠 부재로 emscripten 빌드 불가).
- `wrangler.toml` 호환일: `2026-08-25` → `2026-09-08` (Python 3.14, workerd#6624 수정 스냅샷).

### 7.2 디스패치 우선순위 (`app/password_kdf.py`)

`resolve_kdf_provider(iterations)` 한 곳이 결정하고, 디스패치와 런타임 프로브가
같은 함수를 읽는다.

| 순서 | 제공자 | 조건 |
|---|---|---|
| 1 | `hashlib` | 런타임에 `hashlib.pbkdf2_hmac` 존재 (3.13, 최속) |
| 2 | `cryptography` | 번들 패키지 로드 가능 (3.14) |
| 3 | `webcrypto` | **10만 회 이하 요청에 한정** + dHermetic `runtime_loader` 주입 시 |
| 4 | `python` | dHermetic 테스트 전용 (자동 전환 없음) |
| 5 | `unavailable` | 디스패치가 원인을 명시해 예외 발생 |

- 저장 비용(220,000)은 3번 경로에 절대 도달하지 않는다: 운영 엣지 WebCrypto 상한
  100,000을 다시 밟지 않기 위한 구조적 차단이며, 회귀 테스트가 증명한다.
- 순수 파이썬 구현은 고정 벡터 검증용 대안으로 남기되, 배포 런타임에서 자동으로
  선택되지 않는다(성을 숨기는 자동 강등 금지).

### 7.3 검증 범위

- 격리 3.14 Workerd/Pyodide 레인: 부팅한 인터프리터·저장 해시 220k 왕복·제공자 보고를
  함께 단정한다(`B62_WORKER_KDF220K_PROVIDER`). 이전 #5733 레인은 로컬 Workerd의
  WebCrypto가 220k를 수락해 운영 엣지 상한을 볼 수 없었다.
- 로컬 Workerd 결과는 **운영 엣지의 성공이 아니다**. 운영 검증은 보호 배포 후 실제
  엣지 인증 E2E로만 판정한다 (§7.4).

### 7.4 운영 전환·복구 기록

배포·복구 결과는 본 문서가 아니라 #5479 이슈 코멘트에 실행 시각·버전 ID·응답 상태와
함께 기록한다. 배포 직전 활성 버전 ID를 읽기 전용으로 기록하고, 그 ID를
`rollback_production_code`의 `previous_version_id`로 사용한다.

## 8. 3.14 운영 전환 실측과 롤백 (2026-10-25)

§7의 구현을 실제 운영에 배포하고 측정한 결과, **KDF는 해결됐고 런타임은 실패**했다.

### 8.1 배포

- 병합: PR #5741(`0d816573`) → PR #5746(`2dfd460d`). 보호 배포 run `40109855217` SUCCESS.
- 운영 활성 버전: `git-2dfd460d535cfb2653dc7c6a14acc3ed2b805cd0` (Pyodide 3.14).
- 배포 직전 활성 버전(롤백 대상): `065f62d2-c3c8-4890-9606-ceddf9e232c5` (`git-cccbb5b5`, 3.13).
- 배포 게이트 smoke/secret/binding readback: PASS.

### 8.2 운영 엣지 3.14 측정 (KDF 정상)

| 검사 | 결과 |
|---|---|
| `POST /api/auth/password/register` | 200 (cryptography로 해시) |
| 세션 `/api/auth/status` | `authenticated:true`, `account_method:password` |
| 로그인(정답) | 200 |
| 로그인(오답) | 401 JSON `invalid_credentials` |
| 비밀번호 변경 + 새 비밀번호 로그인 | 200 / 200, 이전 비밀번호 401 |
| 없는 계정 로그인(220k 더미 KDF 경로) | 401 JSON — **3.14에서 KDF 전체 실행 확인** |

즉 `NoGilError`의 원인이던 `hashlib.pbkdf2_hmac` 부재·WebCrypto 10만 상한 문제는 운영 엣지에서 해소됐다.

### 8.3 런타임 결함 (롤백 원인)

동일 3.14 배포에서 동시성/반복 요청이 실패했다.

| 검사 | 3.14 (`git-2dfd460d`) | 3.13 (`git-cccbb5b5`) |
|---|---|---|
| 순차 `GET /health` 25회 | **6회 HTTP 500** | 25회 200 |
| 동시 `/api/auth/status` 8 | **3회 500** | 8회 200 |
| 동시 로그인 8 | **1회 500 + 1회 503** | 8회 401 |

Workers tail 확정 예외:

```
SystemError: Cannot enter a promising task from inside another running promising task.
This is a bug in Pyodide.
```

- 1회는 `introspection.CpuLimitExceeded: Python Worker exceeded CPU time limit` (CPU 8ms 계정).
- `NoGilError`는 3.14 구간에서 **0건**.
- `/health`는 KDF를 쓰지 않는데도 실패했다 → KDF·앱 로직 문제가 아니라 **Pyodide async 브리지 결함**이다.

### 8.4 롤백

- `rollback_production_code` 모드로 기록된 `065f62d2` 복구 성공 (run `40111743619`, 활성 `git-cccbb5b5`).
- 복구 후 재측정: 순차 `/health` 25/25 200, 동시 status 8/8 200, 동시 로그인 8/8 401, tail 예외 0건.
- 같은 모드가 두 번 실패했다: 1차는 공개 origin health 증명이 당시 500 때문에 BLOCKED, 2차는 main SHA 이동. 둘 다 mutation 0.

### 8.5 결론·다음

- 저장 자격증명·회원 데이터·KDF는 변경 없이 유지된다. 3.14용 구현은 dev 의존성과 테스트로 보존하고, Worker 번들에는 넣지 않는다(§7.2 표는 3.14 경로를 재개할 때 그대로 사용).
- 남은 차단점은 **Pyodide 3.14 async 브리지(`promising task`) 결함**이며 app/KDF로 우회할 수 없다. 상류(Cloudflare/Pyodide) 보고 대상이다.
- 다음 실행: ① 최소 재현(단일 isolate에 `await` 체인 다수) 상류 리포트 ② 차기 3.14 스냅샷에서 동일 A/B 재측정 ③ 재개 시 이 문서 §8.3 표를 합격 기준으로 사용.
