# Personal Video Archive

Business number: **13**

Status: **Phase 1 MVP — implemented**

Tracking issue: **#62**

## What is this

Personal Video Archive is a private, topic-first video discovery and reflection product.

A user defines the subjects they want to follow, receives newly published matching YouTube videos in structured topic pages, opens the original video, and keeps private records of what they watched, thought, learned, questioned, and plan to do next.

It is not a replacement video platform, a social network, or a generic recommendation feed.

## Phase 1 implementation

Phase 1 provides a complete deterministic vertical slice using synthetic fixtures and fake providers. No real YouTube API or LLM calls are made.

### Implemented workflows

1. Create a topic from natural-language intent
2. Fake LLM proposes search-rule draft
3. User inspects and edits rules before acceptance
4. Fake discovery provider collects synthetic videos
5. Deduplication by canonical video ID
6. Latest-first feed display
7. Filter by viewing state (all/unseen/opened/saved/in_progress/completed/revisit/irrelevant)
8. Open canonical YouTube URL in a new tab via a single-tab-safe form (records `opened` for unseen videos; explicit user states are preserved, and `opened` never implies `completed`)
9. Manually change viewing state
10. Create and edit private viewing records
11. Request LLM-structured proposal from rough notes
12. Preview proposal, accept or reject
13. Search and filter private records

### LLM-assisted capability map

| Capability | Fake provider | Real provider (deferred) |
|---|---|---|
| Intent → search rules | `FakeLanguageModelProvider.propose_query_rules` | Real LLM with prompt |
| Video classification | `FakeLanguageModelProvider.classify_videos` | Real LLM with metadata |
| Rule change suggestions | `FakeLanguageModelProvider.suggest_rule_changes` | Real LLM with feedback |
| Note structuring | `FakeLanguageModelProvider.structure_record` | Real LLM with schema |
| Title/summary suggestion | `FakeLanguageModelProvider.suggest_title_summary` | Real LLM |

### Deterministic fallback (no LLM required)

Every LLM-assisted workflow has a manual fallback:

- Search rules can be entered directly via the rule review form
- Video classification is optional (feed works without it)
- Note structuring can be skipped (free-form note is always preserved)
- Rule changes can be made directly in the rule edit form

### Provider interfaces

```text
VideoDiscoveryProvider
├── search_videos(rules, cursor) -> SearchPage
├── get_video_details(video_ids) -> list[DiscoveredVideo]
└── health_check() -> ProviderHealthCheck

LanguageModelProvider
├── propose_query_rules(intent) -> QueryRuleProposal
├── classify_videos(videos, rules) -> list[VideoClassification]
├── suggest_rule_changes(feedback, rules) -> RuleChangeProposal
├── structure_record(rough_notes) -> RecordStructureProposal
└── suggest_title_summary(rough_notes) -> (title, summary)
```

Fake implementations: `FakeVideoDiscoveryProvider`, `FakeLanguageModelProvider`

### Data sent to providers (Phase 1)

**Nothing is sent to any external provider in Phase 1.**

- `FakeVideoDiscoveryProvider` generates synthetic videos locally — no network calls
- `FakeLanguageModelProvider` parses text with rule-based heuristics — no network calls
- No API keys, secrets, or user data are transmitted

### Provenance separation

Three distinct provenance types are stored and displayed:

1. **YouTube-sourced metadata** — `DiscoveredVideo.provenance = "youtube"`
2. **Application-derived annotations** — `TopicVideo.provenance = "application"`
3. **User-authored private records** — `PrivateViewingRecord.provenance = "user"`

The UI displays badges for each provenance type.

## Installation

```bash
cd apps/personal-video-archive
python3 -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

## Running locally

```bash
# Start the development server
python -m app.main

# Or with uvicorn directly
uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000` in your browser.

## Testing

```bash
# Run all tests (no network access required)
pytest tests/ -v

# Run only unit tests
pytest tests/unit/ -v

