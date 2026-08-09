"""Build the canonical static Production review for Business 13.

The existing ``build_static_preview`` remains the QA builder and keeps its
visible Preview/Sample-data notice.  This wrapper deliberately preserves the
same deterministic fixtures, inert forms, CSP, noindex and zero-provider
network boundary, then removes only the visible QA chrome and adds the
first-use Guide entry point used for owner Production review.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts import build_static_preview

_BASE_DIR = Path(__file__).resolve().parent.parent
_GUIDE_SOURCE = _BASE_DIR / "guide.html"
_TOP_NOTE_RE = re.compile(
    r'<div class="top-note" role="note">.*?</div>\s*',
    flags=re.DOTALL,
)
_TOP_ACTIONS = '<div class="top-actions">'
_GUIDE_LINK = (
    '<div class="top-actions">'
    '<a href="/guide.html" class="lang-button" '
    'aria-label="30초 사용법">30초 사용법</a>'
)


def main(output_dir: Path | None = None) -> Path:
    out = build_static_preview.main(output_dir)

    if not _GUIDE_SOURCE.exists():
        raise RuntimeError(f"Guide source missing: {_GUIDE_SOURCE}")
    (out / "guide.html").write_bytes(_GUIDE_SOURCE.read_bytes())

    for html_file in out.rglob("*.html"):
        if html_file.name == "guide.html" and html_file.parent == out:
            continue
        html = html_file.read_text(encoding="utf-8")
        html = _TOP_NOTE_RE.sub("", html)
        if _TOP_ACTIONS in html and "/guide.html" not in html:
            html = html.replace(_TOP_ACTIONS, _GUIDE_LINK, 1)
        html_file.write_text(html, encoding="utf-8")

    root = (out / "index.html").read_text(encoding="utf-8")
    if 'class="top-note"' in root:
        raise RuntimeError("Production root still exposes preview notice")
    if 'href="/guide.html"' not in root:
        raise RuntimeError("Production root is missing first-use Guide link")

    print(f"Static Production review built at {out}")
    return out


if __name__ == "__main__":
    main()
