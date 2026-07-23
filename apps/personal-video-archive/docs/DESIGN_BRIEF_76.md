# Design Brief — Business 13 Personal Video Archive Redesign (Issue #76)

Status: Phase 1 deliverable. Written before any template/CSS changes, per CTO contract.

## 1. Goal

Turn the Personal Video Archive from a QA-style route/state matrix into a real product:
a calm, Korean-first bilingual visual archive of videos a person is actually learning from.

- Root `/` is the Korean product home. `/en/` mirrors it in English.
- Every preview card shows a real public YouTube video with its original title, channel,
  and thumbnail. Nothing is faked.
- The static preview is deterministic, zero-network at build time, and inert (no mutation).

Target impression, in one sentence:
"내 학습 영상들을 조용한 서재처럼 정리해 둔 곳" — a quiet study shelf for my learning videos.

## 2. Research sources (official pages only)

| Product | Source consulted | Date |
|---|---|---|
| Readwise Reader | readwise.io/read (official product page) | 2026-07 |
| mymind | mymind.com (official product page) | 2026-07 |
| Capacities | capacities.io (official product page) | 2026-07 |
| Raindrop.io | raindrop.io (official product page) | 2026-07 |

No third-party blog reviews were used.

## 3. Per-product patterns: adopt / reject

### Readwise Reader
Adopt:
- Source-first identity: the original item (here: the YouTube video) is the hero; the app
  frames it, never replaces it. Titles and channels stay verbatim.
- Triage states as a calm workflow (New → Later → Read maps onto our viewing states
  아직 보지 않음 → 저장함 → 보는 중 → 다 봄).
- Daily Review resurfacing → our "다시 볼 영상 / Resurfaced" home section.

Reject:
- Dense article-reader typography and highlight tooling (not a reading app).
- Heavy onboarding/paywall framing.

### mymind
Adopt:
- Privacy-as-value: "Nothing is saved, nothing is tracked" is a feature, stated quietly
  (our small preview notice).
- Calm, no-dashboard aesthetic: no charts, no metrics shouting; generous whitespace.
- Serendipitous rediscovery of saved items → resurfaced section.

Reject:
- Mystery/black-box organization (no visible structure) — our users need explicit topics
  and state filters.

### Capacities
Adopt:
- Three-region desktop shell: left object navigation, center content, right context panel.
- Object-based thinking: videos, topics, records are distinct object types with their own
  cards and detail views.
- Studio-calm visual tone: neutral surfaces, restrained accent use.

Reject:
- Power-user graph/backlink complexity.
- Sidebar density aimed at note-graph users.

### Raindrop.io
Adopt:
- Thumbnail-first collections: large, consistent thumbnail cards are the primary browsing
  unit (our video cards).
- Metadata at a glance: title, source, tags, and state visible without opening the item.
- Multiple view densities (list vs grid) — we ship grid for home/topics, list for records.
- Tag/filter chips above a collection (our state filter pills).

Reject:
- Browser-extension-centric flows and account upsells.

## 4. Design principles

1. The video is the hero. Original title + channel + thumbnail, always verbatim.
2. Calm over clever. One accent color, no gradients, no glassmorphism, no neon.
3. Korean is the default language; English is a first-class mirror, not an afterthought.
4. Product language, never developer language, in the UI.
5. Preview honesty: a small, quiet notice says data is sample data and nothing is saved.
6. Explicit outbound only: open on YouTube in a new tab; no autoplay, no embeds, no trackers.
7. Every state and filter from Phase 1 remains reachable and labeled in both languages.

## 5. Design tokens

All tokens live as CSS custom properties on `:root` in `static/style.css`.

### Color
| Token | Value | Use |
|---|---|---|
| `--bg` | `#faf9f7` | Page background (warm off-white) |
| `--surface` | `#ffffff` | Cards, panels |
| `--surface-2` | `#f3f1ec` | Inset wells, code, filter pill idle |
| `--ink` | `#26241f` | Primary text (warm charcoal) |
| `--ink-2` | `#5f5b52` | Secondary text |
| `--ink-3` | `#8f8a7e` | Tertiary/metadata text |
| `--line` | `#e7e3da` | Borders, dividers |
| `--line-strong` | `#d8d3c7` | Emphasized borders |
| `--accent` | `#2f6b4f` | Single deep forest green: links, active states, primary buttons |
| `--accent-ink` | `#ffffff` | Text on accent |
| `--accent-soft` | `#e6efe9` | Accent tint backgrounds |
| `--focus` | `#2f6b4f` | Focus ring color |

