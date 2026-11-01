# StoryMemory v3.4.0 — SM-082 Universal Source Ingest + Reading Harness v1

Date: 2026-08-27
Status: IMPLEMENTATION + DETERMINISTIC CONTRACT QA PASS
Deployment: DEFERRED_TO_BI_PORTAL
Business: B61
Portal target: /b61/

## What changed

- Added `dist/storymemory-universal-source-runtime.js` with contract `storymemory-universal-source-runtime-1.0`.
- Generalized the SM-057 bounded-context idea from Book-only content to a common Source abstraction.
- Added default adapters for:
  - Book / Bible / Scripture through the existing authoritative Static Corpus adapter.
  - PDF/document-style extracted pages or text.
  - URL/web/YouTube/video/audio transcript or captured-text segments.
- Added stable Source locators, visible ingest-state history, cheap lexical retrieval, current position/selection context, Model Prior hints, Source grounding, user Memory lookup, optional Pack hooks, and bounded provider packets.
- Added a non-invasive bridge from the existing Reader exact-resume state into the Universal Harness. Existing production chat/UI routing is intentionally unchanged.

## Runtime policy

Conversation-ready does **not** require precomputing entities, aliases, mentions, relationships, answer cards, embeddings, or a full knowledge graph. The default path is structural parsing + stable locators + lexical retrieval. Semantic indexing and verified Knowledge Packs remain optional escalation layers.

The LLM may use model prior knowledge as a reasoning/search aid, but Source-specific facts are marked as requiring Source grounding. Full Source transmission remains false by default.

## QA

PASS:
- Book fixture using Odyssey static corpus.
- PDF/document fixture using extracted page/block text.
- URL/transcript fixture using timestamped segments.
- Visible ingest states: RECEIVED → PARSING → STRUCTURING → SEARCH_READY → CONVERSATION_READY.
- Stable locator and current-position binding.
- Book progress boundary / no future evidence in bounded Book retrieval.
- Lexical retrieval.
- User Memory continuity.
- Model Prior policy + Source grounding.
- Optional Pack attach/search hook + fingerprint mismatch guard.
- Bounded external provider context.
- Existing v3.3.6 regressions: 5/5 PASS.
- Static corpus regression: 6 works / 185 units / 12,628 passages.
- `dist/content` byte regression: 192 files, changed 0 / missing 0 / extra 0.
- Existing Reader exact resume at `odyssey:book:17:s1:row:004`, sequence 1600004.

## Explicit non-claims / deferred work

- Raw binary PDF OCR or generic PDF parser acquisition is not claimed. The SM-082 document adapter consumes extracted pages/text supplied by an upstream source adapter.
- Live URL crawling, YouTube fetching, media download, STT, or transcript acquisition is not claimed. The runtime consumes captured text/transcript segments supplied by an authorized upstream adapter.
- Explore / Grounded / Strict Trust Modes and final answer provenance taxonomy are SM-083.
- Current production UI/chat is not rebound to Universal Harness. Mixed-Source UI adaptation is SM-087.
- Executable Pack format/attach-detach lifecycle is expanded in SM-084; Marketplace follows in SM-085.
- No browser deployment/live acceptance is claimed in SM-082.

## Mutation boundary

- Neon mutation: NONE
- Cloudflare mutation: NONE
- BI Portal mutation: NONE
- DNS mutation: NONE
- Odyssey Book 21+ manual knowledge expansion: NONE
