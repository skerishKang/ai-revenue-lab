# Git 추적 산출물 감사 및 재유입 방지 (#5231, 2026-10-20)

```text
DOC_ROLE=REPOSITORY_TRACKED_ARTIFACT_AUDIT
STATUS=COMPLETE
ISSUE=#5231
BASE_MAIN=86d21d54a64d91ba7f266dcf6c9daec20f1e4925
TRACKED_FILES_CLASSIFIED=45
GENERATED_FILES_UNTRACKED=44
SOURCE_FILES_REMOVED=0
TEST_FIXTURE_FILES_REMOVED=0
EVIDENCE_FILES_KEPT=1
SENSITIVE_CREDENTIAL_VALUES_FOUND=0
GIT_HISTORY_REWRITTEN=NO
FORCE_PUSH=NO
PRODUCTION_MUTATION=0
CI_FILTER_CHANGED=NO
PRODUCT_RUNTIME_CHANGED=NO
```

## 1. 왜 이 문서가 있는가

공개 GitHub 저장소(`skerishKang/ai-revenue-lab`, repository visibility = `public`) 루트에 브라우저 QA 산출물, 로컬 에이전트 메모리, 운영 진단 로그가 Git 추적으로 남아 있었다.

원인은 2026-10-15에 병합된 Draft PR 커밋 `b1b9a0cd9`가 작업 트리의 로컬 상태(`.freebuff/project-id`, `.workbuddy-ai/memory/`, `_synccheck/`)를 소스와 함께 커밋한 것이다. `.tmp/b62-browser-qa/`는 2026-10-13 커밋 `99dc354e3`에서 CI 산출물이 함께 커밋되어 들어왔다.

이 문서는 #5231에서 수행한 **파일 단위 분류**와 **재유입 방지 근거**를 기록한다. 경로 이름만 보고 삭제하지 않았고, 각 파일의 실제 내용과 대체 정본을 대조했다.

## 2. 분류 결과

| 경로 | 추적 파일 수 | 분류 | 처리 |
|---|---:|---|---|
| `.tmp/b62-browser-qa/` | 3 | DERIVED TEMP | Git 추적 해제 + 무시 |
| `.workbuddy-ai/memory/` | 2 | DERIVED TEMP | Git 추적 해제 + 무시 |
| `_synccheck/` | 38 | DERIVED TEMP | Git 추적 해제 + 무시 |
| `.freebuff/project-id` | 1 | DERIVED TEMP | Git 추적 해제 + 무시 |
| `padiem-reports/2026-09-25/CLAW3/2825-hwpx-image-insertion-adoption.md` | 1 | MUST-KEEP EVIDENCE | **추적 유지** |

합계 45개 중 44개를 Git 추적에서 해제했고, 1개는 유지했다. **SOURCE 분류 파일은 0개**이고, **TEST FIXTURE 정본도 0개** 제거했다. 정본 테스트 파일은 `.github/tests/`에 그대로 있고, 제거된 사본만 `_synccheck/` 안에 있었다.

## 3. 경로별 근거

### 3.1 `.tmp/b62-browser-qa/` — DERIVED TEMP (3개)

- `mode-light-desktop.png`, `mode-padiem-glass-mobile.png`: `.github/scripts/b62_mode_presentation_browser_qa.py`가 만드는 브라우저 QA 스크린샷.
- `mode-presentation-report.json`: 같은 스크립트가 만드는 QA 결과 JSON.

근거:

- 이 디렉터리는 11개 `.github/scripts/b62_*_browser_qa.py`의 기본 출력 경로(`OUT_DIR` 기본값 `.tmp/b62-browser-qa`)이며, `b62-browser-qa-unified.yml`이 각 job의 결과를 Actions artifact로 업로드한다. CI가 매 실행마다 다시 만든다.
- 저장소 어떤 문서·이슈·워크플로도 이 세 파일을 증거로 인용하지 않는다. 참조는 생성 스크립트와 워크플로의 artifact 업로드 경로뿐이다.
- 같은 워크플로가 만드는 `.tmp/b62-accessibility-browser-qa/`, `.tmp/b62-auth-history-browser-qa/`는 원래 추적 대상이 아니었다. 동일 디렉터리 규칙 하나로 재유입을 막는다.

### 3.2 `.workbuddy-ai/memory/` — DERIVED TEMP (2개)

- `2026-10-13.md`, `2026-10-14.md`: 로컬 에이전트의 일별 작업 메모리.

근거: 저장소 코드·CI·워크플로가 참조하지 않는다. `apps/padiem-chat/tests/test_4139_claw_pc_enrollment_consent_contract.py`가 참조하는 `C:\Users\limone\.workbuddy-ai\binaries\...`는 **개발자 PC의 도구 경로**이며 저장소 루트 `.workbuddy-ai/`와 무관하다. 내용에는 소스 계약·게이트 결과·환경 메모가 섞여 있어 개인 작업 로그 성격이 강하다.

### 3.3 `_synccheck/` — DERIVED TEMP (38개)

