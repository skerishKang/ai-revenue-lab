# COM2 이전을 위한 Cloudflare 자산 목록 — 2026-10-25

추적: #5115. Owner 방침: **인증만 Cloudflare에 남긴다.** 이 문서는 저장소 선언과 워크플로의 이전 설계용 목록이며, 운영 계정 자산 실측·이전 완료·배포 승인 기록이 아니다.

## 1. 조사 범위와 판정 기준

- 기준 main SHA: `ac2443516f039393c2631dc87e279745bf096739`. 전용 astra-2 worktree에서 읽기 조사, 신규 문서 1개만 변경한다.
- 22개 Wrangler 설정(이름이 wrangler.toml인 10개, 이름 변형 TOML 2개, JSONC 10개)과 235개 .github/workflows 파일을 모두 조사했다. TOML만으로 누락되는 Control Plane·Broker JSONC 및 preview 환경도 포함한다.
- 정적 선언 / workflow의 생성·보존·activation 계약 / 실제 served 설정을 구분한다. 아래 미선언은 해당 정적 설정에 없다는 뜻이며, 운영에 없다는 뜻이 아니다. Cloudflare 관리 API, 비밀값 조회, Tabbit, 배포 게이트 실행은 하지 않았다.
- 노출 항목은 요청한 설정 메타데이터·공개 route/domain·바인딩 **이름**·service 대상·workflow 모드뿐이다. 계정/DB/namespace/store/version ID, bucket 실명, secret_name, vars 값, 토큰, URL query/fragment, 개인 PC 경로는 기록하지 않는다.
- 분류: **남김**=인증 기능과 그 인증 전용 저장소/입구; **컴2로 이전**=인증 이외 앱·실행 기능; **이전 시 대체 필요**=Cloudflare 전용 저장/통신/스케줄/배포 API를 사용하는 의존 자산. 이 분류는 Owner 방침의 기술적 적용이며 새로운 운영 변경 허가가 아니다.

## 2. Worker별 정적 설정

flags 약어: PY=python_workers, NO_SDK=disable_python_external_sdk, NODE=nodejs_compat. 미선언 값은 Wrangler 기본값으로 임의 확정하지 않는다. 표의 workers.dev/previews는 선언값이며 실제 도메인은 조회하지 않았다.

| Worker name / 환경 | 설정 근거 | compatibility_date / flags | routes / custom domain | workers.dev / previews | cron | observability |
| --- | --- | --- | --- | --- | --- | --- |
| `b64-ai-reward-router` (기본) | [apps/ai-reward-router/wrangler.jsonc](../../apps/ai-reward-router/wrangler.jsonc) | 2026-08-30 / 미선언 | 미선언 | true / true | 미선언 | 미선언 |
| `padiem-b66-pdf-renderer` (기본) | [apps/b66-pdf-renderer/wrangler.toml](../../apps/b66-pdf-renderer/wrangler.toml) | 2026-08-25 / PY, NO_SDK | 미선언 | false / 미선언 | 미선언 | 미선언 |
| `padiem-com2-backup` (기본) | [apps/com2-backup/wrangler.toml](../../apps/com2-backup/wrangler.toml) | 2026-08-25 / PY, NO_SDK | `com2-backup.padiem.net` (custom_domain) | false / false | 미선언 | 미선언 |
| `ai-revenue-korean-ai-platform` (기본) | [apps/korean-ai-platform/wrangler.toml](../../apps/korean-ai-platform/wrangler.toml) | 2026-07-25 / PY | 미선언 | true / 미선언 | 미선언 | enabled=true; head_sampling_rate=1 |
| `living-fiction-cloudflare-m0` (기본) | [apps/living-fiction/deploy/cloudflare/wrangler.toml](../../apps/living-fiction/deploy/cloudflare/wrangler.toml) | 2026-09-09 / PY | 미선언 | 미선언 / 미선언 | 미선언 | 미선언 |
| `living-fiction-cloudflare-container-m0` (기본) | [apps/living-fiction/wrangler.cloudflare-container.toml](../../apps/living-fiction/wrangler.cloudflare-container.toml) | 2026-09-09 / NODE | 미선언 | 미선언 / 미선언 | 미선언 | 미선언 |
| `padiem-ai-engine-ingress` (기본) | [apps/padiem-ai-engine/ingress/wrangler.toml](../../apps/padiem-ai-engine/ingress/wrangler.toml) | 2026-09-02 / 미선언 | 미선언 | true / 미선언 | 미선언 | 미선언 |
| `padiem-ai-engine-preview-caller` (기본) | [apps/padiem-ai-engine/preview-caller/wrangler.toml](../../apps/padiem-ai-engine/preview-caller/wrangler.toml) | 2026-08-27 / 미선언 | 미선언 | true / 미선언 | 미선언 | 미선언 |
| `padiem-ai-engine` (기본) | [apps/padiem-ai-engine/wrangler.toml](../../apps/padiem-ai-engine/wrangler.toml) | 2026-08-27 / PY | 미선언 | false / 미선언 | 미선언 | enabled=true; head_sampling_rate=1; logs(enabled=true, invocation_logs=true) |
| `padiem-ai-engine-preview` (env.preview) | [apps/padiem-ai-engine/wrangler.toml](../../apps/padiem-ai-engine/wrangler.toml) | 2026-08-27 / PY | 미선언 | false / 미선언 | 미선언 | enabled=true; head_sampling_rate=1; logs(enabled=true, invocation_logs=true) |
| `padiem-chat-connector-acceptance-4139` (기본) | [apps/padiem-chat/wrangler.connector-acceptance-4139.toml](../../apps/padiem-chat/wrangler.connector-acceptance-4139.toml) | 2026-08-25 / PY | 미선언 | false / false | 미선언 | 미선언 |
| `padiem-chat` (기본) | [apps/padiem-chat/wrangler.toml](../../apps/padiem-chat/wrangler.toml) | 2026-08-25 / PY | 미선언 | true / 미선언 | 미선언 | enabled=true; head_sampling_rate=1; logs(enabled=true, invocation_logs=true) |
| `padiem-voice-stt` (기본) | [apps/padiem-voice-stt/wrangler.toml](../../apps/padiem-voice-stt/wrangler.toml) | 2026-08-25 / PY | 미선언 | false / 미선언 | 미선언 | 미선언 |
| `padiem-contact-verification` (기본) | [packages/padiem-control-plane/wrangler.contact-verification.jsonc](../../packages/padiem-control-plane/wrangler.contact-verification.jsonc) | 2026-09-03 / PY, NO_SDK | 미선언 | false / false | 미선언 | enabled=true |
| `padiem-control-plane-engine-admission` (기본) | [packages/padiem-control-plane/wrangler.engine-admission-authority.jsonc](../../packages/padiem-control-plane/wrangler.engine-admission-authority.jsonc) | 2026-09-04 / PY, NO_SDK | 미선언 | false / false | 미선언 | enabled=false |
| `padiem-google-oauth-edge` (기본) | [packages/padiem-control-plane/wrangler.google-oauth-edge.jsonc](../../packages/padiem-control-plane/wrangler.google-oauth-edge.jsonc) | 2026-09-04 / PY, NO_SDK | 미선언 | false / false | 미선언 | enabled=false |
| `padiem-google-oauth-state` (기본) | [packages/padiem-control-plane/wrangler.google-oauth.jsonc](../../packages/padiem-control-plane/wrangler.google-oauth.jsonc) | 2026-09-04 / PY, NO_SDK | 미선언 | false / false | 미선언 | enabled=false |
| `padiem-control-plane-identity-acceptance-4139` (기본) | [packages/padiem-control-plane/wrangler.identity-authority-acceptance-4139.jsonc](../../packages/padiem-control-plane/wrangler.identity-authority-acceptance-4139.jsonc) | 2026-09-04 / PY, NO_SDK | 미선언 | false / false | 미선언 | enabled=false |
| `padiem-control-plane-identity` (기본) | [packages/padiem-control-plane/wrangler.identity-authority.jsonc](../../packages/padiem-control-plane/wrangler.identity-authority.jsonc) | 2026-09-04 / PY, NO_SDK | 미선언 | false / false | 미선언 | enabled=false |
| `padiem-local-agent-broker-state-acceptance-4139` (기본) | [packages/padiem-control-plane/wrangler.local-agent-broker-acceptance-4139.jsonc](../../packages/padiem-control-plane/wrangler.local-agent-broker-acceptance-4139.jsonc) | 2026-09-04 / PY, NO_SDK | 미선언 | false / false | 미선언 | enabled=true |
| `padiem-local-agent-broker-edge` (기본) | [packages/padiem-control-plane/wrangler.local-agent-broker-edge.jsonc](../../packages/padiem-control-plane/wrangler.local-agent-broker-edge.jsonc) | 2026-09-04 / PY, NO_SDK | 미선언 | false / false | 미선언 | enabled=true |
| `padiem-local-agent-broker-state` (기본) | [packages/padiem-control-plane/wrangler.local-agent-broker.jsonc](../../packages/padiem-control-plane/wrangler.local-agent-broker.jsonc) | 2026-09-04 / PY, NO_SDK | 미선언 | false / false | 미선언 | enabled=true |
| `padiem-connector-source-canary` (기본) | [tools/connector-edge-canary/wrangler.toml](../../tools/connector-edge-canary/wrangler.toml) | 2026-10-13 / PY | 미선언 | false / false | 미선언 | 미선언 |

preview의 date/flags/observability는 공통 블록의 선언을 참고 표시했다(운영 유효 설정 실측 아님). env.preview는 name/workers_dev만 명시하며 non-inheritable services/D1/Secrets Store는 그 환경에 재선언하지 않는다. 위 표에서 모든 cron이 미선언이다. workflow의 GitHub schedule은 Worker cron과 별개다.

### 2.1 Service bindings (이름 → 대상)

