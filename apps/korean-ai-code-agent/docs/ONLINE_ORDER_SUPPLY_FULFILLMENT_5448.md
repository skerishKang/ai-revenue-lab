# #5448 온라인 주문·공급사 배송 연계 업무 실증

상태: 기술 검증 완료(가상 케이스 1건)
기준 main: `0a54f8c54a81eae44092f6a7622a1ed4202655eb`
대상 장비: COM2 (K_lipvoice)
저장소: `skerishKang/ai-revenue-lab`

이 문서는 외부에 공유 가능한 **기술 검증 결과**만 담는다. 실제 고객정보, 영업·비용정보,
비공개 사업문서는 이 문서와 저장소에 기록하지 않았다.

---

## 1. 검증한 업무 흐름

온라인 판매채널에서 들어온 **고객 주문**을 받아 공급사 발주 요청을 만들고, 고객에게
배송하고, 배송 상태를 관리하고, 주문�� 닫고, 문제가 생기면 취소·반품·오배송으로
처리하는 8단계 흐름이다.

기존 `kagent.ops_contracts`가 모델링하는 것은 **구매(采购) 방향**이다.
`CommercialRequest` → `SupplierQuoteRequest` → `SupplierQuote` → `QuoteComparison` →
`PurchaseOrder` → `DeliveryCommitment` → `AccountingHandoff` 구조로, 발주서를 공급사에
issued 하면 끝난다.

이번에 필요한 것은 그 반대 방향이다. **고객 주문이 들어와서** 공급사 발주를 만들고,
고객에게 배송해 송장으로 추적하고, 종결하며, 예외를 처리한다. 저장소 어디에도 이
방향의 모델이 없었고, 이 PR이 그 부분을 채운다.

### 1.1 8단계와 책임 분리

| # | 단계 | 자동화 수준 | 사람이 반드시 하는 일 | 필요한 시스템 |
|---|---|---|---|---|
| 1 | 온라인 판매채널 주문 접수 | 자동화 가능 | 채널 주문번호 대조 | 판매채널 주문 목록(CSV 내보내기 또는 브라우저 주문 페이지) |
| 2 | 주문 상품·수량·배송지 확인 | 사람 확인 필요 | 배송지·수령인 표기 오류 정정 | 채널 주문 원문 |
| 3 | 공급사·재고·거래조건 확인 | 사람 확인 필요 | 부족 수량의 대체 공급사·분할 발주 결정 | 재고 시스템(현재 ERP 재고 연계 미확정) |
| 4 | 공급사 발주·배송 요청 초안 | 사람 확인 필요 | 발주 금액·납기일 승인 후 발송 | 공급사 거래 조건과 발주 채널(이메일/메신저/ERP) |
| 5 | 공급사 처리 결과 확인 | 사람만 수행 | 회신 수신과 납기일 확인 | 공급사 회신 수신함 |
| 6 | 송장번호·배송 상태 관리 | 사람만 수행 | 송장번호 입력과 상태 확인 | 택배사 송장 조회(택배사별 API 계약 미확정) |
| 7 | 주문 완료 처리 | 자동화 가능 | 없음 | 없음(내부 기록) |
| 8 | 취소·반품·오배송 대응 | 사람만 수행 | 반품 승인·회수 지시·재배송 판단 | 반품 접수 채널과 회수 택배 정보 |

자동화 수준 개수: 자동화 가능 2, 사람 확인 필요 3, 사람만 수행 3.

**사람 확인 없이 끝까지 도는 단계는 1번과 7번뿐이다.** 3번은 재고 시스템이 붙기
전까지 사람이 판단하고, 4번은 금액·납기일 승인이 선행되며, 5·6·8번은 외부 시스템
계약이 없으면 자동화 대상이 아니다.

### 1.2 상태 그래프

`ops_sales_order.py`가 두 개의 명시적 전이 그래프를 가진다. 종결 상태는 이후 전이를
전부 거부한다.

```
주문: received → confirmed → supplier_ordered → ready_to_ship → shipped
          → delivered → completed
      received/confirmed/supplier_ordered/ready_to_ship → cancelled
      shipped/delivered → return_requested → returned
      shipped/delivered/return_requested → misdelivery → delivered

배송: label_issued → in_transit → out_for_delivery → delivered
      in_transit/out_for_delivery → return_in_transit → returned
      in_transit/out_for_delivery → misdelivery → in_transit
      delivered → return_in_transit
```

송장번호는 첫 관측 이후 변경할 수 없다. 발주는 승인 없이는 `issued`가 될 수 없다.

---

## 2. 기존 기능 재사용 조사 (요구사항 D)

### 2.1 재사용한 기능

