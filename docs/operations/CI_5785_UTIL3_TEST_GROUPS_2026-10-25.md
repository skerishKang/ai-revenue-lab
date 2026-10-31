# #5785 — 의원3종(축사·SNS·회의정리) 독립 테스트 그룹

상태: **SOURCE_COMPLETE / CI_JOB=NOT_ADDED**

이 문서는 #5785의 A·B·C(테스트 구현) 결과와 D(CI 연결 최소 수정안)를 기록한다.
CI 워크플로와 분류기(`.github/workflows/b62-padiem-chat-ci.yml`,
`.github/scripts/b62_ci_impact_scope_3989.py`, `b62-browser-qa-unified.yml`)는
CENTRAL 소유이므로 **이번 작업에서 수정하지 않았다**. 아래 D는 손대지 않은
최소 연결안이며, 필수 CI·branch protection·main push 전체 회귀는 그대로다.

## 1. 기준선 실측 (변경 전)

### 1-1. 로컬 테스트 시간 (Windows, 이 PC)

| 선택 범위 | 파일 수 | 테스트 | pytest 시간 | wall |
|---|---|---|---|---|
| 기존 util 관련 전체 (5608×3 + 5728×4) | 7 | 39 passed | 3.37s | 5.25s |

의원3종 중 한 기능만 확인하려는 경우에도 위 7개 파일을 돌리는 것이 최소
선택이었다. 기능별 하위 선택 명령은 없었다.

### 1-2. 최근 의원3종 관련 PR의 CI (GitHub Actions)

| PR | 성격 | B62 full regression | browser-qa | Worker/Pyodide | 전체 소요 |
|---|---|---|---|---|---|
| #5764 | SNS 사진 기능 | 2m20s | 4m39s | 1m45s | 약 4m40s (browser-qa가 최장) |
| #5776 | SNS 테스트만 수정 | 3m33s | SKIPPED (12개 job skip) | 1m55s | 약 4m06s |

테스트 파일만 바꾼 #5776에서도 `B62 full regression`이 실행됐다. 분류기가
`apps/padiem-chat/**` 변경을 full로 보내기 때문이며, 이는 기존 보호 동작이다.
평균 가속률은 이번 작업에서 주장하지 않는다(선택형 job 미도입).

## 2. 구현 (A·B·C)

### A. 기능별 독립 테스트 그룹

| 그룹 | 파일 | 테스트 | pytest 시간 (wall) |
|---|---|---|---|
| speech (축사·인사말) | `tests/test_5785_speech_tool.py` + `test_5608_util_page_visibility_and_reopen.py` | 17 | 1.36s (3.39s) |
| sns (SNS 홍보) | `tests/test_5785_sns_tool.py` + `test_5728_sns_photo_compose.py` | 9 | 1.67s (3.89s) |
| meeting (회의정리·활동집) | `tests/test_5785_meeting_tool.py` | 7 (+1 xfail) | 1.00s (3.25s) |
| shared (공통 재사용) | `tests/test_5785_util_shared_contract.py` + `test_5608_util_sidebar_submenu.py` + `test_5608_body_glass_unification.py` | 19 | 1.78s (4.15s) |
| all (중복 제거 합집합) | 8 | 52 (+1 xfail) | 3.68s (5.29s) |

공통 하네스는 `tests/_5785_util_harness.js`(실제 `static/util-menu.js` 실행)
+ `tests/_5785_util_runner.py`(시나리오 1회 실행·캐시)이다. #5608/#5728
하네스와 같은 계약을 따르며 제품 경계를 새로 만들지 않는다.

각 그룹이 검증하는 계약:

- speech: 폼 필드 → 프롬프트(분량·말투·샘플 문체) → `/api/chat` → 편집 →
  `{행사명}.txt` 저장 → 목록 → 재열기 본문 일치
- sns: 플랫폼별 프롬프트(블로그/페이스북/인스타그램) → 결과 카드 제목 →
  `{플랫폼 제목}.txt` 저장 → 플랫폼 전환 시 사용자 편집 보존
