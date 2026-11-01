# CTO 도구 (PR 머지 자동화)

CENTRAL CTO가 레인 PR을 머지할 때 쓰는 스크립트. **실행 위치: 컴1(Padiem-Command-Center).** `gh` 로그인 상태 필요, 비밀 값은 쓰지 않음.
작업용 사본은 컴1 `C:\Users\limone\AppData\Local\Temp\cto-iss\`에도 있으나(임시 폴더라 지워질 수 있음), 정본은 이 폴더.

| 스크립트 | 용도 |
|---|---|
| `automerge.py <PR번호> [--delay 초]` | CI를 40초마다 확인 → 실패 잡만 1회 재실행 → 검사가 **1개 이상 등록**되고 모두 끝나면 squash 머지 + 브랜치 삭제. 뒤처지면 update-branch, 일시적 오류는 재시도, 충돌·진짜 CI 실패만 멈추고 사유 한 줄 출력 |
| `merge_ignore.py <PR번호> <무시할 체크 이름…>` | 오탐으로 확인된 체크(예: GitGuardian 오탐)만 무시하고 나머지가 통과하면 머지 |
| `prfail.py <PR번호>` | 실패한 체크의 로그에서 FAILED/Error/assert 줄만 뽑아 보여 줌(원인 파악용) |

## automerge.py (11-01 안정화)

사용 예(PowerShell, 백그라운드) — `--delay 150`이 기존 `Start-Sleep 150` 감싸기를 대체:
```
Start-Process -WindowStyle Hidden python -ArgumentList "tools\cto\automerge.py","6562","--delay","150" -RedirectStandardOutput "am6562.log"
```
전면 실행: `python tools\cto\automerge.py 6562 --delay 150`

### 옵션
| 옵션 | 기본값 | 의미 |
|---|---|---|
| `--delay 초` | 0 | 시작 전 대기. CTO가 감싸던 `Start-Sleep 150`을 이 옵션으로 흡수 |
| `--grace 초` | 180(3분) | 시작 후 이 시간 동안은 검사 상태와 무관하게 머지하지 않음 |

### 11-01 실패 3가지 수정
1. **검사 미등록**(#6556, #6557): PR을 만든 직후엔 CI 검사가 0개라 `pending=0 fail=0`으로 보여 바로 머지를 시도하다 "base branch policy prohibits the merge"로 실패했다. → 검사가 **1개 이상 등록**되고 전부 끝날 때까지 기다리고, 시작 후 **3분(기본)** 은 0개여도(또는 일찍 통과해도) 머지하지 않는다. 검사가 아예 등록되지 않는 PR(예: 문서 전용)은 약 47분 뒤 `RESULT: TIMEOUT`이 나오니 merge_ignore.py나 수동 머지로 처리.
2. **뒤처짐**(#6560): 머지가 "Head branch is out of date"/"BEHIND"로 실패하면 `gh pr update-branch`를 실행하고 **새 CI를 다시 기다린다**(최대 3회, 초과 시 `RESULT: OUT_OF_DATE`). update-branch 직후 남아 있는 허수 fail은 2폴링 동안 무시한다.
3. **바로 종료 금지**: 정책(POLICY)·네트워크(NETWORK) 같은 일시적 머지 실패는 재시도(총 시도 상한 8회). **충돌(CONFLICTING)** 과 **재실행 1회 후에도 실패한 CI(CI_FAIL)** 만 즉시 종료하고 이유를 한 줄로 출력한다.

### 결과 마지막 줄(형식 유지)과 종료 코드
| 코드 | RESULT | 의미 |
|---|---|---|
| 0 | `RESULT: MERGED` | 머지 완료(squash + 브랜치 삭제). 이미 머지된 PR도 0 |
| 1 | `RESULT: CI_FAIL (still failing after one rerun)` | 재실행 후에도 CI 실패 |
| 2 | `RESULT: CONFLICTING (…)` | 충돌 — 수동 해결 필요 |
| 3 | `RESULT: TIMEOUT` | 폴링 한도(70회×40초 ≈ 47분) 내에 머지 조건 미충족 |
| 4 | `RESULT: OUT_OF_DATE (…)` | update-branch 3회 후에도 뒤처짐 |
| 5 | `RESULT: MERGE_RETRY_EXHAUSTED (…)` | 일시적 오류가 상한까지 반복 |
| 6 | `RESULT: STARTUP_ERROR` | PR 조회 실패(네트워크 등) |
| 7 | `RESULT: PR_CLOSED` | PR이 이미 닫힘 |

### 유지된 기존 동작
40초 주기 폴링 · 실패 잡 1회 재실행(`gh run rerun <run> --failed`) · squash 머지 + 브랜치 삭제 · 마지막 줄 `RESULT: …` 형식.

### 시험
`python -m pytest tools/cto/test_automerge.py -q` — gh 호출은 전부 subprocess 모의(실제 GitHub 호출 없음). 검사 미등록 0개 방어·3분 유예, 뒤처짐 복구와 3회 상한, 정책·네트워크 재시도, 정상 머지, 충돌 즉시 종료, CI 재실행 후 실패, `--delay`, 종료 코드를 검증한다.

주의
- GitHub의 auto-merge 기능은 쓰지 않는다(`auto_merge=null`이 정상). 이 스크립트가 그 역할.
- PR이 많을 때는 하나 머지될 때마다 나머지가 충돌한다. 같은 파일을 건드린 PR이 많으면 하나씩 풀지 말고 **통합 브랜치 하나로 합쳐 한 번에 머지**한다(11-01 #6554 사례).
