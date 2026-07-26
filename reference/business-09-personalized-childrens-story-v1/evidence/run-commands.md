# Browser Validation Commands

## Direct-navigation attempt

```bash
cd reference/business-09-personalized-childrens-story-v1
python -m http.server 4179 --bind 127.0.0.1
```

Chromium access to both the local HTTP URL and the local file URL was blocked by the execution environment with `ERR_BLOCKED_BY_ADMINISTRATOR`. No successful direct-navigation result is claimed.

## Executed Chromium validation

```bash
cd reference/business-09-personalized-childrens-story-v1
python evidence/validate-browser.py
```

The validator resolves every referenced local CSS, JavaScript, and SVG file from disk, checks paths and version queries, constructs the exact document in memory, and runs it in actual Chromium through Playwright `page.set_content`. It records desktop, mobile, keyboard, focus, motion, reduced-motion, console, page, asset, and network results in `validation.json`.

## Additional static checks

```bash
find . -type f \
  \( -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.md' -o -name '*.svg' \) \
  -print0 | xargs -0 wc -l

grep -RInE '<link[^>]+href="[^"]+\.css(\?[^"]*)?"|<script[^>]+src="[^"]+\.js(\?[^"]*)?"' index.html

grep -RInE 'https?://|//[^/]' index.html styles scripts assets/images
```

Binary captures were produced with an uncommitted temporary capture helper against the same in-memory Chromium document. They are submitted separately and are not claimed as committed repository evidence.