| 필요한 기능 | 재사용한 위치 | 판정 |
|---|---|---|
| 주문·상품·재고 도메인 계약 | `kagent/ops_contracts.py` `Money` `Item` `Supplier` `PaymentTerms` `LineItem` `PurchaseOrder` `PurchaseOrderLine` `ApprovalProjection` `WorkflowEvidenceRecord` | PRESENT |
| 단일 버전 제품 기록 저장소 | `kagent/ops_ledger.py` `InMemoryOpsLedger` `BusinessObjectEnvelope` | PRESENT |
| 발주 승인 지문 | `kagent/ops_workflow.py` `purchase_order_action_fingerprint` | PRESENT |
| 발주서 문서번호·문서 매니페스트 | `kagent/ops_documents.py` `InMemoryDocumentNumberRegistry` `DocumentNumberAssignment` `PurchaseOrderDocumentManifest` | PRESENT |
| 이메일·업무 메시지 초안과 발송 대기열 | `kagent/ops_communications.py` `CommunicationSendRequest`, `kagent/ops_communication_outbox.py` `InMemoryCommunicationOutbox` | PRESENT |
| 공급사 비교·공급사 이력 | `kagent/ops_comparison.py`, `ops_supplier_history.py`, `ops_supplier_context.py` | PRESENT |
| CSV 읽기(strict 헤더·수식 가드) | `kagent/ops_csv_intake.py` `StrictCsvCommercialRequestAdapter` | PRESENT |
| 문서 파싱·XLSX | `padiem_ai_core/document_normalization.py`, `kagent/document_export.py` | PRESENT |
| 파일 산출물(문서) 생성 | `kagent/document_export.py` `export_outcome_to_file` | PRESENT |
| 브라우저 관측·행동 | `kagent/browser_open.py`, `browser_control_actions.py`, `browser_control_observation.py` (`validate_trusted_page_observation`), `scripts/ops/tabbit_quickcheck.py` | PRESENT (도구) |
| 외부 연결 프레임워크 | `padiem_ai_core/connector_registry.py`, `kagent/connector_platform.py` | PRESENT (프레임워크) |
| 실측 KPI·텔레메트리 | `kagent/ops_pilot.py` `default_pilot_metric_definitions` `PilotKpiEngine`, `kagent/ops_pilot_telemetry.py` `WorkflowTelemetryEvent` `PilotMeasurementBridge` | PRESENT |
| 견적→발주 초안(no-send 가드) | `kagent/order_flow.py` | PRESENT |

### 2.2 기존 구현이 없었고 이번에 추가한 것

| 필요한 것 | 기존 대응 | 판정 | 추가 위치 |
|---|---|---|---|
| 배송지(주소·수령인·연락처) | 없음. `Customer`는 id·workspace·이름만 가진다 | GAP | `ShipTo` |
| 재고·발주처 위치 | 없음. `Item`에 수량이 없다 | GAP | `StockPosition` |
| 송장번호·택배사·배송 추적 | `DeliveryTrackingSnapshot`는 **입고**(공급사→자사) 추적이며 운송장·택배사·고객 개념이 없다 | GAP | `Shipment` `ShipmentStatus` |
| 반품·오배송 | 취소만 존재 | GAP | `ReturnRequest` `ReturnReason` `ReturnStatus` |
| 판매채널 주문 읽기 | `ops_intake`·`ops_csv_intake`는 `CommercialRequest`(구매요청) 전용 스키마 | GAP | `SalesChannelOrderPort` `LocalCsvSalesChannelOrderPort` |
| 고객 주문 상태 머신 | 없음 | GAP | `SalesOrder` `SalesOrderStatus` `ORDER_TRANSITIONS` |

추가는 `kagent/ops_contracts.py`의 `BusinessObjectKind`에 3개 멤버
(`SALES_ORDER`, `SHIPMENT`, `RETURN_REQUEST`)를 넣는 6줄뿐이다. 기존 구매 체인은
그대로다.

### 2.3 PR 밖의 기존 기능과 연결 지점

| 기능 | 연결 방식 | 남은 작업 |
|---|---|---|
| 브라우저 주문정보 조회 | `browser_control_observation.py`의 신뢰 관측 검증 + `SalesChannelOrderPort` 구현체 | 채널 주문 페이지별 DOM 규칙 작성, 인증 세션 연결 |
| 공급사 발주 발송 | `ops_communication_outbox.py` + `gmail_connector.py` / `kakao_business_contracts.py` / `sms_contracts.py` | 채널별 발송 어댑터, 승인 후 발송 경로 |
| 택배사 송장 조회 | 신규 어댑터 필요 | 택배사별 API 계약 미확정. 사람이 조회 결과를 `Shipment`로 입력 |
| 재고 조회 | `ops_delivery.py` `ConnectorBinding` `OpsExecutionProfile` | ERP 재고 원천과 스키마 미확정 |

