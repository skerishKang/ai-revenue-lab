# #4117 Windows 원본 Sol 6.1 — localhost 개발용 화면과 HTTP 실증

2026-10-10 KST. **미인증 개발용, 고객 공개·Production/Secrets/Modal/과금 호출 0건.**

## 사용

Windows의 본 저장소 루트에서:

```powershell
python -B apps/b66-sol61-multipage/native_dev_gateway.py --local-development --port 8761
```

본인 Windows 브라우저에서 **http://127.0.0.1:8761/** 를 열고 `원본 Sol PDF 생성`을 누른다.

- **동일 PDF를 실제 화면 iframe에 표시**한다. `SolMultipage`가 Windows 기본 굴림/맑은 고딕과 Node `QuoteCore`를 사용해 생성한 PDF다. Canvas, JPEG, HTML 인쇄, 다른 렌더러는 없다.
- **동일 Blob URL로 다운로드**, 서버가 직접 응답한 PDF SHA-256과 다시 계산한 WebCrypto SHA-256을 검증한다.
- `Drive용 바이트 일치 검증`은 **같은 PDF 바이트의 복사본을 검증할 뿐** Google Drive API를 호출하거나 저장하지 않는다. 실제 Drive 업로드라고 주장하지 않는다.
- 견적 필드가 바뀌면 기존 PDF URL·다운로드·Drive 검증을 즉시 무효화한다. 비동기 늦은 응답도 무시한다.
- 이전에 승인된 비공개 bundle 인증서 및 public release certificate의 지위를 승계하지 않는다. 모든 응답에 `X-B66-Dev-Release: NOT_CERTIFIED`만 둔다.

## 접근 제한

`127.0.0.1` 전용 바인딩, 명시적 `--local-development`, 서버 실행 시 메모리에서 새로 발급되는 로컬 전용 난수 토큰, 브라우저 Origin/Host 검사, 엄격한 JSON 필드 제한/32KiB 요청/100품목/32MiB PDF 응답 상한, 개인정보·입력·토큰 로그 비활성화, `Cache-Control: no-store`, 다른 출처 CORS 허용 없음. 개발 서버를 프록시나 인터넷에 공개하지 않는다. Windows 시스템 글꼴 파일을 복사·배포하지 않는다.

최초 메인 앱 `/api/b66/quote/native-sol-pdf`와는 **연결하지 않았다**. 이 개발 도구는 로그인된 Saved Skill·릴리스 서비스 인증서를 발급할 수 없고, 온라인 사용자를 인증하지 않는다. 운영 환경에서 재사용 금지.

## 검증

```powershell
python -B -m pytest -q -p no:cacheprovider apps/b66-sol61-multipage/tests/test_native_dev_gateway_4117.py
$env:B66_SOL61_LOCAL_BROWSER = '1'
python -B -m pytest -q -p no:cacheprovider apps/b66-sol61-multipage/tests/test_native_dev_browser_4117.py
```

**실측 12 PASS:** Python HTTP 11개 + 실제 Playwright Chromium 1개. 1품목/4품목의 진짜 PDF 생성·PDF 파서 페이지 검사·PDF 해시, 실제 브라우저 iframe 표시, 다운로드 파일 검증, Drive용 복사 바이트 SHA, 편집 무효화, 원격 Origin/Host/토큰 차단 확인. 일회성 서버는 테스트 뒤 종료된다. 브라우저 실증은 설치된 Windows 브라우저가 있는 경우에만 환경변수로 실행; 기본 CI는 이 무거운 증명을 반복하지 않는다.

## 출시 전 남은 일

1. 인증된 Windows 실행/접근 경계를 가진 서버와 파디엠 인증 사용자 workspace/Saved Skill을 연결한다.
2. 공개 패키지에 대한 새 서비스 인증서를 실증·승인한다(기존 PRIVATE 역사적 인증서 상속 금지); 4품목 이상은 별도 v2 인증.
3. B66 고객 화면 iframe + 다운로드 + 실제 Google Drive `certifiedPdfBytes` 진입점을 같은 인증된 `B66SolPdfSnapshot`으로 전환하고 E2E 비교한다.
4. Production 배포와 Secrets 등은 별도 승인·운영 증거 전까지 실행하지 않는다. **#4117 OPEN / 고객 READY=HOLD.**
