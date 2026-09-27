# B66 Quote Server Adapter

```text
STATUS = SOURCE_READY_NOT_DEPLOYED
ISSUE = #3162
MODEL_DEPENDENCY = NO
SERVER_ROUTE_DEPLOYED = NO
```

This package is the product-owned server boundary for future B66 quotation file intake.

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

## Source-ready intake contract

Future same-origin path reserved by source contract:

```text
POST /api/v1/quote/intake
```

No route is installed or deployed by #3162.

Exact request body:

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

Image intake validates bounded media/extension/size/magic and returns:

```text
kind = image_candidate
next = vision_model_pending
model_called = false
```

This is only a product intake classification. Future execution must still pass through the trusted attachment / IP-CORE multimodal path, which revalidates media bytes.

## Verification

From repository root:

```bash
PYTHONPATH=packages/padiem-ai-core:apps/b66-quote-adapter \
python -m unittest discover -s apps/b66-quote-adapter/tests
```

Refs #3143, #3147, #3162.
