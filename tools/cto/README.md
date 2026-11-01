# CTO 도구 (PR 머지 자동화)

CENTRAL CTO가 레인 PR을 머지할 때 쓰는 스크립트. **실행 위치: 컴1(Padiem-Command-Center).** `gh` 로그인 상태 필요, 비밀 값은 쓰지 않음.
작업용 사본은 컴1 `C:\Users\limone\AppData\Local\Temp\cto-iss\`에도 있으나(임시 폴더라 지워질 수 있음), 정본은 이 폴더.

| 스크립트 | 용도 |
|---|---|
| `automerge.py <PR번호>` | CI를 40초마다 확인 → 실패하면 실패 잡만 1회 재실행 → 모두 통과하면 squash 머지 + 브랜치 삭제. 두 번째 실패·충돌이면 멈추고 결과만 출력 |
| `merge_ignore.py <PR번호> <무시할 체크 이름…>` | 오탐으로 확인된 체크(예: GitGuardian 오탐)만 무시하고 나머지가 통과하면 머지 |
| `prfail.py <PR번호>` | 실패한 체크의 로그에서 FAILED/Error/assert 줄만 뽑아 보여 줌(원인 파악용) |

사용 예(PowerShell, 백그라운드):
```
Start-Process -WindowStyle Hidden python -ArgumentList "tools\cto\automerge.py","6554" -RedirectStandardOutput "am6554.log"
```

주의
- GitHub의 auto-merge 기능은 쓰지 않는다(`auto_merge=null`이 정상). 이 스크립트가 그 역할.
- PR이 많을 때는 하나 머지될 때마다 나머지가 충돌한다. 같은 파일을 건드린 PR이 많으면 하나씩 풀지 말고 **통합 브랜치 하나로 합쳐 한 번에 머지**한다(11-01 #6554 사례).