| Worker / 환경 | Service binding → 대상 Worker | 근거 |
| --- | --- | --- |
| `b64-ai-reward-router` | 미선언 | [apps/ai-reward-router/wrangler.jsonc](../../apps/ai-reward-router/wrangler.jsonc) (기본) |
| `padiem-b66-pdf-renderer` | 미선언 | [apps/b66-pdf-renderer/wrangler.toml](../../apps/b66-pdf-renderer/wrangler.toml) (기본) |
| `padiem-com2-backup` | 미선언 | [apps/com2-backup/wrangler.toml](../../apps/com2-backup/wrangler.toml) (기본) |
| `ai-revenue-korean-ai-platform` | 미선언 | [apps/korean-ai-platform/wrangler.toml](../../apps/korean-ai-platform/wrangler.toml) (기본) |
| `living-fiction-cloudflare-m0` | 미선언 | [apps/living-fiction/deploy/cloudflare/wrangler.toml](../../apps/living-fiction/deploy/cloudflare/wrangler.toml) (기본) |
| `living-fiction-cloudflare-container-m0` | 미선언 | [apps/living-fiction/wrangler.cloudflare-container.toml](../../apps/living-fiction/wrangler.cloudflare-container.toml) (기본) |
| `padiem-ai-engine-ingress` | `ENGINE` → `padiem-ai-engine` | [apps/padiem-ai-engine/ingress/wrangler.toml](../../apps/padiem-ai-engine/ingress/wrangler.toml) (기본) |
| `padiem-ai-engine-preview-caller` | `PREVIEW_ENGINE` → `padiem-ai-engine-preview` | [apps/padiem-ai-engine/preview-caller/wrangler.toml](../../apps/padiem-ai-engine/preview-caller/wrangler.toml) (기본) |
| `padiem-ai-engine` | `PADIEM_CHAT_SERVICE` → `padiem-chat`; `B14_SERVICE` → `ai-revenue-korean-ai-platform`; `CONTROL_PLANE_IDENTITY` → `padiem-control-plane-identity`; `CONTROL_PLANE_ENGINE_ADMISSION` → `padiem-control-plane-engine-admission`; `CONTROL_PLANE_GOOGLE_OAUTH` → `padiem-google-oauth-state` | [apps/padiem-ai-engine/wrangler.toml](../../apps/padiem-ai-engine/wrangler.toml) (기본) |
| `padiem-ai-engine-preview` | 미선언 | [apps/padiem-ai-engine/wrangler.toml](../../apps/padiem-ai-engine/wrangler.toml) (env.preview) |
| `padiem-chat-connector-acceptance-4139` | `IDENTITY_AUTHORITY_SERVICE` → `padiem-control-plane-identity-acceptance-4139`; `LOCAL_AGENT_BROKER_AUTHORITY_SERVICE` → `padiem-local-agent-broker-state-acceptance-4139` | [apps/padiem-chat/wrangler.connector-acceptance-4139.toml](../../apps/padiem-chat/wrangler.connector-acceptance-4139.toml) (기본) |
| `padiem-chat` | `B14_SERVICE` → `ai-revenue-korean-ai-platform`; `IDENTITY_AUTHORITY_SERVICE` → `padiem-control-plane-identity`; `LOCAL_AGENT_BROKER_AUTHORITY_SERVICE` → `padiem-local-agent-broker-state`; `VOICE_STT_SERVICE` → `padiem-voice-stt` | [apps/padiem-chat/wrangler.toml](../../apps/padiem-chat/wrangler.toml) (기본) |
| `padiem-voice-stt` | `CONTROL_PLANE_IDENTITY` → `padiem-control-plane-identity`; `CONTROL_PLANE_ENGINE_ADMISSION` → `padiem-control-plane-engine-admission` | [apps/padiem-voice-stt/wrangler.toml](../../apps/padiem-voice-stt/wrangler.toml) (기본) |
| `padiem-contact-verification` | 미선언 | [packages/padiem-control-plane/wrangler.contact-verification.jsonc](../../packages/padiem-control-plane/wrangler.contact-verification.jsonc) (기본) |
| `padiem-control-plane-engine-admission` | `CONTROL_PLANE_IDENTITY` → `padiem-control-plane-identity` | [packages/padiem-control-plane/wrangler.engine-admission-authority.jsonc](../../packages/padiem-control-plane/wrangler.engine-admission-authority.jsonc) (기본) |
| `padiem-google-oauth-edge` | `GOOGLE_OAUTH_SERVICE` → `padiem-google-oauth-state` | [packages/padiem-control-plane/wrangler.google-oauth-edge.jsonc](../../packages/padiem-control-plane/wrangler.google-oauth-edge.jsonc) (기본) |
| `padiem-google-oauth-state` | 미선언 | [packages/padiem-control-plane/wrangler.google-oauth.jsonc](../../packages/padiem-control-plane/wrangler.google-oauth.jsonc) (기본) |
| `padiem-control-plane-identity-acceptance-4139` | 미선언 | [packages/padiem-control-plane/wrangler.identity-authority-acceptance-4139.jsonc](../../packages/padiem-control-plane/wrangler.identity-authority-acceptance-4139.jsonc) (기본) |
| `padiem-control-plane-identity` | 미선언 | [packages/padiem-control-plane/wrangler.identity-authority.jsonc](../../packages/padiem-control-plane/wrangler.identity-authority.jsonc) (기본) |
| `padiem-local-agent-broker-state-acceptance-4139` | 미선언 | [packages/padiem-control-plane/wrangler.local-agent-broker-acceptance-4139.jsonc](../../packages/padiem-control-plane/wrangler.local-agent-broker-acceptance-4139.jsonc) (기본) |
| `padiem-local-agent-broker-edge` | `LOCAL_AGENT_BROKER_SERVICE` → `padiem-local-agent-broker-state` | [packages/padiem-control-plane/wrangler.local-agent-broker-edge.jsonc](../../packages/padiem-control-plane/wrangler.local-agent-broker-edge.jsonc) (기본) |
| `padiem-local-agent-broker-state` | 미선언 | [packages/padiem-control-plane/wrangler.local-agent-broker.jsonc](../../packages/padiem-control-plane/wrangler.local-agent-broker.jsonc) (기본) |
| `padiem-connector-source-canary` | 미선언 | [tools/connector-edge-canary/wrangler.toml](../../tools/connector-edge-canary/wrangler.toml) (기본) |

### 2.2 상태·파일·비밀 저장 바인딩 (이름만)

| Worker / 환경 | D1 | R2 | KV | Queue | Durable Object | Secrets Store |
| --- | --- | --- | --- | --- | --- | --- |
| `b64-ai-reward-router` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 |
| `padiem-b66-pdf-renderer` | 미선언 | `PADIEM_WORKSPACE_FILES` | 미선언 | 미선언 | 미선언 | 미선언 |
| `padiem-com2-backup` | 미선언 | `COM2_BACKUP_BUCKET` | 미선언 | 미선언 | 미선언 | 미선언 |
| `ai-revenue-korean-ai-platform` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | `PADIEM_B14_CREDENTIAL_08`, `PADIEM_B14_CREDENTIAL_03`, `PADIEM_B14_CREDENTIAL_01`, `PADIEM_B14_CREDENTIAL_12`, `PADIEM_B14_CREDENTIAL_07`, `PADIEM_B14_CREDENTIAL_06`, `PADIEM_B14_CREDENTIAL_02`, `PADIEM_B14_CREDENTIAL_04`, `PADIEM_B14_CREDENTIAL_05`, `PADIEM_B14_CREDENTIAL_09`, `PADIEM_B14_CREDENTIAL_10`, `PADIEM_B14_CREDENTIAL_13`, `PADIEM_B14_CREDENTIAL_11`, `PADIEM_B14_CREDENTIAL_14`, `PADIEM_B14_SERVICE_PROOF_SECRET`, `PADIEM_GRAFANA_OTLP_TOKEN` |
| `living-fiction-cloudflare-m0` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 |
| `living-fiction-cloudflare-container-m0` | 미선언 | 미선언 | 미선언 | 미선언 | `LIVING_FICTION_CONTAINER` | 미선언 |
| `padiem-ai-engine-ingress` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 |
| `padiem-ai-engine-preview-caller` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 |
| `padiem-ai-engine` | `WEB_XLSX_PRIVATE_B62_D1`, `ENGINE_IDEMPOTENCY`, `ENGINE_CONTINUATION`, `ENGINE_CONNECTOR_GRANTS`, `ENGINE_IMAGE_STORE`, `ENGINE_DOCUMENT_STORE`, `ENGINE_EVIDENCE_STORE` | 미선언 | 미선언 | 미선언 | 미선언 | `PADIEM_GRAFANA_OTLP_TOKEN`, `CLAW_ENGINE_DESKTOP_SECRET`, `PADIEM_B14_SERVICE_PROOF_SECRET` |
| `padiem-ai-engine-preview` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 |
| `padiem-chat-connector-acceptance-4139` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 |
| `padiem-chat` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | `CLAW_ENGINE_DESKTOP_SECRET`, `B66_ALERT_RESEND_API_KEY`, `PADIEM_B14_SERVICE_PROOF_SECRET`, `PADIEM_KIRAAI_API_KEY`, `PADIEM_EXLAB_API_KEY`, `PADIEM_GITHUB_APP_CLIENT_SECRET`, `PADIEM_GRAFANA_OTLP_TOKEN`, `ORACLE_MESH_CHANNEL_SECRET`, `ORACLE_MESH_OWNERSHIP_MAP` |
| `padiem-voice-stt` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | `PADIEM_GEMINI_API_KEY`, `PADIEM_GROQ_API_KEY` |
| `padiem-contact-verification` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 |
| `padiem-control-plane-engine-admission` | 미선언 | 미선언 | 미선언 | 미선언 | `CONTROL_PLANE_ENGINE_ADMISSION` | 미선언 |
| `padiem-google-oauth-edge` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 |
| `padiem-google-oauth-state` | 미선언 | 미선언 | 미선언 | 미선언 | `GOOGLE_OAUTH_STATE` | 미선언 |
| `padiem-control-plane-identity-acceptance-4139` | 미선언 | 미선언 | 미선언 | 미선언 | `CONTROL_PLANE_IDENTITY` | 미선언 |
| `padiem-control-plane-identity` | 미선언 | 미선언 | 미선언 | 미선언 | `CONTROL_PLANE_IDENTITY` | 미선언 |
| `padiem-local-agent-broker-state-acceptance-4139` | 미선언 | 미선언 | 미선언 | 미선언 | `LOCAL_AGENT_BROKER_STATE` | 미선언 |
| `padiem-local-agent-broker-edge` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 |
| `padiem-local-agent-broker-state` | 미선언 | 미선언 | 미선언 | 미선언 | `LOCAL_AGENT_BROKER_STATE` | 미선언 |
| `padiem-connector-source-canary` | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 | 미선언 |

전체 정적 설정에서 KV와 Queue 바인딩은 선언되지 않았다. Queue consumer의 binding 필드가 없는 경우 queue 리소스명을 공개하지 않는 원칙을 적용한다. DO class/리소스 ID·Secrets Store store_id/secret_name·D1 database_name/database_id·R2 bucket_name은 의도적으로 생략했다.

### 2.3 정적 파일 밖에서 구성·검증하는 운영 계약

