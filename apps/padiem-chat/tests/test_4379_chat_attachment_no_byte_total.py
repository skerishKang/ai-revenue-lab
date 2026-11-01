"""#4379 3rd slice: the Chat composer carries no PADIEM attachment byte total.

A finite product-side maximum is neither a platform limit nor a provider limit, so
the former 1 GiB image and binary-document ceiling is removed rather than enlarged.
The controls that are real stay enforced: the shape rules, the decompression-bomb
bounds, the incremental streaming transport and the authorization path. Every guard
below fails as soon as a byte total comes back under any number.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
APP = ROOT / "app"
STATIC = ROOT / "static"


def test_the_intake_compares_no_byte_total() -> None:
    for name in ("attachments.py", "binary_documents.py"):
        source = (APP / name).read_text(encoding="utf-8")
        assert not re.search(r"> MAX_(?:IMAGE|BINARY_DOCUMENT)_BYTES", source), name
        assert not re.search(r"MAX_(?:IMAGE|BINARY_DOCUMENT)_BYTES \+ 2", source), name
        assert "1 GiB" not in source, name


def test_the_browser_capability_and_gates_carry_no_byte_total() -> None:
    capabilities = (STATIC / "attachment-capabilities.js").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    binary_js = (STATIC / "document-binary.js").read_text(encoding="utf-8")
    assert "limits.imageBytes" not in app_js
    assert "limits.binaryBytes" not in binary_js
    assert "MAX_BINARY_BYTES" not in binary_js
    for source in (capabilities, app_js, binary_js):
        assert "1 GiB" not in source
        assert "1024 * 1024 * 1024" not in source
    # #5734 stage 2: a text document carries no product-side total either, and
    # the browser no longer reads one.
    for retired in ("textBytes", "textChars", "96 * 1024", "40000"):
        assert retired not in capabilities
    for retired in ("limits.textBytes", "limits.textChars", "MAX_DOCUMENT_BYTES", "MAX_DOCUMENT_CHARS"):
        assert retired not in app_js


def test_the_real_image_and_document_controls_are_untouched() -> None:
    # Each marker is pinned with its delimiter so a rename of the guard itself
    # cannot keep satisfying a bare substring.
    attachments = (APP / "attachments.py").read_text(encoding="utf-8")
    binary = (APP / "binary_documents.py").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    binary_js = (STATIC / "document-binary.js").read_text(encoding="utf-8")
    core = (
        REPO / "packages/padiem-ai-core/padiem_ai_core/document_normalization.py"
    ).read_text(encoding="utf-8")
    # #4379 removes byte totals, not the empty-payload rules that travelled on the
    # same source line as a total, so each rejection is pinned where it now stands.
    assert 'if (file.size < 1) throw new Error(uiT("image-data-empty"));' in app_js
    assert "if (!file || file.size < 1) throw new Error(" in binary_js
    for marker, minimum in (
        ("not in ALLOWED_IMAGE_MEDIA_TYPES:", 2),
        ("not _matches_magic(media_type, data)", 1),
        ("not _matches_magic(media_type, decoded)", 1),
        ("if len(raw) > limit:", 1),
    ):
        assert attachments.count(marker) >= minimum, marker
    for marker in (
        "base64.b64decode(payload, validate=True)",
        "validate_document_identity(",
        "parse_binary_document_via_authority(",
    ):
        assert binary.count(marker) == 1, marker
    # #5734: the size-shaped refusals are gone, so the markers pin what Core
    # still refuses on structural grounds — the inflation ratio, unsafe paths,
    # encryption and DTDs. A byte total may not come back as a hidden cap.
    for marker in (
        '"ooxml_total_inflation"',
        '"ooxml_unsafe_path"',
        '"ooxml_encrypted"',
        '"ooxml_dtd_rejected"',
    ):
        assert core.count(marker) >= 1, marker


def test_the_composer_still_streams_the_file_behind_a_bounded_metadata_frame() -> None:
    transport = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
    assert "new Blob([prefix, header, binary]" in transport
    assert "header.byteLength > 65536" in transport


def test_the_readme_names_the_platform_and_provider_as_the_ceilings() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "no PADIEM byte total" in readme
    assert "platform request limit and the selected Provider" in readme
    assert "decompression bomb" in readme
