## CLAW1 — B62 운영 배포 사전 점검 (읽기 전용)

```text
WORKER=CLAW1
ISSUE=#4522
MAIN_SHA=2235754e14f546f1e31af16484db66b2c9b83235
SOLO_OWNER_POLICY=#4553_MERGED
DEPLOY_SOURCE_CONTRACT=PASS
READONLY_B62_RUN=38362406418
READONLY_008_RUN=38362487958
READONLY_040_RUN=38362491602
D1_008_SCHEMA=EXACT
D1_040_SCHEMA=EXACT
ACTIVE_VS_LATEST_VERSION=EQUAL
ROLLBACK_READINESS=PARTIAL_D1_RECOVERY_PASS_WORKER_PREVIOUS_VERSION_ID_NOT_EMITTED
BINDINGS_SECRETS_PARITY=PARTIAL_LIVE_BINDINGS_PASS_LIVE_SECRET_SET_NOT_EMITTED
CI_GITGUARDIAN=MAIN_NO_CI_RUN_GITGUARDIAN_PASS_ON_PR4553_HEAD
BLOCKER=PREVIOUS_WORKER_VERSION_ID_NOT_EMITTED_BY_APPROVED_READONLY_PATH;PRODUCTION_ENV_ZERO_REVIEWERS_WITH_PATH_LIMITED_AUTO_DEPLOY
PRODUCTION_MUTATION=0
AUTHENTICATED_E2E=NOT_RUN
FINAL=READY_FOR_CENTRAL_REVIEW
```

### 1. 기준 SHA

`2235754e14f546f1e31af16484db66b2c9b83235` — `docs(ops): B62 single-owner release guardrails (#4553)`, 2026-10-13T07:17:40Z 병합, 부모 `dc8f8ee5`, 변경 **1파일(docs)**. 디스패치 직전과 전체 실행 종료 후에 각각 재조회해 동일함을 확인했습니다(드리프트 0). 로컬 브랜치 HEAD는 사용하지 않았습니다.

### 2. 4개 워크플로우 실행 조건·읽기 전용 경계 (소스 검증, exact main)

| 워크플로우 | 트리거 | 허용 모드 | 변이 경계 |
|---|---|---|---|
| `b62-production-code-deploy-gate.yml` | `pull_request`(자기 자신 + 계약 스크립트/테스트 경로) · `workflow_dispatch` | `repository_preflight`, `cloudflare_readonly`, `owner_d1_release_preflight`, `deploy_production_code`, `rollback_production_code` | `permissions: contents: read`. `cloudflare-readonly` job은 `mode != 'repository_preflight'`일 때 실행되며 GET만 사용(`b62_cloudflare_504_readonly_get.sh`, `CF_B62_READONLY_GET=HTTP_200`). 변이 job은 `mode == deploy/rollback`에서만 실행 |
| `b62-claw-d1-migration-008-gate.yml` | `pull_request`(계약 경로) · `workflow_dispatch` | `repository_preflight`, `cloudflare_readonly`, `apply_migration_008` | `contents: read`. 읽기 job은 sqlite_master/PRAGMA만 SELECT, `ROW_DATA_READ=0`. apply job은 `mode == apply_migration_008`에서만 |
| `b62-claw-d1-migration-040-gate.yml` | `pull_request`(계약 경로) · `workflow_dispatch` | `repository_preflight`, `cloudflare_readonly`, `apply_migration_040` | `contents: read`. 읽기 job은 스키마 조회 + D1 Time Travel bookmark **읽기**만 수행. ALTER는 `mode == apply_migration_040` + `PREMUTATION_SCHEMA_STATE == pre_040`에서만 |
| `b62-current-main-production-deploy-trigger.yml` | `pull_request`/`push`(main, **자기 파일 경로만**) | `workflow_dispatch` **없음** | `contents: read`, `actions: write`. `deploy-production` job은 `github.event_name == 'push'`일 때만, `environment: production`에서 `deploy_production_code`를 디스패치 → **읽기 전용 모드가 존재하지 않음** |

모두 공통으로 `test "${GITHUB_REF}" = "refs/heads/main"` + `git rev-parse HEAD == TARGET_SHA`로 exact main을 강제합니다. `b62-production-code-deploy-gate.yml`의 source-contract는 `environment: production` 등장 횟수 == 2를 자기검증합니다(실측 2).

### 3. 실행 (각 1회, 허가된 모드만)

세 실행 모두 `workflow_dispatch`, `--ref main`, `target_sha=2235754e…`로 **1회씩** 수행했고, 변이 job은 전부 `skipped`입니다.