---

## 3. AI 자동화 가능 영역 (요구사항 C)

### 3.1 지금 가능한 단계

- **1단계 접수**: 정해진 CSV 스키마의 채널 주문 내보내기 파일을 읽어 주문 기록으로
  남기는 것. 헤더 불일치, 주문 수준 필드 불일치, 수량·금액 파싱 실패를 전부 거부한다.
- **4단계 초안 생성**: 확인된 주문과 공급사 원가로 공급사 발주 요청서 초안(문서
  markdown, 이메일 본문)을 만드는 것. 초안은 항상 `draft`이고 승인 projection이
  `PENDING`인 상태로 남는다.
- **6단계·7단계 기록**: 사람이 입력한 송장번호와 배송 상태를 기록하고, 배송 완료 후
  주문 완료 처리. 상태 그래프가 전이를 검증한다.
- **8단계 기록**: 취소·반품·오배송 접수와 종결 기록.

### 3.2 사람 확인이 필요한 단계

- **2단계**: 배송지와 수령인 표기. 사람이 원문 주문과 대조한다. 이 PR은 수정률을
  지표로 측정할 수 있게 했고, 가상 케이스에서는 6개 필드 중 1개를 정정했다(20%).
- **3단계**: 재고 부족 시 대체 공급사, 분할 발주, 발주 시점 결정. 자동 계산은
  "어느 라인이 부족한가"까지이고, 결정은 사람의 몫이다.
- **4단계**: 금액·납기일·수량 최종 확인. 자동화는 초안까지만 한다.

### 3.3 자동화 대상이 아닌 단계

- **5단계 공급사 회신 수신**: 사람이 받은 회신을 읽고 납기일을 확정하는 단계다.
  수신함 연동이 없으므로 자동 처리 대상이 아니다.
- **6단계 택배 조회**: 택배사별 API 계약이 확정되지 않았다. 송장번호를 사람이
  입력하면 시스템이 상태 전이를 검증하고 기록한다.
- **8단계 반품 승인·회수 지시·재배송 판단**: 금액 이동과 재배송이 얽여 사람의 결정이다.

### 3.4 이 PR이 지킨 안전 경계

- 공급사 발주 요청은 **항상 초안**이다. 발주 outbound 커넥터를 호출하지 않고,
  발주를 `issued`로 바꾸지 않으며, 발송하지 않는다. outbox 레코드는 `pending`으로
  남고, 발송에는 `ISSUE_PURCHASE_ORDER` 승인 projection이 필요하다.
- **고객 판매 단가는 공급사 문서에 들어가지 않는다.** 발주서 라인은 공급사 원가로
  만든다. 기존 `PurchaseOrderDocumentManifest`의
  `customer_sale_price_exposed=False` 성질이 그대로 유지된다.
- **개인정보는 공유 산출물에서 가린다.** `ShipTo.redacted()`가 이름·연락처·주소를
  마스킹하고, 수령인·연락처·주소 원본은 생성 산출물에 들어가지 않는다. 실제 발송
  본문에만 원본이 들어가고, outbox 레코드는 본문 대신 지문만 보관한다.
- 상태 그래프 밖 전이, 재고 미확인 주문 확인, 승인 없는 발주, 송장 미기재 배송은
  모두 거부한다. 파이럿은 이 5개 가드를 실제로 발동시켜 확인했다.

---

## 4. 가상 주문 1건 실증 결과 (요구사항 B)

가상 주문 1건으로 8단계를 끝까지 돌렸다. 실제 고객정보, 실제 주문, 실제 발주,
실제 발송은 쓰지 않았다.

- 주문: `order_demo_1` / 채널 주문번호 `CH-2026-0011` / 상태 `completed`
- 공급사 발주 요청: `po-order_demo_1-v2` / 상태 `draft` / outbox `pending`
- 라벨 4개, 수량 2행, 총액 32,000 KRW(판매가) — 발주서 총액은 24,000 KRW(공급가)

생성된 산출물은 `apps/korean-ai-code-agent/pilots/order-supply-fulfillment/out/`에 있다.

| 산출물 | 내용 |
|---|---|
| `order_intake_record.json` | 주문 접수 기록 + 재고 확인 결과 |
| `supplier_order_request_draft.md` | 공급사 발주·배송 요청서 초안 |
| `supplier_order_request_email_draft.txt` | 공급사 메시지 초안(이메일 본문) |
| `tracking_input_template.csv` | 송장번호 입력 구조(양식 + 실제 입력 예시) |
| `shipment_tracking.csv` | 배송 상태 관리 기록(4개 관측) |
| `order_lines.csv` | 주문 라인 CSV(개인정보 마스킹) |
| `exception_cases.csv` | 취소·반품·오배송 예외 처리 기록 |
| `order_completion_record.json` | 주문 완료 기록 |
| `fulfillment_case.json` | 케이스 전체 JSON |
| `pilot_report.json` | 실측 시간·오류, 측정 계획, 8단계 자동화 경계 |

