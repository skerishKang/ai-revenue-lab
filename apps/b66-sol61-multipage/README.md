# b66-sol61-multipage

Sol 6.1 **native variable-row / continuous-A4** renderer for the B66 견적서 template.
It lives beside the certified bundle rather than inside it, so the hash-locked
public reference set (`reference/b66-public-standard-templates/cgi/v1`, 18 artifacts,
exact allow-list + SHA-256) is **resolved, never modified**.

## What it is, and is not

* For 1–3 item rows it delegates **verbatim** to the certified
  `quote_template.render_profile`, so certified output for the existing scope stays
  byte-identical. `slots.cjs` and the certified engine are used unchanged.
* It extends the same certified package to 4+ rows / multiple A4 pages. It does not
  replace it, re-create it, or fall back to another renderer.
* Source frame, column and cell geometry is read from the certified package
  (`template.json` bindings and `program.zlib`). Page/line-spacing policy constants
  are explicit in the module; this is the bounded CGI extension, not a generic compiler.
* Money, tax, rounding and Korean number words come exclusively from QuoteCore
  (`quote-core.js`) through `slots_multipage.cjs`; the Python side performs layout
  only.
* No model inference, no network, no browser, no HTML print path.

## Layout and bundle resolution

`SolMultipage(template_dir)` takes the directory that holds `template.json`,
`program.zlib` and `resources.pdf` — the same directory the certified engine itself
expects. It resolves the rest of the certified package from `<parent>/engine` and
`<parent>/quote-core.js`, and **fails closed** if they are absent, instead of
silently importing whatever `quote_template` happens to be on `sys.path`.

```
apps/b66-sol61-multipage/
  sol61_multipage.py                      renderer (CLI + importable API)
  slots_multipage.cjs                     QuoteCore adapter, variable row count
  tests/test_multipage_image_regression.py
```

## Usage

```
python apps/b66-sol61-multipage/sol61_multipage.py \
  --template reference/b66-public-standard-templates/cgi/v1/sol61/template \
  --out /tmp/quote.pdf \
  --request request.json
```

`request.json` is `{"changes": {...}}` or the changes object itself, with
`recipient`, `project`, `issueDate`, `quoteNo` and `items[]`
(`name`, `spec`, `unit`, `qty`, `unitPrice`, `note`). `--items N` builds a synthetic
N-row request. `render()` returns the page plan, page count and totals; the CLI
prints it as JSON.

## Documented deviations (multi-page output only)

* `이하여백` blank filler is not re-emitted: a generated page break already delimits
  the item list.
* `소계 / 부가세 / 합계` breakdown labels are drawn on the final page only.
* For 4+ items, NO-column numbers are regenerated consecutively across pages.
* 4+ row output has **no absolute visual certification** yet. It is verified by
  certified geometry, certified-constant coverage, text-span parity and image
  comparison against the certified render, not against a certified reference image
  for 4+ rows (none exists).
* The multi-page renderer is not covered by `sol61/certificate.json`.

## Tests

```
python -m pytest apps/b66-sol61-multipage/tests/test_multipage_image_regression.py
```

Requires `pypdf`, `PyMuPDF`, and a `node` binary on `PATH` (QuoteCore runs in Node,
exactly as the certified engine does). `B66_SOL61_ENGINE_DIR` overrides where this
renderer is found; `B66_SOL61_BUNDLE_DIR` the certified bundle.

The image test is deliberately **load-bearing**: T3 replays the operator-order bug on
the same page and asserts that the image check fails, so the check cannot go
vacuously green.

## Previous Operator-Order Revision

Measured from the produced PDFs, never from renderer self-report.

| Check | Result |
| --- | --- |
| Certified authority files (7) vs shipped bundle | identical, SHA-256 |
| Certified 1–3 row bytes | byte-identical to the pre-fix certified render |
| Determinism (same input twice) | identical bytes |
| Stress: 1,2,3,4,8,10,25,100,101,125,500 rows | 11/11 pass |
| Certified form constants re-emitted | 85 runs on every page, 0 missing |
| Header / footer text-span parity vs certified render | 46/47 and 6/6 exact, 0 unexplained |
| Whole page: certified render vs true CGI source PDF | 0.0000% pixels (control) |
| Header band pixel diff (N=4/8/25/100, first page) | 0.0011% |
| Title band pixel diff | 0.0000% |
| Footer band pixel diff | 0.0335% |
| Ink outside the certified frame | 0 px on every page of N=4/8/25/100/101/125/500 |
| 500 rows | 51 pages, 2.7 s |

Remaining known gap: the value-bearing 합계금액 line and the multi-page breakdown
block re-encode into a freshly subset font, so their pixel diff against the certified
render is not zero (the certified engine shows the same behaviour at 8.41% on that
same line). This is a limitation of font re-subsetting, not of geometry.

