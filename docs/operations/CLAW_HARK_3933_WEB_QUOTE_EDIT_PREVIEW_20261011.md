# #3933 / #3928 — Hark 웹 XLSX 견적서 변경안 미리보기

**상태: 소스 구현, 실제 운영 검증 전 / 읽기 권한 전용.**

## 웹에서 실제로 동작하는 범위

기존 웹 XLSX 업로드 → 선택 → 독립적인 Core/Engine P01 **읽기 승인** → 별도 R2 작업 사본 생성·다운로드 다음에, 사용자가 학교명과 공급가를 입력하고 **저장 없는 변경안 미리보기**를 실행한다.

`POST /api/claw/office/web-selections/{selection_ref}/quote-edit/preview`는 서버가 인증된 소유자·워크스페이스·동일 선택·실행·원본 SHA·P01 승인된 사본 D1·R2 실제 바이트 해시를 재검증한 경우에만 기존 `revise_single_sheet_quote`를 메모리에서 호출한다. 브라우저는 학교명·공급가 **두 필드만** 제출하며 임의의 파일 경로, 작업 사본 ID, Engine 승인, DB/R2 객체 키를 선택할 수 없다.

반환값은 입력값, 공급가·부가세·합계, 원본·예상 결과 SHA-256 및 **정확한 변경안 SHA-256**이다. 이 변경안 SHA-256은 기존 별도 쓰기 승인 전용 `WorkspaceDocumentStore.create_authorized_web_quote_revision`에서 사용하는 canonical JSON 산출과 동일하다. 이 엔드포인트는 R2/D1에 **어떠한 수정본도 저장하지 않는다**.

미리보기 결과에는 `preview_only=true`, `write_approved=false`, `revised_xlsx_created=false`, `pdf_exported=false`, `pdf_unsupported=true`, `requires_independent_p01_write=true`가 반드시 포함된다. UI는 미리보기임을 명확히 표시하며 다운로드는 승인된 **원본 바이트 작업 사본**만 제공한다.

미승인, 다른 소유자, 실패/거절, 파일 변조, 미지원 XLSX OOXML 양식, 악성 문자열·임의 필드·유효하지 않은 금액을 거부한다. 중복 읽기 승인이나 가짜 PDF를 생성하지 않는다.

## #3928 종료 전 남은 필수 연결

1. 기존 P01 READ와 **구분된** Core/Engine XLSX EDIT/WRITE ToolSpec 및 실제 사용자 변경안 확인·독립 검증, durable one-shot 승인 경계.
2. 사용자 승인 **후에만** 기존 비공개 XLSX 수정본 생성 → 문서/대화 artifact 인덱스 등록 → 정확한 owner-only 수정본 다운로드.
3. 지원하는 견적서 템플릿의 글꼴·페이지 설정·병합 셀을 증명하는 Office 기반 PDF 변환기 연결. 미지원 파일은 정확도 보장 없이 임의 PDF를 만들지 않는다.
4. 운영 배포 및 플래그는 별도 승인 후, 실제 로그인 사용자로 XLSX 변경→PDF→파일 카드→추가 수정까지 브라우저 E2E.

**이번 작업 범위에는 운영 배포, 고객 파일, Secrets, Production D1 변경, 유료 모델 호출이 없다.** 상위 #3928과 #3933/#3932/#3936/#3580은 OPEN으로 유지한다.
