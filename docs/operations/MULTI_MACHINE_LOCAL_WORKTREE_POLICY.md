# Multi-Machine Local Worktree Policy

- Status: **CANONICAL OPERATING CONSTRAINT**
- Effective: 2026-10-07
- Scope: repository-wide AI-assisted development work that runs on more than one developer machine
- Work-identity authority: `AI_DEVELOPMENT_OPERATING_POLICY.md` §6
- Repository entry point: `AGENTS.md`

## 1. Why this constraint exists

AI Revenue Lab work is executed from more than one physical machine. Each machine keeps its own Git clone and its own local worktrees. Git worktree registration metadata is stored inside the clone that created it, so a worktree created on machine A cannot be resolved, repaired, or reused from machine B.

Treating another machine's checkout as an authority has already caused a real defect: a lane read source from a secondary local clone whose local `main` was ~9 days stale and still declared a superseded model primary, which contradicted the current Owner policy. The lane's conclusion was wrong until the exact remote head was read instead.

The rule that follows is simple: **the remote is the only cross-machine source of truth; local checkouts are per-machine working copies.**

## 2. Contract

```text
GITHUB_ORIGIN=CROSS_MACHINE_SOURCE_OF_TRUTH
WORKTREE_METADATA=MACHINE_LOCAL
UNC_REMOTE_MACHINE_REPO=REFERENCE_ONLY
CROSS_MACHINE_UNC_MUTATION=NO

COMP1_CANONICAL_REPO= G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab
COMP1_REFERENCE_FROM_COMP2= \\PADIEM-COMMAND-\내pcG\Ddrive\BatangD\task\workdiary\ai-revenue-lab
COMP2_CANONICAL_LOCAL_REPO= C:\ai-revenue-lab

MACHINE_HANDOFF=COMMIT_PUSH_REMOTE_HEAD
STALE_LOCAL_MAIN_AUTHORITY=NO
WRONG_REPO_MUTATION=NO
REMOTE_FETCH_BEFORE_JUDGMENT=YES
LOCAL_NUMBER_MACHINE_BINDING=NO
```

## 3. Machine identity

| Machine | Role | Canonical local repository |
| --- | --- | --- |
| `COMP1` | Owner workstation (`PADIEM-COMMAND-`, owner user `limone`); hosts the `E:` / `G:` working drives and most long-lived lane worktrees | `G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab` |
| `COMP2` | Secondary development machine (owner user `user`); drives `C:` and `D:` only | `C:\ai-revenue-lab` |

`COMP1` may be reached from `COMP2` only through its network share:

```text
COMP1_REFERENCE_FROM_COMP2=\\PADIEM-COMMAND-\내pcG\Ddrive\BatangD\task\workdiary\ai-revenue-lab
```

That share exposes `COMP1`'s `G:` drive. It does **not** expose `COMP1`'s `E:` drive, and it is not a local repository.

## 4. COMP2 preflight (required before any Git judgment or mutation)

Every lane running on `COMP2` runs this preflight first and records the output in its report:

```bash
git remote get-url origin
git rev-parse --show-toplevel
git fetch origin --prune
git rev-parse origin/main
```

Rules:

- If `git remote get-url origin` is not `skerishKang/ai-revenue-lab`, **STOP**. Do not fetch, commit, push, or mutate anything. `WRONG_REPO_MUTATION=NO`.
- If `git rev-parse --show-toplevel` is not the expected `COMP2` repository for the lane, **STOP** and report the mismatch.
- `REMOTE_FETCH_BEFORE_JUDGMENT=YES`: no staleness, drift, mergeability, or policy claim may be made before `git fetch origin --prune` and a read of the exact remote head.
- The preflight reads the remote; it never writes to another machine.

## 5. Worktree rules

