# Development Evidence Requirements

상태: Canonical  
적용 범위: Issue, branch, Pull Request, local validation, deployment review

## 1. 목적

이 문서는 AI 개발 작업에서 인정되는 최소 증거를 정의한다.

“완료했습니다”, “테스트가 통과했습니다”, “배포했습니다” 같은 서술은 아래 증거가 없으면 최종 판단 근거로 사용하지 않는다.

## 2. 공통 revision identity

모든 구현·검증·리뷰 보고에는 다음을 포함한다.

- Repository full name
- Default branch
- Exact starting base SHA
- Target branch
- Exact reported or tested HEAD SHA
- Base 대비 ahead/behind 또는 merge-base 관계
- Worktree clean/dirty 상태 또는 GitHub branch-only 작업 여부

SHA는 가능한 한 40-character full SHA를 사용한다.

새 commit이 추가된 경우 이전 HEAD의 증거는 새 HEAD의 직접 증거가 아니다.

## 3. Scope evidence

필수 항목:

- Allowed paths
- Forbidden paths
- Changed-file 목록
- File별 변경 목적
- Diff statistics
- 실제 unified diff 또는 GitHub compare/PR patch
- unrelated changes가 없다는 확인

다음은 blocker다.

- 허용 범위 밖 파일 변경
- unrelated dirty file 포함
- 보고서의 changed-file 목록과 실제 diff 불일치
- 대량 생성물·artifact·secret의 비의도적 commit

## 4. Web Developer evidence

Web Developer는 최소한 다음을 제출한다.

### 4.1 Implementation identity

- Starting base SHA
- Final HEAD SHA
- Branch
- Commit 목록
- PR 번호와 상태

### 4.2 Change evidence

- 변경 파일과 목적
- 주요 contract 또는 behavior change
- non-goals가 유지되었는지
- migration 또는 compatibility 영향

### 4.3 Automated validation

각 명령별로 기록한다.

- 실행 명령
- 실행 위치
- 대상 HEAD SHA
- exit code
- passed/failed/skipped 개수
- warning 처리
- 실패 시 핵심 오류 원문

단순히 “pytest passed”라고 쓰지 않고 가능한 경우 다음처럼 기록한다.

```text
Command: python -m pytest -q
Head: <SHA>
Exit: 0
Result: 399 passed, 0 failed, 0 skipped
```

### 4.4 CI evidence

- Workflow 또는 check 이름
- Run URL 또는 status reference
- Trigger event
- Commit SHA
- 각 job 상태
- required check 여부
- rerun 여부

Hosted CI가 없으면 “없음”을 명시하고 대체 검증을 기록한다. 존재하지 않는 CI를 통과했다고 표현해서는 안 된다.

### 4.5 Known limitations

다음 구분을 사용한다.

- 구현하지 않은 non-goal
- 환경 제한으로 검증하지 못한 항목
- 알려진 defect
- production 전 필수 작업
- future roadmap

## 5. Local Validator evidence

Local Validator는 exact PR HEAD에서 다음을 기록한다.

### 5.1 Environment

- OS와 버전
- runtime 버전
- browser와 viewport
- relevant hardware/GPU
- dependency install 방식
- 비밀값을 제외한 필요한 환경 구성

### 5.2 Repository state

- checkout branch
- `git rev-parse HEAD`
- `git status --short` 또는 동등한 상태
- 기존 dirty files 목록
- validation 중 source modification 여부

제품 소스 수정이 발생했다면 `LOCAL_PASSED`를 부여하지 않고 수정 내용을 별도 개발 작업으로 반환한다.

### 5.3 Execution evidence

- 실행 명령
- exit code
- 핵심 stdout/stderr
- 시작 실패 또는 dependency 오류
- 재현 절차

### 5.4 Browser/UI evidence

UI가 관련된 경우 최소한 다음을 확인한다.

- Desktop viewport
- Mobile viewport
- 핵심 user flow
- horizontal overflow
- console errors
- page errors
- failed requests
- loading/empty/error/success state
- 접근성에 영향을 주는 keyboard/focus 동작
- screenshot 또는 video artifact 식별자

스크린샷은 검증한 HEAD와 실행 URL을 연결할 수 있어야 한다.

### 5.5 External integration evidence

외부 API, database, model, deployment가 관련된 경우:

- 사용한 environment 또는 mock/real 구분
- endpoint 또는 provider 식별
- secret 비노출 확인
- 요청 성공·실패 계약
- timeout/retry/fail-closed 동작
- 데이터 생성·삭제·rollback 영향

## 6. CTO final review evidence

Web CTO는 다음을 독립적으로 확인한다.

- reviewed HEAD SHA
- work order의 acceptance criteria별 PASS/FAIL/DEFERRED
- allowed/forbidden path 준수
- 실제 diff와 보고 일치
- CI sufficiency
- Local Validation revision 일치
- 보안·개인정보·권한 경계
- 회귀 위험
- 제한사항의 정확성
- 최종 상태와 근거

`READY` 판정에는 최소한 다음이 필요하다.

1. 필수 acceptance criteria가 모두 PASS이거나, 명시적으로 승인된 non-blocking 조건만 남아 있음
2. required automated checks 통과
3. 필요한 Local Validation 통과
4. reviewed HEAD가 증거의 HEAD와 일치
5. blocker 또는 숨겨진 범위 변경 없음

## 7. Deployment evidence

Production 또는 hosted preview를 완료로 주장하려면 다음을 기록한다.

- stable deployment URL
- deployed commit/release/version ID
- deployment provider와 project/service name
- build/run ID
- 핵심 endpoint HTTP 결과
- browser console/page/network 결과
- 환경변수·binding 구성 상태
- rollback 명령 또는 절차

URL이 열리는 것만으로 배포 revision 일치를 증명하지 못한다.

Branch preview는 production과 구분한다.

## 8. Failure evidence quality

좋은 실패 보고는 다음을 포함한다.

- 예상 결과
- 실제 결과
- 최초 실패 지점
- exact command/action
- minimal reproduction
- 관련 로그 원문
- 환경과 revision
- 소스 수정 없이 재현했는지

원인 추정은 사실과 분리한다.

```text
Observed: HTTP 500 at GET /
Evidence: response status and server traceback
Hypothesis: synchronous handler incompatibility
Unverified: exact runtime limitation until isolated reproduction
```

## 9. Evidence rejection conditions

다음 증거는 단독으로 인정하지 않는다.

- SHA 없는 테스트 결과
- 현재 HEAD와 다른 revision의 결과
- 명령·exit code 없는 “통과” 서술
- 작업자 자신이 만든 화면만 본 주관적 UX 승인
- source를 수정한 뒤 수정 사실을 숨긴 local validation
- URL과 revision 연결이 없는 배포 주장
- 실제 diff 없이 작성한 변경 요약
- 실패·skip·warning 수를 숨긴 집계
- secret 또는 개인정보를 포함한 로그

## 10. 최소 보고 템플릿

- `templates/WEB_DEVELOPER_REPORT.md`
- `templates/LOCAL_VALIDATION_REPORT.md`
- `templates/CTO_FINAL_REVIEW.md`
