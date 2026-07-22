# Personal Video Archive — Local Worker Handoff

Business: **13**
Implementation issue: **#62**
Workspace: `apps/personal-video-archive/**`

This document is intentionally executable as a local setup checklist.

## 1. Preconditions

Before implementation, verify directly:

- the latest `origin/main` SHA;
- Issue #62 state and its accepted implementation criteria;
- there is no existing open implementation PR for this workspace;
- the worktree path does not already exist;
- the proposed branch does not already exist locally or remotely;
- the base commit is the latest fetched `origin/main`;
- no files outside `apps/personal-video-archive/**` are authorized by the implementation issue.

Do not trust an old handoff SHA. Resolve the current remote state at the start of the session.

## 2. Suggested Windows paths

Use a dedicated worktree. Do not reuse another product worktree.

```powershell
$Repo = "G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab"
$Worktree = "G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-personal-video-archive"
$Branch = "feat/personal-video-archive-phase1-mvp-62"
$Venv = "G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-personal-video-archive-venv"
```

If the primary repository is stored elsewhere, change only `$Repo` and `$Worktree`.

## 3. Synchronize the primary checkout

```powershell
Set-Location $Repo
git status --short --branch
git remote -v
git fetch --all --prune
git rev-parse origin/main
git branch -r --list "origin/*personal-video-archive*"
git worktree list
```

Do not clean, reset, stash, delete, or modify an unrelated dirty checkout.

## 4. Create the isolated worktree

```powershell
git worktree add -b $Branch $Worktree origin/main
Set-Location $Worktree
git status --short --branch
git rev-parse HEAD
git merge-base HEAD origin/main
```

Expected result:

- clean worktree;
- `HEAD` equals the selected current `origin/main` base;
- merge base equals the same base commit;
- no unrelated files changed.

## 5. Read before coding

The worker must read:

```text
README.md
apps/README.md
apps/personal-video-archive/README.md
apps/personal-video-archive/PRODUCT_CONTRACT.md
apps/personal-video-archive/LOCAL_HANDOFF.md
docs/decisions/ADR-0002-product-workspaces.md
```

The worker must also inspect one current product workspace for repository conventions, but must not copy its domain assumptions blindly.

## 6. Scope boundary

Default allowed path:

```text
apps/personal-video-archive/**
```

Default forbidden paths include every sibling product, especially:

```text
apps/personal-edition/**
apps/living-travel/**
apps/world-feed/**
apps/living-fiction/**
```

Repository-root or shared-code changes require explicit issue acceptance criteria and CTO approval.

## 7. Phase 1 implementation

The Phase 1 implementation includes:

1. application scaffold inside the workspace (`app/`, `migrations/`, `tests/`, `templates/`, `static/`);
2. topic, query-rule, video, and private-record domain types;
3. persistence with migrations isolated to this workspace;
4. `VideoDiscoveryProvider` interface and `FakeVideoDiscoveryProvider`;
5. `LanguageModelProvider` interface and `FakeLanguageModelProvider`;
6. latest-first topic feed;
7. outbound canonical YouTube link;
8. opened, saved, completed, revisit, and irrelevant states;
9. reflection, plan, rating, tags, and timestamp notes;
10. unit and integration tests with no network calls;
11. LLM proposal validation, preview, and user-controlled acceptance/rejection;
12. provenance separation (YouTube / application / user).

## 8. Credential rule

No secret may be committed.

Future real-provider configuration should use an environment variable such as:

```text
YOUTUBE_API_KEY
```

The final name must be confirmed by the implementation issue. `.env` files, API keys, tokens, user data, and real provider responses must remain untracked.

Phase 1 uses only deterministic fake providers and synthetic fixtures. No real API key is required or accepted.

## 9. Setup and run commands

```powershell
# Create virtual environment
python -m venv $Venv
& "$Venv/Scripts/Activate.ps1"

# Install dependencies
cd $Worktree\apps\personal-video-archive
pip install -e ".[dev]"

# Run the application
python -m app.main
# Then open http://127.0.0.1:8000

# Run tests
pytest tests/ -v

# Run only unit tests
pytest tests/unit/ -v

# Run only integration tests
pytest tests/integration/ -v
```

## 10. Completion report requirements

A local worker report must include:

- local and remote branch names;
- base SHA and final HEAD SHA;
- commit parent relationship;
- changed files and additions/deletions;
- confirmation that all changes remain in the allowed scope;
- exact test commands and outputs;
- whether any real network call was made;
- whether any secret scan found a problem;
- pushed remote branch status;
- remaining risks and deferred work.

The CTO must independently verify the remote diff and CI before merge.
