"""#5728 — big photos are shrunk in the browser, and a failed photo upload says why.

Two slice behaviours the composition tests do not cover:

1. **Large photo.** The Worker cannot decode a multi-megabyte image inside the
   free plan's per-request CPU budget (static/photo-resize.js states the whole
   reason), so the resize target is computed in the browser and the uploaded
   bytes are the resized ones. It is not an upload cap: nothing is refused.
2. **Failed upload.** The old path raised a browser alert with a bare name list.
   The screen now states the same Korean sentence the generation path uses for
   that HTTP status (GEN_ERROR_COPY) and offers [다시 시도] for the same photos.

The resize maths runs in Node against the real module; the wiring is pinned on
the real util-menu.js source, because a canvas decode is not reproducible in the
Node harness.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

CHAT_ROOT = Path(__file__).resolve().parents[1]
STATIC = CHAT_ROOT / "static"
UTIL_MENU = STATIC / "util-menu.js"
PHOTO_RESIZE = STATIC / "photo-resize.js"

RESIZE_PROBE = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const sandbox = { window: {}, Math: Math, Number: Number, Object: Object };
sandbox.window.Image = undefined;
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const r = sandbox.window.PadiemPhotoResize;
const out = {
  big: r.targetSize(4000, 3000),
  tall: r.targetSize(1000, 4000),
  small: r.targetSize(1080, 1350),
  exact: r.targetSize(1920, 1080),
  empty: r.targetSize(0, 0, 1920),
  shrinksBig: r.shouldResize(4000, 3000),
  shrinksTall: r.shouldResize(1000, 4000),
  keepsSmall: r.shouldResize(1080, 1350),
  keepsExact: r.shouldResize(1920, 1080),
  maxEdge: r.MAX_EDGE,
};
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def resize_math(tmp_path_factory) -> dict:
    # Written under pytest's tmp dir, never into the repository tree.
    probe = tmp_path_factory.mktemp("5728-resize") / "probe.js"
    probe.write_text(RESIZE_PROBE, encoding="utf-8")
    result = subprocess.run(
        ["node", str(probe), str(PHOTO_RESIZE)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_big_photo_is_scaled_down_to_the_display_edge(resize_math: dict) -> None:
    """4000x3000 becomes 1920x1440 — the aspect ratio is preserved exactly."""

    assert resize_math["maxEdge"] == 1920
    assert resize_math["big"] == {"width": 1920, "height": 1440}
    assert resize_math["tall"] == {"width": 480, "height": 1920}
    assert resize_math["shrinksBig"] is True
    assert resize_math["shrinksTall"] is True


def test_a_photo_that_already_fits_is_uploaded_without_re_encoding(resize_math: dict) -> None:
    """Re-encoding a small photo would only cost quality, so it is skipped."""

    assert resize_math["small"] == {"width": 1080, "height": 1350}
    assert resize_math["exact"] == {"width": 1920, "height": 1080}
    assert resize_math["keepsSmall"] is False
    assert resize_math["keepsExact"] is False
    assert resize_math["empty"] == {"width": 0, "height": 0}


def test_the_upload_sends_the_resized_bytes_not_the_original() -> None:
    source = UTIL_MENU.read_text(encoding="utf-8")
    # The resizer is consulted before the upload and its bytes are what is sent.
    assert "shrink.resizeDataUrl(original, shrink.MAX_EDGE, type)" in source
    assert "const prepared = await preparePhoto(file);" in source
    assert "uploadProjectImage(\n            currentPid, prepared.blob, file.name, prepared.type," in source
    # No upload refusal: the resize changes the bytes, never the decision.
    assert "prepared.blob" in source and "if (!stored.ok)" in source
    # It is loaded on first photo, so a page that adds no photo loads no script.
    assert 'script.src = "./photo-resize.js";' in source
    # And a browser that cannot decode keeps the original bytes instead of failing.
    assert "typeof window.Image === \"function\"" in source


def test_the_worker_reason_is_written_where_the_shrinking_happens() -> None:
    """The platform limit behind the resize is a comment, not a magic number."""

    module = PHOTO_RESIZE.read_text(encoding="utf-8")
    assert "CPU 10ms" in module
    assert "128MB" in module
    assert "업로드 상한이 아니다" in module


def test_a_failed_photo_upload_says_why_and_offers_retry() -> None:
    source = UTIL_MENU.read_text(encoding="utf-8")

    # The failure keeps its HTTP status, including a dead network (status 0).
    assert "status: res.status" in source
    assert "{ ok: false, file: null, status: 0 }" in source
    # And the screen turns that status into the existing Korean copy.
    assert "GEN_ERROR_COPY[status]" in source
    assert "GEN_OFFLINE_COPY" in source
    assert "사진 저장 실패: " in source
    # The retry control exists, is labelled by the shared constant, and re-runs
    # the same photo set.
    assert 'photoRetry.id = "utilSnsPhotoRetry"' in source
    assert "GEN_RETRY_LABEL" in source
    assert "const retry = failedPhotos.map((f) => f.file);" in source
    # The bare alert is gone.
    assert 'alert("사진 저장 실패' not in source


def test_every_mapped_status_speaks_korean() -> None:
    source = UTIL_MENU.read_text(encoding="utf-8")
    block = re.search(r"const GEN_ERROR_COPY = \{(.*?)\n  \};", source, re.S)
    assert block is not None, "GEN_ERROR_COPY moved"
    entries = re.findall(r'(\d+):\s*"([^"]+)"', block.group(1))
    assert len(entries) >= 6, entries
    for status, sentence in entries:
        assert re.search(r"[가-힣]", sentence), (status, sentence)
