# LOCAL work order — #5448 온라인 주문·공급사 배송 연계 업무 실증

STATUS=IMPLEMENTED / IMPLEMENTED=YES
BASE_MAIN=0a54f8c54a81eae44092f6a7622a1ed4202655eb
ISSUE=#5448
브랜치: `feat/5448-order-supply-pipeline` (워크트리 `D:\work\ai-revenue-lab-5448`)
lane: LOCAL #5448. LOCAL 1(#5446 상품 등록), LOCAL 2(#5447 ERP)와 파일·모듈 경계가 겹치지 않게 분리했다.

## Reuse / scope

- 기존 `kagent.ops_contracts`는 **구매(采购) 방향** 모델이다
  (`CommercialRequest` → `SupplierQuote` → `QuoteComparison` → `PurchaseOrder` →
  `DeliveryCommitment` → `AccountingHandoff`). 발주서를 공급사에 issued 하면 끝난다.
  #5448이 필요한 것은 그 반대 방향, 즉 **고객 주문 → 공급사 발주 → 고객 배송 →
  종결 → 예외 처리**다. 저장소에 이 방향의 모델이 없어 그 부분만 추가했다.
- 재사용: `ops_contracts`(Money/Item/Supplier/PaymentTerms/PurchaseOrder/
  PurchaseOrderLine/ApprovalProjection/WorkflowEvidenceRecord), `ops_ledger`,
  `ops_workflow.purchase_order_action_fingerprint`, `ops_documents`
  (DocumentNumberAssignment/InMemoryDocumentNumberRegistry/PurchaseOrderDocumentManifest),
  `ops_communications` + `ops_communication_outbox`, `ops_comparison`,
  `ops_supplier_history`, `ops_supplier_context`, `ops_csv_intake`,
  `ops_pilot` + `ops_pilot_telemetry`(실측 KPI), `order_flow`(no-send 가드),
  `document_export`, `browser_open`/`browser_control_actions`/
  `browser_control_observation`(브라우저 관측), `padiem_ai_core.connector_registry`.
- 추가: `ShipTo`(배송지), `StockPosition`(재고·발주처), `SalesOrder` +
  `SalesOrderStatus`(고객 주문 상태 머신), `Shipment` + `ShipmentStatus`(송장번호·
  택배사), `ReturnRequest` + `ReturnReason` + `ReturnStatus`(반품·오배송),
  `SalesChannelOrderPort` + `LocalCsvSalesChannelOrderPort`(판매채널 주문 읽기),
  `OnlineOrderFulfillmentCoordinator`(8단계 조립).
- 공유 파일 변경은 `ops_contracts.py`의 `BusinessObjectKind`에 3개 멤버 추가
  (`SALES_ORDER`, `SHIPMENT`, `RETURN_REQUEST`) 6줄뿐이다.
- 새 엔진·모델 라우터·제공자 호출·새 저장소를 만들지 않았다.

## Exclusions / conflict prevention

