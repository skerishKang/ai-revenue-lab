## CLAW1 — trust contract #6131989040 1번(첫 턴 지속 예약) 소스 판정: **BLOCKED** (2026-10-13 KST)

계약 1·2·3번(디스패치 전 서버 발급 지속 예약 + typed 비공개 handoff)의 **사전조건이 현행 소스에서 성립하지 않습니다.** 전체 근거·호출 그래프·최소 설계안은 [#3933 보고](https://github.com/skerishKang/ai-revenue-lab/issues/3933#issuecomment-6140845974)에 있습니다.

```text
MAIN_SHA=5179a7c7df4dcfc1e17b2a35e8de547292b6c013
FIRST_TURN_DURABLE_RESERVATION=MISSING
PRIVATE_TYPED_HANDOFF=MISSING_ENGINE_ADMISSION_IS_A_CLOSED_SET
PR_DRAFT=NONE
PROVIDER_POST=0
PRODUCTION_MUTATION=0
NEXT=STOP_SOURCE_BLOCKER
```

핵심: (a) `conversations` 테이블에 tenant/subject 컬럼이 없고 tenant는 `claw_run_history.workspace_id`로 **run에만** 존재 → owner+tenant 결박 대화 참조를 기존 스키마로 표현 불가, (b) 디스패치 전 대화를 만드는 경로는 XLSX 승인 전용 `create_web_xlsx_p01_run`뿐이며 `append_exchange`는 완료 응답과 같은 트랜잭션에서만 발급, (c) 발급/만료/replay 저장소 부재, (d) Engine 입장 집합(`_ORCHESTRATE_ALLOWED_FIELDS`)이 닫혀 있어 typed context 전달은 cross-service 계약 변경 필요.

#3936 LIVE 검증 범위는 변동 없이 **OPEN**입니다. 이 판정은 구현/운영 증거가 아니며, 승인 시 최소 슬라이스 + 회귀 테스트를 Draft PR로 진행합니다.
