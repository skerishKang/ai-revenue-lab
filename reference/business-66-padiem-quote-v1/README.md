# B66 견적 제품 — 웹 구현 및 유지보수 안내

```text
DOC_STATUS = IMPLEMENTATION_README
SCOPE = reference/business-66-padiem-quote-v1/ source and local verification
PRODUCT_POLICY_AUTHORITY = docs/products/b66/README.md
PDF_FIDELITY_AUTHORITY = docs/products/b66/SOURCE_TEMPLATE_FIDELITY.md
CUSTOMER_READY = NO (last recorded full CGI E2E; see #3751)
```

이 폴더는 B66 견적 제품의 **현재 웹 클라이언트·Cloudflare Pages 브리지 구현**을 담습니다.
폴더 이름에 `reference`가 들어 있어도 단순한 초기 데모의 소스만 있는 것은 아닙니다.
반대로 소스코드에 기능이 존재한다는 사실만으로 실제 고객 환경에서 작동이 검증됐다는
뜻도 아닙니다.

**이 문서는 개발자용 실행·코드 안내서입니다.** 제품 결정은
[공식 B66 제품 문서](../../docs/products/b66/README.md), 원본 견적서 분석·재현·인증의
기술 기준은 [PDF 재현 계약](../../docs/products/b66/SOURCE_TEMPLATE_FIDELITY.md),
모델 권한·승인 기준은
[모델 변경 승인 정책](../../docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md)을 따릅니다.
이 README는 별도의 제품 정책이나 모델 라우팅 규칙을 만들지 않습니다.

## 1. 로컬에서 화면 확인

저장소 루트 기준으로 다음 명령을 실행합니다.

```bash
cd reference/business-66-padiem-quote-v1
python -m http.server 4173
```

브라우저에서 `http://127.0.0.1:4173/`를 엽니다. 정적 HTML/CSS/JavaScript를
확인하는 데 별도 번들러나 모델 API 키는 필요하지 않습니다.

**중요:** Python 정적 서버는 Cloudflare Pages의 `_worker.js`를 실행하지 않습니다.
로그인, 세션, 서버 저장·해석, 비공개 CGI 자산과 인증된 PDF 경로는 실제
브리지·서버 권한 없이 이 명령만으로 검증할 수 없습니다. 로컬 정적 미리보기를
Production E2E로 간주하지 마세요.

Cloudflare Pages 베타 진입점은 `https://quick-quote-kr.pages.dev/`로 설정된
별도 배포 대상입니다. URL 존재와 현재 서비스 정상 작동은 별개의 확인 사항입니다.

## 2. 실제 소스 구성

| 경로 | 구현 책임 |
|---|---|
| `index.html`, `styles.css`, `shell-layout.js` | 화면, 입력 영역, 반응형 레이아웃 |
| `app.js`, `easy-mode.js` | QuoteDraft 편집, 직접 입력·질문형 흐름 및 미리보기 연결 |
| `quote-core.js` | 수량·단가·VAT·합계·날짜의 결정론적 계산 기준 |
| `quote-extraction.js` | 모델 출력의 경계 검증과 사실값 → QuoteDraft 후보 변환 |
| `quote-skill*.js`, `quote-template*.js`, `quote-registration-session.js` | Saved Quote Skill, 템플릿, 승인·후보·렌더링 및 등록 흐름 |
| `padiem-account.js`, `quote-account-scope.js` | 인증 상태, 배정된 Skill, 고객 계정 범위와 서버 실행 브리지 |
| `_worker.js` | Pages 정적 자산 처리 및 허용된 `/api/padiem/*` 경로 중계 |
| `quote-history.js`, `quote-history-server.js` | 브라우저 기록 및 별도 서버 연동 경계 |
| `quote-browser-pdf.js`, `cgi-template-v2.js` | CGI 지정 Skill의 비공개 기준 이미지·투영 기반 브라우저 PDF 처리 |
| `xlsx-export.js` | QuoteCore의 확정값에 근거한 OOXML XLSX 출력 |
| `file-intake.js`, `quote-skill-ui.js` | 브라우저 파일 선택·검사, 등록 UI |
| `quote-embed*.js`, `embed.html` | 별도 임베드 UI·메시지 연결 |
| `tests/` | 기능별 Node 계약·회귀 테스트 |

