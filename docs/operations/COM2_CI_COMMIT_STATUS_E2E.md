# `COM2 full policy` commit-status path

How the one required status check is produced and how to read it, verified against `main` on
2026-10-21. Companion document: `COM2_CI_PRIMARY_FAILOVER_VERIFY.md`.

## The status

- Context: `COM2 full policy`. It is the sole entry in the active ruleset
  `PADIEM COM2 policy gate` (id `25431914`) and is non-strict, so it is required for merging but
  does not have to be re-run after every `main` movement.
- Poster: `.github/workflows/com2-pr-auto-sandbox.yml`. The job writes `pending` on the exact PR
  head with `target_url` pointing at its own run, then writes `success` or `failure` from the
  measured suite outcome. Nothing else posts this context.
- Runner: GitHub-hosted `ubuntu-24.04`. The context name says COM2 for historical reasons only;
  the required policy run is no longer executed on a self-hosted COM2 machine.
- Scope: only an open, same-repository PR head. A fork PR, a closed PR or a run whose trigger
  workflow did not succeed leaves the context absent rather than fabricated.

## End-to-end chain for one push

```text
push to PR branch
→ com2-pr-policy-trigger.yml        (pull_request, hosted, no checkout)  → trusted PR event
→ com2-pr-auto-sandbox.yml          (workflow_run, hosted ubuntu-24.04)   → offline container policy suite
→ POST /statuses/<exact head sha>   context "COM2 full policy"
→ ruleset "PADIEM COM2 policy gate" reads that context and gates the merge
```

Each status is pinned to the head SHA it tested. A later push produces a new SHA, and the previous
run's success does not carry over; the sandbox re-resolves the still-open PR and its current head.

## Reading a run

- `COM2 policy dispatch` success proves only that the trusted PR event was emitted. It is not the
  policy suite result and must not be reported as one.
- The suite verdict is the job in `com2-pr-auto-sandbox.yml`; the `pending` → `success` transition
  on the context is the acceptance signal.
- COM2 browser canaries publish **different**, non-required contexts (for example
  `COM2 B62 generic browser canary`). A canary success is selective special-QA evidence for its
  exact head, never the required gate, and a canary whose QA step is `skipped` by its own path
  selector is not a QA pass.

## Dated record

This file originally described the pilot that first exercised the reporter:

> This documentation-only change exercises the `COM2 full policy` commit status reporter against
> the exact open PR head. It does not alter a product, deploy, or CI policy. Hosted blocking PR
> checks remain active during verification.

That was the state during the COM2-primary pilot. Hosted blocking checks remain active today, and
the required context itself is now produced hosted; the historical wording is kept here unchanged.
