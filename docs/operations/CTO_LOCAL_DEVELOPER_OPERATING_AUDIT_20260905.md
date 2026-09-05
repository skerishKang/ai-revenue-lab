# 웹 CTO ↔ 로컬 개발 모델 운영 체계 감사 (2026-09-05)

- Status: **AUDIT_REPORT** (증거 보고서 · 정책이 아님)
- Audit target: Web CTO(웹 모델) → Web Developer(로컬 모델) → Local Validator 체계
- Audited repository: `skerishKang/ai-revenue-lab`
- Audited base: `main @ 18b6164b99aea0b7534064bd37136dc989b0259f`
- Audit date: 2026-09-05 (UTC)
- Evidence type: `REPOSITORY_AND_GITHUB_API_MEASUREMENT` — 실행한 측정과 그 결과만 기록한다.

## 0. 한 줄 결론

```text
FACTORY_THROUGHPUT           = VERY_HIGH     (정상 작동)
CONTRACT_QUALITY             = HIGH          (정상 작동)
CI_HEALTH                    = GREEN         (정상 작동)
SCOPE_DISCIPLINE             = GOOD          (정상 작동)
CTO_REVIEW_RECORD            = MISSING       (결함 · 심각)
PR_CONTRACT_TEMPLATE_USAGE   = 0%            (결함 · 심각)
INDEPENDENT_VALIDATION       = NEVER_CLAIMED (결함 · 심각)
GOVERNANCE_GUARD_ITSelf      = RED+UNWIRED   (결함 · 심각)
LOCAL_VS_CI_ENVIRONMENT      = DIVERGED      (결함 · 높음)
ATTRIBUTION_ECONOMIC_LEDGER  = MISSING       (결함 · 보통)
```

**요약**: "공장"은 잘 돌아간다. 그런데 **검사관의 판정이 저장소에 남지 않는다.**
구현 증거(테스트 수치, 경계 선언, canary)는 충실히 생산되는 반면, 그 증거를
승인/기각하는 Web CTO의 판정(`READY / CONDITIONALLY_READY / NOT_READY`)은
저장소 어디에도 기록되지 않는다. 지금 구조는 **"개발자가 스스로 보고하고 스스로
머지하는" 단일 행위자 파이프라인**에 가깝고, `AGENTS.md`가 요구하는
행위자 분리(implementation ≠ independent validation)는 실제로는 작동하지 않는다.

---

## 1. 측정 방법

| 측정 | 대상 | 방법 |
|---|---|---|
| PR 리뷰/승인 | 머지된 PR 60건 | `gh pr list --json reviews,reviewDecision` |
| PR 생애주기 | 머지된 PR 60건 | `createdAt`→`mergedAt` |
| 체크 완료 시점 | 머지된 PR 25건 | `commits/{headSha}/check-runs` |
| CI 결과 | 최근 60건 PR | `statusCheckRollup` 결론 집계 |
| `main` 실행 결과 | 최근 60 runs | `gh run list --branch main` |
| PR 본문 템플릿 준수 | 머지된 PR 40건 | `.github/pull_request_template.md` 섹션 정규식 매칭 |
| 이슈 계약 품질 | 최근 이슈 25건 | 섹션/키워드 존재 여부 |
| 산출물 분포 | 머지된 PR 200건 | 제목 태그(`b54`/`b62`/`engine`…)별 additions |
| 로컬 스위트 재현 | Core 스위트 | Linux/Python 3.11 샌드박스에서 `pytest -q` 실행 |
| 거버넌스 가드 | `docs/operations/tests/` | 동일 환경에서 실행 |

표본은 모두 **최근 것**이며, 오래된 이력을 대표하지 않는다.

---

## 2. 잘 되고 있는 것 (유지할 것)

### 2.1 작업 계약(Work contract) 품질 — 높음

최근 이슈 25건은 Web CTO가 작성한 계약으로 보이며 품질이 높다.

