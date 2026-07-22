# Personal Video Archive — Phase 1 Product Contract

Business: **13**
Status: **Phase 1 MVP implemented**
Tracking issue: **#62**

## 1. Product statement

Personal Video Archive lets a user define stable video topics, discover newly published matching YouTube videos without relying on the mixed YouTube Home or Subscriptions feeds, and keep a private record of what each viewed video meant to them.

The product is successful only if it improves both halves of the workflow:

1. finding the right videos with less repeated searching and less irrelevant noise;
2. turning watched videos into durable personal knowledge, reflection, and action.

## 2. Target user

The initial user is a person who repeatedly follows several subjects and currently experiences one or more of these problems:

- recommendation feeds mix unrelated interests;
- channel subscriptions do not map cleanly to subjects;
- the same keyword searches must be repeated;
- useful videos disappear inside large playlists;
- the user cannot easily recover what they thought, learned, questioned, or planned after watching.

The first implementation is private and single-user oriented. Multi-user SaaS assumptions are not authorized in Phase 1.

## 3. Core jobs

### Job A — define a subject

The user creates a persistent topic page from a natural-language intent such as:

> Show me newly published Korean and English videos about meaningful ChatGPT product updates, excluding Shorts and low-value reaction content.

The application stores explicit, inspectable search rules. AI may propose rules, but the user owns and can edit them.

**Phase 1 implementation:** `FakeLanguageModelProvider.propose_query_rules` converts intent into a `QueryRuleProposal` draft. The user reviews and edits the draft in a form before acceptance.

### Job B — inspect a clean topic feed

The application retrieves matching public videos and presents them inside the selected topic rather than one mixed recommendation feed.

Default ordering is newest publication first. Supported alternatives may include view count and relevance where available.

**Phase 1 implementation:** `FakeVideoDiscoveryProvider.search_videos` returns synthetic videos sorted newest-first. The feed is displayed in `templates/topics/feed.html` with clear source labeling.

### Job C — open the source video

Phase 1 opens the canonical YouTube URL in a new browser tab. The application records that the link was opened but does not infer that the video was completed.

**Phase 1 implementation:** An "Open on YouTube" button submits a `POST /topic-videos/{tv_id}/open` form with `target="_blank"` and no JavaScript. The route records `opened` for that topic-video only and 303-redirects the new tab to `https://www.youtube.com/watch?v=<id>`, leaving the archive page in place (no duplicate tab). The open action promotes only an `unseen` record to `opened`; explicit user states (saved, in progress, completed, revisit, irrelevant) are preserved on open. `opened` does not imply `completed`.

### Job D — preserve a private viewing record

The user can store:

- status: unseen, opened, saved, in progress, completed, revisit, irrelevant;
- rating;
- short reflection or long note;
- what was learned;
- disagreement or uncertainty;
- follow-up plan;
- timestamp references entered by the user;
- personal tags;
- viewed or completed date.

These records are application-owned first-party data.

**Phase 1 implementation:** `PrivateViewingRecord` model with all fields. The `/records/{id}` route provides a form for editing. The `/records/{id}/propose-structure` route generates an LLM structure proposal.

## 4. Discovery model

Each topic may contain:

- topic name;
- primary query;
- related queries;
- required terms;
- excluded terms;
- preferred language or languages;
- included or excluded channels;
- publication window;
- duration preference;
- Shorts inclusion preference;
- default ordering;
- manual or scheduled refresh preference.

The implementation preserves the distinction between:

- **YouTube-sourced metadata** — `DiscoveredVideo` with `provenance = "youtube"`;
- **application search rules and ranking annotations** — `QueryRule` and `TopicVideo` with `provenance = "application"`;
- **user-authored records** — `PrivateViewingRecord` with `provenance = "user"`.

The UI does not imply that an application ranking or label is an official YouTube property.

## 5. API and provider contract

### 5.1 Why an API is required

The YouTube Data API v3 is required primarily to perform keyword/topic searches and retrieve public video metadata in a supported, structured way.

Expected operations include:

- search requests for matching video IDs and snippets;
- video detail requests for duration, statistics, and other supported public fields;
- pagination and publication-date filtering;
- metadata refresh for previously stored videos.

The API is not required for the user's private notes, plans, tags, ratings, or application viewing states.

### 5.2 Adapter boundary

Production code depends on application interfaces rather than directly on a Google client library.

