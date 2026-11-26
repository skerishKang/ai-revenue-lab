# -*- coding: utf-8 -*-
"""#7575 batch 3 — versioned dynamic loaders and result-box growth."""
from __future__ import annotations

from pathlib import Path

from _council_module import run

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "council-app.js").read_text(encoding="utf-8")


def test_all_dynamic_loaders_attach_a_version_to_the_injected_node():
    seen = run("asset_loader_versions")
    out, versions = seen["out"], seen["map"]
    expected = {
        "document": "document-export.js",
        "photo": "photo-resize.js",
        "pc": "pc-file-exchange.js",
        "project": "tus-upload.js",
    }
    for loader, asset in expected.items():
        nodes = out[loader]
        assert nodes, (loader, nodes)
        urls = [n["raw"] for n in nodes]
        assert any(asset + "?v=" + versions[asset] in u for u in urls), (loader, urls)

    # The stylesheet loader is part of the same fan-out.
    css = [n["raw"] for n in out["pc"] if n["tag"] == "LINK"]
    assert any("pc-file-exchange.css?v=" + versions["pc-file-exchange.css"] in u for u in css), css
    # project-file-upload.js follows tus-upload.js in the same chain.
    project = [n["raw"] for n in out["project"]]
    assert any("project-file-upload.js?v=" + versions["project-file-upload.js"] in u for u in project), project


def test_versioned_asset_accepts_absolute_urls_and_replaces_an_old_version():
    seen = run("asset_loader_versions")
    probe = seen["probe"]
    assert probe["relative"].endswith("document-export.js?v=deadbee5"), probe
    assert probe["absolute"].endswith("/apps/council/static/document-export.js?v=deadbee5"), probe
    assert probe["absoluteWithQuery"].endswith("photo-resize.js?v=f00d1234"), probe


def test_loaders_version_the_relative_string_before_assignment():
    # Reading a .src back is absolute in a browser; the version must be applied
    # to the literal before it reaches the DOM property.
    assert "versionedAsset(script.src)" not in JS
    assert "versionedAsset(css.href)" not in JS
    for asset in ("document-export.js", "photo-resize.js", "pc-file-exchange.css",
                  "pc-file-exchange.js"):
        assert 'versionedAsset("./static/%s")' % asset in JS, asset
    assert "script.src = versionedAsset(src);" in JS