한 번성 운영 진단 작업 디렉터리이다. 파일별로 다음과 같이 매칭된다.

| 파일군 | 근거 |
|---|---|
| `owner_decision.py` | `apps/padiem-chat/app/claw_web_xlsx_p01_owner_decision.py`와 **바이트 동일**인 사본. 정본은 그대로 있고, 사본만 상대 import가 깨져 실행 불가 |
| `preflight/test_b62_d1_migration_040_gate.py` | `.github/tests/test_b62_d1_migration_040_gate.py`와 **바이트 동일**인 사본 |
| `preflight/b62-claw-d1-migration-008-gate.yml`, `preflight/b62-claw-d1-migration-040-gate.yml` | `.github/workflows/`의 정본과 **바이트 동일**인 사본 |
| `tel-wf.yml` | `.github/workflows/b54-claw-502-retained-telemetry-readonly.yml`과 **바이트 동일**인 사본 |
| `preflight/b62-current-main-production-deploy-trigger.yml` | 2026-10-13에 폐기된 push 자동 배포 트리거의 구버전 초안. 정본은 `B62 Manual-Only Deployment Boundary Contract`로 교체되었고 `actions: write`와 `gh workflow run` 배포 경로가 제거되었다 |
| `preflight/b62-production-code-deploy-gate.yml` | 정본 워크플로보다 **오래된** 스냅샷(정본은 2026-10-19까지 계속 개정됨) |
| `comment_4546*.md`, `comment_4549*.md`, `corrigendum_4549.md` | 이미 GitHub 이슈에 게시된 코멘트의 작업 초안. `6133513559`, `6133525152`, `6133364966`, `6133399843`, `6140095626`, `6140104892` 코멘트가 공개 원본이다 |
| `preflight/comment_3933*.md`, `comment_3936_pointer.md`, `comment_4522_claw1*.md` | 미게시 초안. #3933·#4522는 CLOSED, #3936은 OPEN이며 초안은 결론을推翻하지 않는다. 게시하지 않은 내부 문안을 공개 저장소에 옮기는 것은 이 이슈의 비대상이다 |
| `agg.py`, `cfq.py`, `slices.py`, `zone_analyze.py`, `zone_slices.py`, `negctl_040.py`, `collect.sh`, `dispatch_rest.sh`, `dispatch_slices.sh` | 하드코딩된 로컬 경로(`/e/claw-1012-1/_synccheck/...`)를 쓰는 1회성 진단·디스패치 스크립트. 정본 워크플로는 `.github/workflows/`에 있고 CI는 저장소 밖 경로를 참조하지 않는다 |
| `collect.log`, `rest.log`, `slices.log`, `preflight/run_*.log`, `out/*.json`, `out/slices11.txt` | GitHub Actions 실행 로그와 Cloudflare GraphQL 조회 결과 덤프. 원본은 Actions 아티팩트와 해당 이슈 코멘트에 남아 있다 |

### 3.4 `.freebuff/project-id` — DERIVED TEMP (1개)

근거:

- 저장소 코드·워크플로·테스트 어디에서도 참조하지 않는다.
- 설치된 Freebuff CLI(전역 npm `freebuff` 0.0.122)의 설정 경로는 `~/.config/manicode`이며 저장소 루트 `.freebuff/project-id`를 읽지 않는다.
- 값은 UUID 하나이고 자격증명·키·계정 식별자가 아니다.
- `git rm --cached`만 사용했으므로 개발자 PC의 기존 로컬 파일은 그대로 남는다.

### 3.5 `padiem-reports/2026-09-25/CLAW3/2825-hwpx-image-insertion-adoption.md` — MUST-KEEP EVIDENCE (1개, 유지)

근거:

- `docs/operations/GITHUB_DOCUMENT_GOVERNANCE_AUDIT_CLASSIFICATION_REGISTER_20261014.tsv`에 blob SHA `0829709345f894936d8830f0f1c7122cc916d4be`로 등록된 문서이고, `docs/operations/GITHUB_DOCUMENT_GOVERNANCE_AUDIT_BATCH28_20261013.md`가 이를 `TECH_OWNER_RECORD`로 분류해 인용한다.
- `docs/operations/GITHUB_REPORT_HANDOFF_POLICY.md`가 `padiem-reports/`를 보고 루트로 정한다. 이 문서는 공개 GitHub에 게시된 기술 판단 기록이다.

## 4. 민감정보 판정

- **자격증명 값은 발견되지 않았다.** `_synccheck/cfq.py`는 로컬 `wrangler` OAuth 설정 파일(`~/.wrangler/config/default.toml`)을 **읽기만** 하고 토큰 값을 저장·출력하지 않는다. 저장소 내 어디에도 토큰·키·비밀번호·쿠키·세션값 문자열은 없었다.
- 식별자 수준 값은 존재했다. Cloudflare 계정 ID `9be14bb7b8974e65d0afba647ab16932`와 zone ID `f2197563fb53859673270dcdd9aef28b`, D1 time-travel bookmark ID, Worker version ID가 해당 파일들 안에 있었다.
  - 계정 ID는 이미 `.github/workflows/`, `.github/scripts/`, `.github/tests/` 정본에 상수로 존재하는 공개 값이다.
  - zone ID는 `_synccheck` 안에만 존재했다. 추적 해제로 공개 범위에서 빠진다.
