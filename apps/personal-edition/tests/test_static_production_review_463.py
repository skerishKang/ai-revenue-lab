from __future__ import annotations

import subprocess
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = APP_DIR / "dist-preview"


def test_owner_production_build_is_v7_without_preview_chrome() -> None:
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
    state_index = (OUT_DIR / "preview-states" / "index.html").read_text(
        encoding="utf-8"
    )

    assert 'data-ui-version="b1-personal-edition-v7-collectible-glass"' in root
    # V6 remains the compatibility selector for historical participant CSS, while
    # the V7 design-system marker is the current visual authority.
    assert 'data-art-direction="b1-living-index-v6"' in root
    assert 'data-design-system="b1-collectible-glass-v7"' in root
    assert 'data-owner-ui-approved="false"' in root
    assert 'data-static-production-review="b1-v7-collectible-glass"' in root
    assert "/static/ui-v7-collectible-glass.css?v=b1-collectible-glass-v7-20260814" in root
    assert "/static/ui-v7-collectible-glass-authority.css?v=b1-collectible-glass-v7-authority-20260814" in root
    assert "/static/ui-v7-collectible-glass-polish.css?v=b1-collectible-glass-v7-polish-20260814" in root
    assert "흩어진 기록이" in root
    assert "v7-photo-cluster" in root
    assert 'href="/preview/participant/empty/"' in root
    assert "v3-workflow" in library
    assert "v3-write" in writing

    for html in (root, library, writing):
        assert "UI Preview · Synthetic data · No persistence" not in html
        assert '<div class="preview-banner">' not in html
        assert "PERSONAL EDITION — UI PREVIEW" not in html

    # A separately addressable technical state surface remains available without
    # forcing QA chrome back into the customer-facing Production flow.
    assert 'data-owner-review-root="true"' in state_index


def test_private_access_keeps_visually_active_contract_and_inert_legacy_evidence() -> None:
    template = (APP_DIR / "templates" / "token_entry.html").read_text(encoding="utf-8")
    assert 'class="v3-workflow"' in template
    assert "Private invitation · Entry" in template
    assert '<template data-legacy-access-contract>' in template
    legacy = template.split('<template data-legacy-access-contract>', 1)[1].split(
        "</template>", 1
    )[0]
    assert "access-invitation.webp" in legacy
    assert "access-workflow-step" in legacy
    visible = template.split("</template>", 1)[1]
    assert "access-invitation.webp" not in visible
    assert "access-workflow-step" not in visible
