# B66 E2E Fixture Corpus (#3205)

Synthetic, non-sensitive quotation documents used as the input corpus for the
Business 66 template-cloner acceptance run (#3186).

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
manifest.json                      machine-readable corpus contract
f01-native-quotation.pdf           clean native PDF (extractable text layer)
f02-scanned-quotation.png          image-only quotation (no text layer)
f03-quotation.docx                 OOXML wordprocessing document
f04-quotation.xlsx                 OOXML spreadsheet with real cell structure
f05-column-order-variant.pdf       QTY|ITEM|AMOUNT|PRICE column order
f06-vat-separate.pdf               supply amount + VAT printed separately
f07-vat-inclusive.pdf              VAT-inclusive presentation
f08-vat-exempt.pdf                 tax-exempt presentation
f09-missing-fields.pdf             absent facts stay unknown
f10-fixed-memo-terms.pdf           template-fixed terms block
f11-simple-logo.png                synthetic logo card (no real brand)
f12-multipage-quotation.pdf        item table spans two pages
f13-degraded-scan.png              downscaled / low-quality rotated page
generate_b66_e2e_fixtures.py       the generator that produced all of the above
```

## Regenerating

```bash
cd packages/padiem-ai-core
uv run --extra dev python tests/fixtures/b66_e2e_corpus/generate_b66_e2e_fixtures.py
```

The generator writes both the fixtures and `manifest.json`. It performs no
model call and no network call, and it downloads nothing: the only font it uses
is the repository's OFL-licensed authoring font under
`tests/fixtures/pdf_authoring/`.

## Determinism contract

* `byte_identical` — PDF, DOCX and XLSX fixtures. PDFs are authored through
  `padiem_ai_core.pdf_authoring` (ReportLab `invariant=1`); DOCX/XLSX are
  written by the generator itself as ZIP archives with fixed member metadata.
  Re-running the generator reproduces the committed bytes.
* `normalized` — PNG fixtures. Exact bytes depend on the pinned
  `pypdfium2`/pdfium and Pillow builds, so exact bytes are recorded for
  integrity and cross-platform reproducibility is asserted through
  `normalized_fingerprint`, an 8x8 quantized luminance grid. This is declared
  explicitly per fixture; no fixture silently allows a drifting hash.

`tests/test_b66_e2e_fixture_corpus.py` re-runs the generator into two temporary
directories, checks the two runs against each other, and then checks the
committed bytes (or fingerprints) against the manifest.

## Text language per format

The pinned OFL authoring font is a deliberate 106-character subset, so PDF and
raster fixtures use ASCII field labels (`QUOTE NO`, `RECIPIENT`, `QTY`,
`PRICE`, `AMOUNT`, `SUPPLY`, `VAT`, `TOTAL`, `MEMO`) plus the Korean syllables
the subset actually carries. DOCX and XLSX carry unrestricted UTF-8 Korean
labels (`견적번호`, `견적일자`, `공급자`, `공급받는 자`, `품목`, `수량`, `단가`,
`금액`, `공급가액`, `부가세`, `총액`, `메모`). Numbers, dates and item amounts
are identical across formats.

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
document carries a `SYNTHETIC TEST DATA` marker; the DOCX/XLSX fixtures
additionally carry `실사용 금지`.
