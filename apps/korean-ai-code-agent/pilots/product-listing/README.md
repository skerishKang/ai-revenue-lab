# #5446 온라인 상품 등록·판매채널 운영 실증 — 로컬 작업 결과

```text
DOC_ROLE=BUSINESS_PILOT_LOCAL_RESULT
ISSUE=#5446
BRANCH=feat/5446-product-listing-bp
BASE_SHA=0a54f8c54
DATE=2026-10-21
COM2_MACHINE=K_lipvoice (192.168.0.101)
GOVERNANCE_READ=NOT_READ
EXTERNAL_PUBLISHING=NOT_PERFORMED
CHANNEL_ACCOUNT_ACCESS=NONE
MEASURED_PRODUCTIVITY_CLAIM=NONE
```

이 문서는 공개 저장소에 올릴 수 있는 **기술 결과**만 담습니다. 고객별 사업계획·가격·내부 자료는 포함하지 않았고, 포함하지 않습니다.

---

## 0. COM1 비공개 Governance 문서 열람 여부

```text
GOVERNANCE_READ=NOT_READ
TARGET_PATH=G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-governance
ACCESS_ATTEMPT_1=COM2 에 G: 드라이브 없음 (Get-PSDrive 결과 C/D/Temp 뿐)
ACCESS_ATTEMPT_2=\\192.168.0.2\내pcG\... UNC 경로 접근 실패 (경로 없음)
ACCESS_ATTEMPT_3=COM1(192.168.0.2) SMB 445 포트 연결 실패 (TcpTestSucceeded=False)
RESULT=COM2 에서 COM1 Governance 루트에 접근할 수 없음
```

권한 문제로 열지 못했습니다. 열람하지 않은 상태를 `NOT_READ`로 기록합니다. 이 과제에서 필요한 사업조건·영업전략·가격·개인정보는 이 문서에 포함되지 않았고, 아래 절차는 실제 고객 자료 없이도 돌아가는 형태로 설계했습니다. 대표님 연결 시 Governance 문서를 COM1에서 직접 읽고 값이 달라지는 부분만 반영하면 됩니다.

---

## 1. 재사용 가능한 기존 코드·도구 목록

새 AI 엔진·모델 라우터는 만들지 않았습니다. 아래는 이미 저장소에 있는 계약과 도구를 그대로 사용한 위치입니다.

| 필요 능력 | 재사용한 기존 코드 | 위치 | 상태 |
|---|---|---|---|
| 공급처 파일 수신 (CSV) | `StrictCsvCommercialRequestAdapter` 패턴 (정확한 헤더 집합, 셀 경계, 스프레드시트 수식 가드) | `apps/korean-ai-code-agent/src/kagent/ops_csv_intake.py` | PRESENT (패턴 재사용, 상품 스키마는 신규) |
| 공급처 파일 수신 (XLSX) | `extract_binary_document` (검토된 Core 파서 1개) | `packages/padiem-ai-core/padiem_ai_core/document_normalization.py` | PRESENT |
| 필드 단위 출처·검수 상태 | `ExtractedField` / `ExtractionOrigin` / `FieldReviewStatus` | `apps/korean-ai-code-agent/src/kagent/ops_intake.py` | PRESENT |
| 파싱 결과의 신뢰 승격 차단 | `promote_candidate` 의 "unreviewed → trusted" 규칙 | 같은 파일 | PRESENT |
| 소요시간·오류·개입 측정 | `WorkflowTelemetryEvent` / `PilotTelemetryKind` / `PilotMeasurementBridge` | `apps/korean-ai-code-agent/src/kagent/ops_pilot_telemetry.py` | PRESENT |
| KPI 정의·집계 | `PilotKpiEngine` / `PilotObservation` / `MetricDefinition` / `EvidenceQuality` | `apps/korean-ai-code-agent/src/kagent/ops_pilot.py` | PRESENT |
| 추정치와 실측 분리 | `EvidenceQuality.ESTIMATED` (추정 기준선은 측정 비교에 사용되지 않음) | 같은 파일 | PRESENT |
| 브라우저 입력 액션 어휘 | `classify_browser_control_action` (lease_eligible / step_up_required / prohibited / out_of_scope) | `apps/korean-ai-code-agent/src/kagent/browser_control_actions.py` | PRESENT |
| 브라우저 실행 경계·승인 | P01/Broker/lease 계약 (Electron CDP 단일 권한) | `docs/architecture/PADIEM_BROWSER_EXECUTION_ADAPTER_DECISION_3782.md` | PRESENT (외부 브라우저 백엔드는 RESEARCH 상태) |
| 산출물 파일 저장 | `artifact_export` / `document_export` / `ops_document_renderer` 계열 | `apps/korean-ai-code-agent/src/kagent/` | PRESENT |
| 외부 공개 수집·검색 | `padiem_ai_core.web_runtime` / `search_decision` / `retrieval` | `packages/padiem-ai-core/padiem_ai_core/` | PRESENT (자격증명·연결 필요) |
| 이미지 규격 검사 도구 | Pillow 12.3.0 승인 휠 + `image_helpers` | `packages/padiem-ai-core/padiem_ai_core/image_helpers.py` | PRESENT (승인 휠 설치 필요) |

