# B71 AI Operations — web MVP

**Status:** proposed Business number / technical MVP. Tracking: [#5451](https://github.com/skerishKang/ai-revenue-lab/issues/5451).

This is the web surface for the three B71 workstreams. It is a **static site**
that renders the sample results the workstreams already produced. It calls no
backend, no sales channel, no ERP and no remote computer.

## What it shows

| Screen | Route | Source |
|---|---|---|
| Dashboard | `#/dashboard` | the three workstream reports |
| Product listing | `#/product` | `apps/korean-ai-code-agent/pilots/product-listing/out` (#5446) |
| ERP item master | `#/erp` | `apps/erp-item-master/samples/out` (#5447) |
| Order fulfilment | `#/orders` | `apps/korean-ai-code-agent/pilots/order-supply-fulfillment/out` (#5448) |
| Remote work demo | `#/remote` | empty by design, until a real browser-control session exists |

## Synthetic data

Every screen states that it shows synthetic sample data. The site is not
connected to a customer account, a sales channel, an ERP system or a remote
computer. The remote-work screen is deliberately empty: it shows the event
contract the product already classifies and an explicit "not connected" state,
so the site can never look connected when it is not.

## Data pipeline

`apps/business-71-ai-operations/scripts/build_web_data.py` is the only place
the dataset is produced. It reads the three workstream outputs and writes one
JSON file per screen into `data/`. It re-implements no parser, no normalizer
and no state machine, and it produces deterministic output: re-running it on an
unchanged tree writes byte-identical files.

```bash
python apps/business-71-ai-operations/scripts/build_web_data.py          # rebuild
python apps/business-71-ai-operations/scripts/build_web_data.py --check  # fail when stale
```

## Layout

```text
index.html            # the single deployed entry page
styles/app.css        # PADIEM brand tokens reused from the portfolio console
scripts/app.js        # hash router, filters, downloads
data/*.json           # generated dataset (rebuild with the script above)
evidence/             # local verification script and its recorded result
```

## Verification

```bash
python reference/business-71-ai-operations-v1/evidence/validate-web.py
python -m pytest apps/business-71-ai-operations/tests -q
```

## Confidentiality boundary

No customer names, amounts, negotiated terms, sales strategy, internal
business forecasts, customer information or private policy content appear in
this directory, its dataset, or the issues and pull requests that track it. The
business source of truth is COM1 local `ai-revenue-lab-governance/사업방침/`.
