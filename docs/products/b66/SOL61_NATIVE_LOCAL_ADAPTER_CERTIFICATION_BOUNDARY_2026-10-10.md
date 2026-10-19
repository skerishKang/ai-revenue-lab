# #4117 — Sol 6.1 실제 오프라인 PDF 어댑터 / 공개 패키지 인증 경계

**기준: 2026-10-10 KST.** 이 파일은 신규 v2 출시 인증서가 아니다.

## 발견한 필수 구분

`reference/b66-public-standard-templates/cgi/v1/PUBLIC_RELEASE_MANIFEST.json`에는 다음이 명시되어 있다.

- `historical_sol_certificate_refers_to_original_private_bundle=true`
- `public_bundle_is_exact_unmodified_source_subset=false`
- `runtime_activation=false`

따라서 **현재 공개 패키지의 `sol61/certificate.json`을 그대로 고객 서비스의 바이트 인증서라고 선언할 수 없다**. 인증서 내부 `packageFiles`의 `engine/quote_template.py` 및 `template/template.json` 해시는 공개 패키지의 실제 SHA-256과 다르다. 이것은 공개 Manifest가 열거한 소스 sanitization/경로 적응과 관련된 구분이다. 공개 Manifest는 공개 소스의 해시를 별도로 기록한다. 기존 인증서나 공개 18개 산출물은 수정하지 않았다.

## 신규 구현

`apps/b66-sol61-multipage/native_server_adapter.py`

- 공개 Release Manifest에 기록된 `Sol` 소스·리소스·인증서의 실제 SHA-256을 읽어서 검증. 원본 역사적 인증서의 private `packageFiles`를 공개 배포물의 해시로 오용하지 않는다.
- 실제 `SolMultipage.render`를 호출하고 `PdfReader(strict=True)`로 생성 PDF를 읽어 페이지 수 및 SHA-256 재검증.
- 원본의 승인된 발신자 및 EXCLUSIVE 10% 세금·QuoteCore 원본 산술 규칙만 지원. Source CGI에 없는 송신자 변경·할인·면세 등은 기존 양식을 조용히 변조하지 않고 거절.
- 받은 `render_model.coreTotals` 값은 authority가 아니다. 같은 입력을 인증된 QuoteCore Node adapter에서 다시 계산하여 subtotal/supply/vat/grand/amounts/mode 및 모든 품목을 대조한다. `writtenWords`·화면에 표시할 금액/품목/업체도 대조한다.
- `render_candidate(model)`은 **오프라인 미인증 기술 후보**만 반환. PDF·PDF SHA·페이지 수와 함께 `certified=false, releaseEligible=false`를 기록. **인증 헤더나 정식 서비스 certificate ID를 발급하지 않는다.**
- `render_pdf(...)`는 항상 `native_sol_public_release_not_certified`로 차단. 기존 `/api/b66/quote/native-sol-pdf`에 주입해도 이 public bundle은 고객용 PDF를 만들 수 없다.
- 별도 Production 서비스, 브라우저 Canvas/JPEG, 기존 PDF Worker, GLM, 폰트 대체, 외부 네트워크나 유료 모델을 사용하지 않는다.

## 테스트와 한계

`python -B -m pytest -q -p no:cacheprovider apps/b66-sol61-multipage/tests/test_native_server_adapter_4117.py`

Windows 로컬에서 13 PASS. 1/2/3품목은 실제 공개 Sol PDF를 생성하여 직접 재계산한 바이트와 비교; 1품목은 기존 증거 SHA `5b90ca47...`와 일치. 4품목은 2페이지 실제 PDF를 생성, 기존 기술 증거 SHA `1c96031c...`와 일치하지만 `certified=false`. 발신자·금액·표기·QuoteCore·세금 위조, 미발급 서비스 인증서의 실사용을 차단하는 음성 테스트 포함. 모두 모의 API가 아닌 로컬 파일·실제 Node+Python+PDF 엔진 수행.

**남은 고객 전환 게이트**: (1) 공개 재배포된 Sol 엔진+폰트 버전에 대한 독립 `v1/public` 서비스 인증서, (2) 4+ 다중 페이지 별도 v2 인증, (3) Python+Node+원본 폰트가 동일하게 동작하는 합법적 호스팅, (4) 실제 로그인 Saved Skill/QuoteCore 서버 런타임 연결, (5) 같은 PDF bytes로 화면/다운로드/Drive 사용 확인. 현재 `#4117 OPEN`, 고객 READY=HOLD.
