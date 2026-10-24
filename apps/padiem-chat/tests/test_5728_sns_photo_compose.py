"""#5728 — the SNS photo composition contract.

The Node harness executes the REAL util-menu.js against a fake DOM:

1. the photo-URL text field is gone; a multi-select photo picker exists;
2. picked photos render as thumbnails, can be re-ordered and removed;
3. the generation prompt carries the photo roster (no URL line);
4. the blog preview interleaves photos between paragraphs per position,
   facebook/instagram previews keep photos as separate post media;
5. platform switching preserves the draft text and the photo set;
6. the preview states it is a draft composition aid, never publishing.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

CHAT_ROOT = Path(__file__).resolve().parents[1]
UTIL_MENU = CHAT_ROOT / "static" / "util-menu.js"
HARNESS = CHAT_ROOT / "tests" / "_5728_harness.js"

def test_the_photo_composition_contract() -> None:
    """The checked-in Node harness executes the REAL util-menu.js twice
    against a shared fake project store: session A composes, generates and
    saves (originals + roster + text draft, then removal syncs a deletion);
    session B re-enters and the composition restores itself in order with
    the blog insertion position intact."""
    result = subprocess.run(
        ["node", str(HARNESS), str(UTIL_MENU)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        pytest.fail("harness produced no verdict: " + result.stdout + " / " + result.stderr)
    assert payload.get("ok") is True, payload
    # The re-entry verdict carries the persistence evidence explicitly.
    assert payload.get("photos") == 1
    assert payload.get("restoredPosition") == "0"
    assert "SNS 사진 구성.json" in (payload.get("files") or [])


def test_the_url_field_is_gone_from_the_source() -> None:
    source = UTIL_MENU.read_text(encoding="utf-8")
    assert '"사진 URL"' not in source
    assert "utilSnsPhotoAdd" in source
    assert "utilSnsPreview" in source
    assert "util-sns-media-grid" in source
