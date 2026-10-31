# AI Development Operating Policy

> Web Claw is a locally executing computer agent accessed through a web interface. Its canonical execution, original-content and connector principles are in [Web Claw Local Agent Execution Principle](../architecture/WEB_CLAW_LOCAL_AGENT_EXECUTION_PRINCIPLE_20261020.md). Do not reinterpret web delivery as a reason for cloud-chat-only feature limits or blanket redaction. The authorized connector executes local tasks; preserve actual account/device authorization.


- Status: **CANONICAL REPOSITORY OPERATING POLICY**
- Effective reset: 2026-08-14
- Design authority: `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`
- Evidence authority: `EVIDENCE_REQUIREMENTS.md`
- Test-scope/delivery authority: `TEST_SCOPE_AND_DELIVERY_POLICY.md`
- Deployment authority: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`
- Technology adoption authority: `TECHNOLOGY_ADOPTION_POLICY.md`
- Model/provider decision authority: `MODEL_CHANGE_OWNER_APPROVAL_POLICY.md`
- Dated B14 owner decision/evidence ledger: `B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md` (historical issue and implementation status; not a second approval gate)

## 1쪽 요약 — #5895 (2026-10-27)

본문과 충돌하면 이 요약이 우선한다. 충돌 절 정리 완료(#5964).

본문(§0~§18)의 운영 규칙을 한 쪽으로 정리했다. 판단이 막힐 때 먼저 읽고, 근거는 각 절을 본다. 이 요약은 새 규칙을 만들지 않고 본문을 대체하지도 않는다.

**목표**
- 현재 단계는 MVP/베타 완성이다. 범위: 채팅·클로(일반 채팅, PC 레인, 첨부 문서, 자동화)에 더해, 축사·SNS(Util)·견적서(B66)·PDF·MD 변환을 베타 핵심으로 올린다(Owner 결정 2026-10-28). 방향: 각 메뉴에서 내 PC 파일 가져오기(참고 글·엑셀 양식·변환할 문서)와 결과를 내 PC에 저장.
- 범위를 넓힐 때는 보류 목록(#5882)의 'Util·B66 범위 재개(2026-10-28)' 항목으로 관리한다.

**역할**
- Owner가 결정한다: 모델, 공급자, 비용, 제품 범위.
- CTO가 결정한다: 머지, 배포, 롤백, D1 적용 같은 운영. 설정된 보호장치와 이미 기록된 승인을 반복해서 묻지 않는다.

**배포**
- 공식 게이트 1회만 쓴다. 게이트 밖 수동 배포나 별도 Preview 경로를 만들지 않는다.
- 게이트는 배포하는 앱 경로를 기준으로 main 최신인지 본다. 무관한 레인의 머지가 배포를 세우지 않는다.
- 배포 후 점검은 일반 채팅 1회, PC 레인 코드가 바뀐 배포에만 PC 목록 1회를 더한다.
- 점검 실패는 게이트를 빨강으로 남긴다. 자동 롤백은 하지 않고 사람이 읽게 둔다. 롤백은 일반 채팅이 아예 동작하지 않을 때 쓰는 별도 판단이다.

**유지하는 규칙**
- 비밀 값, 고객 데이터, 공급자 응답 원문을 로그·PR·보고에 남기지 않는다.
- 요청자 권한은 서버에서 검사한다. 브라우저가 보낸 등급·역할·SHA 선택은 그 자체로 권한이 아니다.
- 운영 바인딩을 몰래 제거하지 않는다. 바인딩 정본은 `wrangler.toml`이고, 변경 PR은 CTO 검토 대상이다.
- 파괴적 SQL은 차단한다.
- 배포와 롤백은 게이트에서 1회 기록한다.
- PC 연결 기본 범위 = 로컬 드라이브 전체(Owner 결정 2026-10-28).
- PC 작업은 사용자 확인 없이 실행하고, 쓰기·삭제 전 백업과 변경 기록을 남긴다(Owner 결정 2026-10-28).
- 연결은 "이 PC 연결" 설치 한 번으로 자동된다(Owner 결정 2026-10-28).

**없앤 규칙 — 이제 기준으로 쓰지 않는다 (#5895)**
- 라이브 현재 바인딩이 정답이라는 권위: `wrangler.toml` 선언과 diff로 본다.
- 마이그레이션마다 만들던 별도 게이트 워크플로: 범용 D1 마이그레이션 게이트로 본다.
- Core 파일 SHA 고정 canary: 동작 테스트로 본다.
- 금지 단어 소스 검사: 주석 문구를 이유로 CI를 세우지 않는다.
- 공급자 응답 엄격 파싱과 폴백 금지: #5885의 규칙으로 본다.
- 정확 main 문자열 동일성 확인: 대상 앱 경로 기준 최신 확인으로 본다(#5957).

**새 고정 제한**
- 바이트·초·개수의 새 고정 제한은 추가하지 않는다. 정말 필요하면 Owner에게 묻고, 결정받은 뒤 그 자리에 적는다.


## 0. Public technical development context — consult local business-governance stage

**Public engineering context:** the repository is maintained with limited development capacity. Actual business stage, customer-facing defaults and deployment priorities must be read from the non-public local Governance directory referenced below. Production URLs and actual operator/customer data require evidence, regardless of engineering stage. Technical access controls and configured platform protections remain facts to verify; an unresolved conflict with the business policy is referred to the Owner for a decision.

### Confidential business-governance source

The repository's business decision authority is stored **outside Git**, on the authorized PC under `G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-governance`. Read the local `README.md` index and the applicable documents in `사업방침/`, then `운영방침/`, when a business/product decision or its technical implementation is involved. The former `사업방침/01_CTO_에이전트_운영규칙.md` is a relocation notice; the active CTO rules are in `운영방침/01_CTO_에이전트_운영규칙.md`. The public technical procedures below explain **how** to implement and validate, but do not replace the local business decision. If the source is inaccessible or apparently contradictory, **ask the Owner**; do not infer a new customer permission policy. Never quote or copy private policy substance back into this public repository.

### 0A. CTO outcome order — one useful result before extra evidence

1. State the **next user-visible or operator-visible behavior to make work** (for example, a single B14 model request returning its real status), and identify only the immediate missing dependency.
2. Reuse existing source, a configured workflow and prior relevant checks; implement the smallest correction or run the smallest approved real experiment. Do not create more issues/PRs/documents simply because it is possible.
3. Run the **focused load-bearing regression + required relevant CI**. For a claim about a live integration, run **one** actual bounded integration/smoke check if the environment genuinely permits it. For a straightforward internal model evaluation, one synthetic request (concurrency=1, no auto-retry/fallback) through the *existing approved B14 path* is normally the answer, not a fresh harness or architecture project.
4. If the real check fails, classify the observed response accurately (HTTP 200/model identity, 401/403, 429, 5xx/timeout, or blocked before POST). Repair only a proven product defect. An actual upstream capacity error is useful negative evidence, **not** a mandate for repeated retries or another CI layer.
5. Close the bounded implementation/evaluation issue when its stated scope is decided, including a no-go; accumulate remaining owner-facing E2E acceptance on the existing single product verification issue. Do not confuse a merged PR with runtime success.

**Change-to-test discipline:** a new mandatory check must identify `NEW_FAILURE_MODE`, `PROTECTED_CLAIM`, `EXISTING_EVIDENCE_GAP`, and `BLOCKS_CURRENT_GOAL=YES|NO`. If there is no new failure mode or changed relevant surface, it is not another blocker. Historic CI success remains valid for unchanged files/dependencies. Routine one-file fixes do not require multiple independent validators, load tests, live-customer simulation or repeated full-product matrices.

### 0B. Authority and operating permissions

- The one-person Owner has delegated routine CTO source review, merge and deployment decisions within existing configured protection. Do not ask the Owner to repeat approval already recorded, fabricate a second account/reviewer or treat absence of an independent person as proof of a technical denial. Follow actual protection/rulesets and any **named** manual release guard that applies to the particular Worker.
- A test's **business authorization** and the tool's **actual execution permission** are distinct. If an approved provider evaluation cannot run because a specific tool/platform rejects dispatch before sending, report `NOT_RUN / BLOCKED_AT=<actual layer>`; do not call it a provider failure. Do not evade denial via ad-hoc HTTP, another account, a different API/client/credential or a weakened workflow.
- Preserve owner/workspace isolation, secret protection, non-destructive migration sequencing, real approval before consequential actions, GitHub required checks and existing release/rollback contracts. These safeguards are targeted, not an excuse to introduce unrelated tests or prevent a safe internal demo.

### 0C. Stage escalation: when to harden

Move to **pilot/customer acceptance** when the Owner names actual external test users, customer data or a handoff; move to **commercial release assurance** when paid customers, billing, commitments, higher-risk persistence/identity integrations or external compliance require it. Use §3A, §3C and the test/deployment policies to tighten only the affected claims. An issue label, GitHub environment name or the presence of a Production hostname does **not** alone change the declared product stage.

### 0D. New ChatGPT/agent conversation continuity

Root `AGENTS.md` is the repo-wide instruction for any agent that **reads this repository**; it does **not automatically load into every fresh ChatGPT conversation**. The ChatGPT **Project Instructions** should include a short durable owner-stage rule and point to `AGENTS.md` + this section. On each repository-aware CTO session, verify these documents once, then act; do not reconstruct old gates or request another owner approval without a concrete unmet boundary. Active issue/PR comments report task state, not portfolio-wide behavioral authority.

fresh `main` 문자열 동일성 확인: 폐지(#5895, 2026-10-27) — 대체: 대상 앱 경로 기준 main 최신(main_currency_guard).

### 0E. Push and CI economy

**Batch small commits before pushing.** A single PR push can fan out into many Actions workflows; prefer one coherent push after local focused checks instead of pushing every tiny edit and cancelling the same 10+ checks repeatedly. For urgent fixes, push when ready; never postpone a safety repair solely to save CI minutes.

*(Moved from the `AGENTS.md` entry point during the 2026-10-23 instruction-index restoration; this section is the canonical text and `AGENTS.md` links here.)*

#### 0E-1. Duplicate-work prevention and push scope (Owner session 2026-10-23)

- **Claim before fixing shared breakage.** Before repairing a failing `main` check, or starting a bounded fix another lane could also pick up, post a one-line claim comment (`수정 착수`) on the originating PR or the tracking issue. If a claim already exists, do not start; coordinate in that thread.
- **Fresh-fetch before PR creation and before every push.** If the intended change has already landed on `origin/main`, stop and report instead of applying it. 2026-10-23 cases: #5610 duplicated #5609; #5619 overlapped #5623 and had to be reduced.
- **Force-push scope.** No force push to `main`, to protected branches, or to a branch owned by or inherited from another worker. Publishing a rebase of one's own PR branch uses `--force-with-lease=<branch>:<known remote head>` only.
- **Skipped is not pass.** A `success` run whose suite was skipped by the changeset classifier is not green evidence for that suite; cite the latest run in which the suite actually executed. Latent `main` failures surfaced this way on 2026-10-23 (#5605, #5618 merged while `B62 full regression` was skipped).
- Since #5680 (2026-10-24) every push to main runs B62 full regression and the web-desktop E2E unconditionally; PR lanes keep the changeset classifier.

### 0F. 장애 분석 원칙 (Owner 결정 2026-10-24)

1. 모델은 고정이다. 유료·관리자 레인 = opencode-go muse-spark-1.3-contributor. 장애가 나도 모델·route 변경을 제안하지 않는다. Free(Google)는 RPM으로 실패할 수 있으며 Free 경로로 **기능 테스트**를 하지 않는다. 다만 배포 직후 자격 확인용 1회 호출은 예외다(코드만 기록).
2. TinyFish 검색의 크레딧·인증은 원인 후보에서 제외한다.
3. upstream_auth_error / 401 / 403을 보면 가설을 세우기 전에 **같은 시간대에 공급자를 터미널에서 직접 호출**한다(B14를 거치지 않고, 같은 모델·같은 키). 직접 호출 200 → B14 또는 우리 설정 문제. 직접 호출도 401/403 → 키·공급자 문제로 분류해 Owner에게 보고하고 추적을 멈춘다. 이 단계 없이 "키 문제"라고 보고하지 않는다.
4. HTTP 코드만으로 결론 내지 않는다. 오류를 **만든 서비스의 로그 코드**(B14: upstream_auth_failed / b14_service_proof_required / missing_provider_key 등)를 확보한 뒤 판정한다. 로그는 Workers Logs 또는 wrangler tail로 같은 시각에 잡는다.
5. 세 가지는 분석하지 않고 즉시 Owner 결정을 받는다: ① 모델 ② 코드에 넣어 둔 자체 제한(시한·크기·횟수) ③ Cloudflare 제한. 그 외만 CTO·로컬이 분석한다.
6. 툴 사용 턴에는 실행 시한을 두지 않는다. 진행 중·경과 시간을 보여주고, 실패에만 오류를 보인다. 503을 던지고 뒤늦게 결과를 보여주는 설계는 결함이다.
7. 검색이 실패하면 턴을 죽이지 않고 안내와 함께 답변으로 진행한다.
8. 작업 규칙: 한 로컬 한 작업·순서대로, 작업마다 전용 worktree, 같은 PC의 Tabbit은 한 번에 한 로컬, 배포는 CTO 지시로만·한 번에 하나, PR 전 fresh-fetch, 보고에 헤더 값·키·토큰 금지(코드 이름만).
9. 간헐 실패(되다 안 되다)는 키 값 문제가 아니다 — 키가 틀리면 항상 실패한다. 따라서 "B14 키" 가설은 간헐 장애에서 제외한다. 간헐 실패의 후보는 두 가지뿐이다: (a) 공급자의 간헐 거부 (b) B14 내부의 요청 단위 간헐 실패(시크릿 조회·증명 검증). 3번의 직접 호출 비교로 (a)/(b)를 가른 뒤에만 보고한다.
10. 시크릿 개체 전환(원본 → 중립 사본)은 값 존재 확인 → 배포 직후 health has_key 확인, 실패 시 즉시 롤백 순서로만 수행한다. 개체 ID가 목록에 있다는 것과 값이 들어 있는 것은 다른 사실이다 — 값이 없는 사본으로 `secret_name`을 바꾸면 배포는 성공해도 `has_key`가 false다. 따라서 ① 전환 전에 사본 개체의 값 기록 여부를 메타데이터(list)로 확인하고, ② 게이트 배포 직후 `/api/pilot/health`의 공급자별 `has_key`를 읽고, ③ 하나라도 false면 게이트가 배포 직전에 자동 캡처한 서빙 버전으로 즉시 롤백한다(재시도·임의 재배포 금지). 값은 읽지도 출력하지도 않으며 보고는 불리언과 개수·코드 이름으로만 한다.

11. 새 경로의 수용 기준은 **모든 연산**을 열거한다. PC 경로는 목록·읽기·드라이브 각각의 성공·거부·복구와 dispatch/최종 응답을 확인하며, 일부 연산의 통과를 전체 완료로 쓰지 않는다.
    근거 사례: 목록·읽기 성공 뒤에도 드라이브 503이 남았으므로 드라이브(c)를 독립 수용 항목으로 둔다(#5573).
12. 새 진입점은 공용 장부·공용 엔드포인트의 **계약 테스트를 같은 PR에** 포함한다. admit → 멱등 등록 → dispatch → 결과·복구가 기존 경로와 같은 행을 사용하는지 증명하며, 운영 DB 직접 SQL로 계약 누락을 메우지 않는다.
    근거 사례: Chat 도구 턴의 드라이브 503은 공용 `claw_runs` 계약을 함께 검증해야 함을 보였고, D1 직접 SQL 사례(#5790·#5796)는 코드·정식 게이트 대신 운영 상태를 손보는 절차로 삼지 않는다.
13. 파일 SHA 고정 canary: 폐지(#5895, 2026-10-27) — 대체: 대상 앱 경로 기준 main 최신(main_currency_guard).
14. 모든 거부는 **코드 포함 로그 + 사용자 문장**으로 끝낸다. 거부 경계·안전한 코드로 원인을 구분하고 스트림 최종 오류 또는 거부 관찰을 남긴다. 비밀값·기기 ID·경로·본문은 로그에 넣지 않는다.
    근거 사례: 드라이브의 schema 거부와 downstream 503을 구분할 진단이 없으면 같은 준비 중 화면으로 보였다(#5855·#5573).
15. 테스트 픽스처는 운영의 실제 형태를 대표한다. 정식 기기 ID 문법(`@`·`+` 포함), 새 경로의 pending/admit/등록 상태와 실제 응답 모양을 합성 데이터로 재현하고, 거부·복구도 검증한다.
    근거 사례: 단순 `office-pc` 픽스처는 운영 형태의 device_id 패턴 거부를 놓쳤다(#5855); 실제 식별자·자격증명은 픽스처에 복사하지 않는다.
16. 파일 업로드·파싱·대용량 결과는 컴2 파일 레인이 담당한다. Worker 경로에 새 파일 처리 기능을 추가하지 않는다(#5881).
17. 범위는 채팅/클로(일반 채팅·PC 레인·첨부 문서·자동화)와 축사·SNS(Util)·견적서(B66)·PDF·MD 변환(베타 핵심, 2026-10-28 개정)이다. 미룬 문제는 보류 목록 이슈(#5882)에 적고, 범위를 넓힐 때 그 목록부터 확인한다.

### 0G. MVP/베타 운영 원칙 (Owner, 2026-10-26) — §0F와 충돌 시 0G 우선

#### 운영 원칙 (Owner, 2026-10-26)
1. 극한까지 점검하지 않는다. 실사용에서 오류가 나면 그때 고친다.
2. 기본적인 사용만 되면 바로 다음 단계로 간다.
3. 현재 목표는 완성 — 최소한의 MVP와 베타 사용이다. 견고화·관측성·문서 정비는 막히지 않는 한 뒤로.

#### 점검·보고 규칙
- 배포 후 점검은 일반 채팅 1회. PC 레인 점검은 PC 레인 코드가 바뀐 배포에만 1회.
- 일반 채팅이 아예 안 되면 롤백(복구는 점검이 아니다). 그 외 간헐 오류는 기록만 하고 다음 단계 진행.
- 아스트라 보고는 "됨/안 됨 + SHA 한 줄". 사전점검표·사후표·소명 요구 없음.
- 한 번에 하나씩 지시, 쉬는 로컬은 구현 과제 우선.

## 1. Purpose

AI Revenue Lab separates product authority, design decisions, implementation, validation, CTO review, owner decisions, merge and Production so that fast AI-assisted work does not turn into repeated broad rework.

The repository does not require a fixed `UI → UX → backend` product sequence. The Web CTO selects the smallest evidence slice that answers the current uncertainty.

A separate rule applies when the work contains a **new art direction or material visual redesign**: prove the visual direction cheaply before propagating it broadly.

## 2. Required roles

1. **User / Product Owner** — product goal, priorities, material product/business decisions, explicit owner visual acceptance where applicable.
2. **Web CTO** — current remote audit, work contract, architecture/safety boundaries, visual/evidence gates, final technical review.
3. **Implementation Worker (local model)** — authorized implementation, focused implementation self-check, `DEV_FAST_GATE`, Draft PR/report. In the current operating model this is a local model with GitHub access; after the fast gate passes it may move to the next authorized issue without waiting for the full validation matrix.
4. **Independent Local Validator(s)** — asynchronous independent exact-head browser/OS/hardware/local-runtime validation when required, executed by actors distinct from the Implementation Worker. Windows, Ubuntu and browser/full-regression lanes may run concurrently under separate validator ownership.

One actor may perform several non-independent stages. The same actor must not
claim both implementation and independent Local Validation for the same
revision when independent Local Validation is required.

Canonical machine-readable form of that invariant:

```text
ONE_ACTOR_MAY_PERFORM_MULTIPLE_NON_INDEPENDENT_STAGES
BUT_IMPLEMENTATION_AND_INDEPENDENT_LOCAL_VALIDATION
MUST_NOT_BE_CLAIMED_BY_THE_SAME_ACTOR_FOR_THE_SAME_REVISION
```

Equivalent short form:

```text
IMPLEMENTATION_ACTOR
!=
INDEPENDENT_LOCAL_VALIDATOR
```

## 3. Product-evidence model

Possible evidence targets include:

```text
PRODUCT_FRAMED
COMPETITIVE_DEMO
INVESTOR_DEMO
MVP_VERTICAL_SLICE
SERVICE_LED_PILOT
RUNTIME_PILOT
COMMERCIAL_HARDENING
OPERATING_PRODUCT
```

The work order identifies what is needed now: visual desirability, UX, deterministic simulation, service-led operation, local runtime, live backend/provider, auth/persistence, security or commercial hardening.

UI, UX, backend/runtime, security, deployment, market-reference, commercial and owner-visual verdicts remain separate.

## 3A. MVP delivery closure and validation budget

The operating system optimizes for **validated delivery**, not maximum possible pre-delivery certainty.

When a customer handoff, pilot, or owner-defined delivery target exists, record the accepted handoff blocker set and primary acceptance journey. From that point, validation may expand only when it protects a concrete claim that can still invalidate the handoff.

A new concern is a handoff blocker only when there is concrete evidence of at least one of:

- primary customer journey unusable or materially incorrect;
- authentication/authorization bypass;
- secret, credential, private-data, or material infrastructure leakage;
- data corruption, uncontrolled destructive behavior, or irreversible external harm;
- a P0/P1 failure explicitly named in the work contract or customer promise.

The following default to **post-handoff follow-up**, not new blockers:

- speculative edge cases without a reproduction;
- unrelated legacy debt;
- broad refactors or architecture cleanup;
- additional hardening beyond the accepted MVP threat/failure model;
- optional formats/features not required by the current customer promise;
- repeated re-testing of unchanged surfaces solely because time passed.

### Validation budget

For an MVP closeout, use this order:

```text
1. smallest load-bearing focused regression for the changed defect
2. relevant configured CI for the changed dependency/authority surface
3. bounded Production smoke of the accepted primary journey after deployment
4. broader suites only when the change actually crosses those surfaces
```

Do not start with a repository-wide, product-wide, or all-browser test sweep for a narrow defect unless the change touches shared authority or the work contract explicitly requires that breadth.

If new validation is added after the acceptance matrix is otherwise satisfied, the Web CTO records:

```text
NEW_VALIDATION=
PROTECTED_CLAIM=
WHY_EXISTING_EVIDENCE_IS_INSUFFICIENT=
HANDOFF_BLOCKING_IF_FAILED=YES|NO
```

If those fields cannot be answered concretely, the check is non-blocking follow-up work.

### Fixed handoff gate

Before the final blocker fix is merged, identify the smallest explicit handoff gate:

```text
HANDOFF_BLOCKERS=
HANDOFF_REQUIRED_CHECKS=
HANDOFF_PRODUCTION_SMOKE=
```

Do not silently add new required checks after this point. A later check may join the handoff gate only when it is justified by a new concrete blocker or by a changed high-blast-radius boundary.

Repository CI fan-out may execute more jobs than the handoff requires. Distinguish:

```text
HANDOFF_REQUIRED_CHECK
OBSERVATIONAL_NONBLOCKING_CHECK
```

An automatically triggered unrelated job is not handoff-blocking merely because it exists, is slow, or is still running.

Open P1/P2, hardening, refactor, optional-format, and backlog issues remain non-blocking unless the owner explicitly promotes one or new evidence shows that it invalidates the current customer promise.

### Final Production smoke budget

For a final Production-changing revision, one bounded smoke of the accepted primary journey is the default. Do not repeatedly rerun the same real-account journey without one of:

- a new deployed revision affecting that journey;
- a failed or ambiguous prior smoke;
- a newly reproduced blocker affecting that journey.

```text
UNCHANGED_DEPLOY + PRIOR_CLEAR_PASS != REPEAT_SMOKE_REQUIRED
```

### Evidence carry-forward after main drift

Evidence still belongs to the exact revision that produced it, but unrelated repository drift does not automatically force full revalidation. The Web CTO first determines whether intervening commits affect the tested behavior, transitive dependency, runtime authority, configuration, deployment target, or user-facing surface.

```text
UNRELATED_DRIFT != AUTOMATIC_FULL_RETEST
RELEVANT_DRIFT   = REVALIDATE_AFFECTED_CLAIMS
```

### MVP terminal rule

When:

```text
ACCEPTED_HANDOFF_BLOCKERS=0
FOCUSED_CHANGE_REGRESSION=PASS
RELEVANT_REQUIRED_CI=PASS
REQUIRED_PRODUCTION_SMOKE=PASS
```

the technical disposition is `READY_FOR_CUSTOMER_HANDOFF`.

Exploratory QA may continue after handoff, but it must not delay delivery unless it finds new concrete blocker evidence.

## 3B. Finish-first completion policy

For Padiem platform development, the default active operating mode is **Finish-first** unless the Product Owner explicitly selects another portfolio priority.

```text
PRIMARY_IMPLEMENTATION_AXIS=1
SUPPORTING_BLOCKER_LANES<=2
UNRELATED_IMPLEMENTATION_FANOUT=0
PARALLEL_VALIDATION=ALLOWED
PARALLEL_BLOCKER_REMOVAL=ALLOWED
```

The purpose is to convert already-built source into visible, Production-complete capability rather than maximizing the number of partially completed issues.

A primary axis must describe a user-visible vertical result, not a list of source issues. Record the axis, reference product, current lowest missing dependency, primary blockers, and terminal user result.

For the current Padiem cycle, #3523 defines the axis as Platform -> Engine -> B54 Claw.

Ownership and architecture are decided top-down. Once ownership is known, implementation starts at the lowest missing dependency and moves upward through the vertical slice. Do not keep adding generic capability work when the primary slice is blocked lower in the stack.

Passing a development fast gate releases the actor from waiting on broad unrelated validation, but does not release the actor to unrelated feature work. The actor continues the primary axis, takes one of its concrete blockers, helps reconcile/validate the same axis, or remains idle/background.

A Finish-first axis is not DONE merely because source is implemented, CI is green, or a PR merged.

```text
SOURCE_COMPLETE=YES
MERGED_MAIN=YES
PRODUCTION_ACTIVE=YES
REFERENCE_PRODUCT_E2E=PASS
USER_VISIBLE_RESULT=YES
ROLLBACK_READY=YES
PRIMARY_BLOCKERS=0
```

Until then, report `ACTIVE`.

Shared Padiem Platform infrastructure does not collapse products into one another. Product-local work remains with its product owner. A generic defect discovered inside a product is split to the proper Platform/Core/Engine/Control-Plane owner rather than moving the whole product task into that lane.

### 3B-1. Product-boundary vocabulary carried by the entry point

The following blocks state the product-independence boundary in the exact
literal form reports and work orders use. They were moved here from the
`AGENTS.md` entry point during the 2026-10-23 instruction-index
restoration; `AGENTS.md` links to this section instead of duplicating them.

Product boundaries remain strict. B66 Padiem Quote, B67 Padiem Legal, B62 Padiem Chat, and B54 Padiem Claw are independent products that may reuse Padiem Platform authorities. Shared Platform usage does not authorize moving product-local work into another product's lane.

```text
B66_IS_ENGINE=NO
B66_IS_CLAW=NO
B66_PRODUCT_INDEPENDENT=YES
```

Issue classification before implementation uses the same vocabulary as
`docs/operations/WORKFLOW_STATUS_MODEL.md`:

```text
PRIMARY_BLOCKER
PRIMARY_NONBLOCKING_FOLLOWUP
UNRELATED_BACKLOG
```

Only `PRIMARY_BLOCKER` may preempt the primary lane.

## 3C. Implementation closeout + batched product verification issues

**Owner decision (2026-10-11): one enduring validation issue per product/release acceptance scope, rather than one lingering verification issue for every finished implementation.** This section controls GitHub issue bookkeeping; it does **not** weaken required pre-merge evidence, authority/security checks or the Finish-first product acceptance gate in §3B.

### Issue types and closure authority

1. **Implementation issue (A, C, D ...):** one bounded code/config/document deliverable. To close it, prove the issue's **implementation acceptance**: reviewed exact-head changes; focused tests; applicable required CI, independent validation (or `NOT_REQUIRED` with reason), security and owner gates; authorized merge to the intended branch. Post the PR, exact head/merge SHA, test result and link to the canonical product validation issue before closing. Use `SOURCE_COMPLETE=YES; PRODUCT_LIVE_E2E=NOT_YET_PROVEN` when applicable. A merged PR alone does **not** close an issue whose original acceptance explicitly required operational activation or end-user delivery. Complete that scope or transparently split the remaining work into the existing validation issue **only if it is genuinely validation rather than missing implementation**; do not silently redefine the owner's deliverable.
2. **Consolidated verification issue (B):** one **OPEN** issue per product + release/primary user journey, created when the first implementation needs later integrated evidence; **reuse the existing matching issue** before creating a new one. It owns the actual browser/Production E2E evidence and cross-component test matrix, not a second implementation queue. For Hark WEB-FIRST, use existing **#3936** under epic **#3928**; don't create a parallel Hark test ticket for every PR.
3. **Epic/feature acceptance:** remains open while its own user-visible milestone is incomplete. Closing implementation slices does not imply B/epic closure, operational readiness, production activation, or customer handoff.

### Continuous accumulation: A → B, C → B, D → B

When a new implementation finishes, update B's **single living checklist** with:

- implementation issue/PR and **exact tested SHA / merged SHA**;
- specific affected **user-visible acceptance claim**, component and target environment;
- whether the claim is `SOURCE_CI`, `INDEPENDENT_VALIDATION`, `STAGING` or `PRODUCTION_AUTHENTICATED_E2E`;
- `PENDING | BLOCKED | FAILED | PASS | NOT_REQUIRED`, concrete blocker and immutable **sanitized evidence link**; do not mark `PASS` from an unexecuted workflow or mock;
- any necessary user-authorized credentials, billable calls, external WRITE/SEND, and rollback boundaries.

Deduplicate an existing test rather than appending identical test instructions for each PR. A, C and D may be closed separately while their remaining **legitimate post-merge integrated checks** accumulate in B. If E2E proves an actual code defect, open or reopen only the **specific repair implementation issue**, with a reproduction and B backlink. Do not multiply generic verification issues.

### Efficient validation and truthful finalization

Run B's consolidated journey after the relevant set of changes is deployed/ready; use one bounded end-to-end run covering the accepted path plus required negative authorization cases. Retest only affected claims if a later revision changes the behavior. **Do not batch or postpone** security checks, exact-head CI, independent validation expressly required **before merge**, irreversible external mutations, or an owner-reserved approval. The §3A handoff gate and §3B Finish-first `AXIS_DONE` remain unchanged.

Close B only when **every required scoped checklist item** has real, reproducible evidence; the tested Production version and applicable owner authorization are identified; required external/browser/file outputs and negative controls pass; and known blocking failures are resolved. A blocked Production tool/credential does not count as PASS. B's issue title/body should identify a **single product release/acceptance journey**, not a rolling repository-wide all-products QA bucket.

**Compact implementation closure record:**

```text
IMPLEMENTATION_ISSUE=#A
PR=#NNNN
TESTED_HEAD_SHA=<exact>
MERGE_SHA=<exact>
IMPLEMENTATION_ACCEPTANCE=PASS
REQUIRED_PREMERGE_GATES=PASS|NOT_REQUIRED_WITH_REASON
PRODUCT_LIVE_E2E=PENDING|PASS|NOT_APPLICABLE
CONSOLIDATED_VERIFICATION_ISSUE=#B
ISSUE_CLOSE_REASON=IMPLEMENTATION_SCOPE_COMPLETE
```

**Compact B checklist record:**

```text
SOURCE_ISSUE=#A
PR=#NNNN
ACCEPTANCE_CLAIM=<one concrete user-visible contract>
ENVIRONMENT=PRODUCTION_AUTHENTICATED_E2E
STATUS=PENDING|BLOCKED|FAILED|PASS|NOT_REQUIRED
EVIDENCE=<immutable link or blocker>
```

## 4. Mandatory design-gate overlay for visual redesign

When the work is a new visual system, owner-rejected redesign or broad multi-route visual reset, use:

```text
PRODUCT FRAME
→ REFERENCE TRANSLATION
→ ANCHOR SCREEN
→ ANCHOR_DIRECTION_LOCKED
→ 2–3 ARCHETYPES
→ ARCHETYPE_SYSTEM_PASS
→ FULL_EXPANSION_ALLOWED
→ FULL-SURFACE CONTACT SHEET
→ FULL_SURFACE_VISUAL_PASS
```

UX/backend work may proceed separately when authorized, but an unproven art direction must not be applied across the whole product.

The Web CTO must reject a work order that says, in effect, “redesign all pages now and we will see if the concept works afterward,” unless the product is so small that all distinct surfaces are themselves the archetype set.

## 5. Reference discipline

For material visual work, references are implementation inputs only after they are translated into:

```text
OBSERVE
ADOPT
REJECT
TRANSLATE
TARGET SURFACE
VERIFY
```

Business 06 World Feed is the positive portfolio methodology reference because it established a visual baseline and explicit adopted/rejected patterns before UX expansion. Its actual look is not a portfolio template.

## 5A. Technology landscape gate before substantial implementation

For a net-new or substantially expanded commodity capability, the Web CTO must determine whether existing technology should be bought, adopted, adapted or isolated before authorizing custom code.

Required default sequence:

```text
SEARCH
→ REUSE_INTERNAL
→ BUY
→ ADOPT
→ ADAPT
→ SIDECAR / LOCAL_SERVICE
→ BUILD_FROM_SCRATCH
```

The scan covers credible OSS and commercial options. A paid option is valid when it reduces total time/cost or materially improves quality, support or reliability.

For broad ecosystems, review a bounded candidate set and shortlist at most three. Research must reduce implementation time rather than become an exhaustive project.

Custom build requires explicit justification unless the parent decision already fixed the implementation or the change is a bug fix/tiny glue slice.

Preserve Padiem product authorities, but do not reject an adopted project solely because its internals contain their own parser/decoder/model stack. The relevant invariant is `SECOND_PRODUCT_AUTHORITY=0`.

Canonical details: `TECHNOLOGY_ADOPTION_POLICY.md`.

Technology scans run in parallel with already-approved in-flight implementation. Do not retroactively stop an accepted work order solely because a broader OSS/commercial scan was opened. Apply scan findings to subsequent slices or an explicit component replacement unless CENTRAL records a concrete pause reason.

## 5B. Existing-foundation reassessment before new implementation

Padiem is in a **finish, connect and improve** phase for its established platform foundations. For each newly assigned implementation slice, conduct a **proportionate existing-foundation check first**. This is an execution preflight under this policy, **not** a second technology-adoption authority or a requirement to re-audit an already accepted decision.

Default order:

```text
FRESH-READ CURRENT AUTHORITY / RUNTIME
→ IDENTIFY THE ACTUAL GAP OR REPRODUCE THE FAILURE
→ FIND EXISTING IMPLEMENTATION AND OFFICIAL PLATFORM MECHANISM
→ REUSE / CONFIGURE / REPAIR / EXTEND THE SMALLEST OWNED SURFACE
→ RUN FOCUSED CONTRACT AND RELEVANT RUNTIME CHECKS
→ BUILD NEW MACHINERY ONLY IF A CONCRETE GAP REMAINS
```

Before proposing a new module, tool, workflow, deployment lane, store, adapter, policy or abstraction:

1. Check the current main/issue/PR and accepted architecture decision, plus the existing owner module, configuration, deployment workflow and reusable guard. Separate **source present**, **runtime wired**, **tested**, and **Production active**; do not infer one from another.
2. Identify the specific missing user-visible behavior, failed contract or verified defect. For an external service or platform constraint, verify its current official documentation and supported configuration/API/CLI path before inventing a workaround or blaming the provider.
3. Compare `RETAIN_AS_IS`, `CONFIGURE_OR_CONNECT`, `REPAIR_EXISTING`, `EXTEND_EXISTING`, `ADOPT_OR_ADAPT`, and `BUILD_NEW`. Choose the smallest evidence-backed change. Do not replicate an existing deployment, authorization, model-routing, persistence or validation authority.
4. Reuse tests, guards, official tooling and rollback procedures where available. A green mock or source test does **not** establish real service integration, live approval, secret/binding preservation, or Production activation.
5. Scope validation to the changed claim and actual target environment; do not add a Linux/WSL/browser/production matrix merely as ceremony. Preserve required security and release gates, and record a rollback or fail-closed path for changes that can affect live service.
6. If the preferred solution is `BUILD_NEW`, identify the exact gap existing components cannot meet, why a small repair/extension or upstream capability is insufficient, and the owner of the new component.

A concise work-order or PR note is sufficient; do not create another policy file, issue, checklist bureaucracy or custom framework merely to document this step:

```text
CURRENT_SOURCE_AND_RUNTIME=
VERIFIED_GAP_OR_FAILURE=
OFFICIAL_REFERENCE_IF_RELEVANT=
EXISTING_REUSE_OR_REPAIR_CANDIDATE=
DECISION=RETAIN_AS_IS|CONFIGURE_OR_CONNECT|REPAIR_EXISTING|EXTEND_EXISTING|ADOPT_OR_ADAPT|BUILD_NEW
MINIMAL_CHANGE_AND_PROTECTED_CONTRACT=
FOCUSED_VERIFICATION_AND_ROLLBACK=
```

For a trivial correction, fill only the material fields in a sentence or two. If an accepted parent already supplies the evidence, cite it rather than repeating research. This check **does not** retroactively freeze approved in-flight work or expand a fixed MVP handoff gate; it governs the next consequential change and flags only concrete security, data-loss or contract hazards for explicit escalation. Review/update existing canonical documentation only where an actual source-of-truth mismatch is established.

## 6. Work identity before implementation

Record:

- repository/default branch;
- machine identity (`MACHINE_IDENTITY`) when the work can run on more than one machine; follow `MULTI_MACHINE_LOCAL_WORKTREE_POLICY.md`;
- exact current base SHA;
- branch;
- Issue/owner/work-order authority;
- selected evidence stage;
- current visual gate if applicable;
- allowed/forbidden paths;
- non-goals;
- required automated checks;
- independent validation requirement;
- owner-only decision requirement;
- merge/deployment authority;
- acceptance criteria.

`latest main` is not revision identity.

## 7. Web CTO responsibilities

The Web CTO:

- reads current remote state rather than trusting previous reports;
- fixes exact scope and evidence target;
- enforces reference/anchor/archetype gates for material visual work;
- defines data/security/deployment/non-goal boundaries;
- inspects actual diff and current exact head;
- checks CI and validation sufficiency;
- when a contract defect is found at one runtime trust boundary, traces the same field/meaning through downstream parser, builder/projector, serializer, export and write boundaries before declaring the class closed;
- distinguishes explicit `null`, `undefined`, and missing required properties unless a canonical contract explicitly equates them;
- reviews rendered visual evidence rather than treating CI as taste evidence;
- rejects stale-head evidence unless applicability is documented;
- prevents legacy visual debt from being mislabeled as a new design system;
- assigns final technical `READY / CONDITIONALLY_READY / NOT_READY`.

These statuses never manufacture owner approval or commercial approval.

## 8. Implementation Worker (local model) responsibilities

The developer:

- starts from the authorized exact base or reports drift;
- changes only authorized paths;
- implements only up to the current authorized visual/product gate;
- does not expand all routes when the work order authorizes only an anchor/archetype slice;
- runs the smallest relevant implementation self-checks and the work-order `DEV_FAST_GATE`;
- after `DEV_FAST_GATE=PASS`, records `DEV_ACTOR_RELEASED=YES` and may move immediately to the next authorized issue instead of waiting for Windows/Ubuntu/full-browser validation;
- per-slice proof selection (moved from the `AGENTS.md` entry point during the 2026-10-23 instruction-index restoration): for Windows-first slices, the focused Windows proof may be the `DEV_FAST_GATE`. For web/backend slices, use the smallest focused web/API/contract proof that actually exercises the change. Do not require every supported OS/browser in the implementer's synchronous critical path.
- records exact base/head, files, diff, commands, exits, pass/fail/skip counts and limitations;
- identifies legacy/cascade debt encountered;
- does not self-assign independent validation or final CTO readiness.

The fast gate is not merge approval. It exists to keep implementation throughput independent from slower cross-platform validation.

## 8A. GitHub report handoff

Padiem/CLAW local workers use GitHub as the canonical reporting handoff. The related `ai-revenue-lab` Issue/PR contains only the compact result and immutable report pointers; the complete long-form report is committed to the private `skerishKang/workdiary` repository under `padiem-reports/YYYY-MM-DD/<CLAW>/<task>.md`.

Required pointer block:

```text
REPORT_REPO=skerishKang/workdiary
REPORT_PATH=padiem-reports/YYYY-MM-DD/<CLAW>/<task>.md
REPORT_COMMIT=<immutable workdiary commit SHA>
```

Google Drive/rclone reporting is disabled for this workflow. Large screenshots, Playwright traces, archives and logs should use GitHub Actions artifacts when practical. Passwords, secrets, tokens, cookies, private keys and database credentials must never appear in reports, comments or artifacts.

CENTRAL reads the private report directly from GitHub and independently fresh-reads current main, Issue/PR/head/diff/CI before consequential action. The Product Owner is not required to relay the long report through chat.

Canonical details: `GITHUB_REPORT_HANDOFF_POLICY.md`.

## 9. Visual implementation discipline

For a redesign:

- weak legacy shells may be replaced when the visual thesis requires it;
- redesign is not synonymous with recoloring/material skinning;
- a successful landing page does not prove inner-route coherence;
- a later-route failure must be diagnosed before a new version/concept is created;
- superseded visual generations should leave the active rendering path once the new system is proven;
- repeated `!important` override escalation is a debt signal, not completion.

Follow `CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md`.

## 10. Local Validator responsibilities

Independent validation is **selective**, not automatic for every P0/P1. A bounded deterministic fix defaults to `NOT_REQUIRED` when focused regression + relevant CI can prove the pre-merge claim and live behavior is already covered by the separately authorized post-deploy Production smoke. Require an independent validator when the claim materially depends on a distinct browser/OS/hardware/local-service environment, a high-risk runtime boundary not covered by CI, or an explicit work-contract gate.

When independent validation is required, the validator records:

- expected/actual exact head;
- environment;
- repository/source-modification state;
- commands/exits;
- journeys/results;
- browser/device evidence;
- console/page/network/asset/overflow failures;
- artifacts and reproduction evidence.

Validation lanes should be assigned explicitly when relevant:

```text
VALIDATOR_WINDOWS
VALIDATOR_UBUNTU
VALIDATOR_BROWSER
VALIDATOR_FULL_REGRESSION
```

They may run in parallel while the implementation worker continues other authorized work. A failing validator owns reproduction and may own a bounded repair in its own worktree/repair branch.

If the validator changes product source, that actor has become a repair/implementation actor for the new revision. The modified run is not independent validation of that new revision; revalidation must occur on the resulting exact head by another independent validator when independence is required.

A completed independent validation is not considered auditable until the related PR contains a discoverable exact-head record naming the validator, result and immutable report/artifact pointer (or a recorded `NOT_REQUIRED` reason). The evidence may live in the private report repository, but the PR must point to it.

## 11. CI and automated checks

CI uses three distinct gates:

```text
GATE_A = DEV_FAST_GATE
  smallest focused checks proving the implementation slice
  blocks the implementing actor only until PASS

