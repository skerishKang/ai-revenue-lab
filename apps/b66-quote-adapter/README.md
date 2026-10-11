# B66 서버 파일 어댑터 — 구현·검증 안내

```text
DOC_STATUS = IMPLEMENTATION_README
SCOPE = apps/b66-quote-adapter/
INTAKE_ADAPTER = SOURCE_ONLY
PAGES_INTAKE_ROUTE = HTTP_410_INTAKE_DISABLED
EXTRACTION_REQUEST_BUILDERS = FAIL_CLOSED_MODEL_ROUTE_UNAVAILABLE
PROVIDER_CALLS_IN_THIS_ADAPTER = 0
MODEL_SELECTION_AUTHORITY = NONE
```

이 폴더는 B66의 **파일 검증·분류, 기존 IP-CORE 문서 파서 연결,
모델 출력 검증, QuoteDraft 후보 투영**에 사용하는 Python 소스와 테스트를 담습니다.
**어댑터 소스가 있다는 사실은 파일 자동 분석 API가 가동 중이라는 뜻이 아닙니다.**
현재 페이지의 인테이크는 비활성화되어 있고, 이 모듈은 모델·제공자
선택이나 인증된 Production 실행을 담당하지 않습니다.

제품 정책·원본 견적서 등록 형식은 [B66 공식 README](../../docs/products/b66/README.md),
원본 재현 및 PDF 인증 조건은
[기술 기준](../../docs/products/b66/SOURCE_TEMPLATE_FIDELITY.md),
모델 등록·선택·활성화 권한은
[소유자 모델 정책](../../docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md)에 있습니다.
이 문서는 그 결정을 복제하거나 확장하지 않습니다.

## 1. 코드와 실제 책임

| 파일 | 실제 구현 책임 |
|---|---|
| `app/file_intake.py` | 요청 필드, 파일명·확장자·MIME·크기, 이미지 시그니처를 검증하고 안전한 후보로 분류 |
| `app/extraction_routing.py` | 추출 요청 생성 차단, 이미 얻은 외부 모델 출력 검증, 검증된 사실값의 QuoteDraft 후보 투영 |
| `tests/test_file_intake.py` | 문서 파서 연계, 입력 거부, 크기·형식, 후보 분류 회귀 검사 |
| `tests/test_extraction_routing.py` | 실행 불가 상태, 잘못된 추출값 거부, 금액 계산 권한·출력 경계 회귀 검사 |

문서의 바이너리 구조를 별도로 파싱하지 않습니다.
`file_intake.py`는 `padiem_ai_core.document_normalization.validate_document_identity`와
`padiem_ai_core.document_parser_boundary.parse_binary_document_via_authority`를
재사용하며, 파서 권한을 사용할 수 없으면 실패 상태를 반환합니다.

B66 어댑터가 **소유하지 않는 것**: 모델 선택/호출·API 키,
PDF/DOCX/PPTX/XLSX/HWPX 독립 파서, OCR, 이미지 생성,
실서비스 파일 업로드 승인, 원본 견적서 PDF 재현 엔진, 공급가액·VAT 계산.

## 2. 현재 실행 가능 상태 — 구분 필수

| 경로 | 소스에 존재하는 기능 | 현재 확인된 실행 경계 |
|---|---|---|
| 브라우저 `POST /api/v1/quote/intake` | 요청 경로와 UI 사전 검사 | `reference/business-66-padiem-quote-v1/_worker.js`에서 **HTTP 410 / `intake_disabled`** |
| `handle_intake_payload` | 정확한 요청 구조 검증, 이미지/문서 후보 분류 | **Python 소스 함수**. `SERVER_ROUTE_DEPLOYED=False`; 자체 HTTP 엔드포인트 아님 |
| `build_text_extraction_request` | 텍스트 추출 요청 함수 인터페이스 | `model_route_unavailable` 예외로 차단 |
| `build_image_extraction_request` | 이미지 추출 요청 함수 인터페이스 | `model_route_unavailable` 예외로 차단 |
| `build_scanned_pdf_extraction_requests` | 스캔 PDF 요청 함수 인터페이스 | `model_route_unavailable` 예외로 차단 |
| `normalize_model_output`, `project_to_quote_draft_candidate` | **외부에서 제공된** 비신뢰 추출 결과 검증·후보 변환 | 로컬 검사 함수. 모델 호출·화면 반영 권한 없음 |