```text
VideoDiscoveryProvider
├── search_videos(topic_rules, cursor) -> SearchPage
├── get_video_details(video_ids) -> list[DiscoveredVideo]
└── health_check() -> ProviderHealthCheck

LanguageModelProvider
├── propose_query_rules(intent) -> QueryRuleProposal
├── classify_videos(videos, rules) -> list[VideoClassification]
├── suggest_rule_changes(feedback, rules) -> RuleChangeProposal
├── structure_record(rough_notes) -> RecordStructureProposal
└── suggest_title_summary(rough_notes) -> (title, summary)
```

The adapter exposes quota cost and provider errors in normalized application terms.

### 5.3 Test boundary

- No automated test may call YouTube or Google Cloud.
- A deterministic fake provider and fixed fixtures are mandatory.
- Secrets must never appear in fixtures, logs, committed configuration, screenshots, or error reports.
- Integration with the real provider must be a separately invoked manual or protected environment check.

### 5.4 Credential modes

Phase 1 uses one private operator-controlled credential in a protected server environment.

A future self-hosted or personal-instance edition may offer BYOK onboarding. That flow must:

- guide the user through a dedicated Google Cloud project;
- keep the key outside AI prompts and chat transcripts;
- mask the key in the UI and logs;
- test the key through a narrow server-side endpoint;
- explain quota and restrictions;
- never be positioned as a way for a centralized public service to bypass quota limits.

## 6. Initial information architecture

### 6.1 Today

A compact overview of new videos grouped by the user's topics.

### 6.2 Topics

Persistent subject pages with search rules, latest results, filters, refresh state, and irrelevant-result feedback.

### 6.3 Saved

Videos intentionally retained for later viewing or reference.

### 6.4 Viewing archive

Opened and completed videos with private reflections, plans, tags, ratings, and timestamps.

### 6.5 Settings

Provider status, refresh limits, data export, data deletion, and eventually guided API setup.

## 7. Phase 1 functional scope

### Required (implemented)

- topic create, edit, pause, and archive;
- explicit search-rule storage;
- latest-first video retrieval;
- supported sorting and filters;
- deduplication by canonical video ID;
- topic-to-video association when one video matches multiple topics;
- original YouTube link;
- opened state from outbound-link action;
- user-controlled completion state;
- save, revisit, and irrelevant states;
- rating, reflection, plan, note, tags, and timestamp references;
- search and filter over private records;
- provider adapter and fake provider;
- quota ledger and sync-run audit record;
- failure states that preserve existing local data;
- LLM proposal validation, preview, and user-controlled acceptance/rejection;
- original user text preservation;
- provenance separation (YouTube / application / user).

### Deferred

- official iframe playback;
- automated playback progress;
- Google OAuth for private YouTube account data;
- subscriptions or playlist synchronization;
- collaborative or public archives;
- AI-generated summaries;
- transcript ingestion;
- advertising;
- payments;
- native mobile applications;
- real YouTube Data API integration;
- real LLM provider integration;
- Google Cloud API key setup navigator.

## 8. Data model seed

The first architecture issue should evaluate at least these entities:

```text
Topic
QueryRule
DiscoveredVideo
TopicVideo
PrivateViewingRecord
TimestampReference
SyncRun
QuotaLedgerEntry
ProposalRecord
```

Important constraints:

- `DiscoveredVideo` is deduplicated by provider and provider video ID.
- `TopicVideo` records discovery context and first/last match timestamps.
- `PrivateViewingRecord` is user-owned and must survive provider refresh failures.
- raw API responses should not become the domain model.
- metadata freshness and deletion/unavailability states must be representable.

## 9. Guided reflection

The product may later use a rule-driven question sequence with an AI explanation layer, borrowing the navigator pattern used in other portfolio products.

Examples:

- What was the most useful claim?
- What do you disagree with or need to verify?
- What will you do next?
- Which timestamp should you revisit?

The AI may organize user-authored material but must not invent that the user watched, agreed with, or learned something.

## 10. Success evidence

Phase 1 should collect evidence for:

- number of active topics;
- percentage of retrieved videos marked relevant;
- time from topic entry to useful video open;
- repeat searches avoided;
- opened-to-completed rate;
- percentage of completed videos with a private record;
- records revisited later;
- follow-up plans completed;
- API quota consumed per useful result;
- infrastructure and paid-model cost.

The primary early question is not whether the product can display YouTube results. It is whether the user repeatedly returns because discovery is cleaner and prior viewing becomes more useful over time.

## 11. Acceptance boundary for Phase 1

Phase 1 establishes:

- isolated application scaffold under `apps/personal-video-archive/**`;
- domain types and persistence for topics, videos, and records;
- fake-provider search flow;
- latest-first topic screen using synthetic fixtures;
- outbound YouTube link action;
- private record creation and retrieval;
- deterministic tests;
- no real credential requirement for test or preview.

No other product workspace may be modified without explicit CTO approval.