# Run only integration tests
pytest tests/integration/ -v
```

All 219 tests pass without network access.

## Static UI preview (Cloudflare Pages)

A static, synthetic preview of the accepted Phase 1 UI can be built for hosted
review. It renders the **existing Jinja templates** with synthetic fixture data
— no database, FastAPI server, YouTube API, LLM, API key, or network access is
required, and nothing is persisted.

### Build locally

```bash
cd apps/personal-video-archive
python -m scripts.build_static_preview
```

Output is written to `dist-preview/` (gitignored). Open
`dist-preview/index.html` to browse the preview landing page, which links to
every preview state (topic list, new topic, query-rule review, populated /
filtered / empty / failed feeds, video detail, private records, pending and
accepted AI proposals, record search, and a validation error).

Each topic feed is generated for **all eight filter states**
(`all/unseen/opened/saved/in_progress/completed/revisit/irrelevant`) as real
pages under `topics/<id>/<state>/`, so every filter pill resolves to a generated
file whose selected pill and contents match the requested state — no query
strings are relied on by the static host.

The builder's `main(output_dir=None)` accepts an explicit output directory
(defaulting to the workspace `dist-preview/`), so tests and repeated builds can
target isolated temporary locations without depending on the worktree's
`dist-preview/`.

Every page shows a **"UI Preview · Synthetic data · No persistence"** banner,
carries `noindex, nofollow`, and has all forms and JavaScript made inert.

### Preview tests

```bash
pytest tests/test_static_preview.py -v
```

### Cloudflare Pages configuration

Dedicated project: **ai-revenue-personal-video-archive**

| Setting | Value |
|---|---|
| Repository | `skerishKang/ai-revenue-lab` |
| Production branch | `main` |
| Root directory | `apps/personal-video-archive` |
| Environment variable | `PYTHON_VERSION=3.12` |
| Build command | `python -m pip install -e . && python -m scripts.build_static_preview` |
| Build output directory | `dist-preview` |

`PYTHON_VERSION=3.12` matches `requires-python = ">=3.12"` in `pyproject.toml`;
the `pip install -e .` step installs the runtime dependency (`jinja2`) the
builder needs before the preview is generated into `dist-preview`.

> **Deploy-target clarification.** The dedicated Business 13 preview is served
> only from the `ai-revenue-personal-video-archive` project above. The
> `ai-revenue-personal-edition` Cloudflare Pages project that a repository bot
> may attach to pull requests belongs to a *different* Business workspace — it
> is **not** the Business 13 deploy target and does not affect this product's
> preview. This table documents the intended configuration only; no real
> Cloudflare setting is changed by this work.

The generated `_headers` enforces a restrictive Content-Security-Policy
(`script-src 'none'; form-action 'none'; connect-src 'none'`) plus
`X-Robots-Tag: noindex, nofollow`, and `robots.txt` disallows all crawling.

## Synthetic fixtures vs real data

- All video data is **synthetic** — generated deterministically by `FakeVideoDiscoveryProvider`
- All LLM output is **synthetic** — generated by rule-based heuristics in `FakeLanguageModelProvider`
- No real YouTube data, user data, or API responses are stored or transmitted
- Fixtures are deterministic: the same input always produces the same output

## Deferred (not implemented in Phase 1)

- Real YouTube Data API integration
- Real LLM provider integration (OpenAI, Anthropic, etc.)
- Google OAuth for private YouTube account data
- iframe video playback
- Historical watch-history import
- YouTube comments or community features
- Transcript scraping
- Video download or rehosting
- Advertising
- Google Cloud API key setup navigator
- Payments or subscriptions
- Native mobile applications

## Workspace boundary

All implementation, tests, migrations, fixtures, provider adapters, and product documentation belong under:

```text
apps/personal-video-archive/**
```

Do not modify another product workspace to implement this product. Shared code may be extracted only after an approved cross-product architecture decision.
