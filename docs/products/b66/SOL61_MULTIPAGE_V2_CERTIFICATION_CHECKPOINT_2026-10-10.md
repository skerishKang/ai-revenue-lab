# Sol 6.1 CGI 다중 페이지 v2 — 기술 인증 증거 및 활성화 경계

> **2026-10-10 KST, CENTRAL independently audited checkpoint.** 이 문서는 기존 v1 인증서를 바꾸거나 새 v2 인증 상태를 임의로 활성화하는 파일이 아니다. 원본 Sol 기반 다중 페이지 후보의 기술 검증과 별도 **신규 인증 버전 발급 전 조건**을 구분한다. 관련 [#3839](https://github.com/skerishKang/ai-revenue-lab/issues/3839) · [고객 인수 #4076](https://github.com/skerishKang/ai-revenue-lab/issues/4076).

```text
CERTIFICATION_PACKET_VERSION=2_CANDIDATE
SOURCE_INTEGRATION_PR=#4111_SQUASH_MERGED
SOURCE_MAIN_SHA=66a34b5796e48bd16959a31e5be98cbcbd6cdbbd
SOURCE_HEAD_SHA=95fe85c7be6165ea5364f3e83227a7cc820ac7a1
ADOPTED_LOCAL1_SOURCE_SHA=fc272e9bdd36f3a5be4f9390a60300fbf2e5ec19
SOURCE_LINEAGE=#4001_PLUS_#4092
EXCLUDED_STYLE_VARIANT=#4010_CLOSED_UNMERGED
TECHNICAL_OFFLINE_PDF_EVIDENCE=PASS
OWNER_FINAL_CUSTOMER_LAYOUT_AND_DEVIATION_ACCEPTANCE=PENDING
VERSIONED_V2_RELEASE_CERTIFICATE=NOT_ISSUED
CURRENT_V1_CERTIFICATE=UNCHANGED
RUNTIME_ROUTE_V2_ACTIVATION=NO
PRODUCTION_DEPLOY=NO
FIRST_CUSTOMER_END_TO_END_ACCEPTANCE=#4076_OPEN
```

## P0 최신 발견 — 고객 화면은 아직 실제 native Sol PDF 미리보기가 아님

**2026-10-10 KST CENTRAL 소스 검수 / [수정 이슈 #4117](https://github.com/skerishKang/ai-revenue-lab/issues/4117)**

이 문서는 Sol 다중 페이지 **오프라인 실제 PDF**의 소스·기하·SHA 증거다. **현재 고객 B66 화면이 해당 PDF를 그대로 미리보기/다운로드/Drive에 사용한다는 증거가 아니다.** Owner 요청에 따라 이 구분을 제품 출시의 **P0 전제조건**으로 상향한다.

- 현재 `quote-template-renderer.js`의 CGI 화면은 인증 원본 PDF에서 파생된 고정 private PNG 위에 **별도 CSS/DOM 문자열**을 얹어 보여준다. `quote-browser-pdf.js`는 동일 draw-ops를 Canvas → JPEG **이미지 PDF**로 다시 만든다. CGI 4+품목은 기존 draw-ops의 행수 제한으로 거부되고 미리보기에는 별도 HTML CGI 레이아웃이 표시될 수 있다.
- 현재 `app.js`/ `padiem-account.js`는 CGI PDF 다운로드와 Drive PDF 저장에 **브라우저 래스터 PDF 경로를 우선 사용**한다. `apps/padiem-chat/app/b66_certified_pdf_routes.py`의 다른 PDF Worker도 별도 1페이지 overlay 계약이며 다중 페이지 Sol CLI 엔진과 연결되지 않았다.
- **정정:** 원본 Sol PDF의 PNG를 *배경 이미지로 사용*한다는 사실 ≠ 최신 Sol 렌더러가 만든 **동일 결과 PDF를 보여준다**는 뜻. 이 문서의 4/8/25/100 PDF 해시는 실제 CLI 출력으로 유효하지만 고객 화면/다운로드/Drive 해시라고 주장할 수 없다.
- **필수 구조:** 승인된 CGI Saved Skill + QuoteDraft/QuoteCore → **하나의 인증 Sol 6.1 native PDF renderer** → **같은 PDF 바이트 스냅샷** → 화면 미리보기 / 고객 다운로드 / 고객 동의 Drive 저장. PDF 화면 표시를 위해 실제 PDF를 래스터화해도 되지만 PDF 자체를 브라우저 DOM/Canvas로 **독립 재구성 금지**. 해시·페이지 수·금액과 단일 계정/버전/템플릿 fingerprint 검증, 변경·계정 전환 시 오래된 미리보기 캐시 폐기.
- **미해결 런타임 과제:** Windows 전용 폰트/Node와 Python 렌더러를 고객 서비스에서 안전·합법·결정적으로 구동할 실제 배포 런타임을 검증해야 한다. 이전 별도 Modal standby [#3736](https://github.com/skerishKang/ai-revenue-lab/issues/3736)을 임의 활성화/과금/Secrets 변경 금지. **고객 v2 인증서 발급·4+ 운영 활성화는 #4117의 실제 PDF 일원화와 클라우드 런타임 계약 검증 전까지 HOLD**.

```text
NATIVE_SOL_OFFLINE_REAL_PDF=PASS
CURRENT_CGI_ONSCREEN_PDF_SHA_EQUALS_SOL=NOT_PROVEN
CURRENT_CGI_DOWNLOAD_USES_SOL_NATIVE_BYTES=NO
CURRENT_CGI_DRIVE_USES_SOL_NATIVE_BYTES=NO
LIVE_4PLUS_NATIVE_SOL_RENDERING=NO
P0_BLOCKER=#4117_OPEN
V2_CUSTOMER_RELEASE_CERTIFICATE=HOLD
```

## 1. Source·브랜치·승인된 디자인

- [최신 main 통합 PR #4111](https://github.com/skerishKang/ai-revenue-lab/pull/4111) **MERGED** `66a34b5796e48bd16959a31e5be98cbcbd6cdbbd`, reviewed head `95fe85c7be6165ea5364f3e83227a7cc820ac7a1`.
- 최초 [Draft #4001](https://github.com/skerishKang/ai-revenue-lab/pull/4001)은 **오른쪽 외곽선의 네 구간 연결·페이지 소계 영역 경계 수정**. 이후 [Draft #4092](https://github.com/skerishKang/ai-revenue-lab/pull/4092)는 **마지막 품목 아래 끊기는 내부 세로선·최종 합계 밴드 열선 침범 제거**. 두 수정은 #4092 head에서 연속 구현돼 있으며 최신 main의 `apps/b66-sol61-multipage/**` + 기존 CI 한 워크플로에 10파일로 반영.
- [#4010](https://github.com/skerishKang/ai-revenue-lab/pull/4010)은 왼쪽 정렬을 개선하지만 원본 굵은 상단 이중 프레임을 얇은 단일 선으로 바꾸므로 **고객 원본 스타일 우선 원칙으로 제외**. 세 과거 Draft는 통합/정리 단계에서 **CLOSED, UNMERGED**, 브랜치와 이미지 증거는 보존했다.
- 기존 공개 `reference/b66-public-standard-templates/cgi/v1/**` **변경 파일 0**, 원본 18개와 `PUBLIC_RELEASE_MANIFEST.json`·`sol61/certificate.json` 불변. **1~3품목은 기존 인증 Sol v1 바이트 그대로**. 4품목 이상은 같은 Sol 소스 `program.zlib`와 원본 리소스를 사용하고 외부 PDF/HTML/GLM fallback 없음.

## 2. 검증 단계별 구분

| 게이트 | 결과 | 검증 근거 |
|---|---|---|
| 최신 main 충돌 없는 소스 통합 | **PASS** | #4111 exact-head 검수 및 squash merge |
| 보호 대상 원본 18개+공개 manifest | **PASS** | 코드 변경 0; B66 Public Standard Template Contract CI PASS |
| GitHub exact-head | **PASS** | 4 workflows SUCCESS, 7 check SUCCESS + 16 정상 SKIPPED, 0 FAILURE |
| CENTRAL Windows 집중 기하·원본 계약 | **PASS** | `python -B`, 63 passed / 6 환경 skip / 5 deselected |
| CENTRAL Windows **실제 PDF 생성** 집약검사 | **PASS** | 19 passed / 22 deselected. v1 1~3 바이트 동일, 4/8/25/100 합계/외곽선·로고·도장·PDF 출력을 검증 |
| LOCAL1 수정 전후 실물 이미지 | **PASS (검토 표본)** | CENTRAL은 로컬 `E:\b66-3839-evidence-261010\images\`의 72/144dpi 대표 이미지에서 #4092 두 시각 결함 해소 직접 확인 |
| 4+ 산출물 새 main 재생성·SHA·페이지/행 개수 | **PASS** | 아래 7건, 독립 EVIDENCE.json 및 실제 PDF 로컬 보관 |
| **새 v2 인증 ID/불변 bundle 및 제품 적용 계약** | **아직 미완료** | 현 소스는 내부 `rendererId=b66.sol61.native-multipage.render.v1`, `templateId=cgi-220621-source-vector-v1`을 보고. 이는 원본 Sol 소스에서의 다중 페이지 **첫 버전 renderer** 식별자이며, 승인된 새 **v2 release certificate**가 존재한다는 뜻이 아님 |
| 고객/Owner 전체 양식 허용 오차 최종 서명 | **미완료** | 수정 전 원본에 없는 다중 페이지 구분/여백·마지막 페이지 합계 처리·폰트 재서브셋 등의 일치성 차이에 대한 신규 버전 수용 판단 필요 |
| B66 실제 계정 Saved Skill→QuoteCore→Sol PDF→D1 실운영 | **미완료** | #4076 |
| 새 Production 배포·고객 v2 선택 | **미실시** | Owner 승인된 기존 Pages Production SHA와 별개 |

**절대 혼동 금지:** `SOURCE_MERGED` / `TEST_PASS` / `PDF_HASH_MATCH` / `VERSIONED_CERTIFICATE_ISSUED` / `LIVE_ROUTING_ACTIVE` / `CUSTOMER_ACCEPTED`는 모두 서로 다른 상태다.

## 3. 독립 실제 PDF 매니페스트 — synthetic sample only

새 통합 렌더러를 사용하여 로컬에서 **1/2/3/4/8/25/100품목**을 실제 PDF로 생성하고 PDF SHA와 렌더러 결과 JSON을 대조했다. 4+행 페이지 계획의 행수 합 = 입력 행수 확인. 로컬 파일과 매니페스트는 증거 폴더에서 별도 보존하며 고객 자료·폰트를 Git에 넣지 않는다.

| 품목 | A4 페이지 | 총액(KRW) | PDF SHA-256 |
|---:|---:|---:|---|
| 1 | 1 | 150,700 | `5b90ca47ba11b7c9077ab70c49329b4be83b3c82c7106a5ad9c25fdf43b610f6` |
| 2 | 1 | 472,201 | `5ee5159093e5cd0b60b5a36a96afbe3d1853d610826e46fc58b7e9dd9a0ffec8` |
| 3 | 1 | 984,606 | `2f3613b119beb679fe229745b07405c25e3bf623b44cd90e9668f0796906d08b` |
| 4 | 2 | 1,708,014 | `1c96031cece462a8282df1c06e98c2e752612e2c05af353b1ca670cda2aaf248` |
| 8 | 2 | 3,948,655 | `6516ae4f83ee3a83c74c85ec03cd3de11a6d4800c389ef56c1e9054b5c5c9914` |
| 25 | 4 | 20,850,665 | `ff543efe2320ff513ecabc983623b26a704240567e7fe306b87d80a3f10e383a` |
| 100 | 11 | 196,473,035 | `f314fa9a290c89687878da561a45410164676b2bea47cb50e4f47b3024316232` |

Evidence local: `E:\b66-3839-v2-cert-evidence-261010\`, synthetic PDF 7건, `rows-N.json` 7건, `EVIDENCE.json` SHA256 `661f35f3192139f5421e5eb00dcb122d304d2360e22da216c00ce889ab518038`. 중복 PDF를 Git/Drive에 업로드하거나 새 CI lane을 만들지 않는다.

입증된 원본 SHA:
```text
SOL_MULTIPAGE_RENDERER_PY=8a236cd4ddd214eb7890dae692d5179b07f963490d126be60f28ec0003d29d67
QUOTCORE_ADAPTER_SLOTS_CJS=bb490106e8d11cabadf3e9f68b480ed2d2441f2d46607c5cd303bf5f78cbd646
ORIGINAL_PUBLIC_MANIFEST=2a7b874bb19ad16b0856ec0baab7c89beeab500628f87f0c874fffc852f2e7c6
ORIGINAL_SOL_PROGRAM=92734d4e0dc0febe53af5b81c89058eac46e5ee66d8f568b4cf58a3e44c887e9
ORIGINAL_RESOURCES_PDF=0bc1197cc2d424606e824d15288b9bc16c2d8bfb5755b314cd02f7b0edeb4b87
```

## 4. 승인·인증에서 허용 오차로 확정할 항목

이것은 **승인 요청 후보 목록**이지 승인됐다는 기록이 아니다.

1. **1~3품목:** 기존 v1 PDF 바이트 인증은 한 글자도 약화할 수 없음.
2. **4+품목:** 원본과 같은 상단 헤더·굵은 이중 프레임·도장·로고·결제계좌·색상·표 열 구성을 유지하되 **행이 늘어나 A4 페이지가 갈라지는 변경**은 필연적. 각 페이지의 머리말/푸터와 최종 페이지 합계만 표시하는 구조를 수용할지 명시.
3. **기존 원본 '이하여백' 표기:** 다중 페이지 영역에서는 생략하는 것으로 구현되어 있으므로 고객/Owner가 허용할지 결정.
4. **폰트 재서브셋:** 재생성된 합계/행 문자는 폰트 부분집합이 달라 일부 픽셀까지 100% 동일하지 않을 수 있음. 데이터 누락/변경이나 잘림/겹침/합계 불일치는 불허.
5. **원래 첫 페이지의 빈 가로 안내선:** 원본 스타일의 일부로 남아 있음. #4092의 내부 세로선 결함과 구분해 원본 보존인지 더 다듬을지 고객이 선택.
6. **품목 수 범위:** 본 실증은 4/8/25/100, 기존 LOCAL1 101/125/500 스트레스 증거는 제품 intake 한도 확대 승인이 아님. 입력 상한·아주 긴 개별 행의 페이지 내 배치 등 미검증 사례는 출시 범위에서 별도 제약.

신규 v2 버전 인증서는 승인된 설계 편차를 `CERTIFIED_WITH_TOLERANCE`의 명시적 허용 목록에 넣거나, 모두 중요 요소 불변으로 증명돼야 `CERTIFIED`로 발급한다. **이 문서를 신규 인증서로 가장해 우회하지 않는다.**

## 5. 다음 실제 실행 단계 (중복 테스트 최소)

1. **Owner 최종 v2 레이아웃 승인:** 위 6항목과 실제 수정 전/후 대표 페이지에 대한 동의 또는 제한 범위 결정. #4010은 별도 스타일 변경으로 이미 제외.
2. **별도 버전 신규 v2 인증서/식별자 발행:** Sol v1 package 18개 보호; 원본 보존형 다중 페이지 엔진·QuoteCore·렌더러 SHA·원본 SHA·인수 범위·허용 오차/참조 이미지·독립 재생성 증거를 연결. v1 원본 `certificate.json` 덮어쓰기 금지. 제품 runtime은 인증서/버전·지원 범위가 맞지 않으면 4+ 출력 활성화 **fail-closed**.
3. **#4076 실제 계정 E2E:** 김범신 대표 승인 Saved Quote Skill→Guided/Free-form→QuoteCore→**새 인증 Sol PDF의 실제 바이트**→D1 저장/재열기/타계정 차단을 운영에서 검증. 기존 #4088 오프라인 모의 PDF·모의 D1은 이 증거를 대체하지 않는다.
4. **운영 배포:** 필요할 경우 최신 exact-main과 변경 파일/CI 확인 후 **별도의 Owner 승인**으로 한 번 배포. 이 문서 승인·코드 병합 자체로 자동 Production dispatch 금지.

결론: **실제 다중 페이지 PDF 기술 증거 PASS, 신규 v2 release certificate 및 고객 인수는 아직 미완료**. #3839와 #4076은 계속 OPEN.
