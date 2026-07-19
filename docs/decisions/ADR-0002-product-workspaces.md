# ADR-0002: Organize Each Revenue Experiment as an Independent Product Workspace

- Status: Decided
- Date: 2026-07-20
- Supersedes: repository-root application paths described in the initial Personal Edition architecture

## 1. Decision

AI Revenue Lab is the portfolio repository. Each user-facing revenue experiment lives in its own directory under `apps/`.

```text
ai-revenue-lab/
├─ apps/
│  ├─ personal-edition/
│  ├─ world-feed/
│  ├─ living-travel/
│  └─ living-fiction/
├─ docs/
├─ platform/          # created only when two products demonstrably share code
├─ experiments/       # created when executable benchmark artifacts exist
└─ .github/
```

The first implementation therefore lives under:

```text
apps/personal-edition/
```

and not in repository-root `app/`, `tests/`, `scripts/`, `pyproject.toml`, or `.env.example` paths.

## 2. Rationale

The repository is intended to test several products derived from one AI production thesis. A root-level application would make the first experiment appear to be the entire project and would later force disruptive relocation or ambiguous ownership.

Product workspaces provide:

- clear boundaries between different revenue experiments;
- independent dependencies, commands, tests, data, and deployment choices;
- the ability to stop or archive one experiment without destabilizing others;
- parallel product design and implementation;
- evidence accounting by product;
- a controlled path for extracting genuinely shared components later.

## 3. Workspace contract

Each active product workspace may contain its own:

```text
apps/<product>/
├─ README.md
├─ pyproject.toml or equivalent package manifest
├─ .env.example
├─ app/ or src/
├─ tests/
├─ scripts/
├─ migrations/
└─ product-local fixtures and static assets
```

Commands must be runnable from that product directory unless the root README explicitly provides a workspace-aware command.

## 4. Shared code rule

Do not create a broad shared platform merely because two products might eventually need similar functionality.

Code may move to `platform/` or a shared package only when:

1. at least two implemented products use substantially the same behavior;
2. the interface is supported by working tests in both products;
3. extraction reduces duplication without coupling unrelated release schedules;
4. the change is approved through a separate architecture decision.

Until then, limited duplication is preferable to premature abstraction.

## 5. Product statuses

- `personal-edition`: active first revenue experiment;
- `living-travel`: next specialization candidate and active design track;
- `world-feed`: flagship scale-information candidate and active research track;
- `living-fiction`: active product-concept and narrative-system research track.

Only Personal Edition is authorized for implementation at this stage. Placeholder directories for the other products contain scope and decision records, not speculative application code.

## 6. Parallel-work rule

Parallel work is encouraged when tracks do not depend on unfinished implementation:

- Personal Edition implementation may proceed through narrowly scoped issues;
- Living Travel, World Feed, and Living Fiction may proceed through product contracts, user-loop design, economic hypotheses, and benchmark fixtures;
- common infrastructure must not be implemented in advance of demonstrated reuse;
- no secondary product may silently redefine the first product's implementation contract.

## 7. Consequence for existing issue #3

Issue #3 must use `apps/personal-edition/` as its workspace root. Its allowed files, commands, and changed-file evidence must all be interpreted relative to that directory.