- meeting: 요약 프롬프트 5개 항목 → 저장 → 활동 기록 → 재열기 →
  선택 기록 기반 활동집 프롬프트(`[기록: 파일명]`, 무창작 지시)와 결과
- shared: 세 도구 모두 `POST /api/chat`과 기존 프로젝트 파일 경로만 사용,
  `credentials: "include"`, 생성만으로는 저장이 일어나지 않음

### B. 공통 기능 재사용 검증

`test_5785_util_shared_contract.py`가 실제 요청 로그로 확인한다. 새 API·별도
저장소·별도 인증 없음을 "소스 주장"이 아니라 실행된 fetch 기록으로 검증한다.

### C. 집중 실행

```
apps/padiem-chat$ python scripts/util3_test_groups.py --list
apps/padiem-chat$ python scripts/util3_test_groups.py speech
apps/padiem-chat$ python scripts/util3_test_groups.py sns
apps/padiem-chat$ python scripts/util3_test_groups.py meeting
apps/padiem-chat$ python scripts/util3_test_groups.py shared
apps/padiem-chat$ python scripts/util3_test_groups.py all
```

exit code는 pytest 결과를 그대로 반환한다.

## 3. D. CI 연결 최소 수정안 (CENTRAL 승인 필요, 이번 PR에서 미적용)

기존 분류기와 워크플로를 최대한 재사용하는 최소안:

1. **경로→그룹 표시자만 추가** (`.github/scripts/b62_ci_impact_scope_3989.py`):
   변경 경로가 아래에만 속하면 `util3_group` 출력을 추가한다. 그 외 경로가
   하나라도 섞이면 기존 `full` fail-closed 동작을 유지한다.
   - speech: `tests/test_5785_speech_tool.py`, `tests/test_5608_util_page_visibility_and_reopen.py`
   - sns: `tests/test_5785_sns_tool.py`, `tests/test_5728_sns_photo_compose.py`
   - meeting: `tests/test_5785_meeting_tool.py`
   - shared/공통: 위 표에 없는 `apps/padiem-chat/**`, `.github/**` → `full`

   주의: `static/util-menu.js`, `util-menu.css`는 세 도구의 공용 파일이므로
   **어떤 그룹으로도 축소하지 않고 `full`을 유지**한다.

2. **선택형 job 1개 추가** (`b62-padiem-chat-ci.yml`):
   `util3_group != none`일 때만 `python scripts/util3_test_groups.py <group>`을
   실행하는 job. `b62-test` fan-in에는 **추가 필수 조건으로 넣지 않는다**.
   기존 `B62 full regression`은 그대로 필수로 남긴다.

3. **브라우저 QA**: 의원3종 UI는 기존 `browser-qa` / `util` 관련 job이 계속
   담당한다. 새 job을 만들지 않는다(`b62_browser_qa_path_plan.py` 재사용).

4. 검증 방법(도입 시): 동일 PR에서 (a) 기존 full job 결과 불변, (b) 선택형
   job이 해당 그룹만 실행, (c) `util-menu.js` 변경 시 선택형 job이 붙지 않고
   full만 실행되는지 확인한다.

## 4. 확인 사항과 제약

- `B62 full regression`(main push 포함)과 branch protection은 이번 작업에서
  변경하지 않았다.
- 운영 E2E·실 D1·실 Provider 호출은 이 그룹에 포함되지 않는다
  (`LIVE_VERIFIED=NO`). SNS 사진의 실 DB/이미지 경로는 #5728 소유 그대로다.
- **발견 결함(이 PR에서 수정하지 않음):** `static/util-menu.js`의 회의정리
  `gen()` 마지막 줄이 SNS 빌더 스코프의 `previewBox` / `renderPreview`를
  참조한다. 브라우저는 요약을 표시한 뒤 `ReferenceError: previewBox is not
  defined`를 unhandled rejection으로 남긴다. 사용자 화면의 요약 자체는
  정상이므로 `test_5785_meeting_tool.py`에 strict xfail로 고정했고, 수정은
  #5608/#5731 소유 범위로 남긴다.