GATE_B = ASYNC_VALIDATION
  Windows / Ubuntu / browser / full-regression lanes
  may run in parallel under separate validator actors
  failures block merge of the affected revision, not unrelated development

GATE_C = FULL_VALIDATION
  required configured/relevant exact-head checks before merge
```

A newer PR head should cancel superseded same-PR validation runs where the workflow can do so safely. Draft/synchronize feedback should prefer fast relevant checks; broad cross-platform/full matrices belong to asynchronous validation and the final merge gate rather than the implementation actor's synchronous loop.

Repository-wide test selection and stop rules are defined by `TEST_SCOPE_AND_DELIVERY_POLICY.md` and apply to every Business/app/package.

CI is required when configured/relevant but is never universal completion evidence.

- static/lint tests do not prove visual hierarchy;
- browser mechanics do not prove cross-state art direction;
- screenshots of Entry do not prove a whole site;
- mock/provider tests do not prove live provider behavior;
- HTTP 200 does not prove reviewed Production revision.
- unrelated green jobs do not neutralize a red external security/compliance check.

Use the evidence type that matches the claim. A red external security/compliance signal must be resolved or carry an explicit authorized disposition/waiver with reason before merge; silence on a later squash/main commit is not evidence that the original signal disappeared.

## 12. Revision invalidation

정확 리비전 증거·머지 전 current main 재확인 절차: 폐지(#5895, 2026-10-27) — 대체: 대상 앱 경로 기준 main 최신(main_currency_guard).

## 13. Safety and scope rules

- no ordinary direct `main` feature mutation;
- no unrelated dirty-file inclusion;
- no out-of-scope mutation without contract update;
- no test/assertion/security weakening merely to pass;
- no hidden failure/skip/warning;
- no secrets, credentials, private evidence or personal data in public source/logs/artifacts;
- no hidden validator source edits;
- no `git worktree remove --force` on Windows while the worktree contains junctions/symlinks/reparse points into shared dependency directories; unlink the reparse point first and verify the target remains intact;
- no wrong-project Preview/deployment as product evidence;
- no unverified live-revision claim.

### 13A. Owner-only model/provider decisions

Model/provider selection is not an autonomous Web CTO or worker decision. When a task encounters model selection, replacement, benchmarking, primary/fallback order, provider routing, model-specific credentials/bindings, or activation/deployment, the agent must stop that model work and ask the Product Owner for an explicit current decision.

A model mention, historical approval, worker recommendation, passing benchmark, existing branch, or product blocker does not create model-change authority. Non-model product work may continue when it does not depend on choosing a model.

Canonical contract: `MODEL_CHANGE_OWNER_APPROVAL_POLICY.md` and tracking issue `#3571`.