| run | workflow | mode | jobs | 결론 |
|---|---|---|---|---|
| [38362406418](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38362406418) | production-code-deploy-gate | `cloudflare_readonly` | source-contract=success, cloudflare-readonly=success, deploy/rollback/owner-preflight=**skipped** | success |
| [38362487958](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38362487958) | claw-d1-migration-008-gate | `cloudflare_readonly` | source-contract=success, cloudflare-readonly=success, apply-migration-008=**skipped** | success |
| [38362491602](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38362491602) | claw-d1-migration-040-gate | `cloudflare_readonly` | source-contract=success, cloudflare-readonly=success, apply-migration-040=**skipped** | success |

`b62-current-main-production-deploy-trigger.yml`은 `workflow_dispatch` 입력이 없어 읽기 전용으로 실행할 수 없습니다 → 소스 검증만 수행(§2). 기존 승인 인증 경로(저장소 Secrets + OIDC 없는 토큰 주입)만 사용했고, 401 폴백·로컬 토큰 교체·`wrangler` OAuth 대체는 **하지 않았습니다**.

### 4. 필수 검증 결과 (전부 해당 run의 실제 로그 토큰)

**D1 008 / 040**
- `B62_D1_MIGRATION_008_SCHEMA=EXACT`
- `B62_D1_MIGRATION_040_SCHEMA=EXACT`
- 두 run 모두 `LIVE_PADIEM_CHAT_DB_DERIVED=PASS`, `D1_SCHEMA_QUERY=READ_ONLY`, `ROW_DATA_READ=0`, `D1_IDENTIFIER_OUTPUT=0`, `PRODUCTION_MUTATION=0`, `READONLY_EXACT_MAIN_SHA=PASS`
- 040 게이트 추가: `D1_RECOVERY_AVAILABLE=PASS`, `D1_RECOVERY_BOOKMARK_PRESENT=PASS` (동일 Worker-바인딩 D1 Time Travel 복구점 존재)
- **040 재적용 0건**: 라이브가 `EXACT`이므로 apply job의 `PREMUTATION_SCHEMA_STATE=exact` 경로로 들어가고, `Apply only the additive migration 040 when absent` 단계는 `if: pre_040`로 **건너뛰며** `B62_D1_MIGRATION_040=SKIPPED_ALREADY_APPLIED`, `PRODUCTION_MUTATION=0`을 출력합니다. 즉 재적용 시 발생하는 ALTER 문은 **0건**입니다. (실제 apply 디스패치는 금지 범위이므로 실행하지 않았습니다 — 계약 + 라이브 상태로만 확정)

**서비스 중 / 최신 업로드 버전**
- `ACTIVE_VERSION=e8b432fc-a18c-40ee-8e2e-d39ef7a2fff5`
- `LATEST_VERSION=e8b432fc-a18c-40ee-8e2e-d39ef7a2fff5` → `LATEST_VERSION_EQUALS_ACTIVE_VERSION=PASS`
- `SERVED_VERSION_LINEAGE_OUTCOME=PASS`, `SERVED_VERSION_LINEAGE_REASON=equal`, `SERVED_VERSION_LINEAGE_MUTATION=0`, `SERVED_VERSION_LINEAGE_HTTP_CALLS=0`
- 해석: 미활성 업로드가 남아 있지 않고 서비스 버전 = 최신 업로드 버전입니다(드리프트 0).

**바인딩·Secret**
- 라이브 readback: `IDENTITY_BINDING=PRESENT_EXPECTED`(service→`padiem-control-plane-identity`), `B14_SERVICE` 존재, `PADIEM_CHAT_DB` d1 **정확히 1개**, `ASSETS` **정확히 1개**, 바인딩 이름 중복 0, `PADIEM_CHAT_PUBLIC_BASE_URL_STATE=expected`, `B62_CANONICAL_CUSTOM_DOMAIN=ATTACHED_EXPECTED`, `B62_PUBLIC_ORIGIN_PROOF=PASS`(`CONTROL_AND_DATA_PLANE`), `B62_STREAM_MODEL_TIMEOUT_PARITY=ALIGNED_600`
- Secret: 읽기 전용 감사는 **secret 이름/집합을 출력하지 않습니다**(`SECRET_VALUES_OUTPUT=0`). 완전한 secret 집합 동등성은 배포 시점 가드에서만 강제됩니다 — `b62_binding_state_guard.py`(`BINDINGS_PRESERVED_EXACTLY=PASS`, `SECRET_BINDINGS_PRESERVED=PASS`, `PADIEM_CHAT_QUOTA_SALT` 포함 단언) + `b62_served_version_secret_guard.py verify`. 따라서 배포 전 Secret 보존 "가능 여부"는 **소스 계약으로만** 확인되었고 라이브 secret 이름 집합은 미확인입니다.

