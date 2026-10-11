# Change mode

Choose one:

```text
REPORT_MODE=COMPACT | EXTENDED
DELIVERY_MODE=NORMAL | MVP_HANDOFF
TEST_CLASS=T0 | T1 | T2 | T3
```

Default for a bounded bug fix/tiny glue change is `REPORT_MODE=COMPACT`.

Use `EXTENDED` only when the change is materially broad/high-risk, needs independent environment validation, or the work contract explicitly requires it.

---

## Authority / revision

- Issue / work order:
- Exact starting base SHA:
- Branch:
- Exact current head SHA:

## Scope

- Exact changed files:
- User/runtime behavior changed:
- Explicit non-goals:
- Shared authority / auth / persistence / migration / billing / secret boundary touched? yes/no:

## Implementation evidence

- Focused load-bearing regression:
- Commands/checks run against this head:
- Exit/status and pass/fail/skip counts:
- `DEV_FAST_GATE=PASS|FAIL|NOT_RUN`:
- `DEV_ACTOR_RELEASED=YES|NO`:
- Relevant configured CI:
- Observational/non-blocking CI, if any:
- Known limitations:
- Production mutation: 0 / authorized:

After `DEV_FAST_GATE=PASS`, the implementation actor may continue another authorized issue while independent Windows/Ubuntu/browser/full validation proceeds asynchronously. The fast gate is not merge approval.

Do not present implementer-run local/browser checks as independent Local Validation.

## Validation decision

- Independent validation: REQUIRED / NOT_REQUIRED
- Reason:
- `VALIDATOR_WINDOWS=PENDING|PASS|FAIL|FIXING|NOT_REQUIRED`:
- `VALIDATOR_UBUNTU=PENDING|PASS|FAIL|FIXING|NOT_REQUIRED`:
- `VALIDATOR_BROWSER=PENDING|PASS|FAIL|FIXING|NOT_REQUIRED`:
- `FULL_VALIDATION=PENDING|PASS|FAIL`:
- If REQUIRED, validator / exact head / result / artifact:
- If MVP_HANDOFF, fixed handoff blockers:
- If MVP_HANDOFF, required final Production smoke:

## CTO final status

```text
NOT_REVIEWED / NOT_READY / CONDITIONALLY_READY / READY / READY_FOR_CUSTOMER_HANDOFF
```

Only the Web CTO assigns this status.

---

# EXTENDED-only sections

Complete the sections below only when `REPORT_MODE=EXTENDED`. Delete or leave N/A for COMPACT changes.

## Purpose

State the smallest product/business question this change is intended to answer.

## Technology adoption / build decision

For substantial new commodity capability work:

- Landscape scan required? yes/no + reason:
- Parent adoption decision:
- Internal/OSS/commercial candidates reviewed:
- Selected approach:
- Adoption mode:
- Upstream version/commit:
- License/model-artifact/commercial posture:
- `SECOND_PRODUCT_AUTHORITY=0`:
- `BUILD_FROM_SCRATCH_JUSTIFIED=YES/NO/N/A`:

## Evidence dimensions

Mark `REQUIRED`, `NOT_REQUIRED`, or `PENDING` and link evidence.

- Technical implementation:
- UI / visual:
- UX / journey:
- Backend / runtime:
- Security / privacy:
- Market / reference:
- Commercial / business:
- Production:

## Owner-only decisions

- Required? yes/no:
- Decision/status:
- `OWNER_UI_APPROVED` or equivalent must not be inferred when the contract reserves that decision to the owner.

## Risks and limitations

- Known defects:
- Deferred items:
- Environment limitations:
- Data/secret boundary:
- External security/compliance checks:
- Any red signal + exact disposition/waiver authority:
- Runtime trust-boundary review needed? yes/no + affected parser/builder/projector/serializer/export/write coverage:
- Load-bearing mutation/differential proof required? yes/no + evidence:

## Merge / deployment

- Merge authority:
- Expected head for merge:
- Deployment target/risk level when applicable:
- Last known-good Production source/configuration:
- Recovery fix/revert path:
- Preview/staging/manual deployment exception: none unless explicitly authorized.

For Git-connected projects, an authorized merge to the configured Production branch is the deployment action; do not create a second manual deployment path.

## Completion checklist

Use only the items applicable to this change.

- [ ] Current remote main/head/diff were re-read before final review.
- [ ] The changed claim is demonstrated for the exact reviewed revision.
- [ ] No unrelated files are included.
- [ ] Failed/skipped/unexecuted checks are reported truthfully.
- [ ] No secrets, tokens, credentials, personal data, or private evidence were committed.
- [ ] Independent validation claims satisfy the actor-separation rule and the exact-head validator/result/report pointer is discoverable from this PR, or NOT_REQUIRED is explicitly justified.
- [ ] Required `FULL_VALIDATION` is PASS on the final exact head before merge; pending full validation did not unnecessarily block unrelated implementation work.
- [ ] Any external red security/compliance signal is resolved or has an explicit authorized disposition/waiver; unrelated green CI is not used as a substitute.
- [ ] Contract defects were traced through downstream trust boundaries when applicable; explicit null/undefined/missing semantics are preserved.
- [ ] Load-bearing mutation/differential proof was recorded when required by the work contract/review.
- [ ] Owner-only decisions are not inferred.
- [ ] Production claims, when applicable, are tied to the actual deployed revision.

Do **not** add unrelated tests/checklist items merely because they exist. Follow `docs/operations/TEST_SCOPE_AND_DELIVERY_POLICY.md`.