옛 버전의 Space Bunny 모델 식별자는 `extraction_routing.py`에
**은퇴한 경로의 역사적 메타데이터**로 남아 있을 뿐 실행 승인이 아닙니다.
이 문서나 이 모듈은 새 모델, 무료 우선 정책, 자동 폴백, 예외적
Provider 호출을 승인하지 않습니다.

별도로 존재하는 **인증된 견적 입력 해석** 경로
(`/api/padiem/b66/quote/interpret`)와 이 파일 인테이크 경로는 다릅니다.
해당 해석 경로의 성공·실패를 이 모듈의 활성 상태로 추론하지 마세요.

## 3. 입력 계약과 범위

`handle_intake_payload`에 전달하는 요청의 필드는 다음 **세 개만** 허용됩니다.

```json
{
  "name": "quote.png",
  "media_type": "image/png",
  "base64": "<base64-encoded PNG content>"
}
```

- 문서 하위 계층의 허용 파일 형식: **PDF, DOCX, PPTX, XLSX, HWPX**.
  원본 문서 크기는 IP-CORE 제한인 **2 MiB 이하**.
- 이미지 하위 계층: **JPEG, PNG, WebP**, **4 MiB 이하**.
  확장자/MIME뿐 아니라 이미지 시그니처도 검사합니다.
- `.hwp` 등 금지 형식, 잘못된 base64, 추가 필드, 임의 URL·모델·
  provider·credential 선택 필드는 허용하지 않습니다.
- 이미지는 `image_candidate`와 `model_called=False` 상태로 분류합니다.
  텍스트 없는 PDF는 `scanned_pdf_candidate`로 분류할 수 있지만,
  이는 OCR이나 비전 모델을 실행했다는 뜻이 아닙니다.
- 네이티브 문서는 기존 IP-CORE 검사·파서 권한에 의존하며,
  파서 권한이 없거나 파일 검증에 실패하면 fail-closed합니다.

**주의:** 이는 하위 계층의 검사·분석 가능 형식입니다.
**B66 재사용 견적 템플릿 등록 허용 형식**은 #3586에 따라
`XLSX = ACCEPT`, `HWPX = FUTURE`, `XLS/HWP = REJECT`입니다.
PDF·이미지 입력 후보 분류가 템플릿 등록을 허가하지 않습니다.

## 4. 검증 실행

저장소 루트에서 **Linux / macOS (bash)**:

```bash
PYTHONPATH=packages/padiem-ai-core:apps/b66-quote-adapter \
  python -m unittest discover -s apps/b66-quote-adapter/tests
```

**Windows PowerShell**:

```powershell
$env:PYTHONPATH = "$PWD\packages\padiem-ai-core;$PWD\apps\b66-quote-adapter"
python -m unittest discover -s apps/b66-quote-adapter/tests
```

테스트는 네트워크 호출이 아닌 **로컬 단위·계약 검사**입니다.
2026-10-08 검토 시 이 소스 기준 36개 단위 테스트가 통과했으나,
고객 브라우저·실제 모델·원본 파일 자동 분석·Production 배포 또는
인증 PDF 다운로드의 E2E 통과를 입증하지는 않습니다.
코드를 수정할 때에는 동일 테스트와 경계 회귀를 다시 실행해야 합니다.

## 5. 연결 문서 및 역사

- [B66 공식 제품 문서](../../docs/products/b66/README.md) — 현재 제품 상태·원본 등록 정책
- [B66 문서 재현 계약](../../docs/products/b66/SOURCE_TEMPLATE_FIDELITY.md) — 구조·이미지·PDF 정확성 및 인증
- [B66 웹 구현 README](../../reference/business-66-padiem-quote-v1/README.md) — UI, Pages 브리지, 실제 PDF 경로 안내 (별도 Draft PR #3801에서 개정)
- [기존 어댑터 README 원본](../../docs/history/2026-10-08/B66_QUOTE_SERVER_ADAPTER_README.snapshot.md) — 과거 B14 이미지 연결 서술이 포함된 변경 전 기록, **현행 운영 권한 아님**

관련 구현 이력: #3147, #3162, #3212, #3249.
파일 인테이크를 재활성화하려면 별도의 승인된 모델·보안·배포 검증이 필요하며
이 README 변경만으로 모델 연결이나 Production 경로가 활성화되지 않습니다.
단, `.github/workflows/b66-neutral-pages-beta.yml`은 이 어댑터 경로의
`main` 변경도 감시합니다. **문서 PR의 병합조차 Pages 자동 배포 실행을
유발할 수 있으므로**, 별도 배포 승인과 영향 검토 없이 병합하지 마세요.
