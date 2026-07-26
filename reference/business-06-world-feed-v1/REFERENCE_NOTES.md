# World Feed Reference Notes

- Review date: **2026-07-26 (Asia/Seoul)**
- Scope: publicly accessible official product pages, app listings, Awwwards listings, and Awwwards collection indexes.
- Constraint: third-party screens and brand assets are not embedded in the World Feed UI.
- Result: references informed hierarchy, rhythm, provenance treatment, and motion only. No complete screen was copied.

## Comparable products

### 1. Cosmos

- Inspected surface: official Android app listing and product positioning for curated visual discovery, search, saving, collections, and taste-based following.
- URL: `https://play.google.com/store/apps/details?id=so.cosmos.www`
- Adopted pattern: image-first discovery, strong crop rhythm, compact provenance, restrained visible controls.
- Rejected pattern: creator-network identity and collection-building as the primary product surface.
- World Feed difference: the main artifact is a short personal dispatch mixing world, nearby, and durable-interest signals with source/time context.

### 2. Are.na

- Inspected surface: official About page describing blocks, channels, long-term idea collection, private/collaborative knowledge work, and connected exploration.
- URL: `https://www.are.na/about`
- Adopted pattern: calm density, quiet utility typography, interest adjacency, minimal algorithmic spectacle.
- Rejected pattern: neutral archive grid and project-building workflow.
- World Feed difference: World Feed is a time-oriented edited reading surface with a dominant visual hierarchy, not a personal research database.

### 3. Flipboard

- Inspected surface: official “How It Works” page and current app listing covering personalized topics, magazines, local content, follow/mute, and more/less controls.
- URLs:
  - `https://about.flipboard.com/how-it-works/`
  - `https://play.google.com/store/apps/details?id=flipboard.app`
- Adopted pattern: magazine grouping, topic-led discovery, clear source-forward story units, understandable more/less reaction language.
- Rejected pattern: full news breadth, social-magazine creation, and conventional feed-card repetition.
- World Feed difference: the composition is lighter and more personal, with fewer stories, mixed anatomy, and explicit `세계 / 가까운 곳 / 나의 관심` signals.

### 4. Iconfactory Tapestry

- Inspected surface: official product page for a unified chronological timeline across social, RSS, podcasts, and video sources.
- URL: `https://tapestry.iconfactory.com/`
- Adopted pattern: source identity remains readable, mixed content types maintain a coherent timeline rhythm, compact text cells.
- Rejected pattern: strict chronology, connector setup, rules management, and dense utility controls.
- World Feed difference: World Feed is intentionally edited and personalized; chronology is secondary to a designed dispatch sequence.

### 5. Ground News

- Inspected surface: official product and help pages for My Feed, source comparison, Blindspot, bias/factuality context, and location-based discovery.
- URLs:
  - `https://ground.news/product`
  - `https://help.ground.news/en/articles/485057`
- Adopted pattern: provenance remains visible, personalization can be explained in plain language, source context should not disappear in detail views.
- Rejected pattern: bias bars, analytical density, ratings dashboards, political comparison tooling, and compliance-like visual weight.
- World Feed difference: provenance is secondary and calm; the product centers culture, place, entertainment, neighborhood life, and limited sports culture rather than political-news analysis.

## Editorial and motion references

### 6. Vogue Adria

- Inspected surface: Awwwards magazine/blog listing entry and accessible public editorial shell; Awwwards records an Honorable Mention dated 2025-02-16.
- Reference URL: `https://www.awwwards.com/websites/blogs/`
- Adopted pattern: oversized editorial headline, image/type contrast, confident negative space.
- Rejected pattern: fashion-brand dominance, luxury polish as an end in itself, and full-bleed identity takeover.
- World Feed difference: the large type is used to establish a personal dispatch, then quickly yields to compact mixed-source posts.

### 7. Magazine “Kohkoku” CASE #01

- Inspected surface: Awwwards nominee/listing entry; Awwwards records an Honorable Mention dated 2025-06-13.
- Reference URL: `https://www.awwwards.com/websites/%23247345/`
- Adopted pattern: print-derived rules, paper rhythm, expressive scale shifts, nonuniform editorial blocks.
- Rejected pattern: decorative complexity that delays content recognition and overly literal print simulation.
- World Feed difference: the print grammar is responsive, source-aware, and optimized for fast discovery rather than a magazine replica.

### 8. Into The Amazon

- Inspected surface: Awwwards listing and award record; Awwwards records Site of the Day and Developer Award dated 2025-04-21.
- Reference URL: `https://www.awwwards.com/websites/%23C9B46D/?page=3`
- Adopted pattern: controlled transition between visual layers, image movement that communicates a changed viewpoint, stable context during motion.
- Rejected pattern: immersive takeover, heavy scroll choreography, WebGL/3D, and long-form expedition pacing.
- World Feed difference: Horizon Shift is a 550–750ms CSS transition inside a compact feed state, not an immersive narrative environment.

### 9. Awwwards News + Content / Clean Grids collections

- Inspected surface: Awwwards collection index showing `News + Content`, `Clean Grids`, `Digital Storytelling`, and related pattern libraries.
- Reference URL: `https://www.awwwards.com/basic/collections/`
- Adopted pattern: thin rules, disciplined spacing, asymmetric grids, mixed headline scales, strong image anchoring.
- Rejected pattern: trend collage, generic awards-site visual mimicry, and one-size-fits-all clean-grid templates.
- World Feed difference: the grid is deliberately broken by narrow portraits, text-only dispatches, wide image posts, and distinct signal labels.

## Final synthesis

The final direction combines:

- Cosmos-like image-led discovery;
- Are.na-like calm density;
- Flipboard-like topic clarity and reaction language;
- Tapestry-like mixed-source readability;
- Ground News-like provenance legibility without analytical dashboard density;
- Vogue Adria and Kohkoku-like editorial scale;
- Into The Amazon-like viewpoint transition, reduced to a lightweight CSS motion;
- Awwwards clean-grid discipline, deliberately interrupted to avoid a uniform card wall.

The result is not an AI dashboard. AI is not represented with gradients, bots, sparkles, model selectors, scores, or charts. It is also not a full news portal: the feed is small, personal, image-led, and oriented around discovery rather than comprehensive current-affairs coverage.
