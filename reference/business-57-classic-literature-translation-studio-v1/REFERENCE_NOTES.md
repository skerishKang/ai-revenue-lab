# Reference Notes

Research and verification date: `2026-07-28`

## Research objective

Design a Korean-first literary translation edition that makes source fidelity, modernization, ambiguity, repeated terms, cultural distance and human editorial judgment visible without becoming a generic machine-translator interface.

## Primary and official references

### Project Gutenberg — Frankenstein 1818 edition

- URL: `https://www.gutenberg.org/ebooks/41445`
- Readback: `https://www.gutenberg.org/cache/epub/41445/pg41445-images.html`
- Observed: eBook #41445 identifies the 1818 publication and states that its text was produced from a photo-reprint of the 1818 edition.
- Adopted: exact edition label, chapter number, punctuation readback and bibliographic provenance.
- Rejected: using the generic eBook #84 without resolving whether the UI passage belonged to the 1818 or 1831 edition.

### Wikisource — The Sick Rose

- URL: `https://en.wikisource.org/wiki/Songs_of_Innocence_and_of_Experience_(1826)/Songs_of_Experience/The_Sick_Rose`
- Observed: the 1826-copy transcription preserves stanza and line structure and identifies the poem's 1794 publication context.
- Adopted: explicit textual-source edition and line-break preservation.
- Rejected: copying Blake's illuminated plate or a modern poem illustration.

### Republic of Korea Copyright Act

- URL: `https://www.law.go.kr/법령/저작권법`
- Observed: current Article 39 records the general life-plus-70 term.
- Adopted: work/author/edition/territory/date checkpoint and a caution that production use requires exact clearance.
- Rejected: treating age alone as automatic permission for a modern Korean translation or a particular digitized edition.

### WIPO — Berne Convention

- URL: `https://www.wipo.int/wipolex/en/text/283698`
- Observed: translations are protected derivative works without prejudice to the original, and protected-work authors hold the translation right during the term.
- Adopted: original-work rights and translation rights as separate first-class records.
- Rejected: presenting literary translation as a neutral technical conversion.

### U.S. Copyright Office — Copyright and Artificial Intelligence

- URL: `https://www.copyright.gov/ai/`
- Observed: the Office separates digital replicas, output copyrightability and generative-AI training in a multipart policy study.
- Adopted: explicit model/corpus disclosure and human editorial state.
- Rejected: implying that a generic AI-assistance label resolves corpus permission or authorship questions.

## Editorial references and decisions

### Parallel-text and critical editions

Adopted:

- passage-level source/translation alignment rather than token-by-token interlinear clutter;
- separate folios and edition labels;
- margin notes for consequential terms;
- alternatives and unresolved decisions kept visible;
- source edition and textual provenance as part of the reading product.

Rejected:

- spreadsheet-like red/green code diffs;
- forcing every source token into a one-to-one line;
- hiding uncertainty to imply one mechanically correct answer.

### Publishing proofs and translator manuscripts

Adopted:

- fine rules, folios, proof marks, restrained oxblood and indigo annotations;
- decision ledger with textual status labels as well as colour;
- warm paper, deep ink and stable reading geometry;
- readable paragraph measure and line height.

Rejected:

- dashboard metrics, chat bubbles, generic settings panels, glassmorphism, neon AI and rounded-card walls;
- copied publisher trade dress, translator identities or existing Korean edition typography;
- gradients and external font dependencies.

## Adjacent-product distinction

- **Google Translate / DeepL:** optimize fast general translation; Business 57 centers literary editions, provenance, ambiguity and reviewable decisions.
- **Generic AI chat:** centers conversation and ephemeral output; Business 57 centers one durable source-accountable edition.
- **Business 11 · Language Learning Magazine:** recurring learning publication; Business 57 is a literary translation edition where instruction is secondary.
- **Business 3 · Living Fiction:** creates or branches stories; Business 57 must preserve and account for an existing source.
- **Business 34 · AI Dubbing Studio:** localizes audiovisual speech; Business 57 is text-first and edition-oriented.
- **Business 58 · Personal Writing Voice Studio:** may later supply a consented voice profile; it cannot replace the primary original-fidelity edition or imply a current contract.

## Content decisions checked against Issue #217

- Meaningful ambiguity: `lifeless thing` → `생기 없는 것` / `죽은 몸` / `존재`.
- Multiple alternatives: `dreary` and `instruments of life` each retain visible alternatives.
- Historical term: `instruments of life` is annotated against 1818 natural-philosophy and galvanism context.
- Repeated source root: `life → lifeless → being` is visibly tracked.
- Deliberate difficulty: the fidelity edition retains long purpose syntax and `생명의 기구들`.
- Modernization: the modern-reading edition splits the sentence and concretizes `thing` as `죽은 몸`.
- Loss statement: narrator distance, abstraction and evasive rhythm are explicitly marked as weakened.
- Poetry conflict: literal meaning and the sound/rhythm choice around `howling` are separated.
- Disclosure: source, rights, newly authored Korean, disconnected model/corpus and human-review state are visible.

## Visual and motion decisions

- Direction: `Parallel Literary Edition / 나란히 읽는 번역판`.
- Primary hero: source and original-fidelity spread.
- Secondary surfaces: modern-reading comparison, decision ledger and poetry edition.
- Signature: `Translation Weave` animates only SVG linking rules and rendering emphasis.
- Computed maximum end: `680ms`, verified from actual computed duration plus delay.
- Final state: normal replay and reduced-motion mode expose identical paths, emphasis and annotation information.