## 14. Owner visual authority

The CTO may reject objective defects: overflow, clipping, unreadable contrast, broken hierarchy, functional controls, responsive breakage, inconsistent typography/cross-state system, visible legacy leakage and product-contract mismatch.

Only explicit current owner acceptance creates `OWNER_UI_APPROVED`.

```text
ANCHOR_DIRECTION_LOCKED != OWNER_UI_APPROVED
ARCHETYPE_SYSTEM_PASS != OWNER_UI_APPROVED
FULL_SURFACE_VISUAL_PASS != OWNER_UI_APPROVED
READY != OWNER_UI_APPROVED
DEPLOYED != OWNER_UI_APPROVED
```

## 15. Backend and service-led evidence

Select the smallest appropriate mode:

```text
NO_BACKEND
DETERMINISTIC_SIMULATION
SERVICE_LED
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
PILOT_RUNTIME
COMMERCIAL_HARDENING
```

Backend may start early when it proves product value. Do not build it as ceremony.

Authentication is not mandatory for every MVP; authorization is mandatory whenever private records can be read/mutated.

## 16. Merge and Production

For focused changes inside a stable design system, the live Production owner-review loop may be appropriate after exact-head validation.

For a new art direction/material redesign, follow `LIVE_PRODUCTION_UI_REVIEW_POLICY.md`: anchor and archetype proof precede broad expansion/whole-product live review.

