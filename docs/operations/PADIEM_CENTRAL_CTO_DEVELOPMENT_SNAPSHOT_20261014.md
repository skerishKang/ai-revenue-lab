# PADIEM AI CENTRAL CTO — 개발·이슈·배포 분리 스냅샷 (2026-10-14 KST)

```text
DOC_STATUS = EVIDENCE_SNAPSHOT
OWNER = PADIEM AI CENTRAL CTO
SCOPE = 2026-10-14 개발 인수인계 / B66·Core·Claw SSE / 공개 기술 정보만
BASE_MAIN_SHA = b6d767d01cf6a5bf75e6a9957900f33f1aa3ca08
PRODUCTION_MUTATION_FROM_THIS_DOCUMENT = 0
```

> **권위 주의:** 이 문서는 해당 시점의 공개 기술 증거를 정리한 **날짜별 기록**입니다. 이슈/PR의 후속 댓글, 현재 `main`, 정확한 운영 배포/GET readback이 변동 사실의 최신 권위입니다. 이 문서는 새로운 사업방침·요금/유료 검색 허가·사용자 동의·운영 배포 승인·모델 실행 승인이 아닙니다. 비공개 회사 Governance 원문은 GitHub에 복제하지 않습니다. 의사결정 순서는 [AGENTS.md](../../AGENTS.md)와 [문서 권위 모델](../governance/DOCUMENTATION_AUTHORITY_MODEL.md)을 따릅니다.

## 1. 한눈에 보는 결과와 검증 수준