각 소스의 함수·경계를 실제 코드에서 확인하세요. 이 표는 API 계약의
대체 문서가 아니며, 역사적 파일 수·코드 줄 수 같은 가변 수치는 고정하지 않습니다.

## 3. 견적 생성의 구현 경계

```text
사용자 입력 (질문형·직접 입력 / 인증된 계정의 자유형 입력)
  -> 검증된 견적 사실값 / QuoteDraft
  -> QuoteCore (금액·세금 계산)
  -> 승인된 Saved Quote Skill 및 템플릿
  -> 미리보기 / 지원되는 PDF·XLSX 출력
```

- **질문형·직접 입력:** 브라우저의 결정론적 입력·계산 경로로 동작합니다.
- **자유 문장 견적 해석:** `padiem-account.js`에서 계정·Skill 준비 조건을 검사하고
  `/api/padiem/b66/quote/interpret`를 호출하는 별도 **서버 연동 코드가 존재**합니다.
  존재 자체가 Production 성공을 입증하지는 않습니다.
- **저장된 양식:** 내부 템플릿/프로필은 명시적 승인·고객별 배정·지문 검증과
  연결됩니다. 인증되지 않은 후보를 정상 출력으로 승격시키지 않습니다.
- **계산 권한:** QuoteCore가 유일한 공급가·VAT·총액 계산 권한입니다.
  추출 모델이나 XLSX/PDF 변환기가 별도 금액 계산 엔진이 되어서는 안 됩니다.
- **반복 출력:** 구현·검증된 렌더링 코드를 재사용합니다. 완성된 PDF를 만들 때
  레이아웃을 매번 AI에게 다시 생성시키지 않습니다.