- `_synccheck/out/burst.json`, `_synccheck/out/hours.json`은 운영 zone의 HTTP 요청 경로·상태 집계다. 원본은 Actions 아티팩트와 이슈 코멘트에 남아 있으며, 본 이슈·PR 본문에는 원문을 재게시하지 않았다.
- 과거 Git 이력은 재작성하지 않았다. 공개 저장소 상태 변경은 README 문구 정합화 1건뿐이며, 저장소 자체의 public/private 전환은 이 이슈 범위 밖이다.

## 5. 재유입 방지

`.gitignore`에 아래 규칙만 추가했다. 기존 규칙은 건드리지 않았다.

```text
.tmp/
.workbuddy-ai/
.freebuff/
_synccheck/
padiem-reports/2026-10-06/b66-pdf-preview-parity/
padiem-reports/b66-shell-cgi-v2/
```

마지막 두 줄은 `.github/scripts/b66_pdf_preview_parity.py`, `.github/scripts/b66_shell_cgi_v2_smoke.py`가 매 실행마다 만드는 출력 디렉터리다. `padiem-reports/2026-09-25/`은 추적 증거를 남기기 위해 무시하지 않았다.

회귀 방지 테스트: [`docs/operations/tests/test_no_tracked_generated_artifacts.py`](tests/test_no_tracked_generated_artifacts.py). 이 테스트는 (1) 정리된 경로가 추적되지 않음, (2) 같은 경로가 무시되되 그 무시 출처가 **저장소 `.gitignore`** 임, (3) 저장소 `.gitignore`가 필수 규칙을 실제로 선언함, (4) 유지한 증거와 대체 정본이 여전히 존재함, (5) 루트 README가 저장소를 private로 묘사하지 않음을 함께 검증한다.

(2)가 필요한 이유: 이 PC의 `.git/info/exclude`에 이미 `.tmp/` 규칙이 들어 있다. `.gitignore`에서 같은 규칙을 지워도 **이 PC에서는** 여전히 무시되어 통과해 버린다. `info/exclude`는 저장소에 포함되지 않으므로 새 클론·CI 러너에는 없다. 그래서 무지 여부가 아니라 **무시 출처가 저장소 규칙인지**를 확인해야 새 클론에서 재유입이 막힌다는 사실이 성립한다.

기존 `operations-policy-guard.yml`이 모든 PR에서 `docs/operations/tests` 트리를 수집하므로 별도 워크플로·시크릿·수동 디스패치는 필요 없다.

## 6. README 공개 상태 정합화

- 실제 repository visibility는 `public`이다. 루트 `README.md`가 저장소를 "private product and research repository"로 묘사해 실제 설정과 어긋났다.
- 한 줄을 "public development and engineering repository"로 고치고, **비공개 비즈니스·운영 Governance은 이 저장소에 게시되지 않는다**는 구분과 `AGENTS.md` 포인터를 같은 서술 블록에 남겼다. `docs/README.md`와 `AGENTS.md`의 기존 공개 개발정책 / 비공개 정본 분리 설명은 그대로 재사용했다.
- Governance 원문·공급사 자격증명·고객 자료는 README나 공개 문서에 옮기지 않았다.

## 7. 하지 않은 것

- Git 이력 재작성, force push, 저장소 public/private 전환.
- `infra/ci-runner-3990/` 일괄 삭제 또는 서브모듈 전환. CI 운영 인프라 소스이며 이 이슈 범위 밖이다.
- CI 필터·배포 필터 개편, 제품 런타임·Cloudflare 배포 변경.
- 경로 이름만 근거로 한 파일 삭제, 검증하지 않은 파일의 삭제.
- 실행되지 않은 시크릿 회전, 과거 노출 정리, 비공개 자료의 공개 게시.

## 8. 관련 근거

- 이슈: [#5231](https://github.com/skerishKang/ai-revenue-lab/issues/5231)
- 관련 이슈: [#5210](https://github.com/skerishKang/ai-revenue-lab/issues/5210) (CI 비용 최적화), [#2409](https://github.com/skerishKang/ai-revenue-lab/issues/2409) (장기 아키텍처 분리, 이번 정리와 무관)
- 운영방침: [AI Development Operating Policy](AI_DEVELOPMENT_OPERATING_POLICY.md), [GitHub Report Handoff Policy](GITHUB_REPORT_HANDOFF_POLICY.md), [Evidence Requirements](EVIDENCE_REQUIREMENTS.md)
- 비공개 Governance 원문은 공개 저장소에 복사하지 않는다. 위치와 읽기 규칙은 루트 [`AGENTS.md`](../../AGENTS.md)에만 둔다.
