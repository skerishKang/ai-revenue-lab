# B66 AI 일반대화 → 견적작성 → QuoteCore 인계: 기술 현황 (2026-10-14 KST)


<!-- CENTRAL_POST_REVIEW_9588A22_20261014 -->
## 최신 후속 커밋 반영 — `9588a22` (2026-10-14 KST)

**아래 `85e8ea8` 검토/잔여 결함 표는 최초 CENTRAL 검토 시점의 정확한 발견 기록이며, 후속 HEAD의 현재 미수정 결함 목록이 아니다.** LOCAL4가 동일 [Draft #4658](https://github.com/skerishKang/ai-revenue-lab/pull/4658)에 새 HEAD **`9588a22c176c5619c4f5a391fd1157d2c84992a5`**를 푸시했고, CENTRAL은 다음 보완 코드를 GitHub 소스로 확인했다.

- **P0-A 소스 수정 제출:** 견적 작성 모드 밖에서 모델 제안 delta를 직접 병합하지 않음. 재진입 `quote_create`도 기존 사실을 교체하지 못하도록 하고, 일반 모드·모드 전환·신규 사실 수집 회귀 테스트 추가.
- **P0-B 소스 수정 제출:** D1 슬롯에 `revision INTEGER` 컬럼을 둔 추가형 migration 041, 사용자/워크스페이스 + 예상 revision에 대한 단일 SQL CAS 조건부 UPSERT와 `meta.changes` 검사, 경쟁 패자 `revision_conflict` 409. 두 스레드/별도 SQLite 연결의 동일 슬롯 경쟁과 테넌트별 분리 회귀 추가.
- **P1 소스 수정 제출:** 모델 delta의 정확한 빈 `taxMode:""`는 미입력으로 무시하고, 이미 알려진 세금 유형을 변경·삭제하지 않는다. 그 외 유효하지 않은 값/타입은 거부하도록 테스트 추가.
- **검증 단계:** 후속 HEAD의 GitGuardian, B62 full regression, 운영정책 CI 등은 GitHub에서 SUCCESS로 관측. 마지막 조회 시 상위 `browser-qa`는 **IN_PROGRESS**라 전체 CI 최종 판정은 보류. 해당 웹 브라우저 검사는 B66 참조 제품 화면의 새 대화 API 실사용 E2E를 대체하지 않는다.
- **상태:** `P0_FIXES=SOURCE_SUBMITTED_AND_CODE_INSPECTED`; `CENTRAL_FINAL_ACCEPTANCE=PENDING`; `PR4658=OPEN_DRAFT_UNMERGED`; `MIGRATION_041_PRODUCTION=NOT_APPLIED`; `B66_UI_E2E=NOT_EXECUTED`. 후속 HEAD의 개발자 테스트 정확한 개수와 최종 CI는 LOCAL4 보고/추가 검증 후 확정한다. 최신 main에 문서 커밋이 별도로 반영되었으므로 PR의 merge-forward도 병합 전 확인한다.

원 이슈의 이전 'P0 미수정' 표현은 **`85e8ea8`을 대상으로 한 역사 기록**으로 읽어야 한다. 실제 병합 여부와 운영 인수는 #4658 / #4316 최신 상태에 따른다.
<!-- /CENTRAL_POST_REVIEW_9588A22_20261014 -->

> **성격:** 시점별 중앙 CTO 소스·검증 기록. 새로운 사업방침, 사용 권한, 운영 출시 승인이 아니다. 최신 변경 상태는 아래 이슈/PR 및 GitHub main을 우선한다. 로컬 비공개 사업·운영 정책 원문은 이 문서에 기록하지 않는다.

```text
DOC_STATUS = TECHNICAL_CHECKPOINT
PRODUCT = B66_PADIEM_QUOTE
SOURCE_PR = #4658
SOURCE_HEAD_REVIEWED = 85e8ea842081636b5af10348e3d95c3de41dff63
SOURCE_PR_STATUS_AT_REVIEW = OPEN_DRAFT_UNMERGED
B66_CONVERSATION_PRODUCTION = NOT_DEPLOYED_OR_LIVE_PROVEN
BROWSER_QA = NOT_EXECUTED
OWNER_OF_SOURCE_REPAIR = LOCAL4
FINAL_REVIEW_AND_MERGE = CENTRAL
```

## 단일 작업 권위 및 제품 경계

- **[이슈 #4466](https://github.com/skerishKang/ai-revenue-lab/issues/4466)** — B66 일반 AI 대화, 견적 의도 분류, 다중 턴 상담의 모 이슈.
- **[이슈 #4412](https://github.com/skerishKang/ai-revenue-lab/issues/4412)** — CGI Saved Quote Skill이 없는 고객의 견적 작성 방식 선택 및 표준 QuoteCore 입력 인계.
- **[Draft PR #4658](https://github.com/skerishKang/ai-revenue-lab/pull/4658)** — LOCAL4 구현/수정 브랜치 `local4/4466-4412-ai-quote-261014`; 검토 HEAD `85e8ea8`. 본 기술 기록 작성 시점에는 *병합·실서비스 배포되지 않음*.
- **[이슈 #4316](https://github.com/skerishKang/ai-revenue-lab/issues/4316)** — 이미 존재하는 **단일 B66 운영 E2E 수용 큐**. 브라우저/실회원/실모델 증거를 여기에 축적하고 중복 QA 이슈를 만들지 않는다.
- **[CENTRAL #4658 상세 검토](https://github.com/skerishKang/ai-revenue-lab/pull/4658#issuecomment-6156926725)** — 코드 기준 잔여 결함, 수정 및 회귀 요구의 실행 권위.

이 경로는 새 CGI 템플릿이나 Saved Quote Skill을 생성·승인하지 않는다. 모델은 문맥·견적 사실 **후보**만 추출하며, QuoteCore가 수량·단가 기반 계산의 유일한 권위다. 명시적 고객 `approve_draft`는 **표준 견적 초안 입력 반환**일 뿐 저장·기존 견적 덮어쓰기·PDF 발급 권한이 아니다. 실제 화면에서 재검토 및 저장·발급은 기존 별도 경로로 이어져야 한다.

## LOCAL4 소스 구현 및 재현 결과

| 구분 | 구현·검사한 내용 | 현 상태 |
|---|---|---|
| 실패 A — staged confirm | staged delta를 완전 정규화 facts로 저장 후 delta로 재검증해 `taxMode:""`가 거부되는 이중 정규화 제거 | 변경·테스트 제출 |
| 실패 B — 마이그레이션 검사 | `updated_at`을 `UPDATE`로 읽는 줄 접두사 오탐 제거; 주석 제외 후 실제 SQL statement 첫 동사로 파괴 동작 탐지 | 변경·테스트 제출 |
| 중복 턴 replay | 키워드 전용 인자 `extra`를 위치 인자로 호출해 크래시 나던 경로 보정 | 변경·테스트 제출 |
| 모델의 무단 수량·금액 변경 | 견적 작성 모드에서 모델 intent `confirm` 등과 무관하게 기존 사실 변경은 staged 후 고객 `confirm` 요구 | **부분 구현; 아래 일반 모드 우회 결함 존재** |
| QuoteCore 초안 인계 | `approve_draft` 없거나 작성 방식 미선택·미확정 staged·필수값 누락이면 초안 출력 거부, 서버는 저장/발급하지 않음 | 서버 소스·테스트 제출 |
| 데이터 범위 | 사용자/워크스페이스별 D1 슬롯, bounded state, 요청 revision, 모델/멤버 승인 경계 | **동시 요청 CAS 미보장; 아래 잔여 결함 존재** |

변경 파일 7개: `apps/padiem-chat/app/app_factory.py`, `app/b66_ai_conversation.py`, `app/b66_ai_conversation_routes.py`, `app/b66_ai_conversation_store.py`, `migrations/041_b66_ai_conversation.sql`, `tests/test_b66_ai_conversation_4466.py`, `tests/test_b66_ai_conversation_routes_4412.py` (나머지 경로는 모두 `apps/padiem-chat/` 접두사).

## CENTRAL이 확인한 미해결 결함 — LOCAL4 동일 PR 수정

1. **P0-A: 일반 모드의 견적 사실 변경 우회.** `apply_message_transition`이 `MODE_QUOTE`일 때만 `delta_overwrites_known_facts`로 staged 여부를 검사하고, `MODE_GENERAL`에서는 모델이 제안한 delta를 바로 병합한다. 견적 모드 종료 후 보존된 100개 수량을 모델의 일반 답변이 500으로 바꾸는 경우가 가능하다. *대응:* 서버 승인된 견적 작성 범위 밖에서는 견적 facts 변형을 막고, 재진입 시 기존 사실 교체는 고객 확인으로만 가능하게 한다. 정상 신규 견적 작성·신규값 수집은 보존한다.
2. **P0-B: D1 저장의 revision 경쟁 조건.** 저장 구현이 무조건 `INSERT ... ON CONFLICT DO UPDATE`이므로 같은 revision을 읽은 두 요청 모두 성공한 뒤 마지막 값으로 덮어쓸 수 있다. 순차적 stale 409 테스트만으로 동시성을 증명하지 않는다. *대응:* owner/workspace + 예상 이전 revision을 조건으로 **원자적 CAS**를 수행하고 D1 실제 변경 행 수를 확인, 경쟁 패자는 409 `revision_conflict`, 첫 저장 승자는 유지. 동시 2요청 실 SQLite/D1 어댑터 회귀를 추가한다.
3. **P1 — 빈 세금 유형 사용자 경험.** 모델 delta의 정확한 `{"taxMode":""}`는 세율 변경 승인이 아니라 미입력으로 다룰 수 있게 한다. 기존 세금 유형은 지우지 않는다. `WEIRD` 등 잘못된 값/유형은 계속 차단한다. 이 변경은 위 두 P0 결함의 수용을 대체하지 않는다.

위 두 P0는 코드 검토로 확인한 실패 경로이며, **현재 PR 병합 차단 결함**이다. LOCAL4에게 동일 Draft PR의 수정·merge-forward·회귀를 지시했고 신규 검토자나 신규 기능 이슈를 배정하지 않았다.

## 검증 증거와 비증거

- LOCAL4 **제출 보고**: 집중 4파일 **154 PASS / 0 FAIL**, 전체 앱 **4637 PASS / 4 FAIL / 7 skip**. 실패 4건을 기존 Windows/환경 문제로 분류했으며, CENTRAL이 이 로컬 전체 suite를 동일 환경에서 독립 재실행한 증거는 없다.
- CENTRAL이 GitHub에서 검증한 HEAD `85e8ea8`: B62 full regression 및 관련 워크플로 SUCCESS, **GitGuardian SUCCESS**, 운영정책 CI SUCCESS. HEAD 검사는 위 일반모드 변경 우회와 동시 저장 경쟁 조건을 커버하지 못한다.
- 새 D1 마이그레이션은 **소스에만 존재**한다. 실제 Production D1 적용, B66 고객 UI 연결, 브라우저 QA, 로그인 회원의 실제 provider 응답, 실제 QuoteCore 저장·PDF 사용 여정은 이 PR로 확인되지 않았다.
- 무상 mock/provider 응답 테스트를 Production 모델 호출로 표기하지 않는다. 보고된 유료 모델 호출 0회.

## 완료·대기·다음 실행

1. **LOCAL4:** 같은 Draft #4658에서 P0-A/P0-B를 수리하고 P1 `taxMode` 입력 규칙을 정리한다. 집중 회귀, 실제 저장 경쟁 조건 증명, 최신 main 병합 반영, 정확한 새 HEAD CI·GitGuardian 결과를 보고한다.
2. **CENTRAL:** 코드를 다시 확인하고 통과 시 기존 위임 범위에서 Ready/merge 판단. 미해결 P0인 상태로 병합하거나 운영 D1 마이그레이션을 실행하지 않는다.
3. **B66 UI 담당(추후 기존 작업 조율):** 병합 이후 기존 B66 입력 화면에서 일반 대화→명시적 견적 시작→작성 방식 선택→수정 확인→표준 초안 리뷰로 연결. 새 화면 슬라이스가 없다면 브라우저 QA는 `NOT_EXECUTED` 그대로다.
4. **#4316:** 로그인 회원 + 권한 부여된 실모델 + 무CGI 기본 견적 작성/후속질문 + QuoteCore 미리보기/저장·출력 + 계정 분리의 실제 증거를 누적한다. 소스 병합만으로 운영 인수 이슈를 닫지 않는다.

## 인접 작업 분리 (본 B66 PR 범위 아님)

- **LOCAL2:** [B62 Library Draft PR #4511](https://github.com/skerishKang/ai-revenue-lab/pull/4511) — 저장 파일 이력 페이징. #4658 또는 B66 음성 개발에 합치지 않는다.
- **LOCAL3/STT:** [공통 STT 이슈 #4643](https://github.com/skerishKang/ai-revenue-lab/issues/4643) — [#4644](https://github.com/skerishKang/ai-revenue-lab/pull/4644), [#4660](https://github.com/skerishKang/ai-revenue-lab/pull/4660) 소스 병합, Worker 활성화 OFF 및 실제 caller/tenant/cost authority 미완성. B66 마이크 후속은 [#3404](https://github.com/skerishKang/ai-revenue-lab/issues/3404). **B66 AI 견적대화 #4658 완료 증거와 혼합하지 않는다.**

**상태 기준:** GitHub main/PR/이슈가 변경되면 이 문서의 날짜·HEAD·CI 숫자는 과거의 검토 스냅샷으로 간주한다.
