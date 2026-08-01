# Business 22 · Personal Media Studio

## Status

```text
Proposed Business 22
Personal Media Studio / 개인 미디어 스튜디오
Phase 1 — UI_ONLY
UI_REVIEW_READY candidate only
```

This directory is a static, synthetic visual reference for Issue #223. It demonstrates the **Master Edition Room / 마스터 에디션 룸** metaphor: one bounded source set, one master story spine, seven medium-specific proofs, visible source/omission relationships, and a final human-review surface.

## Synthetic reference project

```text
새벽시장 30일 기록
```

Every person, place, quotation, figure, image, note, interview fragment, map and media object shown here is fictional and synthetic. The local SVG assets do not depict a real market, journalist, creator, interviewee, business or unpublished archive.

## Visual states

The review surface contains exactly seven representative states:

1. `cover` — identity-rich opening and coordinated edition family;
2. `sources` — mixed source ledger, contact sheet, map and timecode;
3. `spine` — master thesis, scenes, audience, repeated message and editorial boundaries;
4. `suite` — article, audio, video, cards, newsletter, interview and book proof;
5. `adaptation` — one source moment adapted differently for four media;
6. `trace` — provenance, omission, editorial decisions and human review;
7. `mobile` — deliberate 390px vertical edition flow.

Use `?state=<name>` to open a state directly, for example:

```text
index.html?state=suite
```

## Review controls

- tab buttons switch representative visual states;
- `ArrowLeft`, `ArrowRight`, `ArrowUp`, `ArrowDown`, `Home` and `End` move among tabs;
- previous/next controls cycle states;
- the adaptation state includes a keyboard-operable replay control;
- replay preserves focus, scroll position and page geometry;
- `prefers-reduced-motion: reduce` renders the same final relay information immediately.

These controls exist only to inspect visual composition and motion. They are not accepted UX.

## Explicit limitations

This reference does **not** implement or claim:

- real upload or source ingestion;
- real AI generation or transformation;
- recording, transcript processing, TTS, voice cloning, audio or video playback;
- timeline, canvas or document editing;
- save, export, download, publishing, scheduling or social integration;
- authentication, authorization, persistence, API, database or backend;
- collaboration, analytics, billing or production readiness;
- complete onboarding, information architecture or end-to-end UX.

## Local review

From this directory:

```bash
python3 -m http.server 4173
```

Then open:

```text
http://127.0.0.1:4173/index.html?state=cover
```

Validation is documented in `VALIDATION.md`. Machine-readable output is stored in `evidence/validation-report.json`.
