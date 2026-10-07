# B66 Reproduction Certification

~~~text
DOC_STATUS = CANONICAL_PRODUCT
OWNER = B66 product
ISSUE_AUTHORITY = #3595
FIRST_REFERENCE_IMPLEMENTATION = CGI
~~~

## Purpose

B66 users generally cannot validate the internal quality of workbook/document analysis. They can validate the result they care about: whether the learned quotation is reproduced like the document their business already uses.

Reproduction certification is therefore a mandatory pre-execution gate for new source-derived templates.

## Baseline certification flow

~~~text
Canonical Quote Template candidate
+ source reference facts
-> reproduction PDF
-> structural/visual oracle
-> critical-element review
-> mutation robustness
-> CERTIFIED | CERTIFIED_WITH_TOLERANCE | REJECTED
~~~

No changed customer/project/amount data is introduced before the baseline reproduction is judged.

## Required evidence dimensions

A single whole-page image score is useful but insufficient.

| Dimension | What it protects |
|---|---|
| Page geometry | page size, orientation, print area, margins, scale, page count |
| Layout geometry | section/table/cell positions, row heights, column widths |
| Text position | X/Y placement and clipping |
| Font identity | source font family, bold/weight and substitution |
| Font size | nominal/rendered size |
| Typography metrics | glyph width, tracking, baseline, line-height |
| Text behavior | wrapping, shrink-to-fit, overflow |
| Table/vector geometry | borders, fills, horizontal/vertical lines |
| Logo geometry | position, size, aspect ratio |
| Stamp geometry | position, size |
| Stamp alpha | transparent/non-ink background behavior |
| Asset layering | stamp/logo/text z-order |
| Reference values | source/sample value parity |
| Raster similarity | whole-page and important-region image difference |

Critical-element failures cannot be hidden by a favorable aggregate raster score.

## Fidelity priority

When debugging reproduction, use source facts first and calibrate renderer behavior second.

~~~text
1. page / layout position
2. font identity
3. text metrics / spacing / baseline
4. logo geometry
5. stamp geometry / alpha / layering
6. lines / fills / remaining raster residual
~~~

Do not make unexplained per-cell nudges while an underlying source metric or systematic renderer calibration remains unresolved.

## Renderer bake-off

Renderer selection is empirical.

~~~text
Canonical -> HTML/Chromium -> PDF
Canonical -> Google Sheets -> PDF
Canonical -> clean XLSX -> Excel/Office -> PDF
Canonical -> future native/document renderer
~~~

Each candidate is judged against the same reference PDF and the same critical evidence dimensions. An office-native renderer is not preferred merely because the source originated in Excel/HanCell. A fast HTML renderer may be the execution renderer when it certifies better and avoids network/cloud conversion latency.

Editable XLSX/Sheet output remains valuable even if it is not the final-PDF renderer.

## CGI evidence lineage

CGI is the first reference implementation. Current evidence lives in issues rather than this stable policy document:

- #3574 — HTML V3 reconstruction and canonical page representation.
- #3578 — native-workbook / renderer bake-off.
- #3581 — Google Drive + Sheets path.
- #3584 — workbook asset/geometry normalization.
- #3545 — CGI source-derived fidelity.
- #3496 — editable/native XLSX output.
- #3586 — source-format intake policy.

Measured scores in those issues are evidence snapshots, not universal thresholds.

## Certification states

~~~text
ANALYZED
REPRODUCTION_IN_PROGRESS
CERTIFIED
CERTIFIED_WITH_TOLERANCE
REJECTED
~~~

CERTIFIED means the required structural and visual gates pass for the declared template scope and bounded mutation-robustness checks pass.

CERTIFIED_WITH_TOLERANCE means a material or noticeable deviation remains, but the user/owner saw it and explicitly accepted it for the convenience/value of the workflow. Record the reference artifact, reproduction artifact, exact accepted differences, their evidence, and explicit acceptance. Do not infer acceptance from silence or continued product use.

REJECTED means the template must not enter normal execution. Preserve source/evidence and either improve/rebuild the template or choose another renderer.

## Mutation robustness

Baseline similarity proves the default/reference instance. Before execution, test representative changes that can stress the layout: short/long recipient, short/long project name, contact/representative text, small/large numeric values, supported item-count boundaries, date/quote number and wrap/shrink-to-fit boundaries.

The objective is not exhaustive combinatorial testing. It is evidence that realistic user changes do not destroy the certified document behavior.

## Threshold policy

There is no universal global RASTER_DIFF < X rule. Each template certification records the metrics and material gates relevant to its source. Strong aggregate similarity cannot waive a critical visible defect. Conversely, minor renderer antialiasing differences do not require pixel identity when geometry, typography, assets and business presentation are materially equivalent.

Only explicit user/owner acceptance may turn a known material deviation into CERTIFIED_WITH_TOLERANCE.

## Runtime consequence

~~~text
UNCERTIFIED_NEW_TEMPLATE_EXECUTION = DENIED
CERTIFIED_TEMPLATE_REPEAT_ANALYSIS = 0
CERTIFIED_TEMPLATE_REPEAT_CERTIFICATION = 0
~~~

The point of certification is to make later quote generation fast and predictable.