Provenance colors (badge text + soft bg + border), muted and desaturated:
| Provenance | Label (ko / en) | Text | Bg | Border |
|---|---|---|---|---|
| `youtube` | YouTube / YouTube | `#a03d2e` | `#f7ece9` | `#ecd6cf` |
| `application` | 추천 / Recommended | `#3f5673` | `#ebf0f6` | `#d3dde9` |
| `user` | 내 기록 / My record | `#2f6b4f` | `#e6efe9` | `#cfe0d6` |
| AI suggestion | AI 제안 / AI suggestion | `#8a6a2f` | `#f6f0e2` | `#e8dcc0` |

State colors: states use neutral pills; only terminal/attention states get a tint
(`다 봄/Watched` = accent-soft, `관심 없음/Not interested` = surface-2 with ink-3 text).

### Typography
- Stack: `"Pretendard Variable", Pretendard, "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`
- No webfont files are loaded (system stack only).
- Scale: `--fs-xs 12px`, `--fs-sm 13px`, `--fs-base 15px`, `--fs-md 17px`, `--fs-lg 20px`, `--fs-xl 26px`, `--fs-2xl 32px`
- Line heights: body 1.6, headings 1.3. Korean text uses `word-break: keep-all`.

### Spacing / radius / shadow
- Space scale (4px base): `--sp-1 4px` … `--sp-8 32px`, `--sp-10 40px`, `--sp-12 48px`
- Radius: `--radius-sm 6px`, `--radius 10px`, `--radius-lg 14px`
- Shadow: `--shadow-1 0 1px 2px rgba(38,36,31,.06)`, `--shadow-2 0 4px 14px rgba(38,36,31,.08)` (cards use shadow-1 + border; hover → shadow-2)

### Interaction
- Focus: `outline: 2px solid var(--focus); outline-offset: 2px` on `:focus-visible`
- Hover: cards lift via border-color → `--line-strong` + shadow-2; links underline
- Transitions: `120ms ease` on color/border/shadow only

## 6. Information architecture

### Paths (Phase 1 contract preserved, mirrored per locale)
| ko | en | Page |
|---|---|---|
| `/` | `/en/` | Home (product shell) |
| `/topics` | `/en/topics` | Topic list |
| `/topics/{id}` | `/en/topics/{id}` | Topic feed (state pills) |
| `/topics/new` | `/en/topics/new` | New topic |
| `/topics/{id}/review-rule` | `/en/topics/{id}/review-rule` | Query-rule review |
| `/videos/{id}` | `/en/videos/{id}` | Video detail |
| `/records` | `/en/records` | Record search/list |
| `/records/{id}` | `/en/records/{id}` | Record detail |
| `/proposals` | `/en/proposals` | AI proposals |
| `/preview-states` | `/en/preview-states` | QA state matrix (kept, secondary) |
| `/health` | `/en/health` | Health |

All 8 feed states stay: `all unseen opened saved in_progress completed revisit irrelevant`.

### Home page sections (both locales)
1. App shell header: product name, language switch, quiet preview notice.
2. Left nav (desktop): 홈, 토픽, 내 기록, AI 제안 (+ QA 미리보기 as a small secondary link).
3. "이어 보기 / Continue watching" — in-progress videos, horizontal row of cards.
4. "새로 발견 / New finds" — recently added videos grid.
5. "토픽 / Topics" — topic cards with counts.
6. "최근 메모 / Recent notes" — latest private records.
7. "다시 볼 영상 / Resurfaced" — one resurfaced video card (mymind/Reader pattern).

### Desktop layout (≥1024px)
- 232px fixed left nav | flexible center (max content 960px) | 300px right context panel
  (≥1280px only; shows "why recommended" + record excerpt + related topic).
- Below 1280px the context panel content folds into the detail page main column.

### Mobile layout (≤767px)
- Top bar: menu button (opens left nav as overlay drawer), product name, language switch.
- Single column; video cards full width; state pills horizontally scrollable;
  no horizontal page overflow at 390px.

## 7. Component specs

### Video card (the core unit)
- 16:9 thumbnail container, `object-fit: cover`, `--radius` top corners; real
  `https://i.ytimg.com/vi/{id}/hqdefault.jpg` (480×360) as the primary image.
- Duration chip bottom-right of thumbnail (e.g. `18:40`).
- Provenance badge top-left of thumbnail.
- Below: title (2-line clamp, verbatim), channel name (ink-2), meta row
  (publish year · views, localized number formatting), state pill.