After authorized merge, verify the configured Git-connected Production against the resulting main/release revision.

### Verdict record requirement

Before merge, the Web CTO (CENTRAL) must post an auditable `CTO_FINAL_REVIEW` record as a PR review or PR comment containing the exact head SHA and results for the **applicable** gates. For a tiny bounded fix, a compact exact-head checklist is sufficient; the full template is not a required ceremony. Prose-only verdict assertions with no reviewable fields are not sufficient.

For P0/P1 or otherwise critical PRs, the final review also records the exact-head independent-validator record (or `NOT_REQUIRED` reason), any load-bearing mutation/differential proof requested by the work contract, and the disposition of every external red security/compliance signal.

### Terminal states for "independent gate pending"

"independent gate pending" is not a mergeable state. Before merge the PR must record one of:

- a link to a completed `LOCAL_VALIDATION_REPORT.md` instantiation for the exact head, or
- `NOT_REQUIRED` with an explicit reason.

### Owner-delegated merges

A merge may be executed by the Implementation Worker only under explicit owner delegation. Delegation must be:

- single-purpose (one named PR/revision),
- head-SHA-pinned 무효화: 폐지(#5895, 2026-10-27) — 대체: 대상 앱 경로 기준 main 최신(main_currency_guard).
- condition-checked at execution time (re-read remote state; required CI/gate results still valid).

## 17. Historical records

Historical phase, UI approval, direction-freeze and audit records remain truthful evidence of their time. They do not override this current operating policy.

In particular, a historical product direction document is now an implementation input/hypothesis until it satisfies the current anchor/archetype process for new material visual work.

## 18. Supporting documents

- Design OS: `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`
- Visual standard: `ui-ux/UI_UX_VISUAL_DIRECTION_STANDARD.md`
- Workflow states: `WORKFLOW_STATUS_MODEL.md`
- Evidence: `EVIDENCE_REQUIREMENTS.md`
- UI/UX/backend dimensions: `UI_UX_BACKEND_PHASE_GATES.md`
- Frontend structure: `CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md`
- New/rebuilt Business playbook: `NEW_BUSINESS_UI_FIRST_PLAYBOOK.md`
- Live visual review: `LIVE_PRODUCTION_UI_REVIEW_POLICY.md`
- GitHub report handoff: `GITHUB_REPORT_HANDOFF_POLICY.md`
- Owner-only model/provider decisions: `MODEL_CHANGE_OWNER_APPROVAL_POLICY.md`
- Templates: `templates/`

## 보류 목록 (나중에 반드시 확인)

정본 이슈: #5882. 범위를 넓힐 때는 이 목록부터 다시 연다.

- [ ] 웹 XLSX 원본 상한 1MiB → 1GiB(#5878 Draft: 선택 저장소·DB CHECK 마이그레이션 071·게이트 미완). 1GiB는 컴2 파일 레인 전제.
- [ ] B66 상수 변경(#5877: 인증 미리보기·견적 번들·키라/체험 파일럿·가이드 초안·견적 이력 128KiB→1MiB 등)은 배포되지만 B66 흐름 실측 검증을 하지 않음 — 범위 재개 시 B66 E2E 1회.
- [ ] SNS 메시지 상한 1MB→10MiB(#5872) 실측 미검증(Slack/Telegram 실제 한도는 공급자 기준).
- [ ] Util은 등급 전달(#5810)까지만. Util 전용 오류 표시·스트리밍 없음.
- [ ] 프로젝트 파일 본문 160KB / content_chars 40,000 DB CHECK(003/068/069) — 올리려면 project_files 재생성 마이그레이션+게이트.
- [ ] 음성 STT 오디오 5MiB(base64), Drive 케이스폴더 PDF 4MB — 업로드 상한 통일(1GiB)은 컴2 파일 레인 이후.
- [ ] #2824 격리 파서 전송 상한 512,768B — 파서 레인 소유자 판단 대기.
- [ ] BYOK 2.0("키만 넣으면 공급자·엔드포인트 자동 등록") 설계 — Owner 사업 방향, 구현 시점 미정.
- [ ] 다른 레인 코드가 Chat 배포에 실려 나가는 문제(#5817 파서 바인딩 미부착, #5850·#5862 등) — 배포마다 변경 스캔은 하되 기능 검증은 안 함.

바인딩은 wrangler.toml이 정답, wrangler.toml 변경 PR은 CTO 검토 필수.