**동시 운영 배포·충돌**
- 디스패치 전후 repo 전체에 `status != completed` run 0건.
- 세 워크플로우의 concurrency group은 각각 `b62-production-code-deploy-gate` / `b62-claw-d1-migration-008-gate` / `b62-claw-d1-migration-040-gate`로 **상호 독립**, 모두 `cancel-in-progress: false`.
- 실제 변이 경로인 deploy gate는 워크플로우 레벨 group을 공유하므로 읽기 감사 ↔ 운영 배포는 **직렬화**됩니다(동시 실행 불가).
- main push 자동 변이 경로는 `b62-current-main-production-deploy-trigger.yml` 하나뿐이며, 해당 파일 경로가 변경될 때만 발화합니다(최근 발화 2026-09-16). `b62-cloudflare-worker-deploy.yml`의 main push는 `Guard initial Worker creation only`로 **fail-closed**(workflow_dispatch + explicit `allow_initial_mock_deploy` + Worker `absent` 필요)이라 운영 Worker를 덮어쓰지 않습니다.

**exact main CI · GitGuardian**
- `2235754e`에 대한 CI 워크플로우 실행은 **없습니다**(path-filter 대상 파일을 건드리지 않은 docs-only 커밋). 이 커밋의 check-run은 `Cloudflare Pages: ai-revenue-world-feed=completed/success` 1건뿐입니다.
- GitGuardian: **PR #4553 head `777df1a8`에서 `GitGuardian Security Checks=SUCCESS`**(squash 병합이라 병합 커밋 자체에는 GitGuardian check-run 없음). 최근 main 커밋 6개 모두 `gitguardian_runs=0` → GitGuardian은 PR 레인에서만 동작합니다.
- `branches/main/protection` = **Branch not protected(404)**, ruleset 0건, required status checks 0건. (#4553의 1인 소유자 정책과 일치)

### 5. 남은 항목 (검증하지 못한 것 · 사실 그대로)

1. **`PREVIOUS_WORKER_VERSION_ID` 미확보 — 필수 항목 중 유일한 미충족**
   읽기 전용 감사는 `${api}/deployments`를 러너 임시파일로 내려받고 **resolved active id만 출력**합니다. 직전 서비스 버전 id는 배포 job 내부에서 `PREVIOUS_VERSION_ID=${active}`로 **변이 직전에** 기록됩니다. 허가된 읽기 전용 모드 중 이 값을 출력하는 모드가 없고, 로컬 토큰 교체/`wrangler` OAuth 대체가 금지되어 있어 직접 조회하지 않았습니다.
   → 최소 수정안(제안, 미실행): `cloudflare_readonly` job에 "deployments 목록에서 active 이전 버전 id를 마스킹 없이 출력 + 최소 1개 존재 단언" 하는 읽기 전용 단계를 추가. 또는 CENTRAL이 배포 시점 캡처(`PREVIOUS_VERSION_ID`)를 롤백 준비로 수용.
   참고로 D1 복구점은 이미 PASS(`D1_RECOVERY_AVAILABLE`), 롤백 경로 자체는 소스에 존재합니다(`rollback_production_code` 모드 + `previous_version_id` 입력, 실패 시 `Auto-rollback to recorded version on any failed step`).
2. **`environments/production` 승인 게이트 없음**: `protection_rules=[]`, `can_admins_bypass=true`, `wait_timer=null`, `deployment_branch_policy=null`. #4553은 1인 소유자 체계를 유지하므로 이를 **변경하지 않았습니다**. 다만 §2의 트리거 워크플로우와 결합하면 "main에서 그 파일 1개를 수정하는 push"가 승인 없이 `deploy_production_code`를 자동 디스패치합니다. 유지/제거는 CENTRAL 판단 사항으로 남깁니다.
3. **라이브 secret 이름 집합 미확인**(§4 참조) — 배포 시점 가드로만 강제됩니다.

### 6. 안전 경계

`PRODUCTION_MUTATION=0` — 배포, Worker 업로드/롤백, D1 ALTER·마이그레이션 재실행, Worker 설정·바인딩·Secret 변경, 인증 변경, 모델 활성화, 보호 설정 변경 **모두 0건**. 토큰·계정 ID·DB 식별자·secret 값은 로그·코멘트 어디에도 출력하지 않았습니다(러너가 `::add-mask::` 처리, 감사 출력 확인).
