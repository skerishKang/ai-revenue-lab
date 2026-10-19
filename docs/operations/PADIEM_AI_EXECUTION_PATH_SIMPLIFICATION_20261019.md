# PADIEM AI 실행 경로 단순화 — 운영 전환 기준 (2026-10-19)

```text
DOC_ROLE=ENGINE_EXECUTION_PLACEMENT_TRANSITION
STATUS=OWNER_DIRECTION_RECORDED / IMPLEMENTATION_NOT_COMPLETE
ARCH_CHOICE=C_CORE_FAST_PATH_PLUS_OPTIONAL_DURABLE_ENGINE
SERVER_SPLIT=NOT_REQUESTED
DEPLOYMENT_MUTATION=NONE_FROM_THIS_DOCUMENT
OWNERSHIP_AUTHORITY=docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md
ARCH_UMBRELLA=#2409
```

## 1. 확정한 기술 방향

- **공통 AI Core(`packages/padiem-ai-core`)는 재사용한다.** 실행 의미론, 모델·도구·에이전트 루프와 검증된 계약의 단일 원본이다.
- **짧은 대화/연속 도구 작업은 제품 서버가 Core 라이브러리를 직접 합성**하는 경로를 우선 검토한다. Chat·Claw·B66에 별도 도구 엔진, 범용 Provider Router, 인증 정본을 중복 구축하지 않는다.
- **독립 AI Engine은 지속 실행과 교차 런타임 서비스를 중심으로 축소**한다. 현재 입구 승인·사용량/환불·멱등성·중단/재개·lease의 운영 계약은 해당 책임의 정본 이전이 실증될 때까지 유지한다.
- **B14는 PADIEM 제공 모델 실행 경로**다. PADIEM Custom(BYOK)은 이미 도입된 별도 서버 측 공급사 직접 호출 경로를 재사용한다. 새 BYOK Router를 만들지 않는다.
- **Broker/Windows Connector/Mesh 실행 경로를 교체하거나 중복 구축하지 않는다.** 단일 기기·owner/workspace·사용 가능 capability 검증, 승인된 경로, 단일 실행/결과 저장의 기존 계약을 유지한다.
- **논리적 책임 분리 ≠ 물리적 Worker 신설.** 새로운 DO, Queue, Workflow, Broker를 우선 구축하거나 기존 운영 Mesh를 중지하지 않는다.

## 2. 실행 경로

```text
PADIEM Chat / Claw / B66
  └─ product adapter + common Core AgentRuntime / ToolRuntime
       ├─ Managed model -> B14 -> selected provider
       ├─ BYOK_DIRECT -> server-owned authenticated credential -> selected provider
       ├─ Short PC/file operation -> existing product PC authority -> existing Mesh/Broker -> connector
       └─ Long-running, pause/resume, external runtime -> existing Engine/Durable authority

Control Plane = canonical identity / tenant / entitlement / usage / audit truth;
Broker/device boundary = exact target, revocation, execution admission and result receipt.
```

위 그림은 **목표 배치**다. 현재 Claw PC 단계는 Engine StepDriver에서 서명된 Chat Worker 콜백을 사용하는 운영 경로이며 전환 전까지 유지한다. 일반 Chat과 기존 B66 견적 모델 호출은 해당 제품의 현재 직결 경로가 우선한다.

## 3. 현재 유지할 연결 자산 및 미완료 기능

| 경로 | 2026-10-19 확인 증거 | 전환 시 처리 |
| --- | --- | --- |
| Claw 자연어 PC 드라이브 조회 | #5015 Pro 실사용 PASS | 운영 경로 유지 |
| Claw 승인 폴더 목록 | #5015 / #4976 실제 1,515B 목록 반환 | 코드·결과 증거 보존 |
| Claw 파일 내용 읽기 | list 다음 `tool_failed`, read dispatch 미생성 | 실패 원인 별도 국소 수리, 실사용 read E2E 필요 |
| Chat PC File Lane | 기존 Engine orchestration bridge 미준비 | 구성 단순 복구 vs Core 직접 실행 중 최소 경로 선택 |
| PC 대상 저장/선택 | PR #5136 병합, 054 schema gate 적용 증거 | Worker 배포 및 로그인 세션 실행 수용을 별도 확인 |
| BYOK_DIRECT | PR #5131/#5137/#5143 병합 | 운영 D1 053, dedicated Secret, UI, 실제 공급사/제품 E2E는 따로 수용 |

진행 상태는 항상 `SOURCE_MERGED / D1_MIGRATED / WORKER_DEPLOYED / LIVE_VERIFIED`로 나누고 구형 증거로 이후 상태를 대체하지 않는다.

## 4. 권한 및 실행 일관성 — 전환 중 필수 보존 계약

