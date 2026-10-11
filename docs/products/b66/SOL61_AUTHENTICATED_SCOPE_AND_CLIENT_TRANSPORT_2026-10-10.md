# #4117 — 로그인 소유자 Sol Native PDF 스코프 API와 프런트엔드 통합 경계

2026-10-10 KST. **실서비스 출시 활성화 아님.**

## 신규 읽기 전용 API

`GET /api/b66/quote/native-sol-scope?saved_skill_id=b66skill_...&item_count=N`

- 반드시 기존 B66 로그인 → `current_user_id` → owner workspace → 승인된 Saved Quote Skill / 템플릿 fingerprint 확인을 거친다.
- 원격 브라우저가 임의의 인증서, 렌더러, workspace, fingerprint를 선택할 수 없다.
- 서비스 소유 `app.state.b66_native_sol_pdf_client` 및 **독립 인증된** `b66_native_sol_releases`가 실제 존재할 때에만 JSON `available=true`, `certificateSha256`, `skillFingerprint`, `profileFingerprint`, `minItems/maxItems`, `itemCount`를 반환한다.
- 기본 Product 앱에서는 여전히 모두 미주입이므로 **503 `native_sol_not_certified`**다. 시뮬레이션에서만 두 값을 주입한다. 인증서가 없으면 private Skill Store조차 읽지 않는다.
- 과거 PRIVATE v1 인증서로 4+ 품목을 인증하지 못한다. 4+ 요청에는 독립 v2 registry가 없으면 503. 계정 소유자가 다르면 404, 비로그인은 401, 잘못된 입력은 400. PDF 생성이나 Drive 호출을 하지 않는다. `private, no-store`를 유지한다.

## Native 클라이언트 전송 어댑터

`quote-sol-pdf-runtime-bridge.js`는 사용자 화면 자동 연결을 수행하지 않는 opt-in 프런트엔드 공용 모듈이다.

1. 같은 출처 GET `native-sol-scope`로 인증된 Saved Skill과 실제 서버 발급 릴리스 범위 확인. 원래 CGI 공개 패키지 인증서나 로컬 개발용 `X-B66-Dev` 값은 사용하지 않는다.
2. 서버 반환 fingerprint와 실제 화면 승인 템플릿 fingerprint 일치 확인.
3. 같은 출처 POST `native-sol-pdf` 결과를 기존 `B66SolPdfSnapshot`이 응답 헤더·바이트 SHA까지 검증한다.
4. `B66SolPdfOutputs`가 **동일한 PDF 바이트 1개**를 PDF iframe Blob, 다운로드, Drive용 복사본으로 분기한다. 로그인 계정 세대가 바뀌거나 `invalidate`되면 오래된 snapshot을 버린다.
5. 503/401/서명 불일치/비정상 응답에 대해 browser Canvas/HTML/JPEG/기존 Worker로 자동 fallback하지 않는다. 인증되지 않은 릴리스로 서비스가 열린 것처럼 표시하지 않는다.

## 실증 및 비용

`apps/padiem-chat/tests/test_b66_certified_pdf.py -k 4117`: **24 PASS**, 인증 스코프/소유권/잘못된 item_count/비활성/4+ v1 상속 거절, 기존 native PDF 응답 보존. 서버 transport는 합성 fixture로만 확인.

`node reference/business-66-padiem-quote-v1/tests/quote-sol-pdf-runtime-bridge.test.cjs`: 계정별 서버 스코프 GET → 원본 PDF POST → 화면/다운로드/Drive 1-바이트 일치, 503·조작·계정 세대 변경 검증. **실제 Windows Sol PDF 바이트**에 같은 테스트를 적용하려면:

```powershell
$env:B66_NATIVE_SOL_TEST_PDF_PATH = 'E:\b66-4117-native-local-evidence-261010\synthetic-4.pdf'
node reference/business-66-padiem-quote-v1/tests/quote-sol-pdf-runtime-bridge.test.cjs
```

실제 PDF 기술 출력의 SHA는 `1c96031cece462a8282df1c06e98c2e752612e2c05af353b1ca670cda2aaf248` (4품목·2페이지)이며, 테스트 서버 인증 스코프 헤더는 **합성**이므로 실제 운영 인증서를 발급했다고 주장하지 않는다.

기존의 경량 B66 public template CI job에 단일 Node 테스트만 추가; browser lane·workflow 신규 생성 없음.

## 최종 연결 전 해야 할 일

실제 Windows 서버 런타임에 정식 승인된 v1-public / v2 인증서 및 편집 금액 재검증 어댑터가 있어야 한다. 그 다음 기존 B66 앱의 미리보기 `quotePaper`, 다운로드 `B66QuoteRuntimeBridge.downloadPdf`, Google Drive `B66QuoteAppBridge.certifiedPdfBytes`를 이 opt-in 전송 경계로 원자적으로 전환하고 **진짜 Google Drive 업로드/재열기**까지 확인한다. 기존 고객 화면/Drive 경로는 이번 변경에서 건드리지 않았다. **#4117 OPEN, 고객 HOLD, Production·Secrets·유료 모델 호출 0.**
