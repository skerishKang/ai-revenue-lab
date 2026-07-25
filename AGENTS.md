# AI Revenue Lab Agent Rules

이 파일은 저장소 전체에 적용되는 AI 작업자 진입 규칙이다. 더 하위 경로에 별도 `AGENTS.md`가 있으면 그 파일은 해당 하위 범위에서 추가 제약을 부과할 수 있지만, 이 파일의 저장소 공통 안전 규칙을 완화할 수 없다.

Canonical policy:

- `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md`
- `docs/operations/WORKFLOW_STATUS_MODEL.md`
- `docs/operations/EVIDENCE_REQUIREMENTS.md`

## Mandatory role separation

다음 역할을 구분한다.

1. **User / Product Owner** — 제품 목표, 우선순위, 주요 UX·비즈니스 결정, 병합·배포 승인
2. **Web CTO** — 작업계약, 아키텍처, acceptance criteria, 독립 최종 리뷰
3. **Web Developer** — 승인된 branch와 범위에서 구현·테스트·Draft PR·CI 대응
4. **Local Validator** — exact PR HEAD를 실제 환경에서 실행·검증하고 원문 증거 제출

한 작업자가 여러 역할을 수행하게 되더라도 각 단계의 책임과 증거를 명시적으로 분리해야 한다.

## Required workflow

```text
User request
→ Web CTO work contract
→ Web Developer implementation
→ GitHub CI
→ Local validation
→ Web CTO final review
→ User approval
→ Merge
→ Production verification
```

## Non-negotiable rules

- 작업 시작 전에 repository, exact base SHA, target branch, allowed paths, forbidden paths를 고정한다.
- 일반 작업에서 `main`을 직접 수정하지 않는다.
- 허용 범위 밖 파일과 unrelated dirty files를 commit하지 않는다.
- 완료 보고보다 Git SHA, 실제 diff, CI 로그, 실행 명령, 브라우저·배포 증거를 우선한다.
- CI 통과는 필요조건일 수 있지만 완료의 충분조건은 아니다.
- Local Validator는 별도 승인 없이 제품 소스코드를 수정하지 않는다.
- 테스트 실패를 숨기거나 테스트를 삭제하거나 acceptance criteria를 사후 완화하여 통과 처리하지 않는다.
- secret, API key, credential, personal data를 commit·로그·PR·대화에 노출하지 않는다.
- 배포 URL이 실제 검토 HEAD 또는 merge SHA와 연결되는지 확인하지 않고 production 완료를 선언하지 않는다.
- `READY`, `CONDITIONALLY_READY`, `NOT_READY` 최종 판정은 Web CTO만 부여한다.
- `READY`는 자동 병합 명령이 아니다. 병합과 배포에는 사용자 승인이 필요하다.

## Required deliverables

### Web CTO

`docs/operations/templates/CTO_WORK_ORDER.md`를 기준으로 작업계약을 작성한다.

### Web Developer

`docs/operations/templates/WEB_DEVELOPER_REPORT.md` 형식으로 구현 증거를 제출한다.

### Local Validator

`docs/operations/templates/LOCAL_VALIDATION_REPORT.md` 형식으로 exact tested SHA와 실행 증거를 제출한다.

### Final review

`docs/operations/templates/CTO_FINAL_REVIEW.md` 형식으로 acceptance criteria별 판정과 최종 상태를 기록한다.
