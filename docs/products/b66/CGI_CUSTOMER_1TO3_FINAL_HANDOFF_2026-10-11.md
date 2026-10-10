# B66 CGI 1~3품목 견적서 — 최종 고객 인수인계 및 증거 패킷

**최신 기준: 2026-10-11 KST.** 첫 CGI 고객 1~3품목 MVP는 사용자 승인 [#4076](https://github.com/skerishKang/ai-revenue-lab/issues/4076) CLOSED. 이 문서가 과거 시점의 미완료 스냅샷보다 우선한다. 역사적 기록은 보존한다.

## 고객 전달 및 사용 안내

- **운영 사이트:** https://quick-quote-kr.pages.dev/ . 내부 QA 사이트 https://padiem-b66-cgi-qa.pages.dev/ 는 고객 운영 주소가 아니다.
- **로그인:** 고객 본인의 기존 비밀번호 계정을 사용한다. 자격증명, 계정 ID, 쿠키, 토큰, 고객정보와 비공개 로고/도장 내용은 공개 자료에 포함하지 않는다.
- **가능한 작업:** 지정된 승인 CGI Saved Quote Skill 및 회사정보 자동 확인 → 질문형 작성 또는 자유 문장 입력 → 단가 누락 시 질문 → QuoteCore 금액·VAT 계산 → 미리보기 및 A4 PDF 다운로드.
- **사용 범위:** CGI 원본 형태의 최대 **3개 품목, A4 한 페이지**. 4개 이상 다중 페이지 및 Sol-native 벡터 PDF는 이번 고객 인수 범위에서 제외된다. 현재 PDF는 이미지 기반이므로 원본의 선택 가능한 텍스트·벡터 구조 또는 PDF 파일 바이트 동일성을 보증하지 않는다.
- **기존 작성 중 견적 보호:** 운영 고객 계정의 실제 Guided D1 슬롯이 PRESENT로 확인됐다. ‘작성 중인 견적 이어하기’를 먼저 열어 내용을 확인한다. 임의의 새 작성, 저장 내용 초기화, 기존 초안 삭제는 하지 않는다. 직접 사용 시 견적서 완성 버튼 → 금액·항목 확인 → 미리보기 → PDF 다운로드 → 로그아웃한다. 외부 송부 전에 고객이 실제 금액과 서식을 최종 확인한다.
- **새 견적 시연:** 고객의 기존 초안 처리를 본인이 확인한 뒤 신규 작성한다. 기존 초안에 영향 없는 데모는 별도 QA 계정에서만 실행한다.

## 실제 검증 증거

| 절차 | 결과 | 신뢰 경계 |
|---|---|---|
| QA 브라우저 A: 로그인 → 질문형 시작 → 서버 D1 PUT/GET | PASS | 실제 분리된 Cloudflare QA D1 |
| QA 브라우저 A 로그아웃 → 독립 브라우저 B 로그인 → 중간 견적 복원·이어쓰기 | PASS | 재로그인·독립 쿠키·실제 D1 |
| 합성 견적: 배관 수량 2, 단가 10,000원, VAT 별도 | PASS | 실제 QuoteCore 총합 22,000원 |
| CGI 승인 원본 형태 미리보기 → A4 PDF 실다운로드 | PASS | 실제 QA 브라우저 다운로드 이벤트 |
| 제품이 발행한 실제 DELETE 후 작성 중 상태 읽기·지연 DB 조회 | PASS | QA D1 초안 0건, 다른 QA 준비자원 보존 |
| 운영 CGI의 자유 문장 전체 요청 → PDF | PASS | 보호된 운영 [#38069160662](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38069160662) |
| 운영 CGI의 누락 단가 추가 질문 → PDF | PASS | 보호된 운영 [#38069493985](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38069493985) |
| 운영 고객 계정 기존 초안: 두 브라우저 로그인·READ-ONLY 조회·복원 UI | PASS | 보호된 [#38077544407](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38077544407); 고객 쓰기/삭제 0건 |
| 운영 고객 계정 *기존* 초안 실제 끝까지 완성·PDF 다운로드 | **NOT_TESTED** | 고객 데이터 보존을 위해 수행하지 않음 |

QA 실제 서버는 별도 D1·R2·비공개 신원 서비스 및 테스트 계정을 사용하고, 승인 CGI Skill 1건·합성 회사 프로필 1건·인증된 원본 로고/도장 자산 2개를 연결했다. 마지막 재검증 후 D1 사용자 1, 작성 중 견적 0, Skill 1, 프로필 1, 자산 2. QA 비밀번호는 Windows 접근 제한 파일에만 저장하며 GitHub에는 보관하지 않는다. 임시 진단 로그 제거한 정상 B66 Worker에서도 전체 흐름을 재실행하여 PASS.

## CGI 원본 PDF 비교의 정확한 의미

- 승인된 공개 원본 PDF SHA 검증 PASS, 단일 페이지 595×841pt A4 PASS.
- 원본 30개 가변 입력 슬롯을 마스킹한 고정 부분의 평균 회색조 픽셀 오차 **0.074/255**, 회색조 차이 16 초과 픽셀 **0.021%** ([#38071689775](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38071689775)).
- 원본 PDF는 텍스트 **887자 추출**, 실제 브라우저 CGI PDF는 추출 가능한 텍스트 **0자**인 JPEG 래스터 PDF. 위 지표는 **가변 필드 완전 동일·벡터 동일·바이트 동일의 증명이 아니다.**
- 1~3품목 MVP의 브라우저 CGI 출력은 승인된 현재 계약을 유지. [#4117](https://github.com/skerishKang/ai-revenue-lab/issues/4117) 및 [#3839](https://github.com/skerishKang/ai-revenue-lab/issues/3839)의 Sol 4~100품목 다중 페이지 웹 연결은 오너 명령에 따라 **PARKED/POST-MVP**, 재개 승인 없이 확대하지 않는다.

## 인수인계와 GitHub 처리

- **#4076:** 승인된 1~3품목 MVP 완료/CLOSED; 새 광범위 CI·B14/B62/Engine 테스트 불필요.
- **#4229:** 운영 고객 기존 Guided 초안 PRESENT, READ-ONLY 2브라우저 접근/복원 PASS, QA 실제 D1 완주/PDF PASS. 단 **기존 고객 초안 실제 완료는 미검증**. 고객의 초안에 함부로 쓰거나 삭제하지 말고 OPEN 유지.
- #4229의 실제 남은 게이트는 **고객 본인 또는 명시적으로 승인된 운영 담당자가 보존된 기존 초안을 끝까지 완성하고, 실제 최종 PDF를 확인**하는 것이다. 기존 초안이 반드시 비워야 한다는 테스트 명목으로 삭제하지 않는다.
- 정상 출력 구조를 원본과 완전히 같은 텍스트/벡터 PDF로 바꾼다는 요구는 별도 개발·승인 대상이다. 이를 1~3품목 MVP의 이미 승인된 출시 기준으로 소급 적용하지 않는다.
- 최종 운영 상태: [#4229 증거 댓글](https://github.com/skerishKang/ai-revenue-lab/issues/4229#issuecomment-6101030900) 및 최신 [Production GET-only 검증](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38077544407). 고객정보/시크릿은 기록하지 않는다.

**최종 판정: 1~3품목 MVP 기능 PASS, 독립 QA 실제 D1 질문형 E2E PASS, 운영 고객 기존 초안 보존·복원 PASS, 운영 고객 기존 초안 완주 NOT_TESTED, 원본 Sol PDF 구조적 동일성 NOT_CLAIMED.**
