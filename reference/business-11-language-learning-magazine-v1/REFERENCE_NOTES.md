# Reference Notes

- Review date: **2026-07-26 (Asia/Seoul)**
- Research scope: official product pages and public editorial/award pages
- Timebox: focused pre-implementation review
- Constraint: no third-party screenshot, brand mark, article text, or full layout is embedded in the result

## Adjacent language-learning products

### 1. LingQ

- URL: `https://www.lingq.com/en/`
- Relevant pattern: target-language text is primary; selected words and phrases remain visibly connected to reading context.
- Adopted: phrase highlighting, vocabulary-in-context, restrained support around a long reading surface.
- Rejected: lesson library, progress claims, subscription framing, vocabulary inventory, and dashboard structure.

### 2. Readlang

- URL: `https://readlang.com/`
- Relevant pattern: click-to-translate keeps the learner near the sentence rather than sending them to a separate dictionary.
- Adopted: small translation fragments and phrase-level inspection close to the source line.
- Rejected: browser-extension utility framing, generic e-reader shell, saved-word workflow, and flashcard continuation.

### 3. Beelinguapp

- URLs:
  - `https://beelinguapp.com/`
  - `https://beelinguapp.com/about`
- Relevant pattern: parallel-language support and story-led learning.
- Adopted: bilingual assistance that remains secondary to the target-language story.
- Rejected: always-on parallel columns, audiobook controls, song/news catalog, glossary game, and conventional app navigation.

### 4. Language Reactor

- URL: `https://www.languagereactor.com/`
- Relevant pattern: authentic language appears with phrase-level comprehension aids and transliteration or translation support.
- Adopted: contextual expression inspection and layered annotation.
- Rejected: video-player dependency, subtitles, playback controls, speech tools, vocabulary toolkit, and dense utility chrome.

### 5. SRS-Stories

- URL: `https://arxiv.org/abs/2512.18362`
- Relevant pattern: stories can be shaped around a learner's known vocabulary while keeping words inside coherent narrative context.
- Adopted: the issue is framed as personally edited for a level and interest, with repeated expressions appearing naturally.
- Rejected: spaced-repetition mechanics, optimization claims, generated-story workflow, and any visible model logic.

## Editorial and design references

### 6. The Pudding

- URLs:
  - `https://pudding.cool/`
  - `https://awards.journalists.org/entries/the-pudding/`
- Relevant pattern: editorial storytelling uses scale shifts, pull quotes, annotated evidence, and custom visual rhythm rather than uniform cards.
- Adopted: strong feature typography, evidence-like marginalia, modular story pacing, and controlled visual explanation.
- Rejected: scroll-driven data interaction, charts, gamified exploration, and elaborate custom narrative mechanics.

### 7. The Dial identity and editorial system

- URL: `https://www.lucyandersen.com/work/the-dial`
- Relevant pattern: a contemporary digital magazine can retain print-periodical gravity while remaining flexible on screens.
- Adopted: firm masthead, serif/sans tension, rules, issue identity, and nonuniform editorial modules.
- Rejected: direct imitation of its identity, historical branding, specific color system, or complete page compositions.

### 8. The Edit Magazine

- URL: `https://theeditmag.com/`
- Relevant pattern: design, objects, and culture are presented with image-led calm, generous whitespace, and long-form editorial confidence.
- Adopted: cultural rather than instructional mood, image captions, quiet source lines, and premium pacing.
- Rejected: lifestyle-commerce adjacency and publication-specific branding.

### 9. Society for News Design digital award coverage

- URLs:
  - `https://www.washingtonpost.com/pr/2025/04/30/worlds-best-designed-digital/`
  - `https://www.sfchronicle.com/about/newsroomnews/article/s-f-chronicle-honored-annual-snd-awards-22259643.php`
- Relevant pattern: strong digital editorial design integrates story hierarchy, typography, illustration, and responsive presentation.
- Adopted: clear visual hierarchy, distinct page rhythms, and mobile treatment as an edition rather than a shrink-wrapped desktop.
- Rejected: newsroom breadth, breaking-news density, live data, and publication navigation systems.

## Adopted visual grammar

- one dominant feature per issue;
- strong masthead, issue number, date, level marker, page numbers, and source lines;
- target-language-first reading with concise Korean support;
- warm paper, black ink, vivid red-orange language accent, muted annotation blue;
- thin rules, underlines, pronunciation marks, margin notes, translation fragments, word-family links, pull quotes, and captions;
- asymmetric editorial grids instead of repeating rounded cards;
- mobile uses a single-column magazine rhythm with one visible annotation cue;
- Margin Echo reveals meaning, usage, and related expression without moving the reading position.

## Rejected product patterns

- flashcard fronts/backs, quiz answer buttons, word-test scores, or memory games;
- generic e-book bookshelf or long article reader with a toolbar;
- AI tutor chat, bot persona, speech assessment, or model confidence;
- school workbook tables, teacher comments, red error counts, grades, or CEFR claims;
- SaaS dashboard sidebars, metrics, rings, streaks, badges, hearts, coins, or ranking;
- uniform rounded cards and generic AI gradients.

## Boundary from Business 4 · Living Learning

Business 4 is a broad adaptive learning system in which the learner's response and understanding influence the next lesson. Its primary product logic is a changing lesson sequence.

Business 11 is an editorial publication. Its primary result is one finished issue that combines reading, vocabulary, one revision note, cultural context, questions, and concise feedback. Phase 1 demonstrates the look of that publication only. It does not claim adaptive sequencing, automatic assessment, lesson generation, or a learner model.
