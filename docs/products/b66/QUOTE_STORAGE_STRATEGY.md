# B66 견적서 저장 전략 — 브라우저 + 파디엠 D1 + 고객 Google Drive

```text
DOC_STATUS=OWNER_APPROVED_PRODUCT_DIRECTION
DECIDED_AT=2026-10-09
PRODUCT=B66_STANDALONE_QUOTATIONS
EXISTING_D1_HISTORY_OWNER=#3405
CUSTOMER_DRIVE_IMPLEMENTATION_OWNER=#3871
PAYWALL_OR_PRICING_APPROVED=NO
CURRENT_CODE_AND_DEPLOYMENT_CHANGE=NO
```

## 결론

**파디엠 클라우드(D1)를 유지하고, 고객 본인의 Google Drive를 선택 가능한 저장소로 추가한다.**
두 저장소를 경쟁·대체 관계로 만들지 않는다.

고객은 견적서를 작성하고 PDF를 내려받는 기본 기능 때문에 반드시 파디엠 클라우드 요금을 낼 필요가 없다.
향후 유료 상품은 저장 공간 자체보다 **파디엠이 제공하는 관리·검색·협업·자동화의 부가 가치**를 중심으로 설계한다.

이 결정은 제품 방향과 새 기능 요구사항을 확정한 것이다. Google Drive 저장·불러오기 기능이 구현되었다는 뜻은 아니다.

## 저장소별 책임

| 저장소 | 사용 목적과 권위 | 다른 기기 | 제품 상태 |
|---|---|---|---|
| **브라우저 로컬 저장** | 해당 브라우저의 임시 작업·오프라인 캐시. 계정별 서버 이력의 권위가 아니다 | 자체 동기화 없음 | 기존 코드 유지 |
| **파디엠 클라우드 — Cloudflare D1** | 로그인한 계정/워크스페이스의 공식 **최근 견적 이력**, 견적 읽기·복사·삭제. QuoteDraft 계열 기록과 검색을 운영 | 동일 파디엠 계정으로 조회 | #3405의 기존 구현·운영 검증 유지 |
| **고객 Google Drive (BYOS)** | 고객이 자기 Google 계정의 Drive에 명시적으로 **견적 저장·불러오기**. 파디엠 D1의 대체 저장소나 필수 로그인 조건이 아니다 | 같은 Google 계정에서 저장한 파일을 선택해 열기 | #3871 신규 개발 |

- **저장 위치는 고객이 선택한다.** 별도 요청 없이는 파디엠 기록을 Google Drive에 복사하거나 반대 방향으로 동기화하지 않는다.
- **기본 견적 작성·기존 D1 저장·PDF 다운로드는 Google Drive 연결이 없어도 동작한다.**
- 로그인 사용자에게 이미 제공하는 D1의 기본 최근 견적 기능과 계정 격리 계약을 유지한다.
- Google Drive 연결 실패·용량 부족·계정 전환은 현재 편집 중인 견적이나 기존 D1 기록을 훼손하지 않는다.

## Google Drive에 저장할 파일

저장 시 두 결과물이 필요하다.

1. **편집 가능한 버전 명시형 견적 JSON**: 고객·거래처 정보, 품목, 수량, 단가, 세금 설정, 견적번호·발행일, 적용된 승인 템플릿의 참조 식별자 등 QuoteDraft 복원에 필요한 값. JSON 스키마 버전과 필요한 메타데이터를 포함한다. 승인 템플릿 전체나 원본 비공개 파일을 무조건 내보내지 않는다.
2. **완성된 PDF**: 기존 승인 Saved Quote Skill + QuoteCore + 인증된 결정적 렌더러로 생성한 문서. PDF는 표시·다운로드 결과이지 편집 데이터나 계산 권위가 아니다.

견적 복원은 **JSON → 입력 검증 → QuoteDraft → QuoteCore 금액·세금 재계산 → 승인된 렌더러 미리보기/PDF** 순서로 한다. JSON에 있던 합계 숫자를 계산 결과로 신뢰하지 않는다. 참조한 템플릿이 미등록·비활성·접근 불가이면 임의로 다른 템플릿을 자동 활성화하지 않고 사용자에게 선택/복구 안내를 표시한다.