## Right Frame Correction - 2026-10-10

The original lower right frame has four connected 0.72pt segments at x=572.572,
y=270.424..605.218. The last segment starts at 453.224, so the body-art filters
dropped it on continuation/last pages. Generated rows only restored it through
the final row. The fixed composer preserves original outer rules as structural
page furniture before these filters; it does not add a cosmetic line over the PDF.

Generated rows now own only their interior vertical grid and one source 0.12pt
horizontal hairline per row. Source column fragments outside generated rows are
retained in the header/summary/footer, avoiding overlapping paints. The original
body-top hairline is retained. Exact outer anchors are 24.587/572.572; interior
column rounding remains unchanged. Last-page rows are budgeted against the
subtotal cell's real top 518.313, rather than its text baseline 532.6978.

Implementation evidence: 39 tests passed with no skips on Windows, plus actual
PDFs at 1,2,3,4,8,10,25,100,101,125,500. Every page of 101 native pages and 101
read-only v2 preview pages passes four-edge single-coverage, 72/144dpi visible
boundary, outer-margin, item order/count, QuoteCore and clearance checks.
Source-v1 1..3 PDFs remain byte-identical to the frozen pre-fix engine. Repeated
renders are deterministic; all 18 original hashes and manifest match. The 101-item
fixture grows from 11 to 12 pages because the real summary cell needs clearance.
The >100 fixtures are renderer stress, not an expanded product-intake promise.

The source seal intentionally paints over part of the top rule. Tests derive
that footprint from its native CTM, prove its occlusion is identical to the issued
source and frozen pre-fix PDF, and also verify the full intrinsic frame without
the seal in an in-memory test page. Actual outputs retain the seal. Original
header double/dotted rules remain intentional source artwork; the zero-overlap
claim concerns generated lower frame/grid ownership, not removal of source style.

```powershell
python -m pip install -r apps/b66-sol61-multipage/requirements-test.txt
$env:B66_SOL61_FRAME_RASTER='1'
$env:B66_SOL61_FRAME_REAL_PDF='1'
$env:B66_SOL61_PRE_FIX_PDF='<frozen-before-8.pdf>'
python -B -m pytest -q -p no:cacheprovider apps/b66-sol61-multipage/tests reference/b66-public-standard-templates/cgi/v1/tests/test_public_bundle_contract.py
```

The existing immutable-bundle GitHub workflow also runs the font-independent
23-test source/vector/raster subset on this renderer's PR paths. Five full
Windows/frozen-PDF control cases are explicitly deselected in that job and run
locally above. CI does not substitute for the full real-PDF matrix or certification.

## Read-Only Sol v2 Integration

PR #4010 remains unchanged at a163f11d2e9c734d66c95293464541d85335ebad. Its existing
verification entrypoint deliberately pins the earlier #4001 Python hash and must
reject this revision. The LOCAL1-only `verify_right_border.py` consumer separately
pins the reviewed new renderer, imports #4010's unchanged derive/render helpers,
and preserves the pinned QuoteCore adapter. One derived v2 candidate is shared
across all 11 counts; every PDF/sidecar stays PENDING/certifiedPath=false.

```powershell
python -B apps/b66-sol61-multipage/verify_right_border.py --bundle reference/b66-public-standard-templates/cgi/v1/sol61 --before-engine <frozen-f25b-engine-dir> --v2-app <read-only-a163-v2-app-dir> --expected-engine-sha <reviewed-renderer-sha256> --out <new-empty-evidence-directory>
```

Outputs include actual before/after/v2 PDFs, first/middle/last 72/144dpi comparison
PNGs, `comparison.html`, and `audit.json`. Frozen pre-fix PDFs fail the boundary
oracle; removing the final native right segment also fails. No v2 activation,
certificate inheritance, Ready conversion, merge, Production or issue closure.
CENTRAL review and Owner visual approval/re-certification remain pending. Extremely
oversized single wrapped rows remain an existing pagination limitation outside
these tested bounded requests.

## Fixed defect history (#3839 review)

`Program.emit_path()` re-emits whole paths verbatim. It wrote `operator operands`
(`m 25.786 707.226`) instead of `operands operator` (`25.786 707.226 m`), so the first
`m` of every path met an empty operand stack and the path started at the page origin:
a stray diagonal was stroked down the left margin (5,467 dark pixels on page 1 of an
8-row quote, reaching x=0.0pt instead of the frame's 24.0pt). Every later operator
happened to find its own operand pair still on the stack, so the frame itself kept
rendering and the defect stayed invisible to any check whose window started at the
form's left edge.
