# #4117 — Native Sol PDF 서버 응답 경계 (2026-10-10)

## 범위 및 결론

PR #4122는 클라이언트 스냅샷 관리자만 추가했다. 이번 변경은 `/api/b66/quote/native-sol-pdf`를 **별도 opt-in 서버 API**로 등록하되, 기존 `/api/b66/quote/pdf` 및 PDF Worker를 변경하지 않는다. 화면·다운로드·Drive 연결은 아직 하지 않는다.

**신규 API의 기본 상태는 503 `native_sol_not_certified`이다.** Cloudflare Worker 초기화에서 native Sol client나 release map을 주입하지 않는다. UI에서 호출하거나 고객의 PDF를 이 API가 생성한다고 주장해서는 안 된다.

## 서버 신뢰 계약

1. 기존 로그인 인증 → 서버에서 사용자 ID·workspace 확인 → 해당 workspace 승인 Saved Skill ID/skill fingerprint 확인 → 내부 승인 프로필 fingerprint 확인. 요청 본문의 user/workspace/certificate 선택을 허용하지 않는다.
2. `render_model`은 QuoteCore output marker, 승인 프로필 fingerprint, taxReview 종료, coreTotals 및 effectiveItems 수를 충족해야 한다. 이 검증만으로 클라이언트의 금액이나 `derivedBy` 주장에 독립적으로 신뢰를 부여할 수는 없다. 실제 Sol 런타임의 서버 측 QuoteCore authority 재검증이 필요하다.
3. 서버 소유 `b66_native_sol_releases`와 `b66_native_sol_pdf_client` **양쪽**이 주입되어야 한다. 출시 인증정보는 사용자 JSON이 아니라 독립 검증된 운영 릴리스에서만 가져온다.
4. 기존 Sol v1 인증서의 scope는 1~3품목 단일 페이지다. 4품목 이상은 독립 발급된 v2 인증서가 없으므로 503. 동일한 v1 SHA를 4+에 복사하지 않는다.
5. 내부 native 응답의 renderer ID, certificate, skill/profile fingerprint, 페이지수, PDF SHA-256을 검증한다. 최종 응답 SHA는 서버가 실제 받은 바이트를 다시 계산한다. MIME은 `application/pdf`, `no-store`, `nosniff`. 검증 실패 시 PDF 바이트·민감한 내부 오류는 공개하지 않는다.
6. 단순 `%PDF-` 및 `%%EOF` 검사로 구조적 유효성을 증명할 수 없다. 런타임 측 실제 PDF 파싱, 페이지/품목·액수 검증, 폰트·레이아웃 실증이 **추가로 필수**다.

## 클라우드 런타임 판단

Cloudflare Python Workers는 Pyodide WASM 환경이다. 공식 문서: https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/ 및 https://developers.cloudflare.com/workers/languages/python/stdlib/ . 패키지는 pure Python 또는 Pyodide/PyEmscripten 호환 조건을 따른다: https://developers.cloudflare.com/workers/languages/python/packages/ .

현재 Sol 렌더러는 `subprocess`로 Node QuoteCore 어댑터를 실행하고 Windows의 한글 폰트 및 Python `pypdf` 리소스에 의존한다. 그래서 기존 Worker 내부에서 동일하게 돌아간다고 간주할 수 없다. 내부 서비스 바인딩으로 다른 **Worker**를 부르는 것과 별도 Python+Node 호스팅을 확보하는 것도 다르다. 공식 서비스 바인딩: https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/ .

배포 가능한 실행처의 Python·Node 버전, 필수 폰트의 라이선스·해시, 파일 리소스 결합, 인증된 서비스 간 전달, 응답 상한 및 서버 측 QuoteCore parity를 실증한 뒤 새 client를 연결해야 한다. Production, Secrets, 별도 Modal 활성화, 유료 호출은 이번 변경에서 하지 않았다.

## 제한 테스트

`apps/padiem-chat/tests/test_b66_certified_pdf.py`에서 #4117 전용 13개 추가. 익명/타계정/승인 누락/잘못된 인증값/SHA/페이지 수/HTML 대체/4+ v1 상속 차단을 검증한다. 합성 바이트를 사용하므로 실제 Sol fidelity 증거가 아니다.

## 남은 순서

- 서버 실행처와 독립 릴리스 인증서 확보 (v2는 별도 승인 필수)
- 진짜 native `SolMultipage.render`와 QuoteCore 스냅샷 검증을 수행하는 서비스 어댑터 구현, 정확한 certificate SHA 발급
- 클라이언트 `B66SolPdfSnapshot`을 이 별도 API에 연결한 뒤 실제 PDF blob을 화면/다운로드/Drive에 공용 사용
- 1/2/3/4/8/25/100품목 원본 보존 + 페이지/계정/SHA/총액 E2E 실증
- #4117 및 #4076은 출시 전까지 OPEN, 고객 READY는 HOLD
