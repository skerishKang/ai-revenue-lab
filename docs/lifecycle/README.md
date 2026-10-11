# 개발 단계별 문서 안내

~~~text
DOC_STATUS = CANONICAL
SCOPE = NAVIGATION_ONLY
~~~

이 문서는 개발 업무를 찾기 위한 **단계별 인덱스**입니다. 진행 순서를 강제하는 새 정책이 아닙니다. 실제로 필요한 검증 범위는 [AI Development Operating Policy](../operations/AI_DEVELOPMENT_OPERATING_POLICY.md)와 [Test Scope and Delivery Policy](../operations/TEST_SCOPE_AND_DELIVERY_POLICY.md)가 정합니다. UI→UX→Backend라는 일률적인 순서를 요구하지 않습니다.

| 단계 / 목적 | 해당 단계의 유일한 정책 원천 | 확인할 증거 종류 |
|---|---|---|
| 사업 제안·등록 | [Business Registry](../portfolio/BUSINESS_REGISTRY.md), [Technology Adoption Policy](../operations/TECHNOLOGY_ADOPTION_POLICY.md) | 사업·소유자 결정 및 기술 채택 근거 |
| 요구사항·설계·책임 경계 | [AI Development Operating Policy](../operations/AI_DEVELOPMENT_OPERATING_POLICY.md), [UI/UX Backend Phase Gates](../operations/UI_UX_BACKEND_PHASE_GATES.md) | 수락된 요구사항, 설계 승인 범위, 아키텍처 책임 구분 |
| 구현·로컬 개발 | [Code Structure Policy](../operations/CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md), [Multi-Machine Worktree Policy](../operations/MULTI_MACHINE_LOCAL_WORKTREE_POLICY.md) | 정확한 브랜치·HEAD, 변경 범위, 개발자 자체 테스트 |
| 테스트·독립 검증 | [Test Scope and Delivery Policy](../operations/TEST_SCOPE_AND_DELIVERY_POLICY.md), [Evidence Requirements](../operations/EVIDENCE_REQUIREMENTS.md) | 필요 범위의 CI, 재현 증거, 독립 검증 판정 |
| CTO 검토·소유자 승인 | [AI Development Operating Policy](../operations/AI_DEVELOPMENT_OPERATING_POLICY.md), [GitHub Report Handoff Policy](../operations/GITHUB_REPORT_HANDOFF_POLICY.md) | exact-head 리뷰, 범위·권한 승인, 남은 위험 |
| 병합·Production·고객 인계 | [Production Deployment and Rollback Policy](../operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md), [Workflow Status Model](../operations/WORKFLOW_STATUS_MODEL.md) | 실제 병합 SHA, 배포 대상 버전, 필요한 Smoke/E2E 판정 |
| 운영·문제 진단·역사 보존 | [Workflow Status Model](../operations/WORKFLOW_STATUS_MODEL.md), [역사 인덱스](../history/README.md) | 해당 리비전의 운영 관찰, 사고 원인, 당시 기록 |

## 단계별 증거의 해석

- **소스 존재**는 기능 연결·인증·고객 실행·Production 활성화를 증명하지 않습니다.
- **개발자 자체 테스트와 독립 검증**은 다른 판정입니다. 독립 검증이 항상 필수라는 뜻은 아니며 해당 작업의 게이트가 결정합니다.
- **Draft PR, CI 성공, merge, 배포, 고객 E2E**는 서로 다른 상태입니다. 한 단계의 성공이 다음 단계의 승인이 되지는 않습니다.
- 정확한 증거 유형과 불충분한 증거의 조건은 [증거 공식 진입점](../evidence/README.md)에서 찾습니다.
- 모델 선정 및 등록은 [모델 진입점](../models/README.md)을 따릅니다. 사업별 요구사항은 [사업별 인덱스](../businesses/README.md)를 참조합니다.

이 문서에는 모델 목록·배포 SHA·개별 사업의 현재 합격 상태를 복사하지 않습니다.
