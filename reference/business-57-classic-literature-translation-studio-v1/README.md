# Business 57 · Classic Literature Translation Studio

## Status

```text
UI_ONLY
CONTRACT_DEMO
PUBLIC_DOMAIN_AND_SYNTHETIC_FIXTURES_ONLY
NOT_DEPLOYED
NOT_UI_APPROVED
```

This workspace is the Phase 1 visual reference for **고전문학 번역실 / Classic Literature Translation Studio**.

It demonstrates how one verified literary source may be reviewed as:

1. original-language source;
2. original-fidelity Korean translation;
3. modern-reading Korean translation;
4. translation-decision ledger;
5. poetry literal/poetic editions;
6. a future contract bridge to an authorized personal writing voice.

## Contract-demo purpose

The reference is intended to explain a potential author, translator, publisher or estate collaboration. It is not a retail product, operational translator or trained author model.

Because the repository is public, it contains no:

- living-author manuscript;
- licensed private corpus;
- contract terms;
- model adapter or weights;
- private prompt package;
- customer data;
- claim of author endorsement.

Future contracted material must remain in an isolated private environment and use the rights/consent controls defined by Business 58.

## Fixtures

### Novel

- Mary Shelley, *Frankenstein* (1818)
- short English excerpt used as a public-domain demonstration fixture;
- Korean translations were newly authored for this UI reference;
- no modern Korean translation was copied.

### Poetry

- William Blake, *The Sick Rose* (1794)
- short original stanza used as a public-domain demonstration fixture;
- Korean literal and poetic versions were newly authored for this UI reference.

See `RIGHTS_AND_SOURCES.md` for the source and rights record.

## Seven states

1. Translation library
2. Source and original-fidelity spread
3. Original-fidelity versus modern-reading comparison
4. Translation decision ledger
5. Poetry edition
6. Mobile reading edition
7. Translation Weave signature motion

## Interaction

- click the seven review tabs;
- use Left/Right Arrow keys to move between states;
- reveal the source sentence in the mobile state;
- replay Translation Weave in the final state;
- `prefers-reduced-motion: reduce` presents the completed weave without staged motion.

## Technical boundary

- plain HTML, CSS and minimal JavaScript;
- repository-local SVG only;
- no external font, framework, API or runtime request;
- no upload, storage, generation, model call or persistence;
- deterministic asset version: `classic-literature-translation-20260727-1`.

## Local review

```bash
cd reference/business-57-classic-literature-translation-studio-v1
python -m http.server 8000
```

Then open `http://127.0.0.1:8000/` in a browser.

Run the static validator:

```bash
python evidence/validate_static.py
```

## Phase gate

This reference must remain Draft and unmerged until Web CTO review and user visual approval. Deployment requires a separately recorded exact-head `UI_APPROVED` decision and separate deployment authorization.
