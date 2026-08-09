from __future__ import annotations

import subprocess
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = APP_DIR / "dist-preview"


def test_owner_production_build_is_v3_without_preview_chrome() -> None:
    subprocess.run(
        [sys.executable, "-m", "scripts.build_static_production"],
        cwd=APP_DIR,
        check=True,
        capture_output=True,
        text=True,
    )

    root = (OUT_DIR / "index.html").read_text(encoding="utf-8")
    library = (
        OUT_DIR / "preview" / "participant" / "empty" / "index.html"
    ).read_text(encoding="utf-8")
    writing = (
        OUT_DIR / "preview" / "participant" / "input" / "index.html"
    ).read_text(encoding="utf-8")
    qa_index = (OUT_DIR / "preview-states" / "index.html").read_text(
        encoding="utf-8"
    )

    assert 'data-ui-version="b1-personal-edition-v3-454"' in root
    assert 'data-static-production-review="b1-v3-454"' in root
    assert "흩어진 기록이" in root
    assert 'href="/preview/participant/empty/"' in root
    assert "v3-workflow" in library
    assert "v3-write" in writing

    for html in (root, library, writing):
        assert "UI Preview · Synthetic data · No persistence" not in html
        assert '<div class="preview-banner">' not in html
        assert "PERSONAL EDITION — UI PREVIEW" not in html

    # Technical QA remains isolated at the explicit state index.
    assert "Personal Edition UI Preview" in qa_index


def test_private_access_uses_v3_system_not_v2_split_photo() -> None:
    template = (APP_DIR / "templates" / "token_entry.html").read_text(encoding="utf-8")
    assert 'class="v3-workflow"' in template
    assert "Private invitation · Entry" in template
    assert "access-invitation.webp" not in template
    assert "access-workflow-step" not in template
