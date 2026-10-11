# B66 E2E Fixture Corpus (#3205)

Synthetic, non-sensitive **Korean** quotation documents used as the input corpus
for the Business 66 template-cloner acceptance run (#3186).

```text
CORPUS_ID = b66-quotation-e2e-v1
ISSUE = #3205   (parent #3186, related #3180 / #3143)
SYNTHETIC = YES
MODEL_CALLS = 0
NETWORK_CALLS = 0
PRODUCTION_MUTATION = 0
```

## Layout

```text
manifest.json                          machine-readable corpus contract
f01-native-quotation.pdf               clean native Korean PDF (extractable text layer)
f02-scanned-quotation.png              image-only Korean quotation (no text layer)
f02-scanned-quotation.source.pdf       the Korean document the scan was rendered from
f03-quotation.docx                     OOXML wordprocessing document
f04-quotation.xlsx                     OOXML spreadsheet with real cell structure
f05-column-order-variant.pdf           수량|품목|금액|단가 column order
f06-vat-separate.pdf                   supply amount + VAT printed separately
f07-vat-inclusive.pdf                  VAT-inclusive presentation
f08-vat-exempt.pdf                     tax-exempt (면세) presentation
f09-missing-fields.pdf                 absent facts stay unknown
f10-fixed-memo-terms.pdf               template-fixed terms block
f11-simple-logo.png                    synthetic logo card (no real brand)
f12-multipage-quotation.pdf            item table spans two pages
f13-degraded-scan.png                  downscaled / low-quality rotated page
f13-degraded-scan.source.pdf           the Korean document the degraded scan came from
generate_b66_e2e_fixtures.py           the generator that produced all of the above
```

## Regenerating

```bash
cd packages/padiem-ai-core
uv run --extra dev python tests/fixtures/b66_e2e_corpus/generate_b66_e2e_fixtures.py
```

The generator writes both the fixtures and `manifest.json`. It performs no
model call, no network call, and downloads nothing.

## Korean fidelity

Every native PDF carries real Korean field labels in its extractable text
layer — `견적서`, `공급자`, `주소`, `사업자번호`, `전화`, `공급받는 자`,
`견적번호`, `견적일자`, `공급가액`, `부가세`, `총액`, `메모`, and the item
table headers `품목` / `수량` / `단가` / `금액`.

The repository's embedded OFL authoring font is a deliberate 106-character
subset and cannot carry a real Korean quotation, and no font may be downloaded.
The fixture family therefore uses ReportLab's built-in Korean CID route:

```text
CID_FONT = HYSMyeongJo-Medium
SOURCE   = reportlab_builtin_adobe_korea1_cid   (pure-Python metrics, no download)
```

This is fixture tooling only: it does not change or widen any product
PDF-authoring authority. The generator refuses to emit a Korean source document
whose labels did not survive text extraction.

Each scan fixture commits the Korean source PDF it was rendered from, and the
manifest records that source's path, digest, and verified label list — so "the
scan came from the Korean quotation path" is directly checkable rather than
asserted.

## Determinism contract

* `byte_identical` — PDF, DOCX and XLSX fixtures. PDFs are authored through the
  ReportLab CID route with `invariant=1`; DOCX/XLSX are written by the generator
  itself as ZIP archives with fixed member metadata and a pinned creator
  platform. Re-running the generator reproduces the committed bytes.
* `normalized` — PNG fixtures. A raster's pixels depend on which CJK font the
  pinned `pypdfium2`/pdfium build can resolve on the running platform, so exact
  bytes are recorded for committed integrity and reproducibility is asserted
  within the generating environment through `normalized_fingerprint`, an 8x8
  quantized luminance grid. This is declared explicitly per fixture; no fixture
  silently allows a drifting hash.

`tests/test_b66_e2e_fixture_corpus.py` re-runs the generator into two temporary
directories and compares the two runs with each other, verifies the committed
file digests and the recomputable raster fingerprints, and compares the
regenerated manifests against the committed one modulo the fields declared
platform-dependent for rasters.

## Template facts versus business facts

Every manifest record separates:

* `template_only_facts` — item column order, header repetition, grid/alignment,
  memo block placement, VAT presentation style, logo placement;
* `variable_content_facts` — recipient, quotation number, date, item
  descriptions, quantities, unit prices, totals, memo text.

The two lists are disjoint by construction and are asserted to be disjoint by
the tests, so #3186 can check
`SOURCE_BUSINESS_VALUES_FROZEN_AS_TEMPLATE_BY_ACCIDENT=NO`.

## Authority boundaries

```text
QUOTECORE_CALCULATION_AUTHORITY=YES
FIXTURE_TOTALS_ARE_EXPECTED_SOURCE_FACTS_ONLY=YES
```

Amounts inside the fixtures are *expected source facts* for extraction
comparison. They are not, and must never become, a calculation authority:
`quote-core.js` in the Business 66 browser remains the only place that
computes quotation totals.

The corpus contains no model or provider identity, no credential, and no real
business registration number, address, phone number or company name. Every
document carries a `SYNTHETIC TEST DATA / 실사용 금지` marker.
