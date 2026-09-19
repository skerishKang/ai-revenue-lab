# Web Developer Report: B14 Candidate Provider Onboarding

## Revision

Lineage of this revision, oldest first:

```text
ORIGINAL_IMPLEMENTATION_BASE=616f4015c3d214f27bf00f1ebb060e3376d1b299
PREVIOUS_REFRESH_BASE=ac344e3f3dcfd2e00d25f2ec087a144fe6d80d6b
PREVIOUS_REFRESH_HEAD=d36acdec78409ca79ae94042ab73f0c69070a11f
REFRESH_BASE=c99c9703866ada4e3ca34dfc95a4d2b98b4eea26
CURRENT_PR_HEAD=GitHub PR #2680 metadata is authoritative after this documentation commit
```

- Branch: `feat/b14-provider-onboarding`
- Related issue: `#2679`

The refresh bases above are merge-forward checkpoints only. No rebase, force-push,
or history rewrite was performed at any point in this lineage. The exact current
head is intentionally not mirrored here: GitHub PR #2680 metadata is the
authoritative source and a self-referential final SHA would go stale on the next
commit.

## Implemented

- Registered Infron / Motif 3, Inception / Mercury 2.5, Atria / Dawn Preview, and Experiential Labs / GPT-5.6 Luna.
- Added confirmed metadata-only Secrets Store bindings using store `f0b09ca04a7b43248154c773704a5616`.
- Added Worker environment allow-list names.
- Kept all four candidates out of public `CATALOG_MODELS` and `b14/auto`; they are exact-ID manual-pin routes only.
- Added tests for route identity, readiness redaction, missing-key fail-closed behavior, cross-provider key isolation, mock zero-call behavior, fixed-origin requests, streaming, and actual response model evidence.

## Route authority (unchanged by this PR)

- Agnes remains the sole executable user-visible Plus route.
- Poolside remains `CANDIDATE_DATA_ONLY` in the user-visible Plus tier.
- The separate internal `b14/auto` fixed-chain still keeps Poolside as its second/spare position.
- `USER_VISIBLE_AUTO=OFF`.
- `SILENT_FALLBACK=NO`.
- This PR changes none of those authorities.

## Cloudflare evidence

The authenticated Tabbit browser inspected the correct `Charliekant@gmail.com's Account` Secrets Store. The following entries were visible as active Workers secrets; values were never opened:

- `PADIEM_INFRON_API_KEY`
- `PADIEM_INCEPTION_MERCURY_API_KEY`
- `PADIEM_ATRIA_API_KEY`
- `PADIEM_EXLAB_API_KEY`

## Self-check

| Check | Result |
|---|---|
| `uv run pytest -q` in `apps/korean-ai-platform` | `916 passed` |
| `git diff --check` | pass |
| Secret values accessed | no |
| Production deployment | no |
| Live provider calls | no |

## Disposition

```text
IMPLEMENTED / ACTIVATION_PENDING
```

This revision only adds evaluation-plane onboarding. It does not activate any candidate as Plus/Pro, alter fixed-chain routing, or claim live performance evidence.
