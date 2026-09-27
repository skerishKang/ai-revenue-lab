# B66 · Padiem Quote / 파디엠 견적

Rapid customer-facing quotation demo for Issue #3136.

## Purpose

Prove the shortest useful workflow:

```text
sender preset
→ recipient/date
→ line items
→ deterministic subtotal/VAT/total
→ live A4 quotation preview
→ browser Print / Save as PDF
```

## Run

No build step and no credentials are required.

```bash
cd reference/business-66-padiem-quote-v1
python -m http.server 4173
```

Then open `http://127.0.0.1:4173/`.

Opening `index.html` directly also works in normal browsers.

## Demo capabilities

- Korean-first quotation UI
- sender preset plus browser-local custom sender save
- recipient/company/contact inputs
- quote date, validity and quote number
- repeatable line items with add/remove
- quantity × unit price deterministic arithmetic
- optional 10% VAT
- live quotation preview
- responsive layout
- print stylesheet for A4 PDF save

## Explicitly not live yet

The UI names the next steps but does not pretend they work:

- uploaded quotation/PDF/image extraction
- OCR / AI quotation normalization
- chat-to-QuoteDraft generation
- server-side document persistence
- real email sending
- authentication or tenant data
- Production deployment

No file is uploaded, no email is sent, and no credential is required by this demo.

## Next implementation seam

All future input modes should converge on one normalized `QuoteDraft` domain object before rendering:

```text
manual form ────┐
upload/OCR ─────┼→ QuoteDraft → validation/calculation → renderer → PDF
chat input ─────┘
```

AI may extract or normalize fields, but money arithmetic remains deterministic application code.

Refs #3136.