- Whole card links to internal detail page; "YouTube에서 열기 / Open on YouTube" is an
  explicit secondary action: `target="_blank" rel="noopener noreferrer"`.
- No autoplay, no iframe, no third-party script.

### Topic card
- Title, description (1-line clamp), video count, state distribution mini-summary,
  sync-status line (product language: "마지막 수집: …" not "provider").

### Record card / detail
- Record detail keeps the Phase 1 state-select form (inert in static preview),
  timestamps, tags, linked video card.

### Language switch
- `한국어 / English` segmented control in header; links to the same page in the other
  locale, preserving path suffix and query (state filter included).

### AI suggestion banner (review-rule page)
- Muted amber tint; product language: "AI가 제안한 수집 규칙을 검토하세요" /
  "Review the collection rule AI suggested". Accept/reject buttons inert in preview.

## 8. Fixture policy

- ≥8 real public YouTube videos, ≥4 distinct channels, Korean + English mix.
  Full verified list in `docs/PREVIEW_VIDEO_SOURCES_76.md`.
- Titles/channels/thumbnails verbatim from YouTube (oEmbed + watch-page verified).
- Thumbnail domain is exactly `i.ytimg.com`; CSP `img-src` allowlist contains only that.
- Watch links: `https://www.youtube.com/watch?v={id}` with `_blank` + `noopener noreferrer`.
- Static preview shows all 8 states × topics deterministically; mutation forms render
  but submit nowhere (no active script/fetch/provider).
- `/static/preview-thumb.svg` may remain as an offline fallback only, never the primary
  card image when a real thumbnail URL exists.

## 9. Accessibility

- Contrast: ink on bg ≥ 7:1; ink-2 ≥ 4.5:1; all badge text/bg pairs ≥ 4.5:1.
- Visible `:focus-visible` ring on every interactive element.
- Thumbnails are decorative context: card link carries the video title as accessible name;
  thumbnails use `alt=""`.
- State is never conveyed by color alone (pill text label always present).
- Touch targets ≥ 40px on mobile; pills scroll instead of wrapping into tiny targets.
- `lang="ko"` on `/`, `lang="en"` on `/en/`.

## 10. Failure modes to avoid (from Phase 1 postmortem)

- QA matrix as home page → home must be the product shell; QA route stays but secondary.
- Big yellow preview banner → replaced by one quiet line in the header.
- Developer jargon in UI (Provider, Fixture, State matrix, Synthetic, LLM query-rule)
  → replaced with product language per §7.
- Fake title/channel pairing → every fixture video is oEmbed-verified (§8).
- English-only UI → Korean is default; parity tests enforce no stray labels.
- "Block all external URLs" test that also blocks legitimate thumbnails → redesigned as a
  strict allowlist: only `https://www.youtube.com/watch?v=` and `https://i.ytimg.com/`
  are permitted; pages.dev / neon.tech / firebase / googleapis / youtu.be still rejected.

## 11. Target impression checklist

A reviewer opening `/` should feel: "이건 실제 제품이다" —
- warm paper-white background, charcoal text, one green accent;
- real thumbnails with real titles in the first viewport;
- Korean everywhere, with an obvious way to switch to English;
- no banner shouting, no jargon, no horizontal scroll on mobile.

## 12. Implementation strategy

- Shared templates + a translation catalog (`app/i18n.py`: `STRINGS` dict keyed by locale;
  `t(locale, key)` helper injected into Jinja globals). No mass template duplication.
- Route layer adds an `/en/` mirror via a `locale` path prefix and a `Locale` dependency;
  all existing Phase 1 routes keep their exact behavior and URLs.
- New partials: `_shell.html` (header/nav/drawer), `_video_card.html`, `_topic_card.html`,
  `_record_card.html`, `_state_pills.html`, `_lang_switch.html`, `_provenance_badge.html`,
  `_preview_notice.html`, `_context_panel.html`.
- Static builder renders both locales, strips inline handlers, emits CSP with
  `img-src 'self' https://i.ytimg.com`, robots deny, noindex.
- Tests: ko/en parity, language-switch state preservation, ≥8 distinct video IDs,
  ≥4 channels, valid HTTPS watch/thumbnail URLs, `_blank`+`noopener`+`noreferrer`,
  real thumbnail in first viewport, allowlist URL test, no mobile overflow,
  determinism, zero-network, full existing suite green.