```text
Purpose / 배경          18/25
Acceptance / 수락기준   22/25
보안·배포 경계 선언      23/25     (PRODUCTION_MUTATION = 0 등)
Required tests           9/25
Non-goals 명시           0/25      ← 유일한 구조적 결함(§3.6)
```

예: `#1890`(Core 문서 정규화)은 `MAX_TEXT_CHARS = BOUNDED`, `OOXML_PATH_TRAVERSAL = REJECTED` 같은
불변식과 Required tests, Acceptance 블록을 갖춘 완전한 계약이다.
**이 계약 품질이 전체 파이프라인의 품질을 떠받치고 있다.**

### 2.2 범위 통제 — 양호

최근 머지 PR 30건 중 **제품 영역을 2개 이상 건드린 PR은 3건(10%)** 뿐이고,
그 3건도 계약상 정당화된다(B62 어댑터 축소, identity binding 게이트).

### 2.3 CI는 실제로 초록색

- 최근 머지 PR 60건의 체크 결론: **SUCCESS 570 / SKIPPED 55 / FAILURE 0**
- `main` 최근 60 runs: success 53 / failure 7 (실패 7건은 §3.4 참고)

### 2.4 게이트를 약화시키지 않음 (중요)

`b62-control-plane-identity-binding-gate`가 Cloudflare 전파 지연으로 flaky하게
실패했을 때, 세 차례의 후속 PR(#1896 → #1898 → #1899) 모두 **fail-closed를 유지**했다.
#1899는 재시도(최대 4회, 5초 간격)를 추가하면서도 마지막 `test "${latest}" = "${active}"`와
`// empty` 가드를 남겼고, 그 사실을 소스 계약 테스트로 고정했다.
→ **"통과를 위해 테스트를 약화하지 말라"는 규칙이 실제로 지켜지고 있다.**

### 2.5 정책 문서가 안정적

`AGENTS.md`, `AI_DEVELOPMENT_OPERATING_POLICY.md`, `EVIDENCE_REQUIREMENTS.md`,
`WORKFLOW_STATUS_MODEL.md`의 마지막 변경은 **2026-08-14**이다.
즉 로컬 개발 모델이 자기를 규율하는 규칙을 고치지 않았다 — **가드레일 침식 없음**.

### 2.6 Draft PR / 스택 관리

열린 PR #1900은 승인 대기 중 슬라이스(S2/S3)를 **DRAFT로 묶어** 올리고,
`origin/main 18b6164b` 기준 drift를 점검했다. 좋은 습관이다.

---

## 3. 깨져 있는 것

### 3.1 [P1] CTO 최종 검토 기록이 존재하지 않는다

```text
MERGED_PRS_WITH_REVIEW      =  0 / 60
MERGED_PRS_WITH_APPROVAL    =  0 / 60
CTO_STATUS_BLOCK_IN_PR_BODY =  0 / 40
FILLED_CTO_FINAL_REVIEW     =  0    (repo-wide, templates/ 제외)
FILLED_CTO_WORK_ORDER       =  0
FILLED_LOCAL_VALIDATION_RPT =  0
```

- 모든 PR은 동일 계정(`skerishKang`)이 열고 머지한다. 리뷰 코멘트는 전부
  Cloudflare Pages 봇 코멘트다.
- `docs/operations/templates/CTO_FINAL_REVIEW.md` 등 4개 템플릿은 존재하지만
  **채워진 인스턴스가 저장소에 0건**이다(AGENTS.md와 operations/README.md에서의
  참조만 존재).
- PR #1900 본문에는 `S2 previously CTO-approved`라고 적혀 있으나, 그 승인을
  증명하는 산출물이 저장소에 없다.
  → `WORKFLOW_STATUS_MODEL.md` §8이 요구하는 `NOT_REVIEWED/NOT_READY/CONDITIONALLY_READY/READY`
  판정이 **SHA에 귀속되지 않는다**. 나중에 "누가 무엇을 승인했는지"를 복원할 수 없다.

**영향**: 승인이 채팅에만 존재하므로 감사·회귀 분석·실패 원인 추적이 불가능하다.
`AGENTS.md`의 "`READY`는 기술/검토 판정이며 자동 머지 명령이 아니다"가 사실상 무력화된다.

### 3.2 [P1] PR 템플릿 준수율 0% (핵심 섹션)

`.github/pull_request_template.md`가 요구하는 섹션의 실제 작성 비율(최근 40건):

```text
## Scope                    18/40
## Authority / revision      0/40   ← base/head SHA 신원
## Evidence dimensions       0/40
## Implementation evidence   0/40
## Independent validation    0/40
## Owner-only decisions      0/40
## CTO final status          0/40
## Completion checklist      0/40
```

부수 측정: 본문에 SHA가 아예 없는 PR **27/40**, 테스트·증거 서술이 없는 PR **13/40**.
PR 본문의 자유 서술("## Purpose / ## Changes / ## Non-goals / ## Verification")은
충실하지만, **정책이 요구하는 필드를 담지 않는다.** 템플릿은 존재하나 강제 장치가 없다.

### 3.3 [P1] 독립 검증(Independent Local Validator) 역할이 한 번도 수행되지 않음

- `LOCAL_VALIDATION_REPORT.md` 인스턴스 0건.
- PR #1900 스스로 `independent gate pending`이라 적고, 그 상태로 스택이 쌓인다.
- 구조적 원인: 구현자(로컬 모델)와 검증자가 **동일 행위자**이므로
  `AGENTS.md`의 행위자 분리 규칙을 만족할 방법이 현재 워크플로에 없다.
- 완화 장치로 "implementation self-check / non-independent"라고 정직하게 표기하는
  관행은 있다(PR #1900, #1899). **표기는 정직하지만, 그 다음 단계가 없다.**

### 3.4 [P1] 거버넌스 가드가 빨간불이고 CI에 연결되어 있지 않다

`docs/operations/tests/test_operating_policy_consistency.py`를 실행하면:

```text
2 failed, 4 passed
  FAIL test_actor_separation_invariant_is_consistent
  FAIL test_active_policy_does_not_restore_mandatory_ui_ux_backend_sequence
```

- 두 실패는 **정책 위반이 아니라 토큰 불일치**다.
  1. `ONE_ACTOR_MAY_PERFORM_MULTIPLE_NON_INDEPENDENT_STAGES` 토큰이 `AGENTS.md`에는 있고
     `AI_DEVELOPMENT_OPERATING_POLICY.md`에는 없다(같은 규칙을 다른 문장으로 서술).
  2. `UI_UX_BACKEND_PHASE_GATES.md`에 테스트가 찾는
     `not a mandatory sequential ceremony` / `SERVICE_LED_PILOT` 문자열이 없다.
- **이 테스트를 실행하는 워크플로가 없다.** (`docs/operations/**`를 경로 필터로
  잡는 워크플로는 `p01-deployment-boundary-guard.yml`뿐이며, 그것도 다른 파일을 본다.)
- 결과: **2026-08-14(#626) 이후 3주간 아무도 이 가드를 실행하지 않았고, 따라서
  가드는 보호를 제공하지 않았다.**

### 3.5 [P2] 로컬(Windows/3.11) ↔ CI(ubuntu/3.12) 환경 불일치

PR #1900 본문 기준 로컬 자체 검증 결과:

```text
Engine full : 853 passed, 2 errors   (Windows env-var-length streaming artifact)
Core named  :  51 passed, 1 failed   (Windows OOXML malformed-path artifact, #1894)
```

감사자가 Linux/Python 3.11 샌드박스에서 Core 전체 스위트를 실행한 결과:

```text
817 passed in 18.95s      (FAILURE = 0)
```

원인 확인: `tests/test_document_normalization.py`의
`test_ooxml_malformed_missing_dtd_encryption_and_paths_fail_closed`는
위험 경로 후보에 `a\b.xml`(백슬래시)을 포함한다. CPython `zipfile.ZipInfo.__init__`은
`if os.sep != "/" and os.sep in filename: filename = filename.replace(os.sep, "/")`로
Windows에서 백슬래시를 슬래시로 정규화하므로, Windows에서는 **악성 엔트리를 만들 수 없어**
테스트가 실패한다. 프로덕션 동작 자체는 안전하지만:

1. **보안 관련 테스트를 로컬에서 실행할 수 없다.**
2. "known Windows artifact"라는 라벨이 붙은 실패가 상주하므로,
   **그 뒤에 진짜 실패가 숨을 수 있다**(`no hidden failure` 규칙과 충돌).
3. Engine은 `requires-python >= 3.12`인데 로컬은 3.11로 보고됨 → 런타임 불일치.

### 3.6 [P2] 계약에 Non-goals가 없다

최근 이슈 25건 중 **non-goals / out-of-scope 명시 0건**.
계약이 "무엇을 하지 않는가"를 적지 않으므로, 범위 초과를 사후에 판정할 기준이 없다.
(다행히 실제 범위 초과는 10% 미만이지만, 이는 규칙이 아니라 우연에 가깝다.)

### 3.7 [P2] 처리량이 검토 용량을 초과한다

```text
MERGED_PRS        = 200  (2026-09-01 ~ 09-05, 4일)   ≈ 50 PR/day
ADDITIONS         = 159,612 lines
MEDIAN_OPEN_TIME  ≈ 7분     (37/60 이 10분 미만)
ISSUES_CREATED_7D = 402   vs  ISSUES_CLOSED_7D = 308   (백로그 증가)
```

- 50 PR/day를 사람(또는 웹 CTO 1인)이 정밀 검토하는 것은 물리적으로 불가능하다.
- 실제로는 **검토 0건**이므로(§3.1) 일관성은 있지만, 그 일관성이 "검토 생략"이다.
- 최근 25건 중 **8건(32%)은 모든 체크가 끝나기 전에 머지**되었다
  (최대 12.8분 먼저). 다행히 해당 head에서 FAILURE는 없었다.

### 3.8 [P2] 산출물의 절반 이상이 "공장 자체"를 만드는 데 쓰인다

머지 PR 200건 기준 additions 분포:

```text
b54 (Local Agent / OAuth / Control Plane)   64 PRs   82,099  (51.4%)
engine                                      31 PRs   20,046
b62 (Padiem Chat)                           45 PRs   18,957
core                                        12 PRs    5,325
b14                                         11 PRs    4,535
```

최근 이슈 200건(3일간 생성)도 **B54가 103건(51%)**.
로컬 에이전트 브로커·OAuth ingress·디스패치 인프라가 절반을 소비한다.
인프라가 필요 없다는 뜻이 아니라, **비율이 예산으로 관리되지 않고 있다**는 뜻이다.
README의 성공 기준("More files, screens, agents, or deployments are not success by
themselves")과 긴장 관계에 있다.

### 3.9 [P3] 경제 원장(Attribution)이 없다

`docs/governance/AI_OPERATING_MODEL.md` §10은 모든 AI 작업을
free inference / paid API / paid consumer-tool / local compute / human work로
귀속시키라고 요구한다. 그러나 커밋 작성자는 전부 `skerishKang`이고,
**어느 모델이 CTO였고 어느 모델이 구현했는지 기록이 없다.**
→ "얼마나 무료 AI로 생산했는가"라는 핵심 사업 지표를 측정할 수 없다.

### 3.10 [P3] 모든 브랜치에 World Feed(B6) Pages 프리뷰가 배포된다

PR마다 `ai-revenue-world-feed` Pages 프리뷰가 붙는다(Core/Engine PR 포함).
`AGENTS.md`는 "Wrong-project Preview는 결함 증거"라고 명시한다.
비용·노이즈 문제이며, 자칫 수락 증거로 오독될 수 있다.

---

## 4. 권고 (우선순위)

### P1 — 이번에 같이 고칠 수 있는 것

| # | 조치 | 근거 |
|---|---|---|
| R1 | 정책 일관성 가드를 CI에 연결하고 빨간불을 해소 | §3.4 |
| R2 | PR 본문 계약 검사기를 추가(기본 **report-only**, `enforce` 입력으로 차단 전환) | §3.2 |
| R3 | CTO 판정을 **GitHub 리뷰 또는 커밋된 `CTO_FINAL_REVIEW` 산출물**로 남긴다. 최소 비용은 리뷰 1건(approve/request changes) | §3.1 |
| R4 | 브랜치 보호로 "승인 1건 + 체크 통과"를 머지 조건으로 설정(가능한 경우) | §3.1, §3.7 |

### P2 — 다음 스프린트

| # | 조치 | 근거 |
|---|---|---|
| R5 | 로컬 실행 환경을 CI와 동일하게(WSL2/Docker + Python 3.12 + `uv`). 불가피한 Windows 전용 실패는 `xfail(reason=...)`로 명시 | §3.5 |
| R6 | 이슈(작업 계약)에 **Non-goals / 금지 경로** 섹션을 의무화 — 이슈 템플릿 추가 | §3.6 |
| R7 | 독립 검증이 필요한 변경 유형을 정의(예: 배포/시크릿/게이트/프로덕션 경로를 건드리는 PR)하고, 나머지는 `NOT_REQUIRED + 사유`로 명시 | §3.3 |
| R8 | WIP 제한: CTO 검토 대기 PR 상한(예: 5개)을 두고 초과 시 신규 구현 중단 | §3.7 |
| R9 | 월간 비중 리포트: infra(b54) vs 제품 additions 비율을 예산(예: ≤30%)으로 관리 | §3.8 |

### P3

| # | 조치 | 근거 |
|---|---|---|
| R10 | 커밋 트레일러 또는 PR 필드로 모델 귀속 기록(`CTO-Model:`, `Dev-Model:`, `Compute:`) | §3.9 |
| R11 | Pages 프리뷰를 관련 프로젝트에만 연결 | §3.10 |

---

## 5. 이번 감사 PR에서 수행한 변경

1. `docs/operations/tests/test_operating_policy_consistency.py`를 **초록불로 복원**
   - 정책 문서 두 곳에 기계 판독 가능한 토큰을 추가(의미 변경 없음, 표현 통일).
2. `.github/workflows/operations-policy-guard.yml` **신규**
   - job `policy-consistency`: 위 테스트 + 계약 검사기 자체 테스트를 **차단 게이트**로 실행.
   - job `pr-contract`: PR 본문 계약 준수 리포트(기본 비차단, `enforce` 입력으로 차단).
3. `.github/scripts/pr_contract_guard.py` + `.github/tests/test_pr_contract_guard.py` **신규**
   - `Authority / revision`, `Evidence dimensions`, `Implementation evidence`,
     `Independent validation`, `CTO final status`, `Completion checklist`,
     base/head SHA, 이슈 연결, 승인 주장 누락 여부를 검사.
4. 본 문서(감사 보고서).

의도적으로 수행하지 않은 것: 정책 **완화**, 기존 PR 편집, 브랜치 보호 설정(권한 범위 밖).

---

## 6. 재현 명령

```bash
# 거버넌스 가드 (수정 전: 2 failed / 수정 후: 6 passed)
python -m pytest -q docs/operations/tests/test_operating_policy_consistency.py

# Core 스위트 (Linux/3.11 기준 817 passed)
python -m pytest -q packages/padiem-ai-core

# PR 본문 계약 리포트 (비차단)
PR_BODY="$(gh pr view 1900 --json body --jq .body)" python .github/scripts/pr_contract_guard.py
```
