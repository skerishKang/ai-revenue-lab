"""Build the owner-facing static Production review for Personal Edition.

This intentionally reuses the deterministic synthetic fixtures from
``build_static_preview`` while keeping QA chrome out of the customer-facing
surface. The QA index remains available at ``/preview-states/``.

The output directory is the existing ``dist-preview`` directory because the
Cloudflare Pages project is already configured to publish that directory.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from scripts import build_static_preview as preview


_PRODUCTION_GUARD_CSS = """
<style id="pe-static-production-guard">
form button[type="submit"], form input[type="submit"] {
  opacity: .52;
  pointer-events: none;
}
.preview-journey-nav {
  margin-top: 1.5rem;
}
.preview-journey-nav .preview-journey-hint {
  display: none;
}
</style>
"""

_CLEAN_PARTICIPANT_REDIRECT = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="robots" content="noindex,nofollow">
<meta http-equiv="refresh" content="0;url=/preview/participant/empty/">
<title>Personal Edition</title></head>
<body><p><a href="/preview/participant/empty/">Private Library로 이동</a></p></body></html>
"""

_CLEAN_EDITIONS_REDIRECT = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="robots" content="noindex,nofollow">
<meta http-equiv="refresh" content="0;url=/preview/participant/published/">
<title>Personal Edition</title></head>
<body><p><a href="/preview/participant/published/">최신 에디션으로 이동</a></p></body></html>
"""


def _production_post_process(html: str) -> str:
    """Apply static safety controls without injecting Preview/QA chrome."""
    if '<meta name="robots"' not in html:
        html = html.replace(
            '<meta name="viewport"',
            '<meta name="robots" content="noindex,nofollow">\n<meta name="viewport"',
            1,
        )
    html = html.replace("</head>", f"{_PRODUCTION_GUARD_CSS}\n</head>", 1)
    return html


def _rewrite_root(out_dir: Path) -> None:
    """Promote the V3 intro to / and preserve the technical state index."""
    qa_dir = out_dir / "preview-states"
    qa_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out_dir / "index.html", qa_dir / "index.html")

    intro_path = out_dir / "preview" / "intro" / "index.html"
    intro = intro_path.read_text(encoding="utf-8")
    intro = intro.replace(
        'href="/preview/participant/access/"',
        'href="/preview/participant/empty/"',
        1,
    )
    intro = intro.replace(
        '<body ',
        '<body data-static-production-review="b1-v3-454" ',
        1,
    )
    (out_dir / "index.html").write_text(intro, encoding="utf-8")


def _write_guide(out_dir: Path) -> None:
    """Render the owner-facing 30-second onboarding guide into Production."""
    env = preview._build_jinja_env()
    edition = preview.make_edition(
        publication_state="published", generation_status="published"
    )
    html = preview._render(
        env,
        "guide.html",
        {"edition": edition},
        "/guide/",
    )
    html = _production_post_process(html)
    guide_dir = out_dir / "guide"
    guide_dir.mkdir(parents=True, exist_ok=True)
    (guide_dir / "index.html").write_text(html, encoding="utf-8")


def _clean_static_navigation(out_dir: Path) -> None:
    participant = out_dir / "preview" / "participant"
    participant.mkdir(parents=True, exist_ok=True)
    (participant / "index.html").write_text(
        _CLEAN_PARTICIPANT_REDIRECT, encoding="utf-8"
    )
    editions = participant / "editions"
    editions.mkdir(parents=True, exist_ok=True)
    (editions / "index.html").write_text(
        _CLEAN_EDITIONS_REDIRECT, encoding="utf-8"
    )


def _assert_owner_surface(out_dir: Path) -> None:
    root = (out_dir / "index.html").read_text(encoding="utf-8")
    writing = (out_dir / "preview" / "participant" / "input" / "index.html").read_text(
        encoding="utf-8"
    )
    library = (out_dir / "preview" / "participant" / "empty" / "index.html").read_text(
        encoding="utf-8"
    )
    guide = (out_dir / "guide" / "index.html").read_text(encoding="utf-8")

    required_root = (
        "b1-personal-edition-v3-454",
        "흩어진 기록이",
        "v3-assembly-stage",
        "/guide/",
    )
    for marker in required_root:
        if marker not in root:
            raise RuntimeError(f"missing B1 V3 Production marker: {marker}")

    required_guide = (
        "Guide · 30 seconds",
        "Personal Edition은",
        "Gather · 시작",
        "Read & Recut",
    )
    for marker in required_guide:
        if marker not in guide:
            raise RuntimeError(f"missing B1 guide marker: {marker}")

    forbidden = (
        "UI Preview · Synthetic data · No persistence",
        '<div class="preview-banner">',
        "PERSONAL EDITION — UI PREVIEW",
    )
    for marker in forbidden:
        if marker in root or marker in writing or marker in library or marker in guide:
            raise RuntimeError(f"owner-facing QA chrome leaked into Production: {marker}")

    if "v3-write" not in writing:
        raise RuntimeError("V3 Writing surface was not generated")
    if "v3-workflow" not in library:
        raise RuntimeError("V3 Private Library workflow surface was not generated")
    if not (out_dir / "preview-states" / "index.html").is_file():
        raise RuntimeError("technical preview-state index was not preserved")


def main() -> None:
    preview._post_process = _production_post_process
    preview.main()

    out_dir = Path(preview._OUTPUT_DIR)
    _rewrite_root(out_dir)
    _write_guide(out_dir)
    _clean_static_navigation(out_dir)
    _assert_owner_surface(out_dir)
    print(f"Static Production review built at {out_dir}")


if __name__ == "__main__":
    main()
