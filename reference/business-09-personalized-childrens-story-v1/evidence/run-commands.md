# Focused Story Bloom Validation Commands

## Scope

Focused correction for Draft PR `#175`, starting from exact head:

```text
d55b09f3a6a90da8eac0cb0c5c8d1a6ead177172
```

Only `reference/business-09-personalized-childrens-story-v1/**` is inspected or changed.

## Direct-navigation limitation

```bash
cd reference/business-09-personalized-childrens-story-v1
python -m http.server 4179 --bind 127.0.0.1
```

Chromium access to both the local HTTP URL and the local `file://` URL remains blocked by the execution environment with `ERR_BLOCKED_BY_ADMINISTRATOR`. No successful direct-navigation result is claimed.

## Executed Chromium validation

```bash
cd reference/business-09-personalized-childrens-story-v1
python evidence/validate-browser.py
```

The validator resolves the exact local HTML, CSS, JavaScript, and SVG files; checks local paths, line limits, and the `personalized-childrens-story-20260726-2` loading token; then executes the assembled document in actual Chromium through Playwright `page.set_content`.

The focused Bloom checks include:

- active Bloom state and `.bloom-book` opacity before replay;
- absence of generic `state-enter` on state 7;
- stable opacity, transform, and geometry for the Bloom section, book, copy, stage, base image, and title;
- changing opacity or transform only on `.bloom-layer` elements;
- actual click of `#replay-bloom` for the second playback;
- final state after the 680ms sequence;
- immediate final state under `prefers-reduced-motion: reduce`.

## Executed binary evidence capture

```bash
cd reference/business-09-personalized-childrens-story-v1/evidence
python capture-bloom-evidence.py \
  --output /mnt/data/personalized-childrens-story-bloom-correction-evidence
```

The capture helper uses the same exact in-memory Chromium document. The GIF starts with a fully visible book, copy, page, and fixed boot while all motion layers are hidden. It then clicks `다시 피우기` and captures the cloud, sail, and path sequence through 680ms.

Generated outside the repository:

- `desktop-1440-story-bloom-start.png`
- `desktop-1440-story-bloom-final.png`
- `story-bloom-680ms.gif`
- `reduced-motion-final-state.png`
- `validation.json`
- `run-commands.md`

## Static checks

```bash
find . -type f \
  \( -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.md' \
     -o -name '*.svg' -o -name '*.py' -o -name '*.json' \) \
  -print0 | xargs -0 wc -l

grep -RIn 'personalized-childrens-story-20260726-1' index.html styles scripts

grep -RInE '<link[^>]+href="[^"]+\.css(\?[^"]*)?"|<script[^>]+src="[^"]+\.js(\?[^"]*)?"' index.html

grep -RInE 'https?://|//[^/]' index.html styles scripts assets/images
```

The ZIP is assembled only from the separate evidence directory and is not claimed as a committed GitHub artifact.