원본 XLSX/HWPX나 회사 로고·도장 등 별도 자산의 자동 Drive 저장은 이 기능의 필수 요구사항이 아니다. 명시적 저장을 지원할 경우에도 별도 검토가 필요하다. **Google Sheets 변환이나 Google PDF 렌더링은 필수 경로가 아니다.** (#3581과 구분)

## 사용자 화면 / 동작

```text
견적 작성 → 미리보기 → PDF 다운로드   (현재 경로 유지)
                       ├─ 파디엠 최근 견적 저장/복사 (#3405)
                       └─ [내 Google Drive에 저장]       (#3871 신규)

좌측 보조 메뉴 → 최근 견적 (현재 #3536/#3405 유지)
                └─ [Google Drive에서 열기]      (#3871 신규)
```

- 첫 단계에서는 고객이 **수동으로 저장하고 수동으로 다시 연다**. 파일 선택, 중복 이름, JSON/PDF 한쪽만 성공한 상태, 재시도 및 취소 상태를 명확히 표시한다.
- Drive 파일의 식별자·권한은 연결한 Google 사용자와 선택된 파일 기준으로 다룬다. 기존 B67/Claw Drive 커넥터를 B66 고객 개인 Drive 권위로 임의 전용하지 않는다. **공식 Google API 및 기존 커넥터 기능을 먼저 확인하고 최소 범위를 선택**한다.
- 다른 PC/브라우저·실제 휴대전화에서 동일 Google 계정으로 파일을 다시 열고 수정할 수 있는지는 후속 **실사용 E2E**에서 입증한다. 구현이나 PC 모바일 에뮬레이터만으로 실기기 PASS라고 보고하지 않는다.
- **양방향 자동 동기화, 충돌 해결, 자동 백업, 팀 공유**는 첫 단계 범위가 아니다. 후속 별도 이슈·승인이 필요하다.

## 수익화 원칙

| 기본/무료 방향 | 고급/유료 방향 후보 |
|---|---|
| 견적 작성, 기본 PDF 다운로드 | 고급 거래처·견적 검색 및 관리 |
| 브라우저 임시 저장 | 확장된 이력·관리 기능 |
| **고객 본인 Google Drive에 수동 저장·불러오기** | 팀 권한·협업 |
| **현재 제공 중인 D1 기본 최근 견적** | 승인된 자동 백업·동기화·반복 업무 자동화 |

**요금·쿼터·보관 기간·유료 등급은 미결정**이다. 이 문서만으로 신규 요금제를 적용하거나, 기존 D1 이력에 제한/과금을 추가하지 않는다. 고객 Google Drive의 용량과 정책은 고객 Google 계정을 따른다.

## 기존 개발에 대한 영향 — 변경 없음

| 현재 작업 | 변경 여부 |
|---|---|
| **#3405** — D1 계정별 최근 견적, 다른 브라우저에서 불러오기, 새 견적으로 복사, 삭제 | **변경 없음. 그대로 마무리** |
| **#3405 남은 검증** — 실제 휴대전화와 일부 견적 상세조회 HTTP 500 | **유지. Drive 개발을 이유로 지연/종료/재작성하지 않음** |
| **#3536** — 단일 견적 입력창·좌측 관리 메뉴 | **변경 없음. 후속 Drive 버튼만 보조 메뉴에 추가** |
| **#3733** — CGI 실제 고객 E2E | **변경 없음** |
| **#3839** — 다중 페이지 PDF | **변경 없음** |
| **#3581** — Google Sheets 기반 템플릿/출력 연구 | **별도 범위. 새 Drive 저장 기능과 병합하지 않음** |
| **QuoteCore / B14 / PDF** | **금액 계산·모델 선택·PDF 생성 경로 변경 없음** |

신규 개발 요청과 검증 기준은 [#3871](https://github.com/skerishKang/ai-revenue-lab/issues/3871), 현행 서버 견적 이력 완성 기준은 [#3405](https://github.com/skerishKang/ai-revenue-lab/issues/3405)를 참조한다.

```text
D1_REPLACEMENT=NO
D1_HISTORY_REWORK=NO
OPTIONAL_CUSTOMER_DRIVE=PLANNED_NOT_IMPLEMENTED
DRIVE_SAVE_EDITABLE_JSON_AND_PDF=PLANNED
FREE_MANUAL_DRIVE_SAVE_DIRECTION=OWNER_APPROVED
PAID_TIERS_LIMITS_PRICES=UNDECIDED
QUOTECORE_CALCULATION_AUTHORITY=UNCHANGED
B14_MODEL_SELECTION_POLICY=UNCHANGED
REPEAT_PDF_MODEL_CALLS=0
```
