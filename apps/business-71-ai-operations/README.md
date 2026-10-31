# B71 AI Operations — technical MVP workspace

Status: **proposed Business number / technical MVP**. Canonical numbering authority: `docs/portfolio/BUSINESS_REGISTRY.md`. Tracking: [#5451](https://github.com/skerishKang/ai-revenue-lab/issues/5451).

## Purpose

Reuse existing AI and automation capabilities to execute repeatable operational work across separate authorized workspaces. This is a small integration seam, not a new ERP, storefront, agent engine, model router or billing platform.

## Parallel technical workstreams

| Workstream | GitHub issue | Boundary |
|---|---|---|
| Product-data preparation and publishing workflow | [#5446](https://github.com/skerishKang/ai-revenue-lab/issues/5446) | Technical data/automation only |
| ERP item-master transformation and import preparation | [#5447](https://github.com/skerishKang/ai-revenue-lab/issues/5447) | Technical integration only |
| Order / fulfillment status workflow | [#5448](https://github.com/skerishKang/ai-revenue-lab/issues/5448) | Technical status/adapter only |

The three active workers own their respective branches and files. This workspace must not overwrite them.

## Minimum reusable job contract

A job receives `workspace_id`, `job_id`, `workflow_kind`, `source_ref`, and `requested_action` from an authorized caller. It produces `status`, `output_refs`, `validation_findings`, `human_review_needed`, `execution_evidence_ref`, and `error_code`.

Define schema and adapters against *existing* Core/Engine/Claw capabilities after confirming the working interfaces; do not create a duplicate authorization layer. Jobs must never treat one business workspace's files or execution authority as interchangeable with another's.

First technical acceptance: one synthetic end-to-end job, with input/output files and recoverable evidence. This README is **not** that acceptance and does not claim runtime implementation.

## Web MVP (static site)

The web surface for the three workstreams lives in
`reference/business-71-ai-operations-v1/`. It is a static site that renders the
sample results the workstreams already produced. It calls no backend, no sales
channel, no ERP and no remote computer, and every screen states that it shows
synthetic data.

```text
LIVE_URL=https://ai-revenue-business-71-ai-operations.pages.dev/
PAGES_PROJECT=ai-revenue-business-71-ai-operations
CUSTOM_DOMAIN=b71.padiem.net (attached, pending until one CNAME record exists)
```

| Path | Role |
|---|---|
| `reference/business-71-ai-operations-v1/` | The deployed static site |
| `apps/business-71-ai-operations/scripts/build_web_data.py` | The only place the site dataset is produced |
| `apps/business-71-ai-operations/tests/test_web_data_contract.py` | Dataset and site contract tests |
| `reference/business-71-ai-operations-v1/evidence/validate-web.py` | Serves the site locally and checks the served bytes |

The builder reads the three workstream outputs and writes one JSON file per
screen. It re-implements no parser, no normalizer and no state machine, and its
output is deterministic so a review can diff the dataset.

## Confidentiality boundary

No customer names, amounts, negotiated terms, sales strategy, internal business forecasts, customer information, or private policy content in public repository sources, issues, tests or PRs. The business source of truth is COM1 local `ai-revenue-lab-governance/사업방침/`; read relevant documents through authorized local access, and keep commercial decisions there.

## Next

1. Reuse three workstream results when available.
2. Build only the smallest missing shared technical seam.
3. Update the canonical portfolio registry via a reviewed PR when proposed-number status and workspace boundaries are reconciled.
4. Connect the remote-work screen to real browser-control events. Until that happens the screen stays empty on purpose, so it cannot look connected when it is not.
