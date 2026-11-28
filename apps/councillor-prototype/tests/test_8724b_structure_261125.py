# -*- coding: utf-8 -*-
"""#8724 steps 3·4 — trimmed CSS and one script.

Unused-selector criterion (written here so the check is reproducible):
a rule is unused when every comma branch has a compound whose element tag,
class, or id never appears in the built seven pages or in the four script
states (lightbox open, activity detail open, no search results, dark theme).
Attribute selectors and pseudo-classes/elements do not make a rule unused.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from css_source import read_site_css

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
STYLES = read_site_css()
# Runtime-only nodes observed in the four states above; they are not in the HTML.
RUNTIME_CLASSES = {"combined-policy-row", "ext-mark", "intro-video-title", "is-empty", "lightbox-open"}
RUNTIME_IDS = {"activityEmpty"}
RUNTIME_TAGS = {"svg", "path", "rect", "circle"}


def _used_sets(tmp_path):
    out = subprocess.run(
        [sys.executable, "scripts/build-dist", "--out", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    classes, ids, tags = set(RUNTIME_CLASSES), set(RUNTIME_IDS), set(RUNTIME_TAGS)
    for page in (tmp_path / "index.html", tmp_path / "about.html", tmp_path / "activity.html",
                 tmp_path / "policy.html", tmp_path / "media.html", tmp_path / "news.html",
                 tmp_path / "404.html"):
        html = page.read_text(encoding="utf-8")
        for group in re.findall(r'class="([^"]+)"', html):
            classes.update(group.split())
        ids.update(re.findall(r'id="([^"]+)"', html))
        tags.update(t.lower() for t in re.findall(r"<([a-zA-Z][\w-]*)", html))
    return classes, ids, tags


def _selectors():
    clean = re.sub(r"/\*.*?\*/", "", STYLES, flags=re.S)
    return re.findall(r"(?:^|\})\s*([^{}@]+)\{", clean, flags=re.M)


def test_no_unused_selector_survives(tmp_path):
    classes, ids, tags = _used_sets(tmp_path)
    unused = []
    for raw in _selectors():
        sel = raw.strip()
        branches = []
        for part in sel.split(','):
            text = re.sub(r"::?[a-zA-Z-]+(\([^)]*\))?", "", part)
            text = re.sub(r"\[[^\]]+\]", "", text)
            ok = True
            for compound in re.split(r"[\s>+~]+", text):
                if not compound or compound in ('*', ':root'):
                    continue
                match = re.match(r"([a-zA-Z][\w-]*)?", compound)
                if match and match.group(1) and match.group(1) not in tags:
                    ok = False
                if any(c not in classes for c in re.findall(r"\.([A-Za-z0-9_-]+)", compound)):
                    ok = False
                if any(i not in ids for i in re.findall(r"#([A-Za-z0-9_-]+)", compound)):
                    ok = False
            branches.append(ok)
        if not any(branches):
            unused.append(sel)
    assert not unused, f"unused CSS selectors: {unused}"


def test_home_script_is_merged_and_small():
    assert not (ROOT / "static" / "home.js").exists(), "home.js must be merged into app.js"
    assert len(APP_JS.splitlines()) <= 1000
    assert "enhanceMediaCards(homeMedia)" in APP_JS
    assert 'label: "정책자료"' not in APP_JS
    sys.path.insert(0, str(ROOT / "scripts"))
    import assemble
    assert "home.js" not in assemble.render("index.html")
    assert "home.js" not in (ROOT / "README.md").read_text(encoding="utf-8")
