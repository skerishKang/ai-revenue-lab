# B66 CGI #4117 — Sol native PDF 단일 스냅샷 클라이언트 계약

**2026-10-10 KST / 상태: FRONTEND LIBRARY CANDIDATE, NOT ACTIVATED**

현 CGI 브라우저 미리보기는 원본 PDF에서 추출한 PNG+DOM 텍스트이고, PDF 다운로드/Drive 저장은 Canvas/JPEG 래스터 경로다. 이는 병합된 원본 Sol 6.1 다중 페이지 PDF가 아니므로 [#4117](https://github.com/skerishKang/ai-revenue-lab/issues/4117) P0의 완성 상태가 아니다.

## 개발 완료된 최초 단위

- `reference/business-66-padiem-quote-v1/quote-sol-pdf-snapshot.js`: **서버가 실제 native Sol 6.1 PDF를 반환할 때만** 인증된 한 벌의 PDF 바이트를 로컬 메모리에 보관하고, `previewUrl()`(실제 PDF Blob URL), `copyBytes()`(고객 PDF 다운로드 및 고객 선택 Drive 저장)를 같은 SHA로 제공하는 재사용 가능 모듈.
- 계정 세션 epoch, 실제 Saved Skill ID, Skill/템플릿 fingerprint, 승인된 인증서 SHA, QuoteCore 파생 모델 전체를 캐시 키로 사용. 견적 수정·계정 변경·로그아웃에서 `invalidate()` 호출 시 blob URL 폐기 및 이전 비동기 응답/다운로드 거부.
- 동일 스냅샷의 동시 요청은 단일 호출로 합치고, 응답에서 PDF 헤더·크기·페이지 수·PDF SHA256·인증서·렌더러/Skill/Template 출처 정보 검증. **브라우저 Canvas PDF, 미인증 범용 Worker, 가짜 HTML/PDF 응답 거부**.
- `tests/quote-sol-pdf-snapshot.test.cjs`: Node 네트워크 없는 계약 테스트. 더미 `%PDF`는 **실제 원본 Sol 파일 인증 증명으로 취급하지 않는다**.
- 기존 [B66 PDF Preview Parity CI](https://github.com/skerishKang/ai-revenue-lab/blob/main/.github/workflows/b66-pdf-preview-parity.yml)의 기존 static-test 단계에 추가하므로 신규 CI workflow·job 없음.

## native PDF 원본 서버가 제공해야 할 계약 (아직 미구현)

서버가 사용자 세션과 워크스페이스, 승인 CGI Saved Skill, Skill fingerprint·템플릿 fingerprint, 모델 `derivedBy=quote-core` 및 확정 값을 **서버에서 재확인한 후** 원본 Sol Python 렌더러(1~3 v1 / 4+ 별도 인증 v2)로 **한 개 PDF 바이트 결과**를 생성해야 한다.

응답은 HTTP 200, `application/pdf`, PDF 바이트와 다음 **신뢰 가능한 first-party 응답 헤더**를 반환해야 한다.

| 헤더 | 필수 검증 |
|---|---|
| `X-B66-Sol-Renderer` | 정확히 `sol61-native` |
| `X-B66-Sol-Certificate-Sha256` | 사전에 사용자 소유 승인 Skill에 연결된 버전별 인증서 SHA와 동일 |
| `X-B66-Sol-Pdf-Sha256` | 실제 반환 PDF bytes SHA256 동일 |
| `X-B66-Sol-Profile-Fingerprint` | 승인된 internalTemplate fingerprint 동일 |
| `X-B66-Sol-Skill-Fingerprint` | 현재 승인된 Skill fingerprint 동일 |
| `X-B66-Sol-Page-Count` | 실제 PDF 페이지 수와 일치하는 1~100 정수 |

헤더는 **브라우저가 보내는 인증 권위가 아니다.** 서버는 비공개 인증 번들·버전·사용자 권한·템플릿 동일성·QuoteCore 계산을 독립 검증해야 한다. 클라이언트가 제공하는 `accountEpoch`는 **오직 브라우저 메모리 캐시 경계**이고 서버의 사용자 식별이나 권한 검증을 대체하지 않는다.

### 아직 미구현 / 이 파일만으로 완료 선언 금지

1. 서버에서 Sol Python + Node + 허용된 폰트/원본 번들을 안정적으로 구동하는 **인증된 실행기**. 기존 Cloudflare 1페이지 overlay Worker나 PARKED Modal #3736을 임의로 대체/활성화하지 않는다.
2. Saved Skill의 새 native Sol 버전별 인증서 및 클라이언트로 전달되는 서버 권한 프로젝션. 원본 공개 Sol v1 18개와 1~3 byte identity 그대로.
3. `padiem-account.js` 실제 인증된 서버 요청 → 이 모듈 `read()`에 연결, `app.js` 화면 내 PDF viewer, 다운로드, Drive JSON/PDF에서 **같은 snapshot**을 사용하도록 전환.
4. 실제 1/2/3/4/8/25/100 품목 브라우저·서버·폰 실제 PDF 및 해시 동일성, 타 계정 격리, session 반전·오래된 응답 거부, 별도 Owner 승인 이후 운영 배포.

**지금 이 모듈은 앱/Worker에서 호출되지 않는다.** 기존 고객 동작은 유지하며 #4117는 OPEN. 이 PR 완료를 실제 Sol 출력 UX가 완성됐다고 주장하지 않는다.
