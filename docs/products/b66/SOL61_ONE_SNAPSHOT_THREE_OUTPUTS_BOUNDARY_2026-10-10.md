# #4117 — Native Sol PDF 1개 → 화면·다운로드·Drive 바이트 공유 경계

2026-10-10 KST. **기술 배선 준비 / 고객 출시 아님.**

## 변경

- `quote-sol-pdf-outputs.js`: 이전 PR #4122의 `B66SolPdfSnapshot`에서 인증된 *같은 PDF 바이트*를 받아 세 출력으로 제공한다.
  - `showPreview(scope, model, iframe)`는 검증된 PDF `Blob`의 URL을 실제 `iframe.src`에 사용. Canvas/JPEG/HTML 캡처 없음.
  - `download(scope, model, fileName)`는 같은 스냅샷의 **복사 바이트**를 다운로드 핸들러로 전달. URL 텍스트·캔버스 새 출력 생성 없음.
  - `driveBytes(scope, model)`는 같은 스냅샷의 **독립 복사 바이트, SHA-256, 인증서 SHA, 페이지수**를 Drive 상위 호출자에게 넘기도록 설계. Google Drive API를 직접 호출하거나 연결을 변경하지 않는다.
  - `invalidate()`는 프리뷰 iframe의 `src`를 즉시 제거하고 Blob URL을 폐기한다. 새로운 편집/계정 범위에서 늦은 응답을 재사용하지 않는다. 인증서 헤더·실제 SHA 검증은 기초 스냅샷 모듈이 시행한다.
- `tests/quote-sol-pdf-outputs.test.cjs`: 실제 PDF Blob 내용, 다운로드 사본, Drive용 바이트 3개가 동일한 SHA를 갖는지, 하나의 요청만 사용하는지, 로그아웃·비동기 응답·조작 SHA·잘못된 파일명을 거절하는지 검증.
- `b66-public-standard-template-contract.yml`: **기존 CI job 1개**에 짧은 Node 계약 테스트를 추가. 새로운 워크플로/브라우저 lane은 만들지 않는다. Linux 기본 실행에서는 합성 PDF 테스트만 실행하고, **실제 Windows Sol 4품목 PDF**는 아래 명령으로 오프라인 검증한다.

## 로컬 실제 Sol 원본 바이트 검증

Windows의 `E:\b66-4117-native-local-evidence-261010\synthetic-4.pdf`는 `SolMultipage.render`로 생성된 실제 4품목·2페이지 기술 후보이고, 고정 증거 SHA는 `1c96031cece462a8282df1c06e98c2e752612e2c05af353b1ca670cda2aaf248`이다.

```powershell
$env:B66_NATIVE_SOL_TEST_PDF_PATH = 'E:\b66-4117-native-local-evidence-261010\synthetic-4.pdf'
node reference/business-66-padiem-quote-v1/tests/quote-sol-pdf-outputs.test.cjs
```

검증 결과: `NATIVE_SOL_ORIGINAL_PDF_FANOUT=REAL_SOL_BYTES_PASS`, `PDF_PREVIEW_DOWNLOAD_DRIVE_SHA_PARITY=PASS`, `ONE_FETCH_FOR_THREE_OUTPUTS=PASS`. 이는 실제 Google Drive 업로드, 브라우저 배포 환경, 상시 Windows 서비스 운영을 증명하지 않는다.

## 고객 경계

**브라우저 `index.html`, `app.js`, `padiem-account.js`, `quote-drive-ui.js`는 이번 단계에서 바꾸지 않는다.** 현재 고객 화면의 기존 렌더링 경로를 중단하거나 인증되지 않은 개발 PDF로 대체하면 안 된다.

실사용 활성화를 위해서는 (1) 적법한 Windows 실행 환경을 동작시킬 Python/Node 서비스, (2) 공개 번들에 대해 독립 발급·승인된 v1 서비스 인증서 및 다중페이지 v2 인증서, (3) 인증된 Saved Skill의 `scope`가 서버에서 공급되는 API, (4) 앱 화면 iframe·다운로드 버튼·Drive `certifiedPdfBytes` 세 진입점의 원자적 전환 및 실제 Google Drive 확인이 필요하다. 원본 font 파일을 Linux로 복사하지 않으며, 원래 Sol 템플릿/역사적 인증서는 수정하지 않는다.

`#4117 OPEN`, 출시 `HOLD`, Production·Secrets·유료 모델 호출 0건.
