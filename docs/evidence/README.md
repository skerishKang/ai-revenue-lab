# 개발·검증·운영 증거 인덱스

~~~text
DOC_STATUS = CANONICAL
SCOPE = NAVIGATION_ONLY
~~~

**증거의 기준은 여기서 새로 정하지 않습니다.** 자료의 증명 범위와 제출 요건은 [Evidence Requirements](../operations/EVIDENCE_REQUIREMENTS.md), 필요한 검증의 범위는 [Test Scope and Delivery Policy](../operations/TEST_SCOPE_AND_DELIVERY_POLICY.md), 최종 판정은 [AI Development Operating Policy](../operations/AI_DEVELOPMENT_OPERATING_POLICY.md)를 따릅니다.

| 증거 유형 | 찾을 곳 | 증명할 수 있는 범위와 한계 |
|---|---|---|
| 기획·설계·시각 자료 | [Evidence Requirements](../operations/EVIDENCE_REQUIREMENTS.md), [UI/UX Backend Phase Gates](../operations/UI_UX_BACKEND_PHASE_GATES.md) | 승인된 디자인·범위에 대한 특정 근거. 백엔드 실행을 자동 입증하지 않음 |
| 소스·변경 범위 | 정확한 Git HEAD, PR diff, [Code Structure Policy](../operations/CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md) | 해당 커밋의 구현물. 운영 배포 여부와 별개 |
| 테스트·CI·재현 | exact-head GitHub Actions 결과, [Test Scope and Delivery Policy](../operations/TEST_SCOPE_AND_DELIVERY_POLICY.md) | 그 리비전에서 실행한 검사의 판정. 실행하지 않은 테스트를 통과했다고 해석하지 않음 |
| 독립 검증 | [Evidence Requirements](../operations/EVIDENCE_REQUIREMENTS.md), [GitHub Report Handoff Policy](../operations/GITHUB_REPORT_HANDOFF_POLICY.md) | 별도 검증자가 실제로 확인한 범위. 개발자 자체 검증과 구분 |
| 모델·제공자 실행 | [모델 권위 인덱스](../models/README.md), [B14 Provider Registration](../../apps/korean-ai-platform/app/pilot/platform.py) | 소스 등록과 실제 자격 증명·라우트·호출 결과를 분리 |
| Production·고객 E2E | [Deployment and Rollback Policy](../operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md), [Workflow Status Model](../operations/WORKFLOW_STATUS_MODEL.md) | 배포된 정확한 revision 및 특정 고객 시나리오의 실행 증거 |
| CTO·소유자 승인 | [AI Development Operating Policy](../operations/AI_DEVELOPMENT_OPERATING_POLICY.md), [GitHub Report Handoff Policy](../operations/GITHUB_REPORT_HANDOFF_POLICY.md) | 해당 PR/범위에 대한 승인 행위. 일반적 권한 확대를 뜻하지 않음 |
| 과거 감사·스냅샷 | [역사 분류 인덱스](../history/README.md), [Documentation Authority Model](../governance/DOCUMENTATION_AUTHORITY_MODEL.md) | 기록된 날짜·리비전에서의 사실. 현재 운영 상태를 자동 선언하지 않음 |

## 증거 등록·조회 규칙

1. **식별:** 해당 사업/이슈/PR, HEAD SHA, 실행 환경, 관찰 시점을 함께 기록합니다.
2. **범위:** PASS/FAIL은 검사한 기능과 리비전에만 적용합니다. 변경된 HEAD에는 종전 결과를 자동 승계하지 않습니다.
3. **보관:** GitHub PR·CI Artifact·검증 보고서 등의 원래 기록을 보존하고, 본 인덱스에 캡처·토큰·비밀값을 중복 저장하지 않습니다.
4. **판정:** 필요한 게이트의 충족 여부는 각 권위 문서와 실제 결과를 대조해 판정합니다.
5. **역사화:** 이전 버전의 근거는 [역사 인덱스](../history/README.md)에서 식별하되, 운영 상태라고 표시하지 않습니다.

[단계별 개발 안내](../lifecycle/README.md) · [공통 정책](../common/README.md) · [사업별 문서](../businesses/README.md)