실행 방법:

```powershell
$env:PYTHONPATH='apps/korean-ai-code-agent/src'
python -m kagent.ops_sales_order_cli
```

---

## 5. 시간·오류 측정 기준 (수락 기준)

측정값을 두 종류로 나누고 섞지 않는다.

| 구분 | 무엇을 재는가 | 측정 방식 | 이번 결과 |
|---|---|---|---|
| `automation_execution` | 자동화 자체가 걸린 시간, 사람 개입 횟수, 수동 재입력 횟수, 자동화 재시도 횟수, 추출 수정률 | 이 실행의 실제 벽시계와 실제 발생 건수 | 소요 0.00006분, 개입 1건, 수동 재입력 2건, 재시도 0건, 수정률 20% |
| `business_step_intervals` | 접수→초안→회신→발송→배송 사이의 업무 리드타임 | 샘플 입력의 가상 업무 시각 | `production_measurement: false` |
| `kpi_observations` | `request_to_rfq_minutes`, `request_to_po_minutes`, `supplier_response_minutes`, `manual_reentry_count`, `owner_intervention_count`, `automation_retry_count`, `extraction_correction_rate` | 기존 `PilotMeasurementBridge` 파생 | phase `shadow` |

`pilot_report.json`에 `baseline_measured: false`, `measured_comparison_available: false`를
명시했다. 수동 처리 기준선을 아직 측정하지 않았으므로 생산성 변화율을 산출하지
않는다. 기준선이 생기면 같은 지표 키로 비교한다.

운영 붙을 때 각 단계를 어떤 시계로 잴지는 `measurement_plan`에 단계별로 적어
두었다(8단계 전부).

오류 신호도 단계별로 지정했다: 채널 주문 식별 실패, 재고 부족 라인 발생 건수,
발주 초안 검증 실패, 회신 미수신 건수, 송장 미발급·상태 정체 건수, 반품 미종결 건수.

---

## 6. 의존 시스템 · 권한 · 미확인 사항

| 항목 | 상태 | 비고 |
|---|---|---|
| 판매채널 종류·계정 | UNKNOWN | 채널별 API 계약 없음. 현재는 CSV 내보내기 기준 |
| 재고 원천(ERP) | UNKNOWN | ERP 재고 연계 스키마 미확정. 현재는 `stock_positions.csv` 입력 |
| 택배사·송장 조회 | UNKNOWN | 택배사별 API 계약 미확정. 사람이 입력 |
| 공급사 발주 채널 | UNKNOWN | 이메일/메신저/ERP 중 무엇인지 미정 |
| 비공개 Governance 사업문서 | **NOT_READ** | 아래 참고 |
| 실제 고객정보 | 사용하지 않음 | 가상 데이터만 사용 |
| 실 발주·실 결제·실 발송 | 수행하지 않음 | 코드 경로로도 차단됨 |

**Governance 접근 제한**: `AGENTS.md`가 지정한 비공개 Governance 루트
(`G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-governance`)를 열람하지 못했다.
이 PC(192.168.0.101)에는 `G:`/`Z:` 매핑이 없고, 192.168.0.2의 SMB 공유
(`\\192.168.0.2\내pcG\...`) 자체가 "네트워크 경로를 찾을 수 없습니다"로 연결되지
않았다. `D:\` 아래에도 `ai-revenue-lab-governance` 로컬 사본이 없다.

이 제한이 이번 작업에 미친 영향은 작다. 가격·계약·고객 대상 결정은 하지 않았고,
고객정보는 가상 데이터만 사용했으며, 산출물은 기술 검증 결과로만 제한했다. 실제
고객 단가를 적용하려면 Governance 문서를 열람한 뒤 다시 계산해야 한다.

---

## 7. 하지 않은 것

- 실제 주문·결제·발주·발송 없음.
- 판매채널 계정·택배사 계정·ERP 계정 연결 없음.
- 모델·제공자 선택 변경 없음.
- 기존 구매 체인(`CommercialRequest` → `AccountingHandoff`) 수정 없음.
- `kagent/cli.py` 수정 없음. 파일럿 실행기는 `kagent/ops_sales_order_cli.py`로
  분리했다.
- 비공개 사업문서 내용을 저장소에 옮기지 않음.
