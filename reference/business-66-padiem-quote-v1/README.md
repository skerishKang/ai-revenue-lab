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
├─ quote-core.js                 견적 도메인 로직 — DOM 없음, 브라우저/Node 겸용
├─ quote-extraction.js           모델 독립 추출 계약 — 검증·provenance·QuoteDraft candidate
├─ quote-history.js              브라우저 로컬 최근 견적(최대 20개) + copy-as-new
├─ app.js                        UI 레이어 — QuoteDraft 상태·렌더링·자동저장 + reviewed apply seam
├─ easy-mode.js                  AI 없는 질문형 Easy Mode + 최근 견적/이어하기 UX
├─ DEMO_GUIDE.md                 데모 운영 가이드 (시연 스크립트·PDF 저장 주의·자동 저장)
├─ tests/
│  ├─ static-contract.test.cjs   정적/권한 경계 계약
│  ├─ quote-core.test.cjs        도메인 로직 Node 단위 테스트
│  ├─ quote-extraction.test.cjs  추출 결과 검증·QuoteDraft 경계 테스트
│  └─ quote-history.test.cjs     최근 견적 저장·불러오기·복사·상한 테스트
└─ README.md
```

File naming rule: flat standard names (`index.html` / `styles.css` / `quote-core.js` / `app.js`),
Korean section banners, one self-contained folder per business.
Every file stays far below the 500-line guideline. No framework, no build step.

## Demo capabilities

- **Easy Mode + 직접 입력** top-level switch
- Easy Mode: Padiem Chat interaction pattern을 참고한 중립 chat UI (메시지, 칩, 하단 composer)
- **AI 없이 동작하는 질문형 견적 만들기**: 받는 곳 → 담당자 → 품목 → 수량 → 단가 → VAT → 비고 → 발신자 → 요약
- 작성 중인 의미 있는 active draft가 있으면 **지난 견적 이어서 하기** 노출
- browser-local **최근 견적 최대 20개** 저장/불러오기/복사해서 새 견적/삭제 확인
- 자유 문장 자동 해석과 파일 읽기는 아직 비연결 상태를 명확히 표시하며 가짜 AI 응답을 만들지 않음
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
node tests/quote-core.test.cjs       # money parse/format, 3-mode VAT math, valid-until, draft normalization
node tests/quote-extraction.test.cjs # model-independent extraction validation + QuoteDraft candidate mapping
node tests/quote-history.test.cjs    # bounded local history, load/copy/delete metadata rules
node tests/static-contract.test.cjs  # structure, Easy Mode, authority, save/restore, print, non-live guards
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

## Easy Mode and recent history

The Easy Mode is deliberately usable before any model is selected:

```text
질문받으며 새로 만들기
→ deterministic question state machine
→ QuoteDraft
→ 기존 직접입력/미리보기 화면
→ 사람의 최종 수정
→ PDF
```

`내용을 한번에 말하기` currently collects the user's text only inside the current page session and explicitly says that semantic AI interpretation is not connected yet. `파일에서 불러오기` likewise performs no upload.

Recent quotations use a separate browser-local key (`quoteBeta.history.v1`) and are capped at 20 snapshots. Snapshot metadata such as totals is derived by `QuoteCore`; trusted totals are not persisted. "복사해서 새 견적" gives the copied draft a fresh quote number/date while preserving useful sender/recipient/item content.

## Extraction boundary

Issue #3147 adds a provider/model-independent boundary:

```text
provider/model output
→ QuoteExtraction.normalizeExtraction()
→ bounded extraction facts + separate evidence/warnings
→ explicit reviewed apply
→ QuoteDraft candidate
→ QuoteCore.normalizeDraft()
→ deterministic calculation/render/PDF
```

The extraction layer never owns line amount, supply, VAT, grand total, or valid-until calculations.
Untrusted source totals are ignored. Missing extraction fields remain null at the extraction boundary;
when an extraction is explicitly applied, missing numeric item fields become editable zero placeholders
rather than fabricated extracted values.

The current upload/chat buttons remain non-live until a governed backend/model adapter is connected.
No provider/model ID or secret lives in the B66 browser code.

Refs #3136, #3144, #3147, #3154.