이번에 추가한 것은 **상품 등록 도메인 모델**과 **채널 중립 투영 엔진** 두 가지뿐입니다.

- `apps/korean-ai-code-agent/src/kagent/ops_product_listing.py`
- `apps/korean-ai-code-agent/src/kagent/ops_product_listing_channels.py` (판매채널 등록 양식 = 데이터)
- `apps/korean-ai-code-agent/src/kagent/ops_product_listing_cli.py` (실행 진입점)
- `apps/korean-ai-code-agent/tests/test_ops_product_listing.py` (44개 계약 테스트)

### 중복 조사

```text
BUILD_NEW_AI_ENGINE=NO
BUILD_NEW_MODEL_ROUTER=NO
BUILD_NEW_BROWSER_ENGINE=NO
BUILD_NEW_DOCUMENT_PARSER=NO
BUILD_NEW_TELEMETRY_STORE=NO
BUILD_NEW=상품 등록 도메인 모델 + 채널 프로필 데이터 + 투영 엔진
REASON=상품 등록 업무 자체가 저장소에 없었고, 기존 계약은 그대로 쓸 수 있었음
```

---

## 2. 온라인 상품 등록 업무 절차

아래 6단계는 저장소 코드로 실행 가능한 단계(1~3, 6)와 사람이 수행하는 단계(4, 5)로 나뉩니다.

### 단계 1. 상품 자료 받기

| 항목 | 내용 |
|---|---|
| 입력 | 공급처 상품 자료 1건 (CSV 또는 XLSX) |
| 처리 | 헤더 집합이 합의된 공급 시트와 정확히 일치하는지 확인 → 불일치 시 즉시 중단 |
| 안전 | 셀 값 상한, 제어문자 차단, 스프레드시트 수식(`= + - @`) 차단, NUL 바이트 차단 |
| 산출물 | `canonical_product.json` (필드별 출처·검수 상태 포함) |
| 자동화 | 자동 (실행 가능) |

공급 시트 헤더 36개: `상품명, 모델명, 브랜드, 제조사, 카테고리, 카테고리코드, 색상, 사이즈, 소재, 무게kg, 가로mm, 세로mm, 높이mm, 단위, 판매가, 정가, 재고수량, 최소주문수량, 품번, 원산지, 보증기간, 부가세구분, 미성년자구매, 배송비유형, 배송비, 발송예정일, 반품교환정책, 요약설명, 상세설명, 검색어, 태그, 대표이미지, 추가이미지, 공급사, 공급가`

### 단계 2. AI로 상품정보 조사 및 정리

| 항목 | 내용 |
|---|---|
| 입력 | `research_notes.json` (조사 결과와 공개 출처 URL) |
| 처리 | 조사 값은 공급처 값을 덮어쓰지 않습니다. 출처 URL은 필드 출처(lacator)에 함께 기록됩니다. |
| 신뢰 규칙 | 조사 값도 처음에는 `unreviewed`입니다. 파싱 정확성과 사업 신뢰는 구분됩니다. |
| 자동화 | 반자동 (조사 수집 자체는 `web_runtime` 경로, 자격증명·연결 필요) |

### 단계 3. 상품 등록용 데이터 생성

| 항목 | 내용 |
|---|---|
| 산출물 | 표준 속성 레코드, 판매채널별 등록 초안 4건, 상세페이지 HTML, 이미지 매니페스트, 검수 체크리스트, 후속 항목 |
| 채널 | 쿠팡 마켓플레이스, 네이버 스마트스토어, 11번가 셀러오피스, 자체몰(카페24 콘솔 기준) |
| 채널 규칙 출처 | 각 프로필에 공개 문서 URL과 확인일이 함께 기록됩니다 (`source_urls`, `source_checked_on=2026-10-21`) |
| 안전 | `공급가`·`공급사`는 내부 전용 속성이므로 어떤 채널 초안에도 들어가지 않습니다 (테스트로 고정) |
| 자동화 | 자동 (실행 가능) |