| 자산 / Worker | 이름 또는 공개 domain | 저장소 근거 | 판정·한계 |
| --- | --- | --- | --- |
| padiem-chat D1 | `PADIEM_CHAT_DB` | [.github/workflows/b62-production-code-deploy-gate.yml](../../.github/workflows/b62-production-code-deploy-gate.yml) | D1 type/name을 게이트가 검증하고 live settings로 생성 config에 보존; 정적 mock config에 없음. |
| padiem-chat R2 | `PADIEM_WORKSPACE_FILES` | [.github/workflows/b62-workspace-r2-binding-gate.yml](../../.github/workflows/b62-workspace-r2-binding-gate.yml) | 기존 바인딩 보존 검증; 실제 바인딩 상태는 미조회. |
| padiem-chat service | `P01_ENGINE_SERVICE → padiem-ai-engine` | [.github/workflows/b62-p01-engine-service-binding-gate.yml](../../.github/workflows/b62-p01-engine-service-binding-gate.yml) | 활성화/롤백 gate 계약; 적용 완료 증빙 아님. |
| padiem-chat service | `GOOGLE_OAUTH_STATE_SERVICE → padiem-google-oauth-state` | [.github/workflows/b62-google-oauth-state-binding-gate.yml](../../.github/workflows/b62-google-oauth-state-binding-gate.yml) | 정적 service 목록에 없는 activation 계약. |
| padiem-chat service | `B66_PDF_RENDERER_SERVICE → padiem-b66-pdf-renderer` | [.github/workflows/b62-b66-pdf-renderer-service-binding-gate.yml](../../.github/workflows/b62-b66-pdf-renderer-service-binding-gate.yml) | 정적 service 목록에 없는 activation 계약. |
| padiem-chat custom domain | `chat.padiem.net` | [.github/workflows/b62-production-code-deploy-gate.yml](../../.github/workflows/b62-production-code-deploy-gate.yml) | 게이트가 Worker 연결 domain을 검증; 정적 routes는 미선언. |
| Google OAuth edge custom domain | `oauth.padiem.net` | [.github/workflows/b54-google-oauth-production-gate.yml](../../.github/workflows/b54-google-oauth-production-gate.yml) | custom domain activation/rollback 계약; query 없음. |
| Broker edge custom domain | `local-agent.padiem.net` | [.github/workflows/b54-local-agent-public-ingress-activation.yml](../../.github/workflows/b54-local-agent-public-ingress-activation.yml) | public ingress activation/rollback 계약. |
| Chat 생성 config | `wrangler.production.generated.toml` | [.github/workflows/b62-production-code-deploy-gate.yml](../../.github/workflows/b62-production-code-deploy-gate.yml) | 정적 TOML 복사만 하지 않고 live settings의 전체 binding 집합을 보존; 이 조사로 전체 운영 binding 집합을 확정할 수 없음. |
| Chat scheduler | `cron 미활성화 계획 계약` | [.github/workflows/b62-automation-scheduler-config-gate.yml](../../.github/workflows/b62-automation-scheduler-config-gate.yml) | repository_preflight/plan_activation/plan_rollback만 제공; CONFIG_MUTATION=0, PRODUCTION_CRON_ACTIVATION=0. |

contact-verification·COM2 backup·Engine ingress·source canary·B64에는 전용 운영 코드 배포 gate를 이 기준 SHA의 workflows에서 확인하지 못했다. 설정 파일 존재만으로 운영 배포 여부를 판단하지 않는다.

기타 런타임 바인딩: Chat의 ASSETS, BROWSER, CF_VERSION_METADATA, B14의 ASSETS, acceptance Chat의 ASSETS/CF_VERSION_METADATA, living-fiction container 런타임은 정적 설정에 존재한다. 모든 plain-text vars 및 일반 Worker secret 값은 이 목록에 포함하지 않았다. Secrets Store 목록은 선언된 바인딩 이름이며 자격증명의 유효성 증거가 아니다.

## 3. 배포·변경 게이트 워크플로

모드는 workflow_dispatch inputs의 mode/stage choices를 우선 기록했다. 선택 입력이 없으면 confirmation/job 분기 또는 이벤트 기반 실행 조건을 기록한다. 파일에 deploy라는 단어가 있어도 dry-run/guard/smoke/readonly이면 운영 코드 배포로 취급하지 않는다. 아래 목록은 실행한 목록이 아니다.

### 3.1 코드 배포·승격·롤백

| 파일명 (모두 .github/workflows) | 대상 Worker | 모드 / 실행 범위 |
| --- | --- | --- |
| [.github/workflows/b14-production-deploy-gate.yml](../../.github/workflows/b14-production-deploy-gate.yml) | ai-revenue-korean-ai-platform | confirmation별 source deploy / rollback / promote-verified-private-candidate / retire-openrouter-secret |
| [.github/workflows/b54-engine-production-deploy-gate.yml](../../.github/workflows/b54-engine-production-deploy-gate.yml) | padiem-ai-engine | confirmation별 exact-main deploy / 지정 version rollback |
| [.github/workflows/b62-production-code-deploy-gate.yml](../../.github/workflows/b62-production-code-deploy-gate.yml) | padiem-chat | `repository_preflight`, `cloudflare_readonly`, `owner_d1_release_preflight`, `deploy_production_code`, `recover_p01_sse_off`, `rollback_production_code` |
| [.github/workflows/b54-control-plane-identity-production-redeploy.yml](../../.github/workflows/b54-control-plane-identity-production-redeploy.yml) | padiem-control-plane-identity | `repository_preflight`, `cloudflare_readonly`, `redeploy_identity_worker` |
| [.github/workflows/b54-engine-a7-cp-admission-production-activation.yml](../../.github/workflows/b54-engine-a7-cp-admission-production-activation.yml) | padiem-control-plane-engine-admission | `repository_preflight`, `cloudflare_readonly`, `activate_cp_engine_admission_worker` |
| [.github/workflows/b54-google-oauth-production-gate.yml](../../.github/workflows/b54-google-oauth-production-gate.yml) | padiem-control-plane-identity / padiem-google-oauth-state / padiem-google-oauth-edge | `repository_preflight`, `cloudflare_readonly`, `account_readonly`, `activate_private_workers`, `activate_custom_domain`, `rollback_custom_domain` |
| [.github/workflows/b54-google-oauth-edge-production-redeploy.yml](../../.github/workflows/b54-google-oauth-edge-production-redeploy.yml) | padiem-google-oauth-edge | confirmation별 repository preflight / readonly / exact-main redeploy |
| [.github/workflows/b54-google-oauth-edge-origin-reconciliation.yml](../../.github/workflows/b54-google-oauth-edge-origin-reconciliation.yml) | padiem-google-oauth-edge | confirmation으로 origin 정합성 재배포 |
| [.github/workflows/b54-google-oauth-state-production-redeploy.yml](../../.github/workflows/b54-google-oauth-state-production-redeploy.yml) | padiem-google-oauth-state | confirmation별 repository preflight / readonly / exact-main redeploy |
| [.github/workflows/b54-google-oauth-private-workers-production-activation.yml](../../.github/workflows/b54-google-oauth-private-workers-production-activation.yml) | padiem-control-plane-identity / padiem-google-oauth-state / padiem-google-oauth-edge | PR 검증 / 경로 제한 main push activation |
| [.github/workflows/b54-local-agent-broker-production-gate.yml](../../.github/workflows/b54-local-agent-broker-production-gate.yml) | padiem-local-agent-broker-state / padiem-local-agent-broker-edge | `repository_preflight`, `cloudflare_readonly`, `bootstrap_private`, `redeploy_private`, `redeploy_state_only` |
| [.github/workflows/b54-local-agent-ingress-remediation-redeploy.yml](../../.github/workflows/b54-local-agent-ingress-remediation-redeploy.yml) | padiem-local-agent-broker-state / padiem-local-agent-broker-edge | `repository_preflight`, `cloudflare_readonly`, `redeploy_fetch_transport` |
| [.github/workflows/b62-password-identity-production-activation.yml](../../.github/workflows/b62-password-identity-production-activation.yml) | padiem-control-plane-identity | `repository_preflight`, `activate_identity_production` |
| [.github/workflows/b62-password-auth-fast-production-activation.yml](../../.github/workflows/b62-password-auth-fast-production-activation.yml) | padiem-chat / padiem-control-plane-identity | 경로 제한 main push → 기존 identity/migration/Chat gate dispatch; 직접 코드 upload 아님 |
| [.github/workflows/padiem-voice-mode1-production-release.yml](../../.github/workflows/padiem-voice-mode1-production-release.yml) | padiem-voice-stt / padiem-control-plane-engine-admission | `readonly`, `activate` |
| [.github/workflows/b66-pdf-renderer-production-gate.yml](../../.github/workflows/b66-pdf-renderer-production-gate.yml) | padiem-b66-pdf-renderer | `repository_preflight`, `deploy_production` |
| [.github/workflows/b54-engine-agent-preview-pilot.yml](../../.github/workflows/b54-engine-agent-preview-pilot.yml) | padiem-ai-engine-preview / padiem-ai-engine-preview-caller | confirmation으로 preview deploy; run_pilot 선택; caller teardown |
| [.github/workflows/b62-cloudflare-worker-deploy.yml](../../.github/workflows/b62-cloudflare-worker-deploy.yml) | padiem-chat | PR/main push는 preflight만; 수동 allow_initial_mock_deploy + Worker absent일 때 최초 mock 생성 |
| [.github/workflows/b03-living-fiction-cloudflare-preview-deploy.yml](../../.github/workflows/b03-living-fiction-cloudflare-preview-deploy.yml) | living-fiction-cloudflare-container-m0 | 수동 승인 preview deploy |

### 3.2 바인딩·도메인·런타임 설정 및 관련 계획 게이트

