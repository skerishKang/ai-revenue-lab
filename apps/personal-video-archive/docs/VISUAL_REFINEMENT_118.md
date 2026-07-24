# Visual Refinement — Business 13 Personal Video Archive (Issue #118)

Status: Phase 2 visual refinement. Written before CSS/template changes, per CTO contract.

## 1. Goal

Raise Business 13 from a solid clickable demo to a visually distinctive, portfolio-grade product presentation.

**Concept:** Private Cinema Archive — 영상과 생각이 함께 축적되는 개인 큐레이션 저널

The product should feel quieter and more editorial than YouTube, more image-led than a note database, and more structured than a mood board. The video thumbnail provides most of the page color. AI is a secondary tier, not the visual protagonist.

## 2. Current screen diagnosis

The current implementation (Phase 1, #76/#78) is coherent and functional, but its visual language reads as a familiar modern SaaS pattern:

- Warm off-white canvas (`#faf9f7`) with forest-green accent (`#2f6b4f`) — a generic "green SaaS" impression.
- Many white rounded cards (`#ffffff`, `border-radius: 10px`) with subtle shadow — repetitive section composition.
- System-font fallback stack that includes `Pretendard Variable` and `SUIT Variable` as first choices, which may not resolve consistently across systems.
- Unicode character icons (`⌕`, `⌂`, `▦`, `✎`, `↺`) in navigation — reads as prototype UI.
- Two-level portal/product chrome that is visually heavy: portal bar is 42px dark, product bar is 62px — content does not dominate the first viewport.
- Record detail carries a form-oriented visual character: edit inputs are visually primary, reading content is secondary.
- Thumbnail presentation and editorial copy do not create a strong, ownable visual identity.
- Hero section uses a dark gradient overlay that competes with the video image.
- Discovery grid uses the same card pattern for all items.
- All sections follow the same eyebrow → heading → description → rounded-card-grid pattern.

## 3. Official benchmark sources reviewed

| Product | Source | Date |
|---|---|---|
| Readwise Reader | readwise.io/read | 2026-07 |
| mymind | mymind.com | 2026-07 |
| Capacities | capacities.io/product, docs.capacities.io/reference/user-interface | 2026-07 |
| Raindrop.io | raindrop.io, help.raindrop.io/collections | 2026-07 |
| MUBI | mubi.com/en/collections | 2026-07 |
| Are.na | are.na, help.are.na | 2026-07 |

## 4. Transferable patterns (adopt)

### Readwise Reader
- Source-first identity: the original item (YouTube video) is the hero; the app frames it.
- Triage states as a calm workflow.
- Daily Review resurfacing → our "Resurfaced" section.

### mymind
- Privacy-as-value: "Nothing is saved" is a feature, stated quietly.
- Calm, no-dashboard aesthetic: no charts, no metrics shouting.
- Serendipitous rediscovery → resurfaced section.

### Capacities
- Three-region desktop shell: left nav, center content, right context panel.
- Object-based thinking: videos, topics, records are distinct object types.
- Studio-calm visual tone: neutral surfaces, restrained accent use.

### Raindrop.io
- Thumbnail-first collections: large, consistent thumbnail cards.
- Metadata at a glance: title, source, tags, state.
- Multiple view densities (grid vs list).
- Tag/filter chips above a collection.

### MUBI
- Curated collection framing and restrained media-first hierarchy.
- Editorial titles that explain *why* something is shown.

### Are.na
- Neutral canvas, content-led composition.
- Blocks/channels as distinct visual units.

## 5. Rejected patterns

- Dense article-reader typography (not a reading app).
- Heavy onboarding/paywall framing.
- Mystery/black-box organization (no visible structure).
- Power-user graph/backlink complexity.
- Browser-extension-centric flows and account upsells.
- Big yellow preview banner (replaced by one quiet line in the header).
- Developer jargon in UI (Provider, Fixture, State matrix, Synthetic, LLM query-rule).
- All sections following the same visual pattern.
- All cards being white rounded boxes.
- Hero image competing with text overlay.
- Generic AI purple or neon accents.
- Glassmorphism or gradients.
- External font/icon CDN dependencies.

## 6. Final palette

| Token | Value | Use |
|---|---|---|
| `--canvas` | `#F4F2ED` | Page background (cool-warm ivory) |
| `--surface` | `#FCFBF8` | Cards, panels |
| `--surface-2` | `#F3F1EC` | Inset wells, filter pill idle |
| `--ink` | `#181816` | Primary text (near-black) |
| `--ink-2` | `#68655F` | Secondary text |
| `--ink-3` | `#8F8A7E` | Tertiary/metadata text |
| `--line` | `#D8D3C9` | Borders, dividers (hairline) |
| `--line-strong` | `#C8C3B8` | Emphasized borders |
| `--signature` | `#7A4035` | Signature accent (muted rust/oxblood) |
| `--signature-soft` | `#F3EBE7` | Signature tint backgrounds |
| `--dark-section` | `#20231F` | Dark editorial section (resurfaced) |
| `--forest` | `#285F49` | Retained only for user-authored/private semantic states |
| `--focus` | `#7A4035` | Focus ring color |

Provenance colors (badge text + soft bg + border), muted and desaturated:

| Provenance | Label (ko / en) | Text | Bg | Border |
|---|---|---|---|---|
| `youtube` | YouTube / YouTube | `#A03D2E` | `#F7ECE9` | `#ECD6CF` |
| `application` | 추천 / Recommended | `#3F5673` | `#EBF0F6` | `#D3DDE9` |
| `user` | 내 기록 / My record | `#285F49` | `#E6EFE9` | `#CFE0D6` |
| AI suggestion | AI 제안 / AI suggestion | `#8A6A2F` | `#F6F0E2` | `#E8DCC0` |

## 7. Final typography scale

- **Sans stack:** `"Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` (Korean-first, no external fonts)
- **Serif stack:** `"Iowan Old Style", Georgia, serif` (only for hero editorial copy, note quotations, resurfaced reflections)
- **Scale:**
  - `--fs-xs: 12px` (metadata)
  - `--fs-sm: 13px` (metadata, captions)
  - `--fs-base: 16px` (body)
  - `--fs-md: 17px` (card titles)
  - `--fs-lg: 20px` (card titles, large)
  - `--fs-xl: 26px` (section headings)
  - `--fs-2xl: 32px` (section headings, large)
  - `--fs-display-desktop: 54px` (home display)
  - `--fs-display-mobile: 36px` (home display mobile)
- **Line heights:** body 1.6–1.7, headings 1.2–1.3
- **Korean text:** `word-break: keep-all`
- **Hierarchy via:** weight, width, tracking, whitespace (not color count)

## 8. Component and layout decisions

### Header
- Portal utility bar: reduced to 28px height, visually quiet dark bar.
- Product header: reduced to 64px desktop, 52px mobile.
- Content dominates the first viewport.
- Mobile maintains two-level architecture with reduced text/height.

### Icons
- Unicode glyph navigation icons (`⌕`, `⌂`, `▦`, `✎`, `↺`) replaced with inline SVG icons.
- Consistent stroke width (1.5px), consistent optical size.
- Desktop ~18px, mobile ~20–22px.
- Decorative vs functional icons distinguished.
- `aria-label` and accessibility preserved.

### Home
- **Hero:** Lead video image takes ~65–70% visual weight. Asymmetric 8/4 grid. Reduced text overlay. Recommendation rationale expressed as a short editorial note, not dashboard metadata.
- **New finds:** Deterministic CSS grid with varied editorial spans. Lead item vs secondary item distinction. No JavaScript masonry. Images and text placed directly on canvas, not all in white rounded cards.
- **Topics:** Thumbnail stack / contact-sheet collection covers. Reduced administrative text. Prioritizes topic name, item count, recency.
- **Recent notes:** Completely different grammar from video cards. Text and quote-centric. First item may combine with image.
- **Resurfaced:** Full-width dark section (`#20231F`). One image, one substantial reflection excerpt, restrained CTA. Strongest ownable visual moment.

### Topic feed
- All 8 viewing-state filters and internal routes preserved.
- Lead video vs secondary video visual hierarchy.
- Improved metadata density and alignment.
- Minimal card shadows.
- Image, hairline, spacing as separators.
- No overlap at 390px.

### Record detail
- No data deletion or contract changes.
- Visually distinct blocks: source video, original note, learned point, agreement, disagreement, uncertainty, follow-up plan, timestamps, tags, AI suggestion.
- Reading screen is primary; edit inputs are visually subordinate.
- Static preview remains inert; live FastAPI form contract preserved.
- Right source panel is a deliberate inspector, not a generic card.

### Cards and surfaces
- Ordinary card shadows substantially reduced.
- 1px hairlines, spacing, image crops as primary separators.
- Ordinary image radius: 4–8px.
- Large radius and shadow reserved for overlays/high-priority panels only.
- No floating white containers for every section.
- Hover/focus states visible without excessive motion.

### Thumbnail quality
- Original YouTube titles, channels, attribution preserved.
- Official YouTube thumbnail URLs only (`i.ytimg.com`).
- No autoplay, iframe, tracker, or YouTube API call.
- Per-fixture `object-position` allowed if deterministic and documented.

## 9. Accessibility decisions

- Contrast: ink on canvas ≥ 7:1; ink-2 ≥ 4.5:1; badge text/bg pairs ≥ 4.5:1.
- Visible `:focus-visible` ring on every interactive element.
- Thumbnails are decorative context: card link carries video title as accessible name; thumbnails use `alt=""`.
- State is never conveyed by color alone (pill text label always present).
- Touch targets ≥ 40px on mobile.
- `lang="ko"` on `/`, `lang="en"` on `/en/`.
- Inline SVG icons with `aria-hidden="true"` where decorative; `aria-label` where functional.

## 10. Why this is distinct from generic SaaS and benchmark products

- **Not generic SaaS:** No beige-vintage look, no neon, no glassmorphism, no gradient overuse, no generic AI purple. Color comes from video thumbnails, not from a brand palette. The dark resurfaced section is a signature moment, not a banner.
- **Not Readwise Reader:** We are video-first, not article-first. No highlight tooling, no dense reading typography.
- **Not mymind:** We have explicit structure (topics, states, filters). No mystery organization.
- **Not Capacities:** No power-user graph/backlink complexity. Simpler three-region shell.
- **Not Raindrop:** No browser extension, no account upsells. More editorial, less utility.
- **Not MUBI:** No movie streaming. Private archive, not public cinema.
- **Not Are.na:** No anonymous blocks. Korean-first bilingual, not English-only.

## 11. Desktop / mobile composition

### Desktop (≥1024px)
- Portal bar (28px) | Product bar (64px) | Content
- Home display: 54px
- Section headings: 32px
- Card titles: 17–20px
- Metadata: 12–13px

### Mobile (≤640px)
- Portal bar (24px) | Product bar (52px) | Content
- Home display: 36px
- Section headings: 24px
- Card titles: 17px
- Metadata: 11–12px
- No horizontal overflow at 390px.

## 12. Preserved contracts

- Korean `/` and English `/en/` routes.
- Locale-preserving navigation.
- All 8 viewing-state filters.
- Real YouTube source anchors with `target="_blank"` and `rel="noopener noreferrer"`.
- Static preview non-persistence disclosure.
- Static preview mutation controls inert.
- Deterministic build.
- Zero-network build possible.
- Current FastAPI/SQLite/provider contract.
- Portal/product semantic separation.