### 단계 4. 판매채널 입력 준비

| 항목 | 내용 |
|---|---|
| 산출물 | `browser_fill_plan.json` — 채널 콘솔 폼의 순서·대상·값 목록 |
| 자동화 | 반 자동 |
| 사람이 하는 일 | 값 입력, 이미지 업로드, 저장·판매요청 |

### 단계 5. 고객 검수

| 항목 | 내용 |
|---|---|
| 입력 | `review_round1.json` 형식의 검수 결과 (`confirmed` / `corrected`) |
| 규칙 | `corrected`는 수정값이 없으면 거부됩니다. 조용한 수정보다 미해결 필드가 낫습니다. |
| 규칙 | 수정이 생성된 상세 설명을 바꾸면 상세 설명의 검수 상태가 다시 `unreviewed`가 되고, 두 번째 검수 라운드가 필요합니다. |
| 자동화 | 반 자동 (사람이 판단, 코드가 기록) |

### 단계 6. 등록 결과 및 소요시간 기록

| 항목 | 내용 |
|---|---|
| 산출물 | `pilot_report.json` — 단계별 실측 시간, 오류·수정 횟수, 사람 개입 횟수, 후속 항목 |
| 자동화 | 자동 (실행 가능) |

### 등록 후 수정·상품정보 관리