| 파일명 (모두 .github/workflows) | 대상 Worker | 모드 / 실행 범위 |
| --- | --- | --- |
| [.github/workflows/b62-p01-engine-service-binding-gate.yml](../../.github/workflows/b62-p01-engine-service-binding-gate.yml) | padiem-chat → padiem-ai-engine | `repository_preflight`, `cloudflare_readonly`, `activate_p01_engine_binding`, `rollback_p01_engine_binding` |
| [.github/workflows/b62-control-plane-identity-binding-gate.yml](../../.github/workflows/b62-control-plane-identity-binding-gate.yml) | padiem-chat → padiem-control-plane-identity | `repository_preflight`, `cloudflare_readonly`, `activate_identity_binding`, `rollback_identity_binding` |
| [.github/workflows/b62-google-oauth-state-binding-gate.yml](../../.github/workflows/b62-google-oauth-state-binding-gate.yml) | padiem-chat → padiem-google-oauth-state | `repository_preflight`, `cloudflare_readonly`, `activate_google_oauth_state_binding`, `rollback_google_oauth_state_binding` |
| [.github/workflows/b62-b66-pdf-renderer-service-binding-gate.yml](../../.github/workflows/b62-b66-pdf-renderer-service-binding-gate.yml) | padiem-chat → padiem-b66-pdf-renderer | `repository_preflight`, `cloudflare_readonly`, `activate_b66_pdf_renderer_binding`, `rollback_b66_pdf_renderer_binding` |
| [.github/workflows/b62-workspace-r2-binding-gate.yml](../../.github/workflows/b62-workspace-r2-binding-gate.yml) | padiem-chat | exact-main contract/preflight; 기존 PADIEM_WORKSPACE_FILES 바인딩 보존 검증; 코드배포 아님 |
| [.github/workflows/b62-claw-live-config-activation-gate.yml](../../.github/workflows/b62-claw-live-config-activation-gate.yml) | padiem-chat | `repository_preflight`, `cloudflare_readonly`, `activate_config`, `activate_p01_sse`, `activate_oracle_mesh_mode`, `activate_chat_orchestration`, `replace_p01_engine_credential`, `rollback_config` |
| [.github/workflows/b62-google-auth-activation-gate.yml](../../.github/workflows/b62-google-auth-activation-gate.yml) | padiem-chat | `repository_preflight`, `cloudflare_readonly`, `activation_plan_readonly` |
| [.github/workflows/b62-google-auth-production-activation-gate.yml](../../.github/workflows/b62-google-auth-production-activation-gate.yml) | padiem-chat | `preflight_only`, `activation_readiness`, `activate_production` |
| [.github/workflows/b62-public-origin-migration-gate.yml](../../.github/workflows/b62-public-origin-migration-gate.yml) | padiem-chat | `preflight_only`, `readiness`, `migrate_production` |
| [.github/workflows/b54-local-agent-public-ingress-gate.yml](../../.github/workflows/b54-local-agent-public-ingress-gate.yml) | padiem-local-agent-broker-edge/state | `repository_preflight`, `cloudflare_readonly`, `activate_custom_domain`, `rollback_custom_domain` |
| [.github/workflows/b54-local-agent-public-ingress-activation.yml](../../.github/workflows/b54-local-agent-public-ingress-activation.yml) | padiem-local-agent-broker-edge/state | `preflight_only`, `activate_public_ingress`, `rollback_remove_custom_domain` |
| [.github/workflows/b54-local-agent-pairing-activation-gate.yml](../../.github/workflows/b54-local-agent-pairing-activation-gate.yml) | padiem-local-agent-broker-edge/state | `repository_preflight`, `cloudflare_readonly`, `canary_contract_evaluate`, `rollback_disable_evaluate`; 전 모드 non-mutating 평가 전용 |
| [.github/workflows/b62-automation-scheduler-config-gate.yml](../../.github/workflows/b62-automation-scheduler-config-gate.yml) | padiem-chat | `repository_preflight`, `plan_activation`, `plan_rollback`; plan only; cron 활성화/설정 변경 없음 |
| [.github/workflows/hark-web-first-runtime-activation.yml](../../.github/workflows/hark-web-first-runtime-activation.yml) | padiem-ai-engine / padiem-chat | `engine_read`, `chat_read`, `engine_write`, `chat_write`, `chat_pdf` |
| [.github/workflows/b62-b66-quote-url-activation-gate.yml](../../.github/workflows/b62-b66-quote-url-activation-gate.yml) | padiem-chat | `repository_preflight`, `cloudflare_readonly`, `activate_b66_quote_url` |
| [.github/workflows/b54-owner-d1-controlled-connection.yml](../../.github/workflows/b54-owner-d1-controlled-connection.yml) | padiem-chat / padiem-ai-engine | `apply`, `rollback`, `promote_latest`; 기존 Owner D1 연결 변경; 코드배포 아님 |
| [.github/workflows/b54-engine-caller-credential-regeneration-gate.yml](../../.github/workflows/b54-engine-caller-credential-regeneration-gate.yml) | padiem-ai-engine + 기존 rotation/smoke gates | `PLAN`, `APPLY` |
| [.github/workflows/b54-engine-caller-registry-v1-provision-gate.yml](../../.github/workflows/b54-engine-caller-registry-v1-provision-gate.yml) | padiem-ai-engine / padiem-chat | `repository_preflight`, `cloudflare_readonly`, `apply_engine_caller_registry_v1` |
| [.github/workflows/b54-engine-caller-registry-overlay-rotation-gate.yml](../../.github/workflows/b54-engine-caller-registry-overlay-rotation-gate.yml) | padiem-ai-engine / padiem-chat | `repository_preflight`, `cloudflare_readonly`, `apply_overlay_credential_rotation` |
| [.github/workflows/b54-engine-caller-registry-base-v1-b54-kagent-removal-gate.yml](../../.github/workflows/b54-engine-caller-registry-base-v1-b54-kagent-removal-gate.yml) | padiem-ai-engine | `repository_preflight`, `cloudflare_readonly`, `apply_base_v1_b54_kagent_removal` |

### 3.3 D1 schema / seed / credential 변경 게이트 (코드배포와 구분)

