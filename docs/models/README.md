# 모델 관련 공식 진입점

~~~text
DOC_STATUS = CANONICAL
SCOPE = NAVIGATION_ONLY
~~~

모델 목록·모델 가격·실행 가능 상태는 수시로 바뀝니다. 이 파일은 모델 정보를 복사하는 또 하나의 원장이 아니라 **각 사실의 소유자를 연결하는 단일 진입점**입니다.

| 확인할 사실 | 공식 근거 |
|---|---|
| 모델 선택·제외·변경에 대한 소유자 승인 | [Model Change Owner Approval Policy](../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md), [Owner Decision Ledger](../operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md) |
| 현재 **main에 병합된** B14 등록 ID, 제공자, 기능 태그 | [B14 단일 JSON 등록 원본](../../apps/korean-ai-platform/app/pilot/b14_models.json), [등록부 파서/검증](../../apps/korean-ai-platform/app/pilot/model_registry_file.py), [B14 Catalog](../../apps/korean-ai-platform/app/pilot/catalog.py), [Provider Registration](../../apps/korean-ai-platform/app/pilot/platform.py). [PR #3819 MERGED](https://github.com/skerishKang/ai-revenue-lab/pull/3819); 병합은 실행 소스의 단일화이지 Production 모델 활성화의 증명이 아닙니다. |
| 소유자 제외 모델의 실행 경계 | [Owner Model Exclusions](../../apps/korean-ai-platform/app/pilot/owner_model_exclusions.py) |
| Plus/Pro/Max 제품 라우트와 HOLD 선언 | [Control Plane Product Tier Routes](../../packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py) |
| B62의 제품 모델 소비 규칙 | [B62 Model Policy](../../apps/padiem-chat/app/model_policy.py) |
| B66 견적 모델 선택 경계 | [정식 Owner 정책 §0A](../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md), [B66 Registered Model Boundary](../../apps/padiem-chat/app/b66_registered_model_boundary.py), [기존 실행 소스](../../apps/padiem-chat/app/b66_b14_free_first_resolver.py). 직접 선택 UI/API 소스는 [PR #3831](https://github.com/skerishKang/ai-revenue-lab/pull/3831)로 main에 병합됐습니다. 이는 사용자 선택 필드의 소스 구현이며, 실제 서비스 배포·고객 E2E 성공은 별도 증거가 필요합니다. |
| Production 실행·키 준비·가용성 | 해당 배포의 **exact SHA, 안전한 진단 결과 및 실제 E2E 증거** |

## 모델 변경 시 원칙

1. **선택과 제외:** 이미 확정된 소유자 결정을 따르며 과거 이슈의 모델명을 새 승인으로 해석하지 않습니다.
2. **등록:** 정확한 모델 ID와 기능은 현재 병합된 B14 소스·테스트에서 확인합니다. 이 인덱스에 모델 목록을 다시 적지 않습니다.
3. **제품:** B62·B66·Claw는 자체적인 모델 승인 원장을 만들지 않고 B14와 Control Plane의 계약을 소비합니다.
4. **출시:** 소유자 승인, 소스 병합, 제품 라우트 연결, Production 실행 검증은 각각 다른 상태입니다.
5. **정합성:** 정책과 실행 소스의 충돌을 표시하고 문서 정정과 실제 라우팅 수정을 분리합니다.

**정리된 정책 / 남은 소스 차이:** 과거 free-first 자동선택 지침은 [#3796 병합](https://github.com/skerishKang/ai-revenue-lab/pull/3796)으로 공식 Owner 정책에서 대체되었습니다. B14 JSON 등록부 [#3819](https://github.com/skerishKang/ai-revenue-lab/pull/3819)와 B66 사용자 직접 선택 UI/API [#3831](https://github.com/skerishKang/ai-revenue-lab/pull/3831)이 모두 main에 병합됐습니다. 그러나 현재 실행 가능한 모델·권한·제공자 사용 가능 상태·고객 E2E는 각 배포 및 실제 증거에서 별도로 확인해야 합니다. [#3836](https://github.com/skerishKang/ai-revenue-lab/pull/3836)은 **과거 통합 CI 증거 전용**으로, #3819 병합 전 합성 HEAD 기준이므로 현재 main을 검증한 것으로 해석하거나 병합해서는 안 됩니다. 이전 Draft/CI는 실제 모델의 Production 가용성 또는 고객 E2E를 증명하지 않습니다. [#3835](https://github.com/skerishKang/ai-revenue-lab/pull/3835) StepFun 추가는 별도 Draft로 유지하며 무료 경로의 지속적인 성공 응답이 확인되지 않았습니다.

[공통 안내](../common/README.md) · [사업별 문서](../businesses/README.md) · [개발 단계](../lifecycle/README.md) · [역사 기록](../history/README.md)