이번 슬라이스 범위 밖입니다. 등록 후 수정·가격 변경·옵션 재고 관리는 ERP/주문 연계 과제(#5447, #5448)와 분리되는 영역입니다. 채널 초안이 "채널 필드 키 → 값" 형태이므로, 수정 단계는 같은 투영 엔진을 재사용해 재초안을 만드는 형태로 확장할 수 있습니다.

---

## 3. 상품 1건의 샘플 등록 데이터

```text
SAMPLE=데모 USB-C 알루미늄 노트북 스탠드 (12.9인치 전용)
MODEL=DEMO-STD-001
SUPPLIER=데모공급사(샘플·내부용)  ← 공개 저장소에 올리지 않는 값이 아니라 샘플 표기
CUSTOMER_DATA=NONE (가상 샘플)
```

- 공급 자료: `apps/korean-ai-code-agent/pilots/product-listing/sample/supplier_products.csv`
- 조사 결과: `apps/korean-ai-code-agent/pilots/product-listing/sample/research_notes.json`
- 검수 1차: `sample/review_round1.json` (33개 필드 확정, `model_name` 1건 수정)
- 검수 2차: `sample/review_round2.json` (수정으로 바뀐 상세 설명 재확정)
- 생성 결과(1차, 검수 전): `pilots/product-listing/out/`
- 생성 결과(2차, 검수 후): `pilots/product-listing/out_reviewed/`

### 2차(검수 후) 채널별 상태

| 채널 | 차단 항목 | 경고 항목 | 검수 전 필드 | 입력 준비 완료 | 남은 사람의 일 |
|---|---|---|---|---|---|
| 쿠팡 마켓플레이스 | 0 | 1 | 0 | NO | 상품정보제공고시(카테고리별 법적 고시) 직접 입력 |
| 네이버 스마트스토어 | 0 | 0 | 0 | YES | 콘솔 입력·이미지 업로드·저장 |
| 11번가 셀러오피스 | 0 | 0 | 0 | YES | 콘솔 입력·이미지 업로드·저장 |
| 자체몰(카페24 기준) | 0 | 0 | 0 | YES | 콘솔 입력·이미지 업로드·저장 |

`입력 준비 완료`는 "차단 결함이 없고 검수 전 필드가 0건"이라는 뜻이며, **게시 가능하다는 뜻이 아닙니다.**

---

## 4. 자동화 가능한 단계와 미완료 단계

```text
PRESENT:
  - 공급 자료 CSV/XLSX 파싱과 정규화
  - 표준 속성 레코드 생성
  - 조사 결과 병합과 출처 기록
  - 채널별 등록 초안 생성(필드명·필수·길이·열거·수치 검증 포함)
  - 상세페이지 HTML 생성
  - 이미지 매니페스트와 채널별 이미지 규격 검사
  - 브라우저 입력 플랜 생성(기존 액션 어휘 기준)
  - 소요시간·오류·개입 측정 기록
  - 검수 결과 반영과 재검수 라운드

GAP (PRESENT_API_BUT_NOT_EXECUTED):
  - 실제 브라우저 콘솔 입력 (bounded lease + 실제 소유자 승인 + 실제 창 세션 필요)
  - 이미지 업로드와 파일 선택
  - 상품 저장·판매요청 제출
  - 실제 채널 API 호출 (계정·인증정보 미제공)

GAP (NOT_IMPLEMENTED_IN_THE_PRODUCT):
  - 쿠팡 상품정보제공고시 자동 생성(카테고리별 법적 고시는 사람이 읽고 입력해야 함)
  - 네이버쇼핑 브랜드 등록·승인 요청
  - 구비서류(인증서·수입신고필증) 준비
  - 카테고리 코드 자동 매칭(채널별 코드 사전 필요)

UNKNOWN:
  - 고객 실제 판매채널 계정·권한·수수료·정산 조건
  - 고객이 사용하는 채널의 실제 조합과 우선순위
  - 실거래 환경에서의 실측 소요시간(아직 측정이 없음)
```

### 브라우저 자동화의 정확한 경계

기존 제품의 브라우저 액션 분류(`browser_control_actions`)에 따라:

| 액션 | 분류 | 실연 시 처리 |
|---|---|---|
| `type` (일반 텍스트 입력) | lease_eligible | 자동 입력 계획에 포함 |
| `upload` (이미지 업로드) | step_up_required | 사람이 수행 |
| `submit` (저장·판매요청) | step_up_required | 사람이 수행 |
| `payment_or_purchase`, `account_or_security_change`, `destructive_action` | prohibited | 수행하지 않음 |

이번 플랜에서 자동 입력 단계는 70건, 사람이 수행하는 단계는 13건(채널 4개 기준)입니다. 제품의 기존 lease/승인 계약을 우회하지 않기 위해 이 경계를 그대로 유지했습니다.

---

## 5. 소요시간 기록 양식

측정값은 `PilotKpiEngine`의 `EvidenceQuality`로 구분됩니다.

| 기록 항목 | 단위 | 종류 | 측정 위치 | 현재 상태 |
|---|---|---|---|---|
| 상품 자료 수신 → 조사·정규화 완료 | 분 | 실측 | `request_to_rfq_minutes` | 실측 가능 (시연 시 기록) |
| 상품 자료 수신 → 등록 초안 준비 완료 | 분 | 실측 | `request_to_po_minutes` | 실측 가능 (시연 시 기록) |
| 전체 작업시간 | 분 | 실측 | `total_minutes` | 실측 가능 (시연 시 기록) |
| 오류 및 수정 횟수 | % | 실측 | `extraction_correction_rate` | 시연 시 기록 |
| 자동화 재시도 횟수 | 회 | 실측 | `automation_retry_count` | 시연 시 기록 |
| 수작업 재입력 횟수 | 회 | 실측 | `manual_reentry_count` | 시연 시 기록 |
| 사람이 직접 개입한 횟수 | 회 | 실측 | `owner_intervention_count` | 시연 시 기록 |
| 사람이 직접 개입한 시간 | 분 | 실측(추가 기록) | 시연 시 수동 기록 | 시연 시 기록 |
| 기존 수작업 예상시간 | 분 | **추정** | `baseline_estimated_minutes` | 42분으로 샘플 입력(예시 값) |
| 완료 결과물 | 파일 | 실측 | `artifacts` | 자동 기록 |
| 추가 작업이 필요한 항목 | 목록 | 실측 | `follow_ups` | 자동 기록 |

저장소의 `pilot_report.json`에 남아 있는 `milestone_minutes`는 **자동 처리 구간의 실행 시간**입니다. 사람의 판단·입력 시간은 포함하지 않습니다. 실제 업무 소요시간은 대표님 연결 후 사람 단위로 측정합니다.

### 측정 원칙

```text
BASELINE_ESTIMATED=42 (샘플 추정치이며 실제 수작업 실측값이 아님)
MEASURED_COMPARISON_AVAILABLE=false
PRODUCTIVITY_CLAIM=NONE
```

코드 수준에서 추정 기준선은 `EvidenceQuality.ESTIMATED`로만 기록되고, KPI 엔진은 추정 기준선으로 절감률을 계산하지 않습니다. **이번 자료에는 절감률·생산성 향상 수치가 없습니다.** 실측값이 없기 때문입니다. 대표님 연결 시 수작업 시간을 실제 측정하면 그때 처음으로 비교 숫자가 나옵니다.

---

## 6. 고객 PC 연결 이후 수행할 기술 검증 항목

### 연결 직후 (0~30분)

1. COM1 Governance 문서 읽기: `G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-governance` → `README.md` → `사업방침/` → `운영방침/`. 이 문서가 정답이며, 위 절차에서 어긋난 부분은 Governance을 따릅니다.
2. 실제 공급처 상품 자료 1건 확보(엑셀 또는 CSV). 실제 자료는 이 저장소에 올리지 않습니다.
3. 실제 자료의 헤더 36개 기준 매핑 확인. 헤더가 다르면 `SUPPLIER_COLUMNS`에 대응 컬럼을 추가합니다(코드 수정, 규칙 변경 아님).
4. 실제 판매채널 우선순위 확인(쿠팡/네이버/11번가/자체몰 중 무엇부터인지).

### 실연 (30~120분)

5. `python -m kagent.ops_product_listing_cli --sample <실제자료폴더> --out <결과폴더>` 실행 → 1차 초안 생성.
6. 생성된 `channel_drafts/*.json`을 채널 콘솔 화면과 나란히 보며 값을 확인·수정 → `review_round1.json` 작성.
7. 2차 실행 `--review review_round1.json` → 정정된 필드 반영. 설명이 바뀌었다면 `review_round2.json`으로 재확정.
8. 실제 채널 계정으로 1개 채널만 먼저 등록 시도(승인·로그인·권한 확인 포함). 대표님 계정으로 진행하며 결제·발주는 하지 않습니다.
9. 소요시간을 단계별로 기록(표 5의 양식).

### 검증 후 (120분 이후)

10. 실제 콘솔 입력 결과를 채널 초안과 대조해 차이를 기록 → 차이 패턴이 쌓이면 `ChannelProfile` 데이터 보강.
11. 실제 소요시간과 수작업 시간이 쌓이면 그때 처음으로 절감률을 산출.
12. 다음 과제(#5447 ERP, #5448 주문·배송)와 중복되지 않는 범위만 남기고, 남은GAP을 다음 PR 후보로 정리.

### 권한·보안 주의

- 실제 채널 계정 로그인·판매승인 요청·결제는 대표님 승인과 실제 계정 범위 안에서만 진행합니다.
- 채널 계정 정보·인증 토큰·고객 자료는 저장소·PR·이슈에 올리지 않습니다.
- 조사 단계의 웹 수집은 `web_runtime` 경로를 쓰며, 사내 자료는 외부로 나가지 않도록 대상을 공개 출처로 한정합니다.

---

## 7. 재현 방법

```bash
cd apps/korean-ai-code-agent
export PYTHONPATH=src

# 1차: 검수 전 초안
python -m kagent.ops_product_listing_cli \
  --sample pilots/product-listing/sample \
  --out pilots/product-listing/out

# 2차: 검수 반영
python -m kagent.ops_product_listing_cli \
  --sample pilots/product-listing/sample \
  --out pilots/product-listing/out_reviewed \
  --review pilots/product-listing/sample/review_round1.json \
  --review pilots/product-listing/sample/review_round2.json \
  --baseline-manual-minutes 42

# 계약 테스트
python -m unittest discover -s tests -p 'test_ops_product_listing.py'
```

테스트: `apps/korean-ai-code-agent/tests/test_ops_product_listing.py` 44건 통과.
전체 kagent 계약 스위트(4251건)도 CI와 동일 경로 구성에서 통과했습니다.

---

## 8. 이번에 하지 않은 것 (범위 밖)

```text
EXTERNAL_PRODUCT_PUBLISHING=NOT_PERFORMED
CHANNEL_ACCOUNT_ACCESS=NONE
ORDER_OR_PAYMENT=NOT_PERFORMED
ERP_WORK(#5447)=UNTOUCHED
ORDER_SHIPPING_LINK(#5448)=UNTOUCHED
NEW_AI_ENGINE=NONE
NEW_MODEL_ROUTER=NONE
```

ERP(#5447)와 주문·배송 연계(#5448)는 다른 과제이므로 소스와 이슈를 건드리지 않았습니다.
