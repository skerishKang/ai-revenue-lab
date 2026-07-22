# Personal Video Archive

Business number: **13**

Status: **Incubation — product contract registered; implementation not started**

Tracking issue: **#60**

## What is this

Personal Video Archive is a private, topic-first video discovery and reflection product.

A user defines the subjects they want to follow, receives newly published matching YouTube videos in structured topic pages, opens the original video, and keeps private records of what they watched, thought, learned, questioned, and plan to do next.

It is not a replacement video platform, a social network, or a generic recommendation feed.

## Product thesis

YouTube organizes discovery primarily around platform recommendations, channels, and a mixed subscription stream. Many users instead want stable, user-controlled topic feeds and a durable record of the meaning they took from each video.

The product therefore combines:

1. **topic subscription** — follow a subject rather than only a channel;
2. **controlled discovery** — include, related, and exclude terms with latest-first defaults;
3. **private reflection** — preserve viewing state, ratings, notes, plans, tags, and timestamp references;
4. **guided setup** — later guide personal-instance users through Google Cloud and API-key setup with a rule-driven navigator and AI explanation layer.

## Phase 1 experience

- Create a topic such as `ChatGPT updates` or `local LLM`.
- Review generated search rules and adjust them when needed.
- See matching videos with newly published videos first.
- Open the canonical YouTube page in a new tab.
- Mark the video as opened, saved, completed, irrelevant, or worth revisiting.
- Record a reflection, plan, question, rating, tags, and useful timestamps.
- Return later to either the topic feed or the user's own viewing archive.

## API boundary

YouTube Data API v3 is needed primarily for:

- keyword and topic search;
- publication-date ordering and supported search filters;
- video identifiers, titles, descriptions, channel information, thumbnails, and publication dates;
- supplementary public metadata such as duration and statistics through video-detail requests.

The product's private notes, plans, ratings, tags, and viewing states are first-party application data and do not require the YouTube API.

All provider access must sit behind an adapter. Automated tests must use deterministic fixtures or a fake provider and must not make network calls.

## Playback decision

Phase 1 opens the original YouTube URL. This keeps the product light and leaves playback, captions, account state, and creator controls on YouTube.

Official iframe playback may be evaluated later for a single video-detail screen. It is not required for the initial product hypothesis.

## Explicit non-goals

- importing historical YouTube watch history;
- YouTube comments or community features;
- public profiles or social feeds;
- downloading, extracting, caching, or rehosting video media;
- transcript scraping;
- synchronizing subscriptions or YouTube playlists in Phase 1;
- AI-generated video summaries in Phase 1;
- advertising before product usefulness and policy compliance are validated.

## Workspace boundary

All implementation, tests, migrations, fixtures, provider adapters, and product documentation belong under:

```text
apps/personal-video-archive/**
```

Do not modify another product workspace to implement this product. Shared code may be extracted only after an approved cross-product architecture decision.

## Next step

Use `LOCAL_HANDOFF.md` to create a local worktree and assign a model to the first isolated implementation issue. Implementation must not begin until the Phase 1 architecture and acceptance criteria are decomposed into a separate GitHub issue.