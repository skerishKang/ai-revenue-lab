from __future__ import annotations

import shutil
from pathlib import Path

from scripts import build_static_preview as preview


_TECHNICAL_PREVIEW_PREFIXES = (
    "/preview-states/",
    "/_preview_state/",
)


def _production_post_process(html: str, *, is_root: bool = False) -> str:
    """Remove QA/debug chrome from customer-facing Production review pages.

    Keep technical preview-state routes available for contract tests, while the
    canonical root and product journey render only the real Personal Edition UI.
    """

    if not is_root:
        return html

    html = html.replace(
        '<div class="preview-banner">UI Preview · Synthetic data · No persistence</div>',
        "",
    )
    html = html.replace("PERSONAL EDITION — UI PREVIEW", "Personal Edition")
    return html


def _rewrite_root(out_dir: Path) -> None:
    rendered = preview._render_template(
        "preview_index.html",
        preview_mode=True,
        _link_prefix="/preview/participant",
    )
    (out_dir / "index.html").write_text(
        _production_post_process(rendered, is_root=True), encoding="utf-8"
    )


def _write_guide(out_dir: Path) -> None:
    guide_dir = out_dir / "guide"
    guide_dir.mkdir(parents=True, exist_ok=True)
    rendered = preview._render_template(
        "guide.html",
        preview_mode=True,
        _link_prefix="/preview/participant",
    )
    (guide_dir / "index.html").write_text(rendered, encoding="utf-8")


def _clean_static_navigation(out_dir: Path) -> None:
    """Ensure no owner-facing route points back to the technical state index."""

    for path in out_dir.rglob("*.html"):
        rel = "/" + str(path.relative_to(out_dir)).replace("\\", "/")
        if rel.startswith(_TECHNICAL_PREVIEW_PREFIXES):
            continue
        html = path.read_text(encoding="utf-8")
        html = html.replace('href="/preview-states/"', 'href="/"')
        path.write_text(html, encoding="utf-8")


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
        'data-art-direction="b1-image-led-v5"',
        "흩어진 기록이",
        "v3-assembly-stage",
        "/guide/",
    )
    for marker in required_root:
        if marker not in root:
            raise RuntimeError(f"missing B1 V5 Production marker: {marker}")

    # These are stable user-journey markers rather than copy from a superseded
    # art-direction pass. V5 intentionally reduced the Guide to four actions.
    required_guide = (
        "Guide · 30 seconds",
        "기록 하나가",
        "Write · 기록",
        "Review · 사람의 확인",
        "Read · 완성본",
        "Recut · 다음 호",
    )
    for marker in required_guide:
        if marker not in guide:
            raise RuntimeError(f"missing B1 V5 guide marker: {marker}")

    forbidden = (
        "UI Preview · Synthetic data · No persistence",
        '<div class="preview-banner">',
        "PERSONAL EDITION — UI PREVIEW",
    )
    for marker in forbidden:
        if marker in root or marker in writing or marker in library or marker in guide:
            raise RuntimeError(f"owner-facing QA chrome leaked into Production: {marker}")

    if "v3-write" not in writing:
        raise RuntimeError("Personal Edition Writing surface was not generated")
    if "v3-workflow" not in library:
        raise RuntimeError("Personal Edition Private Library workflow surface was not generated")
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

    print(f"Production static preview built at {out_dir}")


if __name__ == "__main__":
    main()
