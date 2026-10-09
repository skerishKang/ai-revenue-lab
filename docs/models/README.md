# 모델 관련 공식 진입점

~~~text
DOC_STATUS = CANONICAL
SCOPE = NAVIGATION_ONLY
~~~

모델 목록·모델 가격·실행 가능 상태는 수시로 바뀝니다. 이 파일은 모델 정보를 복사하는 또 하나의 원장이 아니라 **각 사실의 소유자를 연결하는 단일 진입점**입니다.

| 확인할 사실 | 공식 근거 |
|---|---|
| 모델 선택·제외·변경에 대한 소유자 승인 | [Model Change Owner Approval Policy](../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md), [Owner Decision Ledger](../operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md) |
| 현재 **main에 병합된** B14 등록 ID, 제공자, 기능 태그 | [B14 Catalog](../../apps/korean-ai-platform/app/pilot/catalog.py), [B14 Provider Registration](../../apps/korean-ai-platform/app/pilot/platform.py) 및 제공자별 모듈. JSON 단일 등록부 전환은 [Draft #3819](https://github.com/skerishKang/ai-revenue-lab/pull/3819)로 별도 검증 중이며 아직 main 권위가 아닙니다. |
| 소유자 제외 모델의 실행 경계 | [Owner Model Exclusions](../../apps/korean-ai-platform/app/pilot/owner_model_exclusions.py) |
| Plus/Pro/Max 제품 라우트와 HOLD 선언 | [Control Plane Product Tier Routes](../../packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py) |
| B62의 제품 모델 소비 규칙 | [B62 Model Policy](../../apps/padiem-chat/app/model_policy.py) |
| B66 견적 모델 선택 경계 | [정식 Owner 정책 §0A](../operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md), [B66 Registered Model Boundary](../../apps/padiem-chat/app/b66_registered_model_boundary.py), [기존 실행 소스](../../apps/padiem-chat/app/b66_b14_free_first_resolver.py). 직접 선택 UI/API 소스는 [Draft #3831](https://github.com/skerishKang/ai-revenue-lab/pull/3831)이며 main에 아직 병합되지 않았습니다. |
| Production 실행·키 준비·가용성 | 해당 배포의 **exact SHA, 안전한 진단 결과 및 실제 E2E 증거** |

## 모델 변경 시 원칙

1. **선택과 제외:** 이미 확정된 소유자 결정을 따르며 과거 이슈의 모델명을 새 승인으로 해석하지 않습니다.
2. **등록:** 정확한 모델 ID와 기능은 현재 병합된 B14 소스·테스트에서 확인합니다. 이 인덱스에 모델 목록을 다시 적지 않습니다.
3. **제품:** B62·B66·Claw는 자체적인 모델 승인 원장을 만들지 않고 B14와 Control Plane의 계약을 소비합니다.
4. **출시:** 소유자 승인, 소스 병합, 제품 라우트 연결, Production 실행 검증은 각각 다른 상태입니다.
5. **정합성:** 정책과 실행 소스의 충돌을 표시하고 문서 정정과 실제 라우팅 수정을 분리합니다.

**정리된 정책 / 남은 소스 차이:** 과거 free-first 자동선택 지침은 [#3796 병합](https://github.com/skerishKang/ai-revenue-lab/pull/3796)으로 공식 Owner 정책에서 대체되었습니다. 현재 B66 소스와 UI는 아직 별도의 [#3831 Draft](https://github.com/skerishKang/ai-revenue-lab/pull/3831) 병합·독립 검증을 기다립니다. [#3836](https://github.com/skerishKang/ai-revenue-lab/pull/3836)은 #3819 + #3831 + 정책의 **CI 증거 전용** Draft이며 자체 병합 대상이 아닙니다. 이들 Draft의 green CI는 병합, 정확한 모델의 Production 가용성 또는 고객 E2E를 증명하지 않습니다. [#3835](https://github.com/skerishKang/ai-revenue-lab/pull/3835) StepFun 후보 역시 #3819에 종속된 별도 Draft이며 고객용 무료 모델의 안정적 응답이 입증되지 않았습니다.

[공통 안내](../common/README.md) · [사업별 문서](../businesses/README.md) · [개발 단계](../lifecycle/README.md) · [역사 기록](../history/README.md)
