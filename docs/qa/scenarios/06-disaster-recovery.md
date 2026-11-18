# ⑥ 장애 복구

**목적:** 배포 직후 일일 점검에서 실패 판정이 나왔을 때, 화면과 서버를 구분해 원인을 좁히고 front만 직전 운영 버전으로 되돌리는 순서를 대본화합니다. 화면을 고치는 것이 먼저가 아니라 판정 줄을 읽고 범위를 가르는 것이 먼저입니다.  
**사전 조건:** 배포 기록(릴리스 로그)과 컴2 배포 저널을 읽을 수 있어야 합니다. 게스트 화면은 로그인 없이 재현합니다. 계정·토큰·식별자 값은 이 대본에 적지 않고 현장 기록에서 읽습니다.  
**튜토리얼 공개 범위:** 없음(운영 대본)  
**촬영한 단계:** 없음

| 단계 | 사용자 동작 → 기대 화면·응답 | 확인 지표 | 튜토리얼 캡션 |
|---|---|---|---|
| 1 | 일일 점검 로그에서 집계 줄 읽기 → `USAGE_CHECK verdict=... flows=8 checked=8 failed=N` 표시 | `verdict=FAIL`이면 실패, `failed` 수 | — |
| 2 | 흐름별 판정 줄 8개 읽기 → `USAGE_FLOW name=... verdict=... code=... head=...` 표시 | `verdict`, `code`, `head` | — |
| 3 | 이전 실행의 같은 `name` 줄과 나란히 비교 → 바뀐 `verdict`·`code`·`head`만 표시 | 이전 실행 대비 변화 | — |
| 4 | 배포 직후 릴리스 기록의 검증 단계 읽기 → 표적별 `VERIFY ... =match`, 미스매치 여부 표시 | `PAGES_VERIFY_FAIL` 유무, mismatch 항목 | — |
| 5 | 컴2 배포 게이트·저널 읽기 → `COM2_DEPLOY_SUMMARY=chat:PASS ...`, 적용된 마이그레이션과 백업, 트레이스백 0 확인 | `chat:PASS`, `COM2_DEPLOY_CHAT_MIGRATION_APPLIED`, `TRACEBACKS=0` | — |
| 6 | 컴2가 의심스러우면 저널의 health 재시도·트레이스백·마이그레이션 실패를 먼저 확인 → 없으면 컴2 배제 | health 시도 횟수, 실패 줄 유무 | — |
| 7 | 게스트 브라우저에서 첫 화면 재현 → 로그인 없이 `/api/pc/pairings`의 401이 콘솔 오류로 표출되는지 확인 | `USAGE_BROWSER name=browser_shared_login console_error=...`, 재현 횟수 | — |
| 8 | 화면 스탬프 대조 → 페이지의 `?v=` 값과 `USAGE_FLOW name=browser_stamp ... head=` 값이 이번 배포 기록의 스탬프와 같은지 확인 | 스탬프 일치 여부 | — |
| 9 | 원인 확정 → 컴2 게이트 PASS, 마이그레이션 정상, 게스트에서만 콘솔 오류, 스탬프가 새 배포면 front 원인 | 위 5–8 항목의 조합 | — |
| 10 | front 롤백 버전 확인 → **이번** 배포 기록의 `previous front Version ID`(요약의 `FRONT_VERSION_PREV`) 값을 읽음 | 기록 안의 직전 Version 줄 | — |
| 11 | front만 되돌리기 → front Worker 디렉터리에서 `npx wrangler rollback <직전 Version ID>` 실행 | 롤백 대상 값, 명령 성공 | — |
| 12 | 컴2·마이그레이션 유지 → 예전 SHA 직접 배포는 하지 않고, 되돌리기가 필요하면 revert PR → main 머지 → 재배포 경로만 사용. 마이그레이션 표는 DROP하지 않음 | 배포 SHA가 `origin/main`인지, ledger·백업 유지 | — |
| 13 | 롤백 뒤 1차 확인 → `chat.padiem.net /health=200`, 게스트 콘솔 오류 0, 페이지 `?v=`와 `browser_stamp head=` 대조 | HTTP 200, 콘솔 오류 줄 0, 스탬프 일치 | — |
| 14 | `USAGE_FLOW` 다시 실행 → 8개 흐름 모두 PASS, 특히 `browser_shared_login`이 PASS로 돌아옴 | `USAGE_CHECK verdict=PASS failed=0`, 해당 흐름 `verdict=PASS` | — |
| 15 | 섞인 상태 기록 → 컴2 트리 SHA와 페이지 스탬프 `?v=`를 대조해 front와 컴2 버전이 다를 수 있음을 상태로 남김 | 컴2 SHA vs 페이지 스탬프, 불일치 시 원인 재판정 | — |

