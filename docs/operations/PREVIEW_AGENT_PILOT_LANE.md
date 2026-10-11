# Preview Agent Pilot Lane — as built

```
Scope     , #2786 Stage 11-C (M3-2 / M3-3.5) as it exists on main
PRs        #2878 (lane files) · #2879 (wire pilot caller + workflow) · #2880 #2881 #2882 (pilot fixes)
Evidence   pilot run 35638452853 (head 7306ac05) — success
Status     retained as an internal validation lane (Stage 12 §8 decision)
```

## 1. Purpose

Give the bounded Agent runtime a place to be exercised end to end **outside Production**, with no provider call,
no user data and no Production binding, and with everything that is created for a run removed again when the run
finishes.

## 2. Components

### 2.1 Preview engine worker — `padiem-ai-engine-preview`

Declared as `[env.preview]` in `apps/padiem-ai-engine/wrangler.toml`:

```text
name          padiem-ai-engine-preview
workers_dev   false                    (no route, no public URL)
vars          ENGINE_DEPLOY_ENV = "preview"
              ENGINE_AGENT_PREVIEW_ENABLED = "ENABLE_PREVIEW_AGENT_PILOT"
bindings      none — no services, no D1, no KV/R2
secrets       none standing
```

The worker composes a synthetic, in-memory Agent authority only when both markers are present; every other route
fails closed. Production carries no `[vars]` section at all, so the markers cannot leak into it.

### 2.2 Ephemeral caller worker — `padiem-ai-engine-preview-caller`

Source: `apps/padiem-ai-engine/preview-caller/` (`worker.mjs`, `wrangler.toml`, `test/worker.test.mjs`).

```text
name          padiem-ai-engine-preview-caller
workers_dev   true                     (routable only while the run lasts)
vars          PREVIEW_ENGINE_CALLER_ID = "preview-pilot-caller"
binding       [[services]] PREVIEW_ENGINE -> padiem-ai-engine-preview
```

Deployed by the pilot job, deleted by its teardown step.

### 2.3 Ephemeral caller registry entry

For the duration of a run the workflow injects a one-app caller registry entry into the preview engine
(`caller_id=preview-pilot-caller`, `allowed_app_ids=["engine-a5-agent-synthetic"]`) plus an in-memory credential
generated for that run. The entry is removed by the teardown step.

## 3. Lifecycle

```text
dispatch (workflow_dispatch only)
  -> preview-config-guard        exact-main assertion + wrangler preview-isolation contract test
  -> deploy-preview              if confirmation == 'DEPLOY_B54_ENGINE_AGENT_PREVIEW'
                                 exact-main + account assertion, pywrangler deploy --env preview,
                                 GET-only read-back of preview and Production served versions
  -> preview-pilot               if run_pilot == 'RUN_B54_ENGINE_AGENT_PREVIEW_PILOT'
                                   provision ephemeral caller registry + credential
                                   deploy ephemeral caller worker
                                   execute the synthetic task through the Service Binding
                                   assert post-pilot Production health
  -> teardown (if: always)       delete the caller worker
                                 delete the caller-registry entry from the preview engine
                                 PREVIEW_PILOT_TEARDOWN=PASS
```

## 4. Operating contract

| Item | Decision |
|---|---|
| Trigger | manual dispatch; optionally once per release candidate |
| Lifetime | minutes (one run) |
| Secret | ephemeral — created for the run, deleted by teardown |
| Access | internal only; the caller worker is workers.dev-routable only while the run lasts |
| Deletion | automatic (`if: always` teardown step) |
| Production binding | none |
| Provider calls | 0 (synthetic in-memory authority) |
| User data | 0 |

## 5. Production isolation

```text
- no step ever names the Production worker as a deploy target; deployment is `--env preview` only
- the preview engine worker holds no Production binding and no standing secret
- the caller worker binds only to the preview engine worker
- every run ends with teardown, and the teardown step runs even when the job failed earlier
- Production is observed read-only: served-version read-back, and a post-pilot health check
```

Note on the post-pilot health assertion: it reads the bounded health posture key set
(`engine_capability_posture()`), which does not contain `agent_skill_runtime`. It is therefore a posture check,
not a capability check; the isolation itself rests on the structural facts above rather than on that assertion.

## 6. Evidence

```text
pilot run 35638452853   workflow_dispatch, head 7306ac05, SUCCESS   (Stage 11-C M3-3.5)
earlier attempts        run 35633042287 / 35635188710 / 35636679047 — failure, fixed by #2880 / #2881 / #2882
capability promotion    #2883 records the pilot evidence in the capability declaration comment
```

## 7. Running it

```text
workflow_dispatch  .github/workflows/b54-engine-agent-preview-pilot.yml
inputs             target_sha            = exact main SHA
                   confirmation          = DEPLOY_B54_ENGINE_AGENT_PREVIEW
                   run_pilot             = RUN_B54_ENGINE_AGENT_PREVIEW_PILOT   (optional)
requires           CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID (repository secrets)
```

## 8. Cleanup and rollback

```text
normal path   teardown removes the caller worker and the caller-registry entry automatically
interrupted   if a run dies before teardown, remove the two ephemeral objects by hand:
                npx wrangler delete --name padiem-ai-engine-preview-caller --force
                npx wrangler secret delete PADIEM_ENGINE_CALLER_REGISTRY_V1 --name padiem-ai-engine-preview
lane itself   the preview engine worker is not a Production rollback surface; Production rollback uses the
              deploy gate with an explicit rollback_version_id
```

## 9. Non-goals

```text
- not a Production rollback surface
- no public route on the preview engine worker
- no provider runtime and no user data in the synthetic task
- no activation of any capability other than the one under test
```