- LOCAL 1(#5446)은 `ops_product_listing.py` / `ops_product_listing_channels.py` /
  `ops_product_listing_cli.py` / `pilots/product-listing/`을 만들고 있다. LOCAL 2(#5447)의
  브랜치는 아직 없다. 이번 작업은 `ops_sales_order*.py` / `pilots/order-supply-fulfillment/`
  라는 별도 경로에 두어 파일 충돌을 피했다.
- `kagent/cli.py`는 건드리지 않았다. 파일럿 실행기는 `kagent/ops_sales_order_cli.py`로
  분리했다(LOCAL 1의 `ops_product_listing_cli.py`와 같은 방식).
- 기존 구매 체인과 `ops_delivery_tracking`(입고 추적) 의미는 변경하지 않았다.
- 실제 주문·결제·발주·발송·게시 없음. 실제 고객정보 사용 없음. 공개 GitHub에
  영업·비용·비공개 정책 기재 없음.
- 모델·제공자 선택 변경 없음.

## LOCAL result (2026-10-21) — IMPLEMENTED

### 상태도와 책임 분리

`apps/korean-ai-core`가 아니라 `apps/korean-ai-code-agent`(Claw 업무 런타임)에 넣었다.
이 앱이 이미 보유·운영하는 업무 계약·리드저·승인·아웃박스·텔레메트리 계층이 있기
때문이다.

| # | 단계 | 자동화 수준 | 사람이 반드시 하는 일 |
|---|---|---|---|
| 1 | 온라인 판매채널 주문 접수 | 자동화 가능 | 채널 주문번호 대조 |
| 2 | 주문 상품·수량·배송지 확인 | 사람 확인 필요 | 배송지·수령인 정정 |
| 3 | 공급사·재고·거래조건 확인 | 사람 확인 필요 | 부족 수량 대체 공급사 결정 |
| 4 | 공급사 발주·배송 요청 초안 | 사람 확인 필요 | 금액·납기일 승인 후 발송 |
| 5 | 공급사 처리 결과 확인 | 사람만 수행 | 회신 수신·납기일 확인 |
| 6 | 송장번호·배송 상태 관리 | 사람만 수행 | 송장번호 입력·상태 확인 |
| 7 | 주문 완료 처리 | 자동화 가능 | 없음 |
| 8 | 취소·반품·오배송 대응 | 사람만 수행 | 반품 승인·회수 지시·재배송 판단 |

자동화 가능 2 / 사람 확인 필요 3 / 사람만 수행 3. 상세 분석은
`apps/korean-ai-code-agent/docs/ONLINE_ORDER_SUPPLY_FULFILLMENT_5448.md`에 있다.

### 가상 주문 1건 결과

가상 주문 `order_demo_1`(채널 주문번호 `CH-2026-0011`)을 8단계 전부 통과했다.

- 주문 상태 `completed`
- 공급사 발주 요청 `po-order_demo_1-v2`, 상태 `draft`, outbox `pending`
- 발주서 총액 24,000 KRW(공급가) / 주문 판매액 32,000 KRW(판매가). 판매 단가가
  공급사 문서에 들어가지 않음을 테스트로 고정했다.
- 배송 관측 4건(label_issued → in_transit → out_for_delivery → delivered), 송장
  `TRK-2026-0001`
- 예외 케이스 2건(반품 종결, 오배송 접수)
- 산출물 10개: `apps/korean-ai-code-agent/pilots/order-supply-fulfillment/out/`
  (주문 접수 기록, 발주 요청서 초안 md, 이메일 초안 txt, 송장 입력 구조 csv,
  배송 상태 csv, 주문 라인 csv, 예외 처리 csv, 주문 완료 기록 json, 케이스 json,
  파일럿 리포트 json)

### 안전 경계

- 공급사 발주 요청은 항상 `draft`. outbound 커넥터를 호출하지 않고, 발주를
  `issued`로 바꾸지 않고, 발송하지 않는다. outbox는 `pending`으로 남고 발송에는
  `ISSUE_PURCHASE_ORDER` 승인 projection이 필요하다.
- 상태 그래프 밖 전이, 재고 미확인 주문 확인, 승인 없는 발주, 송장 미기재 배송은
  거부한다.
- `ShipTo.redacted()`가 이름·연락처·주소를 마스킹한다. 수령인·연락처·주소 원본은
  생성 산출물에 없으며, 발송 본문에만 들어가고 outbox 레코드는 본문 대신 지문을
  보관한다.
- 가드 5종을 파이럿이 의도적으로 발동시켜 확인했다(5/5 발동).

### Tests

- 신규: `apps/korean-ai-code-agent/tests/test_ops_sales_order.py` (30 cases),
  `apps/korean-ai-code-agent/tests/test_ops_sales_order_pilot.py` (14 cases).
  합계 44 passed.
- Mutation proof: 결함을 되돌려 테스트가 실제로 실패하는지 확인했다. 5개
  변이(전이 그래프 삭제, 마스킹 해제, 운송장 변경 허용, 판매가를 공급가로 대체,
  승인 요구 제거) 전부 잡혔다.
- 집중 회귀: `ops_`/`order_flow`/`ledger`/`document_number` 선택으로 398 passed,
  1 failed. 실패 건 `test_order_flow.py::
  test_end_to_end_through_real_adapter_and_fake_transport`은 `p01_engine_request_failed`
  로, 이 환경에서 `origin/main` pristine 트리(LOCAL 1 워크트리, 동일 HEAD
  `0a54f8c54`)에서도 동일하게 실패하는 기존 환경 건이다. 이번 변경과 무관하다.
- 환경 제약: 이 PC의 `padiem-control-plane`/`padiem-ai-core` editable 설치가
  사라진 `C:\Temp\wt-arl3413`을 가리켜 `kagent.cli` import가 깨진다. PYTHONPATH를
  현재 워크트리로 맞춰 회귀를 돌렸다.

### 측정 방식

`automation_execution`(실행에서 실제 잰 자동화 소요시간·개입·수동 재입력·재시도·
수정률)과 `business_step_intervals`(샘플 가상 업무 시각, `production_measurement:
false`)을 분리해 기록했다. 기준선 미측정 상태이므로 `baseline_measured: false`,
`measured_comparison_available: false`이며 생산성 변화율을 산출하지 않는다.
운영 붙을 때 단계별 시계 원천과 오류 신호를 `measurement_plan`에 8단계 전부
정의했다.

### Not covered here

- 판매채널·택배사·ERP 실연결, 실제 발주·발송, 실 계정 인증: 없음.
- 브라우저 주문 페이지 조회 어댑터: 도구(`browser_control_observation.py`)는
  확인했고, 채널별 DOM 규칙은 작성하지 않았다.
- 재고 원천 연계: `stock_positions.csv` 입력으로 대체했다.
- 비공개 Governance 문서: **NOT_READ**. 이 PC에 `G:`/`Z:` 매핑이 없고
  `\\192.168.0.2\내pcG\...` SMB 공유 자체가 연결되지 않으며, `D:\` 아래에도
  `ai-revenue-lab-governance` 사본이 없다. 가격·계약·고객 대상 결정은 하지 않았고
  고객정보는 가상 데이터만 사용했다. 실제 단가 적용은 Governance 열람 후 재계산이
  필요하다.
- 운영 배포, 브라우저 실검증: `DEPLOYED=NO`, `LIVE_VERIFIED=NO`.
- 전체 kagent 스위트 무제한 실행: 이 환경에서 900초를 넘겨 중단했다. blast radius
  (`BusinessObjectKind` 소비자 전수) 기준 선택 회귀를 대신 실행했다.