| 레인 / 이슈 | PR·정확한 증거 | 2026-10-14 확인 상태 | 남은 검증 또는 다음 실행 |
| --- | --- | --- | --- |
| LOCAL5 / [#4379](https://github.com/skerishKang/ai-revenue-lab/issues/4379) | [#4656](https://github.com/skerishKang/ai-revenue-lab/pull/4656) → `d15036a084ebee3f3d0de0caee537e080c8247c3` | **MERGED**; 11 신규 + 16 기존 집중 회귀 = 27 PASS, 공급자 호출 0 | LOCAL5 범위 종료. 여러 제품의 잔여 모델 용량/자원 경계 때문에 #4379는 OPEN |
| COMP2 LANE A / [#4465](https://github.com/skerishKang/ai-revenue-lab/issues/4465), [#4468](https://github.com/skerishKang/ai-revenue-lab/issues/4468) | [#4659](https://github.com/skerishKang/ai-revenue-lab/pull/4659), HEAD `79f2ab3e0552e810bebd33a743574df655062777` → `26ff5aea6a5bc1bbad4f8102955b471ecbca6ad1` | **MERGED**; Core 2,074 PASS (COMP2 보고), exact-head CI/GitGuardian 실패 0 | Engine/P01/Claw Core 실제 디스패치의 서버 KST 사전지침 1회 구성 소스 확보. 제품별 실운영 배포·실사용 증거와 혼동 금지 |
| COMP2 LANE B / [#4469](https://github.com/skerishKang/ai-revenue-lab/issues/4469) | [#4509](https://github.com/skerishKang/ai-revenue-lab/pull/4509), HEAD `d8c0bbb4324de0d332105d7e62bdba6bf2c0191c` → `b6d767d01cf6a5bf75e6a9957900f33f1aa3ca08` | **MERGED**; 오프라인 42 PASS (COMP2 보고), exact-head 체크 36개 실패 0, GitGuardian SUCCESS | B66 공개 사실 검색 경로는 서버 승인 **기본 OFF**. 실제 TinyFish/Daum 호출, 비용 승인, Production B66 인증 E2E는 별도 HOLD |
| 공통 STT / [#4643](https://github.com/skerishKang/ai-revenue-lab/issues/4643) | [#4660](https://github.com/skerishKang/ai-revenue-lab/pull/4660) → `942dfb2c035a5966f4ff3ed2f7ec661aa9038787` | **MERGED**; 256KiB 스트림 읽기 보호·활성화 엄격 비교, 제품 통합 아님 | 기능 기본 OFF, 유료 공급자 권한·바인딩·운영 마이크 연결은 별도 |
| COMP2 LANE C / [#4655](https://github.com/skerishKang/ai-revenue-lab/issues/4655), [#4657](https://github.com/skerishKang/ai-revenue-lab/issues/4657) | [#4661](https://github.com/skerishKang/ai-revenue-lab/pull/4661), HEAD `2034ff993537392f375fd7bbc5df35fe7d8eecde` | **DRAFT / NOT MERGEABLE BY CENTRAL ACCEPTANCE**. GitHub 기계적 mergeable/CI success와 보안 수용은 구분 | 아래 §2 제품 경계 보완 및 UI 연결 필요 |
| LOCAL4 B66 견적 AI / [#4466](https://github.com/skerishKang/ai-revenue-lab/issues/4466), [#4412](https://github.com/skerishKang/ai-revenue-lab/issues/4412) | [#4658](https://github.com/skerishKang/ai-revenue-lab/pull/4658), HEAD `85e8ea842081636b5af10348e3d95c3de41dff63` | **DRAFT / CHANGES REQUESTED**. 기존 exact-head CI/GitGuardian success는 결함 해소 증명이 아님 | 아래 §3 사실 무단변경·원자적 revision·빈 taxMode 수정, LOCAL4 재검증 |
| Claw 실제 SSE / [#3936](https://github.com/skerishKang/ai-revenue-lab/issues/3936), [#4318](https://github.com/skerishKang/ai-revenue-lab/issues/4318) | 운영 SSE 활성화 [#38472381060](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38472381060), GET-only [#38472621423](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38472621423) | **활성화 GET 당시 TRUE 증명 / 사용자 SSE 전송 순서 최종 수용 미완료** | 아래 §4 로컬 가상 캡처 검증. 추가 실모델 POST는 아직 허가되지 않음 |

**독립적인 사실 층위:** `SOURCE_MERGED` ≠ `CI_PASS` ≠ `WORKER_DEPLOYED` ≠ `ACTUAL_PROVIDER_USED` ≠ `AUTHENTICATED_E2E_ACCEPTED`. 단순 Cloudflare Pages 프리뷰 성공도 Chat/Claw/B66 운영 경로 배포 증거가 아닙니다.

## 2. COMP2 #4661 — B66 안전 Markdown + 대화 저장

- **Markdown (#4655):** 신규 `reference/business-66-padiem-quote-v1/b66-safe-markdown.js`는 `**굵게**`, 목록/문단을 안전한 DOM 노드와 텍스트 노드로 표현하고 불일치 구문을 원문 보존합니다. 오프라인 DOM 테스트 통과. **`easy-mode.js` 실제 말풍선에는 아직 미연결**이므로 사용자 화면 수정 완료/운영 반영으로 기록하지 않습니다.
- **대화 저장 (#4657):** 신규 `apps/padiem-chat/app/b66_conversation_store.py`가 기존 `HistoryStore`를 감싸고 소유자 확인을 시도하지만 **사용자 스코프만** 확인합니다. 현재 main `history.py`의 `list_conversations`/ `search_conversations`는 `user_id`로 검색, `get_conversation`/ `delete_conversation`는 `id + user_id`만 검사합니다. **동일 계정의 Chat·Claw·B66 제품 기록이 서로 노출·삭제될 수 있는 위험**이 있어 CENTRAL이 Ready·병합 차단했습니다.
- `project_id`만 설정하거나 B66 화면에서 결과를 사후 필터링하는 것으로는 충분하지 않습니다. 일반 Chat `/api/conversations` API가 같은 사용자의 B66 대화를 역방향으로 접근할 수 있고 페이지네이션/검색도 누락될 수 있습니다.
- **필수 수리:** 서버 유래/위조 불가 제품 구분자를 기존 canonical D1/R2 데이터 접근 경계에서 일관되게 강제. B66↔Chat/Claw의 양방향 목록·검색·상세·삭제·이어쓰기·추가 입력 차단, 사용자 A/B 교차 접근 차단, 신원 전환 시 구요청 반영 차단, 중복/재시도·R2 원문 누락 때 모델 선호출 없음·명시적 오류 검증.
- 기존 `get_conversation_model_context`의 원문/R2 복원 계약을 재사용하며, `get_conversation`의 8,000자 미리보기를 모델의 과거 원문으로 속이지 않습니다. **새 별도 DB 생성 금지**; 제품 식별용 최소 스키마 보강이 실제로 필요하면 소스·D1 마이그레이션/출고 보호를 별도 증명합니다.
- 중앙 검토 근거: [첫 번째 차단 댓글](https://github.com/skerishKang/ai-revenue-lab/pull/4661#issuecomment-6156896776), [실제 HistoryStore SQL 확인](https://github.com/skerishKang/ai-revenue-lab/pull/4661#issuecomment-6157025814).
- 파일 소유권: COMP2가 **기존 #4661을 보완**합니다. #4509는 이미 병합되어 해당 파일 소유권이 풀렸지만 #3763 오래된 음성 PR은 무조건 병합하지 않습니다. 첫 화면/브랜드 버튼, 별도 「이전 AI 대화」 목록·검색·재개, 기존 「최근 견적」 분리는 새 기준 main에서 순차 통합합니다. 새로운 전제품 공유 기억은 [#4654](https://github.com/skerishKang/ai-revenue-lab/issues/4654) 미래 설계로 남깁니다.

## 3. LOCAL4 #4658 — 자연스러운 견적 대화 / QuoteCore 인계

이 PR은 모델이 분류한 intent를 서버 상태 전이에서 검증하고, 실제 계산/저장 권한을 기존 QuoteCore 및 명시적 사용자 확인에 남기려는 독립 범위입니다. 새로운 `migrations/041_b66_ai_conversation.sql`은 **대화의 의미·견적 사실·revision을 저장하는 서버 상태 슬롯**으로서 §2의 Chat/Claw 장기 메시지 HistoryStore와 용도가 다릅니다. 별도 스키마가 소스 PR에 포함됐다는 사실은 **운영 D1 적용**을 의미하지 않습니다.

CENTRAL의 기존 [#4658 정확한 HEAD 검토](https://github.com/skerishKang/ai-revenue-lab/pull/4658#issuecomment-6156926725)에서 다음 결함이 확인되어 Draft 유지:

1. **P0-A — 일반 대화 모드에서 보존된 견적 사실 무단 덮어쓰기:** `apply_message_transition`이 quote 모드 밖에서 모델 delta를 합치는 경우가 있습니다. 견적 모드 종료 후 기존 수량 100을 일반 모델 답변의 500으로 바꾸지 못해야 하며, 일반 메시지의 새 품목도 견적 상태에 자동 쓰기하면 안 됩니다. 재진입 시 충돌은 명시적 확인 또는 거부.
2. **P0-B — D1 동시 요청의 revision 경쟁:** 현재 unconditional UPSERT와 load→모델→save 사이의 경쟁으로 두 요청이 동일한 과거 revision을 읽고 둘 다 성공할 수 있습니다. 단일 SQL 원자적 compare-and-swap/영향 행 확인으로 하나만 성공, 다른 하나는 유한한 `409 revision_conflict`; 실제 SQLite-D1 어댑터 경쟁 회귀 필요.
3. **P1 — 모델 delta의 빈 `taxMode: ""`**는 새 승인된 과세 방식이 아니라 미지정입니다. 기존 값 삭제나 승인된 변경처럼 취급하지 않도록 검사.

**LOCAL4가 같은 Draft PR에서 수정**, 최신 main으로 충돌 없이 동기화·focused + 실제 D1 race 테스트·exact-head CI/GitGuardian 재확인 뒤 CENTRAL이 병합 판단. 이미 한 시정사항이나 테스트는 재개발하지 않습니다. QuoteCore 계산·견적 저장·PDF 서명·CGI 템플릿 권한을 우회하지 않습니다.

## 4. Claw P01 SSE #3936 — 로그인 완료와 원본 이벤트 증명의 차이

**이미 입증된 별개 사실**

- 보호된 B62 운영 코드 배포 [#38470802422](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38470802422) SUCCESS (당시 승인된 코드 `d2fdd148f0d3d699c06002cd0194ce1832c70213`).
- 별도의 SSE 운영 활성화 [#38472381060](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38472381060) SUCCESS, 이후 독립 GET-only [#38472621423](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38472621423)에서 **SSE flag TRUE**. 이후 main에 병합된 변경을 자동 운영 배포된 것으로 주장하지 않습니다.
- 예전 인증된 Claw QA 세션에서 `POST /api/claw/general` 1회, `200 text/event-stream`, UI 모델 응답, 새로고침 후 사용자/AI 2개 메시지 및 `completed` 실행 기록이 관찰됐습니다. **공급자 측 실제 물리 POST 횟수는 UNKNOWN**이며, 성공 기록이 이벤트 프레임 순서/terminal 횟수 증거는 아닙니다.
- 이후 GET-only 사전확인 3건 `200`: 로그인 `signed_in`, live SSE capability `true`, 지정 모델 `google/gemini-3.5-flash-lite` selectable. BSK의 GET 진단은 정상 캡처됐지만 **실제 스트리밍 본문 보존을 증명하지 못했습니다**.

```text
CAPTURE_READY = BLOCKED
PRIOR_LIVE_SSE_FRAMES = UNAVAILABLE_FROM_PRIOR_RUN
P01_EVENT_ORDER = NOT_PROVEN
TERMINAL_EXACTLY_ONCE = NOT_PROVEN
SSE_DONE_FRAME_COUNT = NOT_PROVEN
APPROVAL_DENY_CANCEL = NOT_TESTED
STATUS_ONLY_RECONNECT = NOT_TESTED
ADDITIONAL_MODEL_POST_IN_GET_ONLY_PREFLIGHT = 0
PRODUCTION_MUTATION_IN_GET_ONLY_PREFLIGHT = 0
ISSUE_3936 = OPEN
```

**다음 실행 소유자: LOCAL1 (Claw/Engine/P01).** Desktop Commander `Padiem-Command-Center` 원격 장치가 CENTRAL 조회 당시 **Offline**이라 LOCAL1 자체 Windows 환경으로 전환했습니다. GitHub [LOCAL1 지시](https://github.com/skerishKang/ai-revenue-lab/issues/3936#issuecomment-6156967765)는 완료 명령이 아니라 **작업 배정**이며, LOCAL1의 실제 가상 스트림 테스트 결과는 아직 확인되지 않았습니다.

1. 모델/공급자 0회 호출인 **로컬 가상 SSE fixture**를 사용합니다. 실제 브라우저 `fetch`와 동등한 전송에서 두 개 이상 순서가 있는 P01 스타일 이벤트와 terminal 1회, `done` 1회를 생성합니다.
2. DevTools Preserve log / EventStream 또는 적절한 CDP·Playwright 스트림 레코더가 **응답 body의 event/data 원본, 순서, terminal count를 종료 후에도 보존하는지** 검증합니다. metadata/기존 D1 `completed`만 저장한 BSK 진단은 부적격입니다.
3. 가상 테스트가 입증되면 `CAPTURE_READY=PASS_FOR_RECORDER_FIXTURE`로 보고하고 **중지**합니다. 입증 실패 시 `CAPTURE_READY=BLOCKED`로 이유를 보고합니다. 실제 실사용 SSE 검증 PASS를 선언하지 않습니다.
4. 가상 캡처 준비 **이후에만**, 실모델 무해한 요청 **정확히 1회**에 대한 별도 대표 승인을 요청합니다. 기존 1회 승인은 소비됐습니다. 반복 POST·타 모델 대체·재연결용 재실행·승인/거부/취소 부수효과 테스트를 지금 수행하지 않습니다. Cookie/토큰/원문 사용자 데이터·비식별화하지 않은 HAR를 공개하지 않습니다.

이 절차는 캡처 방법 수용 문제이지, SSE 운영 서비스가 실패했다는 판정이 아닙니다. #3936·[플랫폼 통합검증 #4318](https://github.com/skerishKang/ai-revenue-lab/issues/4318)은 OPEN입니다. [#4522](https://github.com/skerishKang/ai-revenue-lab/issues/4522)의 D1 040/배포 게이트 구현 완료와 실제 사용자 연계 수용도 구분합니다.

## 5. 소유자/파일 충돌·작업 순서

| 소유자 | 현재 해야 할 실제 작업 | 수정·병합 금지 / 의존성 |
| --- | --- | --- |
| CENTRAL CTO | PR/이슈 사실 확인, 격리·동시성 검수, exact-head CI/GitGuardian 확인, 위임 범위 내 Ready·병합 및 기술 문서 정리 | 다른 LOCAL/COMP2 워크트리 동시 편집 금지. 병합과 운영 배포는 별개 |
| COMP2 | #4661 제품 권한 양방향 격리, 서버 소유권·R2 원문, 안전 Markdown 화면 연결, 대화 목록·검색·복원 | #4509의 오래된 작업 브랜치 재작업 금지, #3763 음성 UI 강제 병합 금지 |
| LOCAL4 | #4658 견적 사실·D1 revision 원자성·빈 taxMode 해결 후 같은 PR 갱신 | COMP2 UI 파일 동시 변경, 새 041 운영 D1 적용, 실모델 과금 호출 금지 |
| LOCAL1 | #3936 **오프라인 가상 SSE 프레임 캡처 검증** 후 결과 제출 | 승인 없는 실모델 POST·Worker/SSE PATCH·Secrets/운영 설정 변경 금지 |
| LOCAL5 | #4656 테스트 범위 종료 | 동일 완료 작업 반복 금지 |

**간결한 후속 순서:** (1) COMP2 #4661 소유권 차단 해소/마크다운 UI 연결, (2) LOCAL4 #4658 견적 상태 보호 결함 수정, (3) CENTRAL이 각각 정확한 HEAD에 대한 CI·보안·권한·회귀 확인 후 병합, (4) LOCAL1이 #3936 가상 캡처 증거 회수. 순서상 독립 레인은 충돌 없는 범위에서 병렬 가능. 새로운 독립 검토자, 중복 정책/인덱스, 불필요한 이슈, 과도한 재검증 생성 금지.

## 6. 연결되는 현재 권위 및 제외 사항

- 기술 개발 운영정책: [AI DEVELOPMENT OPERATING POLICY](AI_DEVELOPMENT_OPERATING_POLICY.md), [GitHub 보고 원칙](GITHUB_REPORT_HANDOFF_POLICY.md), [문서 공식 진입점](../README.md).
- 기존 제품 디자인/음성 조율: [Chat·Claw·B66 UI·Voice 인수인계](PADIEM_CHAT_CLAW_B66_UI_VOICE_HANDOFF_20261014.md). 본 문서가 이를 대체하지 않습니다.
- 다른 장기 과제: [#4654 공통 AI 성격/기억](https://github.com/skerishKang/ai-revenue-lab/issues/4654) **DESIGN-HOLD**, [#4139 PADIEM Connector](https://github.com/skerishKang/ai-revenue-lab/issues/4139) **별도 구현 레인**, 오래된 B66 음성 [PR #3763](https://github.com/skerishKang/ai-revenue-lab/pull/3763) **자동 병합 금지**.
- 실제 외부 검색 비용/공급자 쿼리 전송, 계정간 정보 공유, 새로운 사업 정책, 모델 권한 확장 또는 운영 출시 여부는 이 스냅샷으로 결정하지 않습니다.
- **정정 원칙:** 이 문서와 이후 GitHub 기록이 충돌하면 각 PR/이슈의 최신 검증 가능한 HEAD, 병합 기록, 운영 readback과 사용자의 명시적 승인 사실을 우선합니다.