고객이 등록할 수 있는 재사용 원본 양식은 현재 **XLSX만 허용**하며,
HWPX는 미래 지원 대상이고 XLS/HWP는 제외됩니다(#3586).
이는 범용 파일 검사·참조 문서 분석의 기술적 가능 범위와 다릅니다.

## 4. PDF와 XLSX — 경로를 혼동하지 말 것

| 경로 | 구현 설명 | 검증 범위 |
|---|---|---|
| CGI 전용 브라우저 PDF | `quote-browser-pdf.js`가 승인된 CGI Skill과 비공개 기준 PNG, 지문·치수·해시를 검증하고 캔버스 투영으로 PDF 바이트를 생성 | 기록된 승인된 CGI Guided 브라우저 PDF E2E PASS |
| 그 밖의 승인된 PDF 요청 | `padiem-account.js`의 런타임 브리지가 `POST /api/padiem/b66/quote/pdf`로 전달; 서버 측 인증·바인딩·템플릿 정책에 종속 | 코드 경로 존재만으로 Production 성공 아님 |
| 브라우저 인쇄 | 초기 데모·브라우저 인쇄 관련 방식 | CGI 인증 PDF 경로와 동일하다고 주장하지 않음 |
| XLSX | `xlsx-export.js`가 확정 QuoteDraft/QuoteCore 값을 사용하여 워크북 생성 | PDF 인증 또는 원본 XLSX 완전 동일성의 자동 증명이 아님 |

**중요:** CGI 브라우저 PDF의 캔버스·이미지 기반 생성과
[PDF-native 범용 재현/인증 기술](../../docs/products/b66/SOURCE_TEMPLATE_FIDELITY.md)은
구현이 서로 다른 경로입니다. 단순 브라우저 인쇄, HTML→PDF 변환,
인증된 CGI 브라우저 PDF, 서버 PDF를 하나의 기능으로 취급하지 마세요.
모든 PDF 경로의 제품 승인·원본 일치 여부는 각각의 증거로 판단합니다.

## 5. 인증·업로드·배포 경계

- `_worker.js`는 `/api/padiem/*` 중 허용된 경로만 브리지로 전달하며,
  로컬 정적 서버에서는 해당 브리지가 동작하지 않습니다.
- 현재 `POST /api/v1/quote/intake` 경로는 `_worker.js`에서
  **`410 intake_disabled`**로 닫혀 있습니다. 파일 선택 UI와 검증 코드의
  존재를 자동 업로드·분석 성공으로 표시하지 마세요.
- `quote-skill-ui.js`에는 인테이크 요청 코드가 있으나, 실제 가동 여부는
  상기 서버 경계와 배포된 API의 확인 결과를 우선합니다.
- 브라우저 파일 선택의 사전 검사와 서버 측 파일 처리·모델 사용 허가는
  별개입니다. 새 파일 형식·모델·인증 권한을 README 수정으로 활성화하지 않습니다.
- `.github/workflows/b66-neutral-pages-beta.yml`은 B66 소스 폴더의 변경을
  감시합니다. **이 README만 main에 병합해도 Pages 배포 워크플로가 실행될
  수 있습니다.** PR에서의 검증과 Production 반영은 서로 다른 승인 게이트입니다.

## 6. 검증 명령과 고객 준비 상태

```bash
cd reference/business-66-padiem-quote-v1
node tests/static-contract.test.cjs
node tests/quote-core.test.cjs
node tests/quote-browser-pdf.test.cjs
node tests/mvp-runtime.test.cjs
node tests/xlsx-export.test.cjs
node tests/padiem-account-bridge.test.mjs
```

이는 해당 테스트가 **로컬에서 실행하는 회귀 검사**입니다.
통과하더라도 현재 배포 SHA, 실계정 로그인, 비공개 자산, 선택된 실제 모델,
자유형 입력·후속 질문 및 PDF 다운로드를 검증한 것은 아닙니다.
소스 단위 테스트와 고객 인수 E2E는 구분해야 합니다.

**2026-10-08에 기록된 실제 CGI 고객 시나리오 상태**(#3751, #3733):
- 인증된 로그인·배정 Skill·Guided 계산·미리보기·브라우저 PDF: **PASS**.
- Complete Freeform 견적 해석: **HTTP 502 / upstream_timeout**.
- Partial Freeform/follow-up: **NOT TESTED**.
- 당시 정확히 호출된 모델과 타임아웃 발생 지점: **미확인**.
- 전체 고객 인수: **`CUSTOMER_READY=NO`**.

이는 **당시 특정 실행의 결과**이며 최신 서비스 버전의 재검증 결과를
대신하지 않습니다. 모델의 무료·유료 여부, 제공자 선택·권한은
[현행 소유자 정책](../../docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md)
및 명시적 승인에 따릅니다. 가격 필터 제거 문서 PR #3796은
아직 Draft이므로 실행 코드 반영 여부를 따로 검증해야 합니다.

## 7. 문서 책임과 이전 기록

- [B66 공식 대표 문서](../../docs/products/b66/README.md) — 현재 제품 정책·작업 범위·권위 지도.
- [B66 PDF 재현 기술 기준](../../docs/products/b66/SOURCE_TEMPLATE_FIDELITY.md) — 원본 분석·인증·PDF 일치성.
- [초기 Quote Beta README 원본 이력](../../docs/history/2026-10-08/B66_QUOTE_BETA_REFERENCE_README.snapshot.md) — 지금 문서를 대체하기 전 기록; 현행 정책 아님.
- [초기 데모 운영 가이드(과거 기록)](../../docs/history/2026-10-08/B66_QUOTE_BETA_DEMO_GUIDE.snapshot.md) — 과거 시연 절차의 원본 보관본이며 현행 고객 사용 안내가 아님. 보관 경로는 별도 Draft PR #3803에서 추가됨.

다른 문서의 과거 모델·데모 가정을 이 폴더의 현행 실행 권한으로 해석하지 마세요.
