# Web CTO Work Order: B14 Candidate Provider Onboarding

## Authority / revision

- Repository: `skerishKang/ai-revenue-lab`
- Branch: `feat/b14-provider-onboarding`
- Product-evidence stage: `RUNTIME_PILOT`
- Related issue: `#2679`

Lineage of this revision, oldest first:

```text
ORIGINAL_IMPLEMENTATION_BASE=616f4015c3d214f27bf00f1ebb060e3376d1b299
PREVIOUS_REFRESH_BASE=ac344e3f3dcfd2e00d25f2ec087a144fe6d80d6b
PREVIOUS_REFRESH_HEAD=d36acdec78409ca79ae94042ab73f0c69070a11f
REFRESH_BASE=c99c9703866ada4e3ca34dfc95a4d2b98b4eea26
CURRENT_PR_HEAD=GitHub PR #2680 metadata is authoritative after this documentation commit
```

Refresh bases are merge-forward checkpoints only; no rebase, force-push, or
history rewrite was used. The exact current head is not mirrored here because
GitHub PR #2680 metadata is the authoritative source and a self-referential
final SHA would go stale on the next commit.

## Objective

Add four owner-confirmed candidate providers to the B14 Worker evaluation plane so their performance can be measured without exposing credentials or changing the current user-visible Plus route or the internal fixed-chain spare position.

## Confirmed Cloudflare metadata

Authenticated browser inspection of the `charliekant@gmail.com` Cloudflare account confirmed active Workers Secrets Store entries. Secret values were not opened or read.

| Provider | Binding | Model | Fixed origin |
|---|---|---|---|
| Infron | `PADIEM_INFRON_API_KEY` | `motif/motif-3` | `https://llm.onerouter.pro/v1` |
| Inception | `PADIEM_INCEPTION_MERCURY_API_KEY` | `mercury-2.5` | `https://api.inceptionlabs.ai/v1` |
| Atria | `PADIEM_ATRIA_API_KEY` | `Atria-Dawn-Preview` | `https://api.atria-asi.ai/v1` |
| Experiential Labs | `PADIEM_EXLAB_API_KEY` | `gpt-5.6-luna` | `https://api.experientiallabs.ai/v1` |

## Scope

- Add provider registration modules and exact model metadata.
- Add metadata-only Secrets Store binding declarations to `wrangler.toml`.
- Add Worker binding allow-list entries.
- Register candidates in private exact-ID lookup only.
- Add network-free mock, readiness, credential-isolation, direct request, streaming, and actual-response-model tests.
- Preserve the current user-visible Plus route, the internal fixed-chain spare position, and public catalog boundaries.

## Route authority (preserved, not changed by this work order)

- Agnes remains the sole executable user-visible Plus route.
- Poolside remains `CANDIDATE_DATA_ONLY` in the user-visible Plus tier.
- The separate internal `b14/auto` fixed-chain still keeps Poolside as its second/spare position.
- `USER_VISIBLE_AUTO=OFF`.
- `SILENT_FALLBACK=NO`.
- This work order changes none of those authorities.

## Non-goals

- No candidate becomes `b14/auto` eligible.
- No candidate is added to the user-facing catalog.
- No Plus/Pro route activation or tier change; no new executable Plus route and no change to the existing Poolside `CANDIDATE_DATA_ONLY` status.
- No Production deployment, direct Wrangler mutation, Preview/staging bypass, or Docker.
- No secret value access, logging, screenshots, or reports.
- No live provider performance measurement in this onboarding revision.

## Acceptance criteria

1. Each candidate has an exact provider ID, fixed HTTPS origin/host, model ID, upstream model, and confirmed binding name.
2. Missing credentials fail closed before transport calls.
3. Mock mode performs zero upstream calls.
4. Provider credentials cannot be borrowed across candidates.
5. Direct and streaming requests preserve exact upstream model and actual response model evidence.
6. Candidates remain explicit-only/private and cannot enter `b14/auto`.
7. B14 full tests, compile checks, and diff scope checks pass.

## Evidence boundary

- Cloudflare readiness: metadata-only, browser-confirmed, values not accessed.
- Implementation verification: local, non-independent until a separate validator runs on the committed head.
- Live performance evidence: not produced by this revision.
- Production: deferred; separate owner-authorized activation work required.