1. **Identity**: 제품 ingress가 canonical subject/tenant/workspace를 검증한다. 다른 신뢰 경계로 전달할 때는 기존 서명된 실행 문맥과 caller authority를 유지한다. 서비스 내부 중복 조회는 줄일 수 있지만 실행 권한 확인을 삭제하지 않는다.
2. **Device**: 저장된 PC 선택은 preference이지 실행 grant가 아니다. run은 한 effective device에 고정된다. offline/revoked/unavailable이면 다른 PC로 자동 전환하지 않는다.
3. **Idempotency**: `tool_call_ref`, owner/run/device의 상관관계, 단일 dispatch/receipt, 외부 작업 exactly-once 경계를 유지한다. 실패 조회 때문에 POST를 재전송하지 않는다.
4. **Error**: 하위 서비스의 상태·닫힌 error code를 보존한다. `pc_files_denied` 같은 평탄화로 진단 코드를 잃는 지점을 국소적으로 보정한다. 원시 credential/고객 PC 내용은 운영 로그에 노출하지 않는다.
5. **State owner**: 제품 히스토리/D1이 원대화 결과 표시의 정본이다. 장시간 실행 진행·lease/continuation 정본은 현재 Engine에 유지한다. 최종 결과는 기존 owner/run/conversation으로 한 번만 귀속시킨다.
6. **Core versioning**: 공통 의미론을 제품별 복사/수정하지 않는다. 동일 Core 계약 스키마 및 프로듀서-컨슈머 회귀를 재사용하고, 배포 버전 차이를 확인한다.
7. **BYOK**: 고객 키 원문을 프론트엔드·모델 프롬프트·로그·이슈에 노출하지 않는다. 전용 암호 키를 사용하고 Model B14/BYOK 경로의 권한·usage/audit 결과를 동일 정본에 기록한다.

## 5. 최소 전환 순서와 수용 조건

### Track A — 기존 연결 완성

A1. #5015/#4976의 보존된 실행 기록에서 read 단계 최초 실패 코드/호출 경계를 확보한다. 이전 400/status-keyset 수정과 목록 타임아웃 수정을 동일 장애로 재진단하지 않는다.

A2. 기존 ToolRuntime/서명 콜백/상대 경로 계약에서 원인에 해당하는 부분만 수정한다. 기존 성공한 폴더 조회를 반복하지 않고, 집중 테스트와 적용 후 1회 실제 TXT 읽기→원대화 결과로 수용한다.

A3. #5136 선택 저장 및 054 스키마의 배포/실사용 결과를 검증한다. 대표 기존 인증 Tabbit에서 새 대화 선택 PC→동일 대상 실행을 한 번 확인한다. COM2 실행자·Mesh ON과 기존 장치 등록을 유지한다.

### Track B — Engine 책임 축소 (Track A와 파일 소유 범위 분리)

B0. #2409 기존 경계 매트릭스와 #1743 Engine 프로그램의 현재 구현/운영 사용 여부를 재사용한다. 코드 이동보다 호출·정본·실배포 경계를 우선 확정한다.

B1. 제품 전용 PC StepDriver와 공통 Core 도구 루프의 **단일 동기 수직 경로**만 선택해 직접 실행할 수 있는 얇은 제품 어댑터를 마련한다. 기존 Engine 경로는 즉시 삭제하지 않는다.

B2. 같은 승인 범위·동일 원대화 출력·도구 2회(list→read)·선택 기기 고정·거부 시나리오에서 Core 직접 경로와 기존 Engine 경로의 동등성을 확인한다. 기존 Tabbit 세션/집중 계약/필수 CI만 재사용한다.

B3. 배포 전후의 p95 응답 지연, 도구 dispatch 실패율, Worker CPU·번들/cold start, 호출당 비용을 실측 비교한다. 기준치가 없는 경우 임의 퍼센트나 고정 CPU/벽시계 제한을 만들지 않는다.

B4. 작업/세션별 **sticky execution route**를 적용한다. 두 경로가 같은 run에 중복 실행·중복 쓰기를 하지 않는다. 기동 단계에서는 Engine 원래 경로로 되돌릴 수 있어야 한다.

B5. 수용된 짧은 실행만 제품 Core로 이동하고, durable/continuation/교차 런타임 소비를 Engine에 남긴다. Worker를 새로 분할하는 결정은 관측된 필요가 있을 때 별도로 한다.

## 6. 병렬 담당 경계

- **PC Track**: #5015/#4976 및 PR #5136 후속. 기존 Device/Chat/Engine 계약에서 연결 오류·배포·실사용 수용만 담당.
- **Architecture Track**: #2409 기반 운영 문서·새 좁은 전환 이슈 및 Core 직접 실행 대상 선정. PC Track이 수정 중인 파일을 동시에 대량 개편하지 않는다.
- **독립 검증**: 기존 CI·테스트·Tabbit 증거를 재사용하고, 과도한 풀리그레션 또는 불필요한 Playground/새 Playwright 설치는 만들지 않는다.

## 7. 관련 정본

- [#5015 PC/Drive 공통 도구](https://github.com/skerishKang/ai-revenue-lab/issues/5015)
- [#4976 PC 파일 조회](https://github.com/skerishKang/ai-revenue-lab/issues/4976)
- [PR #5136 — PC 선택/복원](https://github.com/skerishKang/ai-revenue-lab/pull/5136)
- [#5121 BYOK_DIRECT](https://github.com/skerishKang/ai-revenue-lab/issues/5121)
- [#2409 경계/마이그레이션](https://github.com/skerishKang/ai-revenue-lab/issues/2409)
- [#1743 Engine capability](https://github.com/skerishKang/ai-revenue-lab/issues/1743)
- [Capability ownership](../architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md)
- [Vertical stack](../architecture/PADIEM_AI_VERTICAL_STACK.md)

이 문서는 기술 실행 기준이며 영업/고객 위임 정책의 신규 결정이 아니다. COM1 비공개 Governance 문서의 원문·요약 및 Credential 식별자는 공개 저장소에 복사하지 않는다.
