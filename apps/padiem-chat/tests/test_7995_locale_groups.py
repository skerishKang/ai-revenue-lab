"""#7995 — the split locale groups keep one ko/en authority and all contracts."""
from __future__ import annotations

import re
from pathlib import Path

import locale_bundle
import pytest

from _support import locale_usage_source as sheets

STATIC = Path(__file__).resolve().parents[1] / "static"
INDEX = sheets.sheet("index.html")
BOOT = sheets.sheet("locale.js")


def test_every_group_is_loaded_before_the_bootstrap():
    positions = [INDEX.index('<script src="./%s"></script>' % name)
                 for name in locale_bundle.GROUP_NAMES]
    boot = INDEX.index('<script src="./locale.js"></script>')
    capability = INDEX.index('<script src="./attachment-capabilities.js"></script>')
    binary = INDEX.index('<script src="./document-binary.js"></script>')
    app = INDEX.index('<script src="./app.js"></script>')
    assert capability < max(positions) < boot < binary < app


def test_ko_en_parity_covers_every_group():
    ko, en = locale_bundle.keys("ko"), locale_bundle.keys("en")
    assert ko and set(ko) == set(en)
    for lang in ("ko", "en"):
        assert all(isinstance(value, str) and value for value in locale_bundle.keys(lang).values())


def test_no_key_is_declared_twice():
    for lang in ("ko", "en"):
        observed: dict[str, int] = {}
        for path in locale_bundle.GROUP_PATHS:
            for key in re.findall(r'^\s*"((?:[^"\\]|\\.)*)":',
                                  locale_bundle.group_text(path, lang), re.M):
                observed[key] = observed.get(key, 0) + 1
        assert not [key for key, count in observed.items() if count > 1], lang


def test_one_key_per_line_and_every_file_under_cap():
    for path in locale_bundle.GROUP_PATHS:
        source = sheets.source(path)
        assert len(source.splitlines()) <= 1000, path.name
        for block in (locale_bundle.group_text(path, "ko"),
                      locale_bundle.group_text(path, "en")):
            for line in block.splitlines():
                if line.strip():
                    assert len(re.findall(r'"(?:[^"\\]|\\.)*":', line)) == 1, (path.name, line)
    assert len(BOOT.splitlines()) <= 1217


def test_bootstrap_exposes_the_same_public_api():
    for symbol in ("VALID", "apply", "getCurrent", "getUrlLocale", "text",
                   "localizeExisting", "window.PadiemLocaleGroups"):
        assert symbol in BOOT
    assert "const labels = { ko: {}, en: {} };" in BOOT
    assert "Object.assign(labels.ko" in BOOT and "Object.assign(labels.en" in BOOT


def test_7990_copy_lives_in_the_pc_group():
    pc = locale_bundle.group_text(locale_bundle.GROUP_PATHS[3], "ko")
    assert '"pc-command-ready-badge": "연결됨 · 명령 준비 안 됨"' in pc
    assert '"pc-command-ready-help": "이 PC 에 Windows 로 로그인돼 있는지' in pc
    ui = sheets.sheet("pc-command-ready.js")
    assert "ctx.uiT(key)" in ui
    assert 'uiText("pc-command-ready-badge")' in ui
    # #8211: the missing row reads its own word through the same call.
    assert ('uiText(missing ? "pc-helper-missing-help" : "pc-command-ready-help")'
            in ui)
    copy_block = ui.split("var COPY = {", 1)[1].split("};", 1)[0]
    assert "badge:" not in copy_block and "help:" not in copy_block