- `WORKTREE_METADATA=MACHINE_LOCAL`. A worktree is created and removed only on the machine whose clone registered it.
- Do not attempt to reuse, repair, prune, or re-register a worktree whose absolute path belongs to another machine (for example `COMP1`'s `E:\...` or `G:\...` paths seen from `COMP2`).
- Reconstruct the required state locally from the remote branch instead:

```bash
git worktree add -b <local-branch> <COMP2_LOCAL_PATH> origin/<remote-branch>
```

- `UNC_REMOTE_MACHINE_REPO=REFERENCE_ONLY`. The `\\PADIEM-COMMAND-\...` share is read-only reference material.
- `CROSS_MACHINE_UNC_MUTATION=NO`. Never run `git worktree add`, `git fetch`, `git commit`, `git push`, `git checkout`, or any other mutating Git command against the `COMP1` repository over the share. Mutating another machine's clone corrupts its worktree registry and can disturb unrelated lanes.
- Local branches may be named freely; a different local branch name never changes the push target. Push to the existing remote branch explicitly:

```bash
git push origin HEAD:<remote-branch>
```

## 6. Machine-bound absolute paths

Work orders frequently name absolute paths, because lanes are started with a specific directory (`E:\claw-...`, `C:\Temp\wt-...`). Those paths are **machine-bound**: a drive letter that exists on `COMP1` may not exist on `COMP2` at all.

When the requested work directory does not exist because its drive is absent on the current machine:

- do not treat it as a repository defect;
- do not silently mutate an unrelated checkout to compensate;
- record the requested path, the observed drive set, and the substitute path actually used, and surface all three in the report.

## 7. Source-of-truth and staleness rules

```text
GITHUB_ORIGIN = CROSS_MACHINE_SOURCE_OF_TRUTH
LOCAL_MAIN    = MACHINE_LOCAL_WORKING_COPY
```

- `STALE_LOCAL_MAIN_AUTHORITY=NO`. A local `main`, a stale remote-tracking ref, or a lane's cached checkout carries no authority for drift, policy, or mergeability claims. Only the freshly fetched remote head does.
- `MACHINE_HANDOFF=COMMIT_PUSH_REMOTE_HEAD`. The unit of handoff between machines is a commit pushed to the remote, identified by its exact head SHA. Uncommitted local work is not handoff material.
- A lane's report must name the exact base SHA and exact head SHA it worked against, so a lane on another machine can reproduce the revision without trusting any local checkout.
- Evidence belongs to the SHA it tested, regardless of which machine produced it.

## 8. Python editable-install hazard

Machines and lanes share one Python interpreter per user environment. Editable installs (`pip install -e`) record an **absolute path to the worktree that installed them**, so `import` may silently resolve to a different worktree's source than the lane is editing.

Before treating any test result as evidence for a revision:

- confirm the import origin, for example:

```bash
python -c "import padiem_ai_core, padiem_control_plane; print(padiem_ai_core.__file__); print(padiem_control_plane.__file__)"
```

- pin the current worktree explicitly with `PYTHONPATH`, or use a dedicated per-lane environment, so the code under test is the code under review;
- never report a passing run whose imports came from another lane's worktree, and never reconstruct another lane's editable install as a side effect.

## 9. Scope boundary

This policy governs machine and worktree handling only.

It does not authorize any product change. Changing the operating documents under `docs/operations/` is the only mutation this policy requires; product source, model lanes, provider registration, routing, secrets, bindings, and Production remain untouched by it.

```text
OPERATIONS_DOCS_ONLY=YES
MODEL_SELECTION_CHANGE=NO
NEW_MODEL_REGISTRATION=NO
LIVE_MODEL_CALLS=0
LIVE_PROVIDER_CALLS=0
PRODUCTION_MUTATION=0
```

## 10. Short form

```text
REMOTE_IS_TRUTH=YES
LOCAL_CHECKOUT_IS_AUTHORITY=NO
FETCH_BEFORE_JUDGMENT=YES
OTHER_MACHINE_REPO_MUTATION=NO
OTHER_MACHINE_WORKTREE_REUSE=NO
RECONSTRUCT_FROM_REMOTE_BRANCH=YES
HANDOFF_VIA_COMMITTED_REMOTE_HEAD=YES
VERIFY_IMPORT_ORIGIN_BEFORE_TESTS=YES
LOCAL_LANE_NUMBER_IS_MACHINE_BOUND=NO
STOP_ON_REMOTE_IDENTITY_MISMATCH=YES
```