운영 기록(사고·런북·컷오버·상태 보고)은 비공개 운영 기록 위치(거버넌스 폴더, 같은 상대 경로)에 두고 이 대본에는 절차와 판정 줄 형식만 둡니다(2026-11-11, #7404). 버전·스탬프 값은 오래된 문서에서 가져오지 않고 그 배포의 기록에서 다시 읽습니다.

## 판정 줄 읽는 법

- 집계: `USAGE_CHECK verdict=<PASS|FAIL|SKIPPED> flows=8 checked=<수> failed=<수> skipped=<수> elapsed_ms=<수>`. `verdict`가 `FAIL`이면 `failed`된 흐름 이름을 아래 줄에서 찾습니다.
- 개별 흐름: `USAGE_FLOW name=<이름> verdict=<판정> elapsed_ms=<수> entry_ms=<수> answer_ms=<수> code=<코드> head=<스탬프 또는 요약>`. 이름별로 `verdict`와 `code`를 이전 실행과 비교합니다. `SKIPPED`는 실패가 아니라 미실행이므로 원인 목록에서 제외합니다.
- 콘솔 오류: `USAGE_BROWSER name=<이름> console_error=<코드>`. 같은 코드가 여러 줄 나오면 한 흐름의 반복 재현으로 봅니다.
- 복구 점검: `USAGE_FLOW name=restore_smoke verdict=<판정> ... code=<코드>`. 이 줄의 PASS는 백업 복원 경로만 확인한 것이며 화면 장애가 없었다는 뜻이 아닙니다.

## 원인을 가르는 순서

1. 컴2 배포 게이트와 저널을 먼저 봅니다. `COM2_DEPLOY_SUMMARY`가 PASS이고 마이그레이션이 정상 적용됐으며 트레이스백이 없으면 컴2 배포는 원인에서 제외합니다.
2. 게스트 브라우저에서 같은 화면을 다시 엽니다. 로그인 상태와 무관하게 콘솔 오류가 나오면 front가 표시 단계에서 오류를 만든 것입니다. 서 쪽 응답 자체가 비정상이면 1단계 판정을 다시 봅니다.
3. 스탬프를 대조합니다. `browser_stamp head=`와 페이지 `?v=`가 이번 배포 값이면 front가 새 버전으로 나간 상태입니다.
4. 세 항목이 모두 맞으면 front 롤백으로 범위를 좁힙니다. 하나라도 어긋나면 그 항목부터 다시 확인하고 성급하게 롤백하지 않습니다.

## 롤백 경계

- front: `npx wrangler rollback <직전 Version ID>`. 값은 이번 배포 기록의 직전 Version 줄에서 읽습니다. 오래된 문서에 적힌 값을 쓰지 않습니다.
- 컴2: `deploy_from_main.sh`는 `origin/main`이 아닌 SHA를 거부합니다. 따라서 예전 SHA로 되돌리는 직접 배포는 없고, 되돌리기가 필요하면 revert PR을 main에 머지한 뒤 그 SHA로 재배포합니다.
- 마이그레이션: 적용된 표를 DROP하지 않습니다. 적용 ledger와 배포 전 백업을 유지한 채로 둡니다.

## 롤백 뒤 화면 상태

front만 직전 버전으로 돌아가므로 front와 컴2가 서로 다른 버전인 섞인 상태가 정상일 수 있습니다. 이때는 컴2가 서비스하는 트리 SHA와 페이지가 노출하는 스탬프 `?v=`를 각각 읽어 두 값이 다름을 상태로 기록합니다. 두 값이 같다고 가정하지 않고, 달라진 지점이 있으면 원인을 가르는 순서를 한 번 더 돌립니다. pages 미러(`padiem-chat.pages.dev`)는 front와 별도 표면이므로 검증 단계의 mismatch 항목을 따로 확인합니다.

이 대본의 자동 시험은 백업을 임시 데이터 폴더에 복원하고 GET만 확인하는 격리 점검입니다. 운영 호스트에서 전체 복원을 실행하지 않습니다.
