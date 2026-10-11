# B62 TinyFish Search — JS Fetch → HTTPX 이중 압축해제 수정·운영 수용 기록 (#4375)

**증거 기준:** 2026-10-12 KST (2026-10-11 UTC 운영 실행)  
**대상 저장소/제품:** `skerishKang/ai-revenue-lab` / B62 Padiem Chat, 공개 웹 Search  
**판정:** `SOURCE_MERGED=YES`, `PRODUCTION_DEPLOYED=YES`, `SEARCH_TRANSPORT_502_NOT_REPRODUCED_IN_BOUNDED_PROBES=YES`; **전체 모델 답변 E2E는 별도 미완료**.  
**관련:** [구현 PR #4375](https://github.com/skerishKang/ai-revenue-lab/pull/4375), [중복 원본 PR #4049](https://github.com/skerishKang/ai-revenue-lab/pull/4049), [기존 완료 이슈 #3523](https://github.com/skerishKang/ai-revenue-lab/issues/3523), [B62 실사용 통합검증 #4317](https://github.com/skerishKang/ai-revenue-lab/issues/4317), [Search 우선순위 정책 #3385](./PADIEM_WEB_SEARCH_PROVIDER_POLICY_3385.md).

## 1. 무엇을 해결했고 무엇은 아직 아닌가

과거 실제 Production에서 공개 검색 `POST /api/chat` 요청이 간헐적으로 HTTP 502 `web_unavailable`을 반환했고, Worker의 안전한 고정 범주 로그가 `TINYFISH_EGRESS_FAILURE=TRANSPORT`, `TINYFISH_EGRESS_KIND=DECODING`을 표시했다. 웹 공급자 자격증명·쿼리·모델 자체 오류로 단정하지 않는다. [실측 근거 #3523](https://github.com/skerishKang/ai-revenue-lab/issues/3523#issuecomment-6090243048).

**실제 원인과 수정:** Cloudflare Workers의 JS Fetch는 응답 스트림을 이미 압축 해제해 전달할 수 있지만, 상류의 압축된 표현을 가리키는 `Content-Encoding` 및 `Content-Length` 헤더가 남을 수 있다. 이를 `httpx.Response`에 그대로 전달하면 HTTPX가 이미 해제된 본문을 다시 해제하다 `httpx.DecodingError`를 낸다. `apps/padiem-chat/worker.py`의 **외부 웹 JS Fetch → HTTPX 어댑터만** `gzip`/`br`/`deflate`에 대해 그 두 헤더를 제거한다. 무관한 헤더는 유지한다.

**변경하지 않은 것:** TinyFish/Daum 공급자 우선순위·API 호출 형태·키, HTTP 402/429 외 fallback 제한, 재시도 횟수, B14 모델 수동 선택, Engine/Claw 승인, D1 데이터, Cloudflare 운영 플래그 및 기존 바인딩. 사용자용 임의 기본 모델 선택도 하지 않았다.

## 2. 소스·리뷰·CI 근거

| 구분 | 확정 사실 |
| --- | --- |
| 최초 수정 | PR #4049, head `3c3b193775fd49643e59d1707326285c0032e189`; 나중에 중복으로 병합 없이 종료 |
| 채택 PR | [#4375](https://github.com/skerishKang/ai-revenue-lab/pull/4375), head `aa3ad73c739ad619aff798c09b1ba2cb53ca34f1` |
| CTO 기술 리뷰 | [#4375 review #5484188333](https://github.com/skerishKang/ai-revenue-lab/pull/4375#pullrequestreview-5484188333) — `COMMENTED` 기록, `CTO_FINAL_REVIEW=PASS_FOR_READY`; **독립 GitHub APPROVED 리뷰라고 주장하지 않음** |
| 코드 변경 | `apps/padiem-chat/worker.py` +15줄, `apps/padiem-chat/tests/test_worker_web_fetch_transport.py` +27줄, 총 2개 파일 |
| 검증 | 구현자 집중 테스트 **9 PASS**. 수정 제거 시 gzip/br/deflate **3 FAIL** → 복원 후 9 PASS(구현자 보고); CTO가 변경 패치·배포 계약 별도 확인 |
| 병합 전 exact-head CI | 43 checks = **16 SUCCESS + 27 SKIPPED, 실패/대기 0**, `MERGEABLE/CLEAN` |
| Squash 병합 | `56126669ab2f19af1e7db9114f77eaca105f1554` |
| 중복 PR #4049 | **CLOSED / NOT MERGED**, [종료 사유](https://github.com/skerishKang/ai-revenue-lab/pull/4049#issuecomment-6111593868); 원본 브랜치 삭제하지 않음 |

[구현 담당자 검증](https://github.com/skerishKang/ai-revenue-lab/pull/4375#issuecomment-6111555820)과 CTO 리뷰는 증거 출처가 다르다. 집중 테스트를 CTO가 재실행했다고 기록하지 않는다.

## 3. 실제 B62 보호 배포 — 두 시점의 버전을 혼동하지 않기

### #4375 병합 직후 배포

- **Run:** [B62 Production Code Deploy Gate #38159060878](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38159060878) — **SUCCESS**.
- **정확한 source:** `56126669ab2f19af1e7db9114f77eaca105f1554`.
- **구 제공 버전:** `fd8b9c41-8ffd-4b73-8eaa-4917d239099d`.
- **신규 제공 버전:** `075a0f45-1410-4c67-9788-239cf4af3cf5`.
- `PREMUTATION_EXACT_MAIN_SHA=PASS`, `B62_D1_MIGRATION_008_SCHEMA=EXACT` (읽기 전용), `NEW_VERSION_ACTIVE=PASS`, `B62_BINDING_AUTHORITY_PRESERVED=PASS`, `BINDINGS_PRESERVED_EXACTLY=PASS`, `FULL_SECRET_SET_EQUALITY=PASS`, Custom Domain 유지, `B62_PRODUCTION_SMOKE=PASS`.
- **State adoption/rollback 없음.** 기존 시크릿 값 조회·수정, 운영 변수 강제 교체, D1 데이터 변경 없음.

### 직후 다른 담당자의 B66 관련 main 전진 및 재배포

- **후속 main:** `503877696634c4af9bd8619e9c8817af621c8b8f`; 부모 커밋이 **#4375 병합본 `56126669...`**. 후속 변경 파일은 B66 영역에 한정되며 위 외부 웹 전송 어댑터는 변경하지 않았다.
- **후속 Run:** [B62 보호 배포 #38159318770](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38159318770) — **SUCCESS**.
- **2026-10-12 KST 해당 체크포인트의 실제 최신 제공 버전:** `bcd7f479-a240-4fd9-8025-fe293d81d224`.
- 동일하게 새로운 버전 활성화, 기존 바인딩 전체 및 시크릿 집합 보존, Custom Domain, 운영 스모크가 PASS였다.
- **이 문서의 버전 번호는 그 시점의 스냅샷이다.** 그 뒤 배포 여부는 새 read-only 운영 조회로 판단한다. 이전 `075a0f45...`가 계속 최신이라고 주장하지 않는다.

기존 운영 배포 방법은 [`.github/workflows/b62-production-code-deploy-gate.yml`](../../.github/workflows/b62-production-code-deploy-gate.yml)에만 따른다. 다른 B66 변경을 뒤집거나 예전 main을 재배포하지 않는다.

## 4. 실제 서비스 검색 검증과 범위

**환경:** 공인 `https://chat.padiem.net`, 격리된 일회용 Tabbit Browser 프로필, *공개 기관 누리집* 검색어. 고객 데이터·로그인 쿠키·비공개 파일·비밀값 사용 없음.

| 배포 구간 | 브라우저 실제 결과 | 해석 |
| --- | --- | --- |
| #4375 바로 이후 제공 버전 `075a0f45...` | 공개 검색 6회: 모두 HTTP **503 `model_profile_unassigned`**, **502 미발생** | Worker 공개 검색 경로에서 예전 HTTP 502가 제한된 실측 동안 재현되지 않음; 모델 답변은 아직 없음 |
| 동시 Worker 안전 진단 로그 | 적어도 한 요청에서 `GROUNDING_SEARCH_EVIDENCE=QUALITY_SELECTED` | Core에서 provider search와 증거 선택을 거쳐 B14 synthesizer 단계에 도달했음을 입증 |
| 후속 B66 제공 버전 `bcd7f479...` | 공개 광주 누리집 검색 1회 HTTP **503 `model_profile_unassigned`**, 502 미발생 | 위 소스 fix 유지 상태에서 검색 전송 502 재발은 관찰되지 않음 |

모두 합해 **공개 검색 7회에서 종전 HTTP 502/DECODING 증상 미재현**. 다만 안전 Worker 로그의 `QUALITY_SELECTED` 직접 실측은 **최소 1회**이며 모든 시도의 상류 응답을 독립적으로 검증했다고 과장하지 않는다. 간헐적 502가 영원히 재발하지 않음을 증명하는 SLA도 아니다.

초기 `urllib` CLI는 CDN/브라우저 경계에서 `/health` 포함 HTTP 403·비JSON을 반환했다. 이를 Worker 검색 실패로 오인하지 않았고, 올바른 도메인의 실제 Tabbit 세션에서는 홈페이지 200 및 위 503 결과를 확인했다.

**중요한 구분:** `model_profile_unassigned`는 의도적으로 보류된 B14 모델 프로필/제품 선택 경계에 관한 **별도 503**이다. 이 상태를 해결하려고 모델을 자동 지정하거나 임의 fallback을 켜지 않는다. 로그인·사용자 수동 모델 선택→답변→저장/재조회의 **B62 전체 E2E는 [#4317](https://github.com/skerishKang/ai-revenue-lab/issues/4317)**에서 계속 관리한다. 특정 Claw Golden Path [#3523](https://github.com/skerishKang/ai-revenue-lab/issues/3523)은 그 자체 증거로 **이미 CLOSED**이며 이번 503 때문에 재개하지 않는다.

## 5. 장애가 다시 관측될 때만 수행할 후속 진단

1. `GET`만으로 *그 시점*의 실제 활성 B62 Worker 버전/운영 바인딩을 확인한다. 선행 업로드 버전이나 특정 날짜의 `main`을 활성 버전이라고 추정하지 않는다.
2. 고객 데이터 없는 공개 쿼리에서 동일한 `HTTP 502 web_unavailable`이 **새로** 관측될 때, 적절히 승인된 범위 안에서 고정 범주의 Worker 로그(`TINYFISH_EGRESS_FAILURE`, `TINYFISH_EGRESS_KIND`, `TINYFISH_SEARCH_NORMALIZATION`, `GROUNDING_SEARCH_EVIDENCE`)를 상관관계 확인한다. 사용자 검색어·전체 URL·API Key·응답 본문/예외 문자열은 기록하지 않는다.
3. `DECODING` 502와 `model_profile_unassigned` 503, 사용량 402/429, B14 provider 오류를 **다른 범주**로 유지한다. 일반 전송 실패에서 Daum Search로 우회하지 않는다.
4. 재현된 새 코드 결함이 있으면 최소 테스트와 코드 수정 PR로 처리하고, 일반 B62 최종 이용자 검증은 기존 #4317에만 누적한다. 과거 WRITE/승인 또는 모델 호출을 임의 재전송하지 않는다.

## 6. 이슈 정리·수용 상태

| 작업 | 2026-10-12 KST 당시 정확한 상태 |
| --- | --- |
| #4375 압축해제 어댑터 수정 | **MERGED / SOURCE_CI_PASS / DEPLOYED / BOUNDED_SEARCH_502_NOT_REPRODUCED** |
| #4049 원본 중복 PR | **CLOSED / NOT_MERGED** |
| #3385 검색 공급자 정책 구현 | **CLOSED / COMPLETE**; TinyFish 우선, TinyFish 402/429에만 Daum 한 번 |
| #3523 Claw 첫 Golden Path | **CLOSED** (기존 실사용 Claw 성공 근거); 이번 B62 검색 교정과 완전한 B62 모델 E2E 혼동 금지 |
| #4317 일반 Chat 통합 운영 검증 | **OPEN**. 인증 사용자·정확한 모델 선택·실제 답변·프로젝트/파일·모바일 E2E는 별도 증거 필요 |
| #3933 / #3936 Hark WEB-FIRST | 각자의 구현·검증 소관 유지; 이 B62 전송 패치로 Hark 기능 완료 선언하지 않음 |

```text
PR_4375=MERGED
MERGE_SHA=56126669ab2f19af1e7db9114f77eaca105f1554
PROD_PROOF_RUN_1=38159060878:SUCCESS
PROD_PROOF_RUN_2=38159318770:SUCCESS
LAST_CHECKPOINT_ACTIVE_VERSION=bcd7f479-a240-4fd9-8025-fe293d81d224
SERVING_PATCH_IN_LINEAGE=YES
PUBLIC_BROWSER_SEARCH_HTTP_502_OBSERVED=0_OF_7_BOUNDED_PROBES
SEARCH_EVIDENCE_QUALITY_SELECTED=AT_LEAST_ONE_SERVING_REQUEST
FULL_B62_MODEL_SYNTHESIS_E2E=NOT_PROVEN
OBSERVED_MODEL_BOUNDARY=HTTP_503:model_profile_unassigned
NEXT_ACCEPTANCE_OWNER=ISSUE_4317
EXTRA_PRODUCTION_MUTATION_REQUIRED_FOR_DOCS=NO
```

**GitHub 원본 운영 증빙:** [병합·첫 배포·첫 6회 실측](https://github.com/skerishKang/ai-revenue-lab/pull/4375#issuecomment-6111700330), [후속 B66 배포·새 버전 재검증](https://github.com/skerishKang/ai-revenue-lab/pull/4375#issuecomment-6111723511).
