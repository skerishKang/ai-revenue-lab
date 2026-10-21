# Online Product Listing Pilot — #5446

Status: **Local business-pilot slice (COM2)**  
Parent family: **B54 Padiem Claw Ops**  
Issue: **#5446**  
Local result document: [`../../../pilots/product-listing/README.md`](../../../pilots/product-listing/README.md)

## What this slice is

A preparation slice for the "온라인 상품 등록·판매채널 운영" business workflow. It takes one supplier product file, merges researched product facts, and produces the artifacts a seller console needs:

- one canonical product record with per-field provenance and review state;
- one registration draft per sales channel;
- a detail-page description;
- an image manifest checked against each channel's image rules;
- a bounded browser fill plan;
- a measured work log.

It publishes nothing. It opens no seller account, calls no channel API, uploads no image and submits no form.

## Reuse, not a new engine

The slice adds no AI engine, no provider call, no model route and no new authority. It reuses the existing Claw Ops contracts:

| Need | Reused source |
|---|---|
| field provenance and review state | `kagent/ops_intake.py` (`ExtractedField`, `ExtractionOrigin`, `FieldReviewStatus`) |
| supplier CSV intake pattern | `kagent/ops_csv_intake.py` |
| supplier XLSX parsing | `padiem_ai_core.document_normalization.extract_binary_document` |
| measured work log | `kagent/ops_pilot.py`, `kagent/ops_pilot_telemetry.py` |
| estimated-vs-measured separation | `kagent/ops_pilot.py` (`EvidenceQuality`) |
| browser action vocabulary | `kagent/browser_control_actions.py` |

New code: the product-listing domain model, the channel profile data and the channel-agnostic projection engine.

## Channel profiles are data

A channel registration form changes whenever the channel changes its console, so the field set lives in `kagent/ops_product_listing_channels.py` as declarative data with the public seller-document URLs and the date each profile was last checked. Coupang, Naver Smart Store, 11st and an own-mall (Cafe24-style) console are covered.

## Honest measurement rule

A baseline the team has not measured stays an estimate. `EvidenceQuality` keeps the two apart and the KPI engine refuses to compute a percent change from an estimated baseline. The pilot therefore reports measured durations and counts, and reports no productivity delta until a real manual baseline exists.

## Issue map

```text
#5446  Online product listing / sales-channel operations pilot (this slice)
#5447  ERP work (separate task, untouched)
#5448  Order and shipping linkage (separate task, untouched)
```
