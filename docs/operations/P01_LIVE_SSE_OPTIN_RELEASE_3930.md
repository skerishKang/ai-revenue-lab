# #3930 — P01 live SSE opt-in release boundary (B62)

This is a **controlled release procedure**, not evidence that Production SSE or authenticated model-backed E2E is live.

## Authority and prerequisites

1. #3523 Production Golden Path owns the **code** release using the existing `b62-production-code-deploy-gate.yml`. The Worker must serve a **single 100% version** annotated `B62 production code <exact current main SHA>`. PR merge is not deployment.
2. The served version and current Worker settings must retain the Engine/P01 service, caller, credential, CP identity, D1/session/quota bindings, `PADIEM_CHAT_RUNTIME_MODE=b14`, `PADIEM_CHAT_LIVE_ENABLED=true` and the **separately authorized** `PADIEM_CLAW_P01_LIVE_CANARY_SUBJECT_ID` `secret_text` binding. The opt-in gate **never creates or rotates** a Secret and never chooses or falls back between AI models.
3. Only after those checks pass may an authorized production operator dispatch **the existing** `b62-claw-live-config-activation-gate.yml` with:
   - `mode=activate_p01_sse`
   - `target_sha=<exact current main SHA>`
   - `confirmation=CONFIRM_ACTIVATE_B62_P01_SSE_OPTIN`
   - existing GitHub `production` environment approval.
4. `b62_p01_sse_optin_gate.py` checks the immutable served-version/lineage, required settings and types, and constructs a **single-variable** `PADIEM_CLAW_P01_LIVE_SSE_ENABLED=true` patch. All other bindings use Cloudflare `inherit/latest`, including secrets. An existing exact `true` is no-op. Unsupported, duplicate, wrong-type, incorrect runtime, source mismatch and missing Canary subject are fail-closed.
5. The workflow captures a rollback-compatible settings artifact named `b62-claw-config-premutation-settings`, confirms exact main and unchanged served state immediately before PATCH, then polls the new served version and checks that settings/served bindings changed **only** in the SSE flag while script, assets and runtime identities remain identical. If proof fails, it reports blocked, never reports authenticated user success, and requires controlled recovery.

## Existing rollback-config reuse

A failed configuration transition must be reviewed by the production owner. To use the pre-mutation snapshot, dispatch the **existing** workflow with `mode=rollback_config` and `confirmation=CONFIRM_ROLLBACK_B62_CLAW_LIVE_CONFIG`; provide the recorded `rollback_version_id` and `premutation_run_id` from the activation run, `credential_created_by_activation=false`, and **`sse_optin_rollback=true`**. This narrowly authorizes removing or restoring the SSE flag against that exact snapshot without broadening the legacy default rollback target set. Existing code-version rollback and config snapshot readback remain distinct and still require approval. If untrusted drift or lost secrets obstruct snapshot restoration, refuse automated claims and require manual recovery.

Do not invoke live mutation, Secrets APIs, model POSTs, or authenticated user sessions from source CI. After release, rerun the read-only `b62_p01_live_sse_readiness.py` against the **actual** served version and separately obtain #3523 / #3930 authenticated low-risk canary acceptance. `CANARY_PREFLIGHT_READY` is not `AUTHENTICATED_E2E=PASS`.
