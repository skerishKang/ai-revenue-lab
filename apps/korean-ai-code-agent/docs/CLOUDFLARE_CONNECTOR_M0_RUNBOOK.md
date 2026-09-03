# B54 Cloudflare Connector M0 Runbook

Issue: #1725  
Parent: #1650  
Related operational gate: #1589

## Authority

```text
Trusted connector authority
  = Cloudflare credential custody + exact resource binding

P01
  = tool / approval / evidence authority

B54 Cloudflare connector
  = bounded Cloudflare read/write adapter contracts
```

Raw API tokens, Global API keys, build tokens and environment-variable values never enter B54 task/model state.

## #1589 is separate

#1589 is the immediate operational problem of stopping unrelated monorepo commits from triggering B14 Production Workers Builds.

This connector can later inspect/manage the same build configuration, but #1650/#1725 must not be used as a reason to postpone the external #1589 fix.

## Read-first resource model

The connector binds exact resources:

```text
Padiem workspace
→ Cloudflare account
   ├─ exact Workers
   ├─ exact Pages projects
   └─ exact zones
```

No wildcard/all-account binding is accepted by repository M0.

Visible safe state includes:

- Worker versions;
- active Worker deployment and traffic percentages;
- explicit prior rollback target;
- Pages production and preview deployments;
- successful inactive production rollback target;
- Workers Builds root directory;
- branch include/exclude;
- path include/exclude;
- build/deploy command fingerprints;
- environment-variable names only;
- bounded logs/status evidence.

Cloudflare-originated logs and metadata are untrusted data, not instructions.

## Workers version/deployment distinction

Cloudflare Workers versions capture Worker code/configuration state. Deployments determine which version(s) serve traffic.

Repository M0 therefore never treats a version ID as proof that it is currently active. Current Production state must come from deployment readback.

A Worker deployment may contain one version at 100% or two versions whose percentages total 100%.

## Worker rollback

A Worker rollback activates a previous version by creating a new deployment. Platform-resource state such as KV/R2/D1/Durable Object resources is not fully versioned with Worker code, so rollback compatibility must be checked before approval.

Production plan requires:

```text
expected current deployment
+ exact target version
+ source/artifact identity
+ bounded diff
+ explicit P01 approval/evidence
+ recovery target
+ rollback/resource compatibility review
+ post-action deployment readback
+ smoke evidence
```

## Pages rollback

Pages preview and production deployments are distinct.

Only a successful inactive production deployment may be used as repository M0 rollback target. Preview deployments never satisfy rollback eligibility.

## Workers Builds configuration

Current Workers Builds exposes configuration including:

- root directory;
- branch includes/excludes;
- path includes/excludes;
- build/deploy commands;
- build-time environment variables.

Repository M0 exposes path/branch/root configuration and command fingerprints, but not environment-variable values or build tokens.

Workers Builds configuration API has a distinct credential boundary: current Cloudflare documentation requires a user-scoped API token with Workers Builds Configuration permission. The connector must not silently substitute a broad all-account credential.

## Preview vs Production

```text
PREVIEW
  = preview_deploy / retry_preview_build
  = separate non-Production plan

PRODUCTION
  = production_deploy
  = worker_rollback
  = pages_rollback
  = build_config_update
  = explicit Production plan only
```

Authentication alone never grants Production authority.

## Forbidden defaults

```text
DNS_DEFAULT_WRITE = NO
SECRET_READBACK = NO
GLOBAL_API_KEY = NO
BILLING_MUTATION = NO
MEMBERSHIP_MUTATION = NO
ALL_ACCOUNT_BINDING = NO
```

DNS mutation, if ever added, requires a dedicated stronger tool/issue rather than generic Cloudflare Production authority.

## Production receipt

A successful Production action is not complete until the connector records:

```text
before release
approved target release
actual after release
provider request ref
recovery target
readback evidence
smoke evidence
smoke PASS
```

If actual readback does not equal the approved target, or smoke fails, the receipt cannot claim success.

## Live gate

Before #1650 can be marked live-ready:

1. bind an exact Cloudflare account and exact resources;
2. validate least-privilege API token/OAuth permissions and expiry;
3. inspect current Worker/Pages release state;
4. prove current and rollback targets are visible;
5. inspect Workers Builds root/watch paths without secret values;
6. verify #1589 watch-path behavior separately;
7. perform read-only status/log canary;
8. if preview writes are enabled, perform one approved preview canary;
9. Production action requires separate explicit owner/P01 approval;
10. prove post-action readback, smoke and recovery path.

## Non-claims

```text
REAL_CLOUDFLARE_CREDENTIAL_CONFIGURED = NO
REAL_CLOUDFLARE_READ = NO
REAL_PREVIEW_DEPLOY = NO
REAL_PRODUCTION_DEPLOY = NO
REAL_ROLLBACK = NO
REAL_BUILD_CONFIG_MUTATION = NO
REAL_DNS_MUTATION = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```
