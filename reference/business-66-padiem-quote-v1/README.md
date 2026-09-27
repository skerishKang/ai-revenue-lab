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

Opening `index.html` directly also works in normal browsers (plain script, no modules).

## Project structure

```text
reference/business-66-padiem-quote-v1/
├─ index.html                    화면 구조만 (약 167줄)
├─ styles.css                    스타일 + A4 인쇄 규격 (약 104줄)
├─ app.js                        입력 → 결정론적 계산 → 미리보기 렌더링 (약 205줄)
├─ DEMO_GUIDE.md                 데모 운영 가이드 (시연 스크립트·PDF 저장 주의·알려진 제한)
├─ tests/
│  └─ static-contract.test.cjs   정적 계약 테스트 (HTML/CSS/JS 3파일 대상)
└─ README.md
```

File naming rule: flat standard names (`index.html` / `styles.css` / `app.js`),
Korean section banners inside `app.js`, one self-contained folder per business.
Every file stays far below the 500-line guideline.

## Verification

```bash
node tests/static-contract.test.cjs
# → B66_PADIEM_QUOTE_STATIC_CONTRACT=PASS
```

The contract test pins the visible screen structure, the A4 print CSS,
the deterministic money math (`Math.round(qty * price)`, `Math.round(subtotal * 0.10)`),
browser-local persistence, and the explicit non-live warnings.

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
