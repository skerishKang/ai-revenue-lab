# B66 · Quote Beta / 견적서 만들기

Rapid customer-facing quotation demo for Issue #3136.

## Purpose

Prove the shortest useful workflow:

```text
sender preset
→ recipient/date (+ auto-computed valid-until)
→ line items (Korean comma money input)
→ deterministic supply/VAT/total (3 tax modes)
→ live A4 quotation preview
→ browser Print / Save as PDF (single page when content fits)
```

## Run

No build step and no credentials are required.

```bash
cd reference/business-66-padiem-quote-v1
python -m http.server 4173
```

Then open `http://127.0.0.1:4173/`.

Opening `index.html` directly also works in normal browsers (plain scripts, no modules).

## Beta entrypoint

After the #3144 main deployment, the neutral public beta entrypoint is:

```text
https://quick-quote-kr.pages.dev/
```

This is a Cloudflare Pages beta URL only. No custom domain or public product brand is attached yet.

## Project structure

```text
reference/business-66-padiem-quote-v1/
├─ index.html                    화면 구조만 (약 183줄)
├─ styles.css                    스타일 + A4 인쇄 규격 (약 134줄)
├─ quote-core.js                 견적 도메인 로직 — DOM 없음, 브라우저/Node 겸용 (약 219줄)
├─ app.js                        UI 레이어 — QuoteDraft 상태·렌더링·자동저장 (약 346줄)
├─ DEMO_GUIDE.md                 데모 운영 가이드 (시연 스크립트·PDF 저장 주의·자동 저장)
├─ tests/
│  ├─ static-contract.test.cjs   정적 계약 테스트 (14개 계약)
│  └─ quote-core.test.cjs        도메인 로직 Node 단위 테스트
└─ README.md
```

File naming rule: flat standard names (`index.html` / `styles.css` / `quote-core.js` / `app.js`),
Korean section banners, one self-contained folder per business.
Every file stays far below the 500-line guideline. No framework, no build step.

## Demo capabilities

- Korean-first quotation UI
- sender preset, browser-local custom sender save, sender address
- recipient/company/contact + recipient address
- quote date, validity, quote number, **auto-computed valid-until date**
- repeatable line items with add/remove; **Korean comma money input** (`1,500,000` accepted, formatted on blur)
- **three tax modes**: 별도 (EXCLUSIVE) / 포함 (INCLUSIVE) / 면세 (EXEMPT), mode shown on the quote
- deterministic money math in `quote-core.js` — stored draft never stores totals; they are always derived
- **whole-draft autosave to localStorage** with corrupted/old-schema fallback to the default demo state
- **새 견적** reset button behind a confirmation dialog
- live quotation preview, responsive layout (mobile item rows restacked for full price visibility)
- print stylesheet: A4, UI removed from print layout via `display:none` — **no blank trailing page**, table header repeats on multi-page output

## Verification

```bash
node tests/quote-core.test.cjs      # money parse/format, 3-mode VAT math, valid-until, draft normalization
node tests/static-contract.test.cjs # 14 static contracts (structure, schema, save/restore, print, non-live guards)
```

The static contract pins the screen structure, the QuoteDraft schema, draft save/restore,
the three VAT formulas (`Math.round(subtotal * 0.10)`, `Math.round(grand / 1.10)`, exempt = 0),
the A4 print layout (visibility hack removed), and the explicit non-live warnings.

## Explicitly not live yet

The UI names the next steps but does not pretend they work:

- uploaded quotation/PDF/image extraction
- OCR / AI quotation normalization
- chat-to-QuoteDraft generation
- server-side document persistence
- real email sending
- authentication or tenant data
- branded/custom-domain Production rollout

No file is uploaded, no email is sent, and no credential is required by this demo.

## Next implementation seam

All future input modes should converge on one normalized `QuoteDraft` domain object before rendering:

```text
manual form ────┐
upload/OCR ─────┼→ QuoteDraft → validation/calculation → renderer → PDF
chat input ─────┘
```

AI may extract or normalize fields, but money arithmetic remains deterministic application code
(`quote-core.js`).

Refs #3136, #3144.
