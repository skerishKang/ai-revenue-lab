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
* Every geometric value is read at run time from the certified package
  (`template.json` bindings and the `program.zlib` drawing program). Nothing is
  hard-coded or guessed.
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
* The certified NO-column row numbers `1..3` are not continued past the first page.
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

## Verification of this revision

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

## Fixed defect history (#3839 review)

`Program.emit_path()` re-emits whole paths verbatim. It wrote `operator operands`
(`m 25.786 707.226`) instead of `operands operator` (`25.786 707.226 m`), so the first
`m` of every path met an empty operand stack and the path started at the page origin:
a stray diagonal was stroked down the left margin (5,467 dark pixels on page 1 of an
8-row quote, reaching x=0.0pt instead of the frame's 24.0pt). Every later operator
happened to find its own operand pair still on the stack, so the frame itself kept
rendering and the defect stayed invisible to any check whose window started at the
form's left edge.
