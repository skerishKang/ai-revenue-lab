# B54 Local Agent Public Ingress Activation Runbook v1

## Authority

Issue: #1828 — `[B54][Local Agent M2p] Audit and gate public authenticated broker ingress before Windows live canary` (Phase B)

This document records the fail-closed activation procedure for the Padiem Local Agent public HTTPS ingress at `https://local-agent.padiem.net`, the preflight invariants the gate enforces, the rollback (route-removal) procedure, and the evidence the gate records on each run.

## Scope

The activation gate (`b54-local-agent-public-ingress-activation.yml`) does **not** redeploy Workers. It verifies the already-audited public boundary and records activation evidence, or detaches the custom domain during rollback. Worker versions must match the post-remediation pins:

```text
STATE_VERSION = b5b5e0f1-96de-4521-8242-86466b4b1803  (padiem-local-agent-broker-state)
EDGE_VERSION  = c2217fb5-3a63-4fd5-90d9-431bd94c4a97  (padiem-local-agent-broker-edge)
```

## Current disposition

```text
PHASE_A_COMPLETE = YES
DOMAIN_STATE = PRESENT_EDGE (local-agent.padiem.net -> padiem-local-agent-broker-edge)
BOUNDED_SMOKE = PASS (405 / 404 / 401)
ACTIVATION_GATE_MERGED = <PR_SHA>
ACTIVATION_GATE_READY = YES (owner authorization pending)
WINDOWS_LIVE_CANARY = HOLD (separate work order)
USER_ROLLOUT = HOLD (separate work order)
```

## Activation procedure (owner authorization → gate dispatch)

The only actor authorized to dispatch the activation gate is the Product Owner (or a CTO-approved owner delegate), using an explicit confirmation phrase. The gate refuses to mutate without it.

1. Confirm current `main` SHA.

   ```bash
   git fetch origin main && git rev-parse origin/main
   ```

2. Dispatch the activation gate on `main` with the exact current SHA and the owner confirmation phrase.

   ```bash
   gh workflow run b54-local-agent-public-ingress-activation.yml --ref main \
     -f mode=activate_public_ingress \
     -f target_hostname=local-agent.padiem.net \
     -f exact_main_sha=<CURRENT_MAIN_SHA> \
     -f confirmation=ACTIVATE_B54_LOCAL_AGENT_PUBLIC_INGRESS_LOCAL_AGENT_PADIEM_NET
   ```

3. Watch the run; every job must be `success`:

   ```bash
   gh run watch <RUN_ID> --exit-status
   ```

4. Record evidence from the run log (`gh run view <RUN_ID> --log`):

   ```text
   HOSTNAME_VALIDATION=PASS
   EXACT_MAIN=PASS
   DEPLOYED_VERSION_PIN=PASS
   PRIVATE_STATE_WORKER_PUBLIC=NO
   EDGE_SERVICE_BINDING=PASS
   ROUTE_VALIDATION=PASS
   DNS_AUTHORITY_MUTATION=NO
   PREMUTATION_EXACT_MAIN=PASS
   IMMEDIATE_PREMUTATION_BASELINE=PASS
   CUSTOM_DOMAIN_ALREADY_ACTIVE=YES | CUSTOM_DOMAIN_ATTACH=SUCCESS
   PUBLIC_CUSTOM_DOMAIN_READBACK=PASS
   PUBLIC_405_404_401_SMOKE=PASS
   VERSIONS_PRESERVED=PASS
   WORKER_REDEPLOY=NO
   DURABLE_OBJECT_MUTATION=NO
   DNS_MUTATION=NO
   WINDOWS_LIVE_CANARY=NO
   USER_ROLLOUT=NO
   PRODUCTION_READY=NO
   ```

## Preflight checks

Every gate run, regardless of mode, executes `preflight-verification`:

- `target_hostname` input must equal `local-agent.padiem.net`.
- `exact_main_sha` input must equal current `origin/main` (re-fetched at run time).
- Cloudflare read-only inspection:
  - Account Workers domains list contains exactly one entry for `local-agent.padiem.net`, bound to `padiem-local-agent-broker-edge`.
  - `padiem-local-agent-broker-state` has zero public domain entries (`PRIVATE_STATE_WORKER_PUBLIC=NO`).
  - Both Workers have `workers_dev=false` and `preview_urls=false`.
  - Each Worker has exactly one active deployment version at 100%, matching the pinned post-remediation version.
  - Edge settings retain the `LOCAL_AGENT_BROKER_SERVICE` service binding to the state Worker.
  - The gate performs no DNS authority mutation (`DNS_AUTHORITY_MUTATION=NO`); DNS authority checks are limited to Workers-domain topology readback.

## Rollback procedure

Rollback removes the public route (custom domain) only. It never deletes the Workers, their Durable Object state, or their storage migrations, and it never redeploys.

```bash
gh workflow run b54-local-agent-public-ingress-activation.yml --ref main \
  -f mode=rollback_remove_custom_domain \
  -f target_hostname=local-agent.padiem.net \
  -f exact_main_sha=<CURRENT_MAIN_SHA> \
  -f confirmation=ROLLBACK_B54_LOCAL_AGENT_PUBLIC_INGRESS_REMOVE_CUSTOM_DOMAIN
```

Evidence recorded on success:

```text
ROLLBACK_EXACT_MAIN=PASS
CUSTOM_DOMAIN_DETACH=SUCCESS
STATE_WORKER_DELETED=NO
EDGE_WORKER_DELETED=NO
DURABLE_OBJECT_DELETED=NO
DURABLE_OBJECT_STORAGE_MIGRATION=NO
WORKER_REDEPLOY=NO
VERSIONS_PRESERVED=PASS
DNS_MUTATION=NO
```

After rollback the public HTTPS boundary for `local-agent.padiem.net` is removed on the Workers side; DNS for the hostname is outside this gate's authority and is intentionally untouched.

## Evidence recording

- Evidence belongs to the exact `exact_main_sha` the gate ran against; re-run the gate if `main` moved.
- Activation evidence is recorded in the #1828 issue (Phase B completion comment) and in the run log.
- No evidence of `WINDOWS_LIVE_CANARY` or `USER_ROLLOUT` is claimed by this gate; those require separate work orders.

## Forbidden before owner authorization

```text
ACTIVATE_WITHOUT_CONFIRMATION = FORBIDDEN
ROLLBACK_WITHOUT_CONFIRMATION = FORBIDDEN
TARGET_HOSTNAME_OTHER_THAN_LOCAL_AGENT_PADIEM_NET = FORBIDDEN
WORKER_REDEPLOY_DURING_ACTIVATION = FORBIDDEN
DURABLE_OBJECT_DELETE_DURING_ROLLBACK = FORBIDDEN
DURABLE_OBJECT_STORAGE_MIGRATION_DURING_ROLLBACK = FORBIDDEN
WORKER_DELETE_DURING_ROLLBACK = FORBIDDEN
DNS_AUTHORITY_MUTATION_BY_GATE = FORBIDDEN
WINDOWS_LIVE_CANARY_CLAIM = FORBIDDEN
USER_ROLLOUT_CLAIM = FORBIDDEN
PRODUCTION_READY_CLAIM = FORBIDDEN
```