| 파일명 (모두 .github/workflows) | 대상 Worker | 모드 / 실행 범위 |
| --- | --- | --- |
| [.github/workflows/b54-calendar-authority-provision-gate.yml](../../.github/workflows/b54-calendar-authority-provision-gate.yml) | padiem-ai-engine / 관련 D1 | 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b54-calendar-grant-seed-gate.yml](../../.github/workflows/b54-calendar-grant-seed-gate.yml) | padiem-ai-engine / 관련 D1 | 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b54-claw-artifact-d1-026-gate.yml](../../.github/workflows/b54-claw-artifact-d1-026-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `readonly`, `apply_026`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b54-claw-history-014-015-apply-gate.yml](../../.github/workflows/b54-claw-history-014-015-apply-gate.yml) | padiem-chat / PADIEM_CHAT_DB | 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b54-engine-d1-provision-gate.yml](../../.github/workflows/b54-engine-d1-provision-gate.yml) | padiem-ai-engine / 관련 D1 | 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b54-slack-grant-seed-gate.yml](../../.github/workflows/b54-slack-grant-seed-gate.yml) | padiem-ai-engine / 관련 D1 | 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b54-telegram-authority-provision-gate.yml](../../.github/workflows/b54-telegram-authority-provision-gate.yml) | padiem-ai-engine / 관련 D1 | 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b54-telegram-grant-seed-gate.yml](../../.github/workflows/b54-telegram-grant-seed-gate.yml) | padiem-ai-engine / 관련 D1 | 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-auth-d1-migration-012-gate.yml](../../.github/workflows/b62-auth-d1-migration-012-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_012`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-auth-d1-migration-024-gate.yml](../../.github/workflows/b62-auth-d1-migration-024-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_024`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-b66-d1-migration-021-gate.yml](../../.github/workflows/b62-b66-d1-migration-021-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_021`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-b66-d1-migration-022-gate.yml](../../.github/workflows/b62-b66-d1-migration-022-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_022`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-b66-d1-migration-023-gate.yml](../../.github/workflows/b62-b66-d1-migration-023-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_023`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-b66-d1-migration-025-gate.yml](../../.github/workflows/b62-b66-d1-migration-025-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_025`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-b66-d1-migration-027-gate.yml](../../.github/workflows/b62-b66-d1-migration-027-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_027`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-b66-d1-migration-028-gate.yml](../../.github/workflows/b62-b66-d1-migration-028-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_028`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-b66-d1-migration-045-gate.yml](../../.github/workflows/b62-b66-d1-migration-045-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_045`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-automation-migrations-gate.yml](../../.github/workflows/b62-claw-automation-migrations-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_018`, `apply_migration_019`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-d1-migration-008-gate.yml](../../.github/workflows/b62-claw-d1-migration-008-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_008`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-d1-migration-009-gate.yml](../../.github/workflows/b62-claw-d1-migration-009-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_009`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-d1-migration-010-gate.yml](../../.github/workflows/b62-claw-d1-migration-010-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_010`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-d1-migration-011-gate.yml](../../.github/workflows/b62-claw-d1-migration-011-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_011`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-d1-migration-040-gate.yml](../../.github/workflows/b62-claw-d1-migration-040-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_040`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-d1-migration-054-gate.yml](../../.github/workflows/b62-claw-d1-migration-054-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_054`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-d1-migration-058-gate.yml](../../.github/workflows/b62-claw-d1-migration-058-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_058`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-d1-migration-059-gate.yml](../../.github/workflows/b62-claw-d1-migration-059-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_059`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-github-d1-migration-046-gate.yml](../../.github/workflows/b62-claw-github-d1-migration-046-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_046`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-mesh-d1-migration-047-gate.yml](../../.github/workflows/b62-claw-mesh-d1-migration-047-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_047`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-mesh-d1-migration-048-gate.yml](../../.github/workflows/b62-claw-mesh-d1-migration-048-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_048`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-mesh-d1-migration-049-gate.yml](../../.github/workflows/b62-claw-mesh-d1-migration-049-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_049`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-mesh-d1-migration-063-gate.yml](../../.github/workflows/b62-claw-mesh-d1-migration-063-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_063`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-claw-mesh-d1-migration-067-gate.yml](../../.github/workflows/b62-claw-mesh-d1-migration-067-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_067`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-d1-migration-013-gate.yml](../../.github/workflows/b62-d1-migration-013-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_013`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-d1-migration-060-gate.yml](../../.github/workflows/b62-d1-migration-060-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_060`, `apply_migration_061`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-d1-migration-062-gate.yml](../../.github/workflows/b62-d1-migration-062-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_062`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-d1-migration-065-gate.yml](../../.github/workflows/b62-d1-migration-065-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_065`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-d1-migration-066-gate.yml](../../.github/workflows/b62-d1-migration-066-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_066`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-identity-shadow-d1-migration-007-activation.yml](../../.github/workflows/b62-identity-shadow-d1-migration-007-activation.yml) | padiem-chat / PADIEM_CHAT_DB | 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b66-admin-d1-migration-037-gate.yml](../../.github/workflows/b66-admin-d1-migration-037-gate.yml) | padiem-chat / B66 admin D1 | `readonly`, `apply`; 수동 confirmation으로 schema/seed/provision; 코드배포 아님 |
| [.github/workflows/b62-b66-e2e-skill-provision-gate.yml](../../.github/workflows/b62-b66-e2e-skill-provision-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `d1_readonly`, `assign_test_skill` |
| [.github/workflows/b62-d1-migration-068-069-gate.yml](../../.github/workflows/b62-d1-migration-068-069-gate.yml) | padiem-chat / PADIEM_CHAT_DB | `repository_preflight`, `cloudflare_readonly`, `apply_migration_068_069`; D1 068/069 schema 변경, 코드배포 아님 |

### 3.4 Pages 및 별도 제품 배포

이들은 Worker 배포 게이트와 구분한다. 저장소 전체 조사 누락을 막기 위해 포함하며, 현재 Padiem AI 계정/COM2 이행 범위를 다른 비즈니스에 자동 적용하는 근거가 아니다.

| 파일명 | 대상 | 모드 |
| --- | --- | --- |
| [.github/workflows/b60-production-deploy.yml](../../.github/workflows/b60-production-deploy.yml) | B60 Pages | 파일별 push/workflow_dispatch 조건; Pages deploy |
| [.github/workflows/b62-pr-preview.yml](../../.github/workflows/b62-pr-preview.yml) | padiem-chat-pr-preview (Pages; Worker 아님) | 파일별 push/workflow_dispatch 조건; Pages deploy |
| [.github/workflows/b66-neutral-pages-beta.yml](../../.github/workflows/b66-neutral-pages-beta.yml) | B66 Pages | 파일별 push/workflow_dispatch 조건; Pages deploy |
| [.github/workflows/deploy-approved-business-07-08.yml](../../.github/workflows/deploy-approved-business-07-08.yml) | B07/B08 Pages | 파일별 push/workflow_dispatch 조건; Pages deploy |
| [.github/workflows/deploy-approved-business-pages.yml](../../.github/workflows/deploy-approved-business-pages.yml) | 승인 business Pages | 파일별 push/workflow_dispatch 조건; Pages deploy |
| [.github/workflows/deploy-business-10-fan-magazine.yml](../../.github/workflows/deploy-business-10-fan-magazine.yml) | B10 Pages | 파일별 push/workflow_dispatch 조건; Pages deploy |
| [.github/workflows/deploy-business-11-12-ui.yml](../../.github/workflows/deploy-business-11-12-ui.yml) | B11/B12 Pages | 파일별 push/workflow_dispatch 조건; Pages deploy |
| [.github/workflows/padiem-lab-ci.yml](../../.github/workflows/padiem-lab-ci.yml) | Padiem Lab Pages | 파일별 push/workflow_dispatch 조건; Pages deploy |
| [.github/workflows/provision-approved-business-pages.yml](../../.github/workflows/provision-approved-business-pages.yml) | 선택 business Pages | 파일별 push/workflow_dispatch 조건; Pages deploy |

### 3.5 배포가 아닌 계약

| 파일명 | 대상 / 성격 | 모드·근거 |
| --- | --- | --- |
| [.github/workflows/b03-living-fiction-cloudflare-m0-ci.yml](../../.github/workflows/b03-living-fiction-cloudflare-m0-ci.yml) | 해당 앱 bundle CI | deploy --dry-run; 실제 Worker 배포 아님 |
| [.github/workflows/b14-worker-json-bundle-preflight.yml](../../.github/workflows/b14-worker-json-bundle-preflight.yml) | 해당 앱 bundle CI | deploy --dry-run; 실제 Worker 배포 아님 |
| [.github/workflows/b62-padiem-chat-ci.yml](../../.github/workflows/b62-padiem-chat-ci.yml) | 해당 앱 bundle CI | deploy --dry-run; 실제 Worker 배포 아님 |
| [.github/workflows/connector-edge-python-sdk-canary.yml](../../.github/workflows/connector-edge-python-sdk-canary.yml) | 해당 앱 bundle CI | deploy --dry-run; 실제 Worker 배포 아님 |
| [.github/workflows/padiem-ai-engine-ci.yml](../../.github/workflows/padiem-ai-engine-ci.yml) | 해당 앱 bundle CI | deploy --dry-run; 실제 Worker 배포 아님 |
| [.github/workflows/b62-current-main-production-deploy-trigger.yml](../../.github/workflows/b62-current-main-production-deploy-trigger.yml) | padiem-chat 경계 계약 | PR source-contract만; 과거 main push 자동 production dispatch 폐기 |

## 4. Owner 방침에 따른 3분류

### 4.1 Worker 실행 자산

| Worker / 환경 | 분류 | 판단 근거 (1줄) |
| --- | --- | --- |
| `b64-ai-reward-router` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-b66-pdf-renderer` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-com2-backup` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `ai-revenue-korean-ai-platform` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. 진행: #5897(Workers 없이 실행)·#5900(상류 스위치)·아래 PR-3(컴2 배포 묶음) — 코드·문서 등록까지이며 설치·기동·배포는 미수행. |
| `living-fiction-cloudflare-m0` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `living-fiction-cloudflare-container-m0` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-ai-engine-ingress` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-ai-engine-preview-caller` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-ai-engine` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-ai-engine-preview` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-chat-connector-acceptance-4139` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. acceptance는 검증 fixture이며 운영 잔류 확정 아님. |
| `padiem-chat` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-voice-stt` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-contact-verification` | **남김** | 사용자 식별·로그인·OAuth/연락처 검증 역할만 잔류; 업무 권한·Connector 상태는 분리 이전. |
| `padiem-control-plane-engine-admission` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-google-oauth-edge` | **남김** | 사용자 식별·로그인·OAuth/연락처 검증 역할만 잔류; 업무 권한·Connector 상태는 분리 이전. |
| `padiem-google-oauth-state` | **남김** | 사용자 식별·로그인·OAuth/연락처 검증 역할만 잔류; 업무 권한·Connector 상태는 분리 이전. |
| `padiem-control-plane-identity-acceptance-4139` | **컴2로 이전** | 인증 운영 본체가 아닌 acceptance 검증 fixture이므로 COM2로 이전하고 잔류 인증과 계약 검증. |
| `padiem-control-plane-identity` | **남김** | 사용자 식별·로그인·OAuth/연락처 검증 역할만 잔류; 업무 권한·Connector 상태는 분리 이전. |
| `padiem-local-agent-broker-state-acceptance-4139` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. acceptance는 검증 fixture이며 운영 잔류 확정 아님. |
| `padiem-local-agent-broker-edge` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-local-agent-broker-state` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |
| `padiem-connector-source-canary` | **컴2로 이전** | 인증 이외의 UI·실행·AI 호출·기기 통신·렌더링·파일·검증 런타임. |

identity Worker에 업무 권한/기기 상태 기능이 함께 있어도 Worker 전체 기능을 인증으로 간주하지 않는다. 인증 최소 기능은 남기고 업무 entitlement·engine admission·broker 상태는 COM2로 분리한다. Google OAuth의 로그인 state는 남기며 Drive/Gmail 등 업무용 OAuth grant 실행·보관은 별도 분리 설계가 필요하다. 실제 데이터 경계는 후속 구현에서 검증한다.

### 4.2 바인딩·기반 자산별 분류

| 자산 (이름만; 같은 역할은 묶음) | 분류 | 판단 근거 / COM2 대체 (1줄) |
| --- | --- | --- |
| `padiem-b66-pdf-renderer` / R2: `PADIEM_WORKSPACE_FILES` | **이전 시 대체 필요** | 파일·백업은 인증 기능이 아니므로 HDD 파일 저장소와 메타데이터/해시/보존 정책으로 대체. |
| `padiem-com2-backup` / R2: `COM2_BACKUP_BUCKET` | **이전 시 대체 필요** | 파일·백업은 인증 기능이 아니므로 HDD 파일 저장소와 메타데이터/해시/보존 정책으로 대체. |
| `ai-revenue-korean-ai-platform` / Secrets Store: `PADIEM_B14_CREDENTIAL_08`, `PADIEM_B14_CREDENTIAL_03`, `PADIEM_B14_CREDENTIAL_01`, `PADIEM_B14_CREDENTIAL_12`, `PADIEM_B14_CREDENTIAL_07`, `PADIEM_B14_CREDENTIAL_06`, `PADIEM_B14_CREDENTIAL_02`, `PADIEM_B14_CREDENTIAL_04`, `PADIEM_B14_CREDENTIAL_05`, `PADIEM_B14_CREDENTIAL_09`, `PADIEM_B14_CREDENTIAL_10`, `PADIEM_B14_CREDENTIAL_13`, `PADIEM_B14_CREDENTIAL_11`, `PADIEM_B14_CREDENTIAL_14`, `PADIEM_B14_SERVICE_PROOF_SECRET`, `PADIEM_GRAFANA_OTLP_TOKEN` | **이전 시 대체 필요** | 모델·기기간 통신·GitHub·알림·관측 자격증명은 COM2 서비스용 보안 저장소로 대체; 값 복사/출력 금지. |
| `living-fiction-cloudflare-container-m0` / DO: `LIVING_FICTION_CONTAINER` | **이전 시 대체 필요** | Broker/admission/container 상태는 인증과 별개; 로컬 상태 서비스·DB·동시성/연결 수명 처리로 대체. |
| `padiem-ai-engine` / D1: `WEB_XLSX_PRIVATE_B62_D1`, `ENGINE_IDEMPOTENCY`, `ENGINE_CONTINUATION`, `ENGINE_CONNECTOR_GRANTS`, `ENGINE_IMAGE_STORE`, `ENGINE_DOCUMENT_STORE`, `ENGINE_EVIDENCE_STORE` | **이전 시 대체 필요** | 인증 외 실행/문서/멱등성/증거 상태; 로컬 DB로 schema·트랜잭션·복구 의미를 이전. |
| `padiem-ai-engine` / Secrets Store: `PADIEM_GRAFANA_OTLP_TOKEN`, `CLAW_ENGINE_DESKTOP_SECRET`, `PADIEM_B14_SERVICE_PROOF_SECRET` | **이전 시 대체 필요** | 모델·기기간 통신·GitHub·알림·관측 자격증명은 COM2 서비스용 보안 저장소로 대체; 값 복사/출력 금지. |
| `padiem-chat` / Secrets Store: `CLAW_ENGINE_DESKTOP_SECRET`, `B66_ALERT_RESEND_API_KEY`, `PADIEM_B14_SERVICE_PROOF_SECRET`, `PADIEM_KIRAAI_API_KEY`, `PADIEM_EXLAB_API_KEY`, `PADIEM_GITHUB_APP_CLIENT_SECRET`, `PADIEM_GRAFANA_OTLP_TOKEN`, `ORACLE_MESH_CHANNEL_SECRET`, `ORACLE_MESH_OWNERSHIP_MAP` | **이전 시 대체 필요** | 모델·기기간 통신·GitHub·알림·관측 자격증명은 COM2 서비스용 보안 저장소로 대체; 값 복사/출력 금지. |
| `padiem-voice-stt` / Secrets Store: `PADIEM_GEMINI_API_KEY`, `PADIEM_GROQ_API_KEY` | **이전 시 대체 필요** | 모델·기기간 통신·GitHub·알림·관측 자격증명은 COM2 서비스용 보안 저장소로 대체; 값 복사/출력 금지. |
| `padiem-control-plane-engine-admission` / DO: `CONTROL_PLANE_ENGINE_ADMISSION` | **이전 시 대체 필요** | Broker/admission/container 상태는 인증과 별개; 로컬 상태 서비스·DB·동시성/연결 수명 처리로 대체. |
| `padiem-google-oauth-state` / DO: `GOOGLE_OAUTH_STATE` | **남김** | 인증 전용 identity/OAuth state 저장 경로만 Cloudflare 잔류; 업무 상태는 분리. |
| `padiem-control-plane-identity-acceptance-4139` / DO: `CONTROL_PLANE_IDENTITY` | **이전 시 대체 필요** | acceptance 상태는 로컬 DB/상태 서비스로 대체; 운영 인증 DO와 분리. |
| `padiem-control-plane-identity` / DO: `CONTROL_PLANE_IDENTITY` | **남김** | 인증 전용 identity/OAuth state 저장 경로만 Cloudflare 잔류; 업무 상태는 분리. |
| `padiem-local-agent-broker-state-acceptance-4139` / DO: `LOCAL_AGENT_BROKER_STATE` | **이전 시 대체 필요** | Broker/admission/container 상태는 인증과 별개; 로컬 상태 서비스·DB·동시성/연결 수명 처리로 대체. |
| `padiem-local-agent-broker-state` / DO: `LOCAL_AGENT_BROKER_STATE` | **이전 시 대체 필요** | Broker/admission/container 상태는 인증과 별개; 로컬 상태 서비스·DB·동시성/연결 수명 처리로 대체. |
| padiem-chat D1: PADIEM_CHAT_DB | **이전 시 대체 필요** | 혼합 업무 DB 전체를 인증으로 남기지 않음; 로컬 DB로 옮기고 인증 전용 레코드만 분리. |
| padiem-chat R2: PADIEM_WORKSPACE_FILES | **이전 시 대체 필요** | workflow 운영 계약상 파일 바인딩; HDD + 로컬 메타데이터 저장으로 대체. |
| 모든 service bindings (§2.1 및 §2.3) | **이전 시 대체 필요** | Worker service fetch/RPC는 COM2 내부 API로, 남기는 인증 authority 호출은 기존 계정/사용자 경계를 유지한 원격 인증 API로 대체. |
| ASSETS (Chat/B14/acceptance) | **이전 시 대체 필요** | 정적 자산 전달을 COM2 웹서버로 대체. |
| BROWSER | **이전 시 대체 필요** | Cloudflare Browser Rendering 호출을 COM2 브라우저/렌더러 서비스로 대체. |
| CF_VERSION_METADATA | **이전 시 대체 필요** | Worker version API 대신 COM2 배포 SHA/릴리스 메타데이터 제공. |
| living-fiction container 런타임 | **이전 시 대체 필요** | Cloudflare container/DO 수명주기 대신 COM2 프로세스·컨테이너 운영 경로 선정; 실행/설치 승인 아님. |
| Worker cron / Chat scheduler 계획 | **이전 시 대체 필요** | 현재 정적 cron 미선언; 후속 예약 실행은 COM2 scheduler의 멱등성·재시도·중복 실행 제어로 연결. |
| observability enabled/logs/sampling 선언 | **이전 시 대체 필요** | 인증 Worker 관측은 잔류 가능; 이전 Worker의 요청 로그·샘플링·OTLP 전달을 로컬 관측으로 대체. |
| oauth.padiem.net / 인증 Worker 진입점 | **남김** | 로그인/OAuth callback 인증 경로이며 query/개인별 callback 값은 기록하지 않음. |
| chat.padiem.net / local-agent.padiem.net / com2-backup.padiem.net | **이전 시 대체 필요** | 비인증 UI·기기통신·백업 입구를 COM2 origin으로 연결; DNS/TLS/공개 연결 방식은 후속 설계. |
| preview / acceptance / source canary 실행 | **컴2로 이전** | 운영 인증 기능이 아닌 테스트 런타임; 잔류 인증과의 contract test는 유지. |
| 코드·설정 배포 게이트 (§3.1/3.2) | **이전 시 대체 필요** | 인증 대상 gate는 유지하고 나머지는 COM2 build/release/health/명시적 rollback 경로로 재연결. |
| D1 migration/seed 게이트 (§3.3) | **이전 시 대체 필요** | 인증 전용 schema만 잔류 가능; 이전 schema의 로컬 migration/backup/rollback으로 대체. |
| Pages 배포 (§3.4) | **컴2로 이전** | 인증 외 정적 UI는 원칙상 이전; 별도 제품·계정별 실제 이행 범위는 해당 Owner 작업에서 확정. |

## 5. 전수 조사 색인과 확인 한계

- §2 표에 모든 Wrangler 파일과 별도 preview 환경을 포함했다. §3은 코드 배포·설정/계획·데이터·Pages를 구분했다. 아래 색인은 모든 workflow 파일의 조사 포함 여부와 분류 위치를 보존한다.
- 운영 리소스 수량·현재 active 버전·실제 route·workflow activation 완료 여부·secret 존재/유효성은 UNKNOWN/NOT_QUERIED다. 워크플로에 선언된 후보·gate 이름을 운영 자산 존재로 단정하지 않는다.
- 관측/CI/canary가 Cloudflare를 읽거나 사용자 테스트를 호출할 수 있으므로 아래 참고 분류를 무조건 무변경/무네트워크로 해석하지 않는다. 운영 코드 배포 게이트인지와 제품 smoke/readonly/계약 검증인지의 구분이다.
- 실제 이전은 인증 전용 API 분리, 데이터 snapshot/복구 검증, service binding API 대체, COM2 ingress/프로세스 운영, 마지막 전환·롤백을 별도 구현 PR에서 정한다. 이 문서는 현재 설정·workflow·운영 상태를 변경하지 않는다.

| workflow 파일 | 조사 결과 / 상세 위치 |
| --- | --- |
| [.github/workflows/audit-cloudflare-pages-credentials.yml](../../.github/workflows/audit-cloudflare-pages-credentials.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b03-living-fiction-cloudflare-m0-ci.yml](../../.github/workflows/b03-living-fiction-cloudflare-m0-ci.yml) | §3.5 dry-run |
| [.github/workflows/b03-living-fiction-cloudflare-preview-deploy.yml](../../.github/workflows/b03-living-fiction-cloudflare-preview-deploy.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b14-agnes-production-smoke.yml](../../.github/workflows/b14-agnes-production-smoke.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b14-candidate-live-smoke.yml](../../.github/workflows/b14-candidate-live-smoke.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b14-deploy-gate-contract-tests.yml](../../.github/workflows/b14-deploy-gate-contract-tests.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b14-exlab-live-oneshot.yml](../../.github/workflows/b14-exlab-live-oneshot.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b14-gemini-live-oneshot.yml](../../.github/workflows/b14-gemini-live-oneshot.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b14-gemini-served-version-readonly.yml](../../.github/workflows/b14-gemini-served-version-readonly.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b14-model-evaluation-live.yml](../../.github/workflows/b14-model-evaluation-live.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b14-production-deploy-gate.yml](../../.github/workflows/b14-production-deploy-gate.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b14-worker-json-bundle-preflight.yml](../../.github/workflows/b14-worker-json-bundle-preflight.yml) | §3.5 dry-run |
| [.github/workflows/b32-ai-skill-studio-ci.yml](../../.github/workflows/b32-ai-skill-studio-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b48-source-verification.yml](../../.github/workflows/b48-source-verification.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b52-source-verification.yml](../../.github/workflows/b52-source-verification.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b53-padiem-sidecar-s0-ci.yml](../../.github/workflows/b53-padiem-sidecar-s0-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b53-source-verification.yml](../../.github/workflows/b53-source-verification.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-calendar-authority-provision-gate.yml](../../.github/workflows/b54-calendar-authority-provision-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b54-calendar-grant-seed-gate.yml](../../.github/workflows/b54-calendar-grant-seed-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b54-calendar-production-readiness-preflight.yml](../../.github/workflows/b54-calendar-production-readiness-preflight.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-calendar-read-production-canary.yml](../../.github/workflows/b54-calendar-read-production-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-claw-502-retained-telemetry-readonly.yml](../../.github/workflows/b54-claw-502-retained-telemetry-readonly.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-claw-artifact-d1-026-gate.yml](../../.github/workflows/b54-claw-artifact-d1-026-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b54-claw-history-014-015-apply-gate.yml](../../.github/workflows/b54-claw-history-014-015-apply-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b54-claw-history-014-015-readonly.yml](../../.github/workflows/b54-claw-history-014-015-readonly.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-cloudflare-zone-route-readonly-probe.yml](../../.github/workflows/b54-cloudflare-zone-route-readonly-probe.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-control-plane-identity-production-redeploy.yml](../../.github/workflows/b54-control-plane-identity-production-redeploy.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b54-drive-grant-d1-readonly-attestation.yml](../../.github/workflows/b54-drive-grant-d1-readonly-attestation.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-drive-read-production-canary.yml](../../.github/workflows/b54-drive-read-production-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-drive-runtime-retained-telemetry-readonly.yml](../../.github/workflows/b54-drive-runtime-retained-telemetry-readonly.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-a6-readonly-attestation.yml](../../.github/workflows/b54-engine-a6-readonly-attestation.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-a7-admission-readonly.yml](../../.github/workflows/b54-engine-a7-admission-readonly.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-a7-authenticated-user-canary.yml](../../.github/workflows/b54-engine-a7-authenticated-user-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-a7-cp-admission-production-activation.yml](../../.github/workflows/b54-engine-a7-cp-admission-production-activation.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b54-engine-agent-preview-pilot.yml](../../.github/workflows/b54-engine-agent-preview-pilot.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b54-engine-binding-readonly-audit.yml](../../.github/workflows/b54-engine-binding-readonly-audit.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-caller-authority-readonly-gate.yml](../../.github/workflows/b54-engine-caller-authority-readonly-gate.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-caller-credential-regeneration-gate.yml](../../.github/workflows/b54-engine-caller-credential-regeneration-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b54-engine-caller-registry-base-v1-b54-kagent-removal-gate.yml](../../.github/workflows/b54-engine-caller-registry-base-v1-b54-kagent-removal-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b54-engine-caller-registry-overlay-rotation-gate.yml](../../.github/workflows/b54-engine-caller-registry-overlay-rotation-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b54-engine-caller-registry-v1-provision-gate.yml](../../.github/workflows/b54-engine-caller-registry-v1-provision-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b54-engine-credential-equivalence-diagnostic-gate.yml](../../.github/workflows/b54-engine-credential-equivalence-diagnostic-gate.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-d1-provision-gate-contract-tests.yml](../../.github/workflows/b54-engine-d1-provision-gate-contract-tests.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-d1-provision-gate.yml](../../.github/workflows/b54-engine-d1-provision-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b54-engine-deploy-gate-contract-tests.yml](../../.github/workflows/b54-engine-deploy-gate-contract-tests.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-drive-s4-readonly-gate.yml](../../.github/workflows/b54-engine-drive-s4-readonly-gate.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-e9-shared-runtime-readonly.yml](../../.github/workflows/b54-engine-e9-shared-runtime-readonly.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-google-oauth-binding-readonly.yml](../../.github/workflows/b54-engine-google-oauth-binding-readonly.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-production-deploy-gate.yml](../../.github/workflows/b54-engine-production-deploy-gate.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b54-engine-production-smoke-only-gate.yml](../../.github/workflows/b54-engine-production-smoke-only-gate.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-engine-same-process-write-auth-diagnostic-gate.yml](../../.github/workflows/b54-engine-same-process-write-auth-diagnostic-gate.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-gcp-seoul-n2-live-probe-gate.yml](../../.github/workflows/b54-gcp-seoul-n2-live-probe-gate.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-gmail-grant-d1-readonly-preflight.yml](../../.github/workflows/b54-gmail-grant-d1-readonly-preflight.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-gmail-postseed-readonly-attestation.yml](../../.github/workflows/b54-gmail-postseed-readonly-attestation.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-gmail-read-production-canary.yml](../../.github/workflows/b54-gmail-read-production-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-google-oauth-edge-origin-reconciliation.yml](../../.github/workflows/b54-google-oauth-edge-origin-reconciliation.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b54-google-oauth-edge-production-redeploy.yml](../../.github/workflows/b54-google-oauth-edge-production-redeploy.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b54-google-oauth-private-workers-production-activation.yml](../../.github/workflows/b54-google-oauth-private-workers-production-activation.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b54-google-oauth-production-gate.yml](../../.github/workflows/b54-google-oauth-production-gate.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b54-google-oauth-readonly-main-audit.yml](../../.github/workflows/b54-google-oauth-readonly-main-audit.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-google-oauth-state-production-redeploy.yml](../../.github/workflows/b54-google-oauth-state-production-redeploy.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b54-local-agent-broker-production-gate.yml](../../.github/workflows/b54-local-agent-broker-production-gate.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b54-local-agent-ingress-remediation-redeploy.yml](../../.github/workflows/b54-local-agent-ingress-remediation-redeploy.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b54-local-agent-pairing-activation-gate.yml](../../.github/workflows/b54-local-agent-pairing-activation-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b54-local-agent-public-ingress-activation.yml](../../.github/workflows/b54-local-agent-public-ingress-activation.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b54-local-agent-public-ingress-gate.yml](../../.github/workflows/b54-local-agent-public-ingress-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b54-oauth-browser-canary-contract-tests.yml](../../.github/workflows/b54-oauth-browser-canary-contract-tests.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-owner-d1-controlled-connection.yml](../../.github/workflows/b54-owner-d1-controlled-connection.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b54-phasea-metrics-control-readonly.yml](../../.github/workflows/b54-phasea-metrics-control-readonly.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-slack-grant-seed-gate.yml](../../.github/workflows/b54-slack-grant-seed-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b54-slack-production-readiness-preflight.yml](../../.github/workflows/b54-slack-production-readiness-preflight.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-slack-read-production-canary.yml](../../.github/workflows/b54-slack-read-production-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-telegram-authority-provision-gate.yml](../../.github/workflows/b54-telegram-authority-provision-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b54-telegram-grant-seed-gate.yml](../../.github/workflows/b54-telegram-grant-seed-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b54-telegram-production-readiness-preflight.yml](../../.github/workflows/b54-telegram-production-readiness-preflight.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-telegram-read-production-canary.yml](../../.github/workflows/b54-telegram-read-production-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b54-vercel-parser-live-probe-gate.yml](../../.github/workflows/b54-vercel-parser-live-probe-gate.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b55-source-verification.yml](../../.github/workflows/b55-source-verification.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b57-source-verification.yml](../../.github/workflows/b57-source-verification.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b58-source-verification.yml](../../.github/workflows/b58-source-verification.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b60-official-source-intake.yml](../../.github/workflows/b60-official-source-intake.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b60-product-ci.yml](../../.github/workflows/b60-product-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b60-production-deploy.yml](../../.github/workflows/b60-production-deploy.yml) | §3.4 Pages |
| [.github/workflows/b62-auth-d1-migration-012-gate.yml](../../.github/workflows/b62-auth-d1-migration-012-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-auth-d1-migration-024-gate.yml](../../.github/workflows/b62-auth-d1-migration-024-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-automation-canary-gate.yml](../../.github/workflows/b62-automation-canary-gate.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-automation-scheduler-config-gate.yml](../../.github/workflows/b62-automation-scheduler-config-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b62-b66-d1-041-042-044-release.yml](../../.github/workflows/b62-b66-d1-041-042-044-release.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-b66-d1-migration-021-gate.yml](../../.github/workflows/b62-b66-d1-migration-021-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-b66-d1-migration-022-gate.yml](../../.github/workflows/b62-b66-d1-migration-022-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-b66-d1-migration-023-gate.yml](../../.github/workflows/b62-b66-d1-migration-023-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-b66-d1-migration-025-gate.yml](../../.github/workflows/b62-b66-d1-migration-025-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-b66-d1-migration-027-gate.yml](../../.github/workflows/b62-b66-d1-migration-027-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-b66-d1-migration-028-gate.yml](../../.github/workflows/b62-b66-d1-migration-028-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-b66-d1-migration-045-gate.yml](../../.github/workflows/b62-b66-d1-migration-045-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-b66-e2e-skill-provision-gate.yml](../../.github/workflows/b62-b66-e2e-skill-provision-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-b66-pdf-renderer-service-binding-gate.yml](../../.github/workflows/b62-b66-pdf-renderer-service-binding-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b62-b66-production-browser-canary-contract.yml](../../.github/workflows/b62-b66-production-browser-canary-contract.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-b66-quote-url-activation-gate.yml](../../.github/workflows/b62-b66-quote-url-activation-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b62-binding-state-guard.yml](../../.github/workflows/b62-binding-state-guard.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-browser-cache-seed.yml](../../.github/workflows/b62-browser-cache-seed.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-browser-qa-unified.yml](../../.github/workflows/b62-browser-qa-unified.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-chat-quota-snapshot-readonly.yml](../../.github/workflows/b62-chat-quota-snapshot-readonly.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-claw-automation-migrations-gate.yml](../../.github/workflows/b62-claw-automation-migrations-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-d1-migration-008-gate.yml](../../.github/workflows/b62-claw-d1-migration-008-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-d1-migration-009-gate.yml](../../.github/workflows/b62-claw-d1-migration-009-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-d1-migration-010-gate.yml](../../.github/workflows/b62-claw-d1-migration-010-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-d1-migration-011-gate.yml](../../.github/workflows/b62-claw-d1-migration-011-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-d1-migration-040-gate.yml](../../.github/workflows/b62-claw-d1-migration-040-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-d1-migration-054-gate.yml](../../.github/workflows/b62-claw-d1-migration-054-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-d1-migration-058-gate.yml](../../.github/workflows/b62-claw-d1-migration-058-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-d1-migration-059-gate.yml](../../.github/workflows/b62-claw-d1-migration-059-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-github-d1-migration-046-gate.yml](../../.github/workflows/b62-claw-github-d1-migration-046-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-live-config-activation-gate.yml](../../.github/workflows/b62-claw-live-config-activation-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b62-claw-mesh-d1-migration-047-gate.yml](../../.github/workflows/b62-claw-mesh-d1-migration-047-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-mesh-d1-migration-048-gate.yml](../../.github/workflows/b62-claw-mesh-d1-migration-048-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-mesh-d1-migration-049-gate.yml](../../.github/workflows/b62-claw-mesh-d1-migration-049-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-mesh-d1-migration-063-gate.yml](../../.github/workflows/b62-claw-mesh-d1-migration-063-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-mesh-d1-migration-067-gate.yml](../../.github/workflows/b62-claw-mesh-d1-migration-067-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-claw-production-smoke-gate.yml](../../.github/workflows/b62-claw-production-smoke-gate.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-cloudflare-worker-deploy.yml](../../.github/workflows/b62-cloudflare-worker-deploy.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b62-control-plane-identity-binding-gate.yml](../../.github/workflows/b62-control-plane-identity-binding-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b62-current-main-production-deploy-trigger.yml](../../.github/workflows/b62-current-main-production-deploy-trigger.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-d1-migration-013-gate.yml](../../.github/workflows/b62-d1-migration-013-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-d1-migration-060-gate.yml](../../.github/workflows/b62-d1-migration-060-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-d1-migration-062-gate.yml](../../.github/workflows/b62-d1-migration-062-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-d1-migration-065-gate.yml](../../.github/workflows/b62-d1-migration-065-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-d1-migration-066-gate.yml](../../.github/workflows/b62-d1-migration-066-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-glass-animation-timing-certification.yml](../../.github/workflows/b62-glass-animation-timing-certification.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-google-auth-activation-gate.yml](../../.github/workflows/b62-google-auth-activation-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b62-google-auth-production-activation-gate.yml](../../.github/workflows/b62-google-auth-production-activation-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b62-google-oauth-state-binding-gate.yml](../../.github/workflows/b62-google-oauth-state-binding-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b62-identity-shadow-d1-migration-007-activation.yml](../../.github/workflows/b62-identity-shadow-d1-migration-007-activation.yml) | §3.3 데이터/schema |
| [.github/workflows/b62-identity-shadow-d1-readonly-diagnostic.yml](../../.github/workflows/b62-identity-shadow-d1-readonly-diagnostic.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-live-content-marker-gate.yml](../../.github/workflows/b62-live-content-marker-gate.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-live-logout-reuse-check.yml](../../.github/workflows/b62-live-logout-reuse-check.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-live-long-context-canary.yml](../../.github/workflows/b62-live-long-context-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-mobile-touch-hosted-fallback.yml](../../.github/workflows/b62-mobile-touch-hosted-fallback.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-neutral-mock-copy.yml](../../.github/workflows/b62-neutral-mock-copy.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-p01-engine-service-binding-gate.yml](../../.github/workflows/b62-p01-engine-service-binding-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b62-p01-sse-immutable-forensic.yml](../../.github/workflows/b62-p01-sse-immutable-forensic.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-padiem-chat-ci.yml](../../.github/workflows/b62-padiem-chat-ci.yml) | §3.5 dry-run |
| [.github/workflows/b62-padiem-chat-react-ci.yml](../../.github/workflows/b62-padiem-chat-react-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-password-auth-fast-production-activation.yml](../../.github/workflows/b62-password-auth-fast-production-activation.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b62-password-identity-production-activation.yml](../../.github/workflows/b62-password-identity-production-activation.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b62-pr-preview.yml](../../.github/workflows/b62-pr-preview.yml) | §3.4 Pages |
| [.github/workflows/b62-production-code-deploy-gate.yml](../../.github/workflows/b62-production-code-deploy-gate.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b62-public-origin-migration-gate.yml](../../.github/workflows/b62-public-origin-migration-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b62-script-lineage-comparator.yml](../../.github/workflows/b62-script-lineage-comparator.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-security-headers.yml](../../.github/workflows/b62-security-headers.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-static-audits.yml](../../.github/workflows/b62-static-audits.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-workspace-r2-binding-gate.yml](../../.github/workflows/b62-workspace-r2-binding-gate.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/b64-ai-reward-router-ci.yml](../../.github/workflows/b64-ai-reward-router-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b66-3396-cgi-two-browser-readonly.yml](../../.github/workflows/b66-3396-cgi-two-browser-readonly.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b66-4229-owner-existing-guided.yml](../../.github/workflows/b66-4229-owner-existing-guided.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b66-admin-d1-migration-037-gate.yml](../../.github/workflows/b66-admin-d1-migration-037-gate.yml) | §3.3 데이터/schema |
| [.github/workflows/b66-cgi-final-handoff-smoke.yml](../../.github/workflows/b66-cgi-final-handoff-smoke.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b66-cgi-partial-live-canary.yml](../../.github/workflows/b66-cgi-partial-live-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b66-neutral-pages-beta.yml](../../.github/workflows/b66-neutral-pages-beta.yml) | §3.4 Pages |
| [.github/workflows/b66-pdf-preview-parity.yml](../../.github/workflows/b66-pdf-preview-parity.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b66-pdf-renderer-production-gate.yml](../../.github/workflows/b66-pdf-renderer-production-gate.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/b66-public-standard-template-contract.yml](../../.github/workflows/b66-public-standard-template-contract.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b66-quote-model-benchmark.yml](../../.github/workflows/b66-quote-model-benchmark.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b66-three-model-quality-eval.yml](../../.github/workflows/b66-three-model-quality-eval.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b67-browser-pdf-parser-qa.yml](../../.github/workflows/b67-browser-pdf-parser-qa.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b67-drive-case-folder-a6-browser-contract.yml](../../.github/workflows/b67-drive-case-folder-a6-browser-contract.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b67-drive-case-folder-d1-readonly-gate.yml](../../.github/workflows/b67-drive-case-folder-d1-readonly-gate.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/ci-3990-ephemeral-runner-benchmark.yml](../../.github/workflows/ci-3990-ephemeral-runner-benchmark.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/claw-connect-contract-tests.yml](../../.github/workflows/claw-connect-contract-tests.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/claw4-3083-desktop-shell-ci.yml](../../.github/workflows/claw4-3083-desktop-shell-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/cloudflare-pages-auth-check.yml](../../.github/workflows/cloudflare-pages-auth-check.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/cloudflare-r2-readonly-auth-probe.yml](../../.github/workflows/cloudflare-r2-readonly-auth-probe.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-accessibility-canary.yml](../../.github/workflows/com2-b62-accessibility-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-auth-history-canary.yml](../../.github/workflows/com2-b62-auth-history-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-conversation-delete-canary.yml](../../.github/workflows/com2-b62-conversation-delete-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-conversation-export-canary.yml](../../.github/workflows/com2-b62-conversation-export-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-deep-research-canary.yml](../../.github/workflows/com2-b62-deep-research-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-document-canary.yml](../../.github/workflows/com2-b62-document-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-error-retry-canary.yml](../../.github/workflows/com2-b62-error-retry-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-generic-browser-canary.yml](../../.github/workflows/com2-b62-generic-browser-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-image-canary.yml](../../.github/workflows/com2-b62-image-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-project-delete-canary.yml](../../.github/workflows/com2-b62-project-delete-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-project-files-canary.yml](../../.github/workflows/com2-b62-project-files-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-projects-canary.yml](../../.github/workflows/com2-b62-projects-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-saved-outputs-canary.yml](../../.github/workflows/com2-b62-saved-outputs-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-structured-answer-canary.yml](../../.github/workflows/com2-b62-structured-answer-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-touch-auto.yml](../../.github/workflows/com2-b62-touch-auto.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-touch-canary.yml](../../.github/workflows/com2-b62-touch-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-b62-web-search-canary.yml](../../.github/workflows/com2-b62-web-search-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-backup-contract-tests.yml](../../.github/workflows/com2-backup-contract-tests.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-ci-runner-pilot.yml](../../.github/workflows/com2-ci-runner-pilot.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-mobile-hosted-failover-watch.yml](../../.github/workflows/com2-mobile-hosted-failover-watch.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-policy-hosted-failover-watch.yml](../../.github/workflows/com2-policy-hosted-failover-watch.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-pr-auto-sandbox.yml](../../.github/workflows/com2-pr-auto-sandbox.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-pr-policy-trigger.yml](../../.github/workflows/com2-pr-policy-trigger.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/com2-pr-sandbox.yml](../../.github/workflows/com2-pr-sandbox.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/connector-edge-python-live-canary.yml](../../.github/workflows/connector-edge-python-live-canary.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/connector-edge-python-sdk-canary.yml](../../.github/workflows/connector-edge-python-sdk-canary.yml) | §3.5 dry-run |
| [.github/workflows/connector-resident-merge-safety.yml](../../.github/workflows/connector-resident-merge-safety.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/deploy-approved-business-07-08.yml](../../.github/workflows/deploy-approved-business-07-08.yml) | §3.4 Pages |
| [.github/workflows/deploy-approved-business-pages.yml](../../.github/workflows/deploy-approved-business-pages.yml) | §3.4 Pages |
| [.github/workflows/deploy-business-10-fan-magazine.yml](../../.github/workflows/deploy-business-10-fan-magazine.yml) | §3.4 Pages |
| [.github/workflows/deploy-business-11-12-ui.yml](../../.github/workflows/deploy-business-11-12-ui.yml) | §3.4 Pages |
| [.github/workflows/documentation-navigation-daily-audit.yml](../../.github/workflows/documentation-navigation-daily-audit.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/erp-item-master-ci.yml](../../.github/workflows/erp-item-master-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/hark-web-first-runtime-activation.yml](../../.github/workflows/hark-web-first-runtime-activation.yml) | §3.2 설정/연결/계획 |
| [.github/workflows/internal-platform-registry-ci.yml](../../.github/workflows/internal-platform-registry-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/ip-sidecar-runtime-contract.yml](../../.github/workflows/ip-sidecar-runtime-contract.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/kilo-space-bunny-anonymous-live-probe.yml](../../.github/workflows/kilo-space-bunny-anonymous-live-probe.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/living-learning-padiem-core-ci.yml](../../.github/workflows/living-learning-padiem-core-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/living-travel-ci.yml](../../.github/workflows/living-travel-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/operations-policy-guard-hosted-backup.yml](../../.github/workflows/operations-policy-guard-hosted-backup.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/operations-policy-guard.yml](../../.github/workflows/operations-policy-guard.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/p01-deployment-boundary-guard.yml](../../.github/workflows/p01-deployment-boundary-guard.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/padiem-ai-engine-ci.yml](../../.github/workflows/padiem-ai-engine-ci.yml) | §3.5 dry-run |
| [.github/workflows/padiem-control-plane-ci.yml](../../.github/workflows/padiem-control-plane-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/padiem-designer-ci.yml](../../.github/workflows/padiem-designer-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/padiem-lab-ci.yml](../../.github/workflows/padiem-lab-ci.yml) | §3.4 Pages |
| [.github/workflows/padiem-r2-c14-media-upload.yml](../../.github/workflows/padiem-r2-c14-media-upload.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/padiem-voice-mode1-production-release.yml](../../.github/workflows/padiem-voice-mode1-production-release.yml) | §3.1 코드 배포/승격/롤백 |
| [.github/workflows/padiem-voice-stt-ci.yml](../../.github/workflows/padiem-voice-stt-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/personal-edition-ci.yml](../../.github/workflows/personal-edition-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/personal-video-archive-ci.yml](../../.github/workflows/personal-video-archive-ci.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/provision-approved-business-pages.yml](../../.github/workflows/provision-approved-business-pages.yml) | §3.4 Pages |
| [.github/workflows/provision-padiem-phone-demo.yml](../../.github/workflows/provision-padiem-phone-demo.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/validate-b01-v6-living-index.yml](../../.github/workflows/validate-b01-v6-living-index.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/validate-b14-alpha.yml](../../.github/workflows/validate-b14-alpha.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/validate-b35-commercial-source.yml](../../.github/workflows/validate-b35-commercial-source.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/validate-b54-kagent.yml](../../.github/workflows/validate-b54-kagent.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/validate-b59-living-archive.yml](../../.github/workflows/validate-b59-living-archive.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/validate-b63-validation.yml](../../.github/workflows/validate-b63-validation.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/validate-pages-provisioning-contract.yml](../../.github/workflows/validate-pages-provisioning-contract.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/validate-portfolio-console-pr-434.yml](../../.github/workflows/validate-portfolio-console-pr-434.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/web-desktop-nonmodel-e2e.yml](../../.github/workflows/web-desktop-nonmodel-e2e.yml) | 참고 CI/관측/canary/계약; 운영 코드배포 목록 밖 |
| [.github/workflows/b62-d1-migration-068-069-gate.yml](../../.github/workflows/b62-d1-migration-068-069-gate.yml) | §3.3 데이터/schema |
