# B66 Quote Server Adapter

```text
CANONICAL_ADAPTER_SOURCE = YES
IMAGE_EXTRACTION_SOURCE_WIRED_TO_B14 = YES (#3249)
NATIVE_DOCUMENT_INTAKE_ROUTE_SOURCE_ONLY = YES
BROWSER_MODEL_PROVIDER_IDENTITY = 0
```

This package is the product-owned server authority for B66 quotation intake/extraction. Runtime deployment state is tracked separately by the B14/Pages deployment gates; this document describes source ownership.

## Ownership

```text
Browser file chooser / UX
  -> B66 product adapter
  -> IP-CORE document identity + parser authority
  -> later extraction adapter
  -> #3147 QuoteExtraction boundary
  -> QuoteDraft
```

B66 owns:

- accepted product file categories and Korean user-facing failure semantics;
- request-shape bounds;
- projection of a parsed document into a future quotation-extraction input;
- classification of image/native-document/scanned-PDF candidates.

B66 does **not** own:

- a custom PDF/DOCX/PPTX/XLSX/HWPX parser;
- model/provider routing;
- inference credentials;
- OCR implementation;
- generic multimodal execution semantics.

## Browser-visible intake contract

The B66 browser uses one same-origin product path:

```text
POST /api/v1/quote/intake
```

For the image-registration MVP, Pages `_worker.js` proxies this bounded request to the existing B14 Worker. The B14 endpoint stages and reuses `app/extraction_routing.py` as the canonical #3212 request-builder/model-output validator.

The separate `file_intake.py` native-document parser boundary remains source-only for now; PDF/DOCX/PPTX/XLSX/HWPX automatic content analysis is not claimed by #3249.

Exact browser request body for the image MVP:

```json
{
  "name": "quote.pdf",
  "media_type": "application/pdf",
  "base64": "<bounded base64>"
}
```

Unknown fields fail closed. In particular there is no request surface for:

```text
model
provider
provider_id
model_id
base_url
route
url
secret
```

## Product allowlist vs parser capability

This component describes lower-level intake/parser capability. It is not the B66 quotation-template registration allowlist.

~~~text
NATIVE_PARSER_CAPABILITY
!=
B66_TEMPLATE_REGISTRATION_POLICY
~~~

For source-derived quotation-template onboarding, the current product policy is governed by #3586: accept .xlsx now, reject legacy .xls, and treat .hwpx as a future supported candidate while rejecting legacy .hwp. A lower-level parser being capable of another native document category does not automatically expose that format in B66 template registration.

## Supported categories

Native binary documents, up to Core's 2 MiB limit:

- PDF
- DOCX
- PPTX
- XLSX
- HWPX

Images, up to the existing Core/B14 4 MiB image limit:

- JPEG
- PNG
- WebP

Legacy `.hwp` remains unsupported.

## Native document reuse

The adapter reuses:

```python
padiem_ai_core.document_normalization.validate_document_identity
padiem_ai_core.document_parser_boundary.parse_binary_document_via_authority
```

It does not implement a second parser.

A PDF parser result with `pdf_empty_text` is projected as:

```text
kind = scanned_pdf_candidate
next = scanned_pdf_vision_pending
```

No OCR or vision call is made.

If the reviewed parser authority is unavailable in the runtime, intake fails closed.

## Image boundary

`file_intake.py` still provides a model-free image classification seam for generic server composition.

The live image-registration source path introduced by #3249 instead reuses `extraction_routing.py` directly:

```text
bounded image bytes
-> build_image_extraction_request()
-> canonical B14 multimodal/manual route
-> normalize_model_output()
-> server-owned provenance + bounded extraction facts
-> Saved Quote Skill review
```

The browser cannot supply a model/provider/route/credential. Untrusted model output is validated server-side before any extraction facts are returned to the product.

## Verification

From repository root:

```bash
PYTHONPATH=packages/padiem-ai-core:apps/b66-quote-adapter \
python -m unittest discover -s apps/b66-quote-adapter/tests
```

Refs #3143, #3147, #3162, #3212, #3249.
