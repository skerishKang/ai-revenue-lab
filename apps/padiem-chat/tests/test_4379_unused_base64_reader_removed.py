"""#4379: the unused Base64 reader helper is gone from the Chat composer.

The composer reads a document attachment as text. The Base64 data-URL reader
next to it had no caller: one declaration and no reference anywhere in the
repository, so it was a second, unused path into the browser's Base64
encoder. The helper and the locale key that only it used are removed, and
this guard fails as soon as either comes back under any name.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_the_unused_base64_reader_helper_is_gone() -> None:
    app = read("app.js")
    assert "readAsDataUrl" not in app
    assert "readAsDataURL" not in app
    # The FileReader is still used for the text path, so the browser API itself
    # stays; only the unused Base64 branch is gone.
    assert app.count("new FileReader()") == 1
    assert "reader.readAsText(file, \"UTF-8\");" in app


def test_the_text_reader_is_still_the_one_the_composer_calls() -> None:
    app = read("app.js")
    assert "function readAsText(file)" in app
    assert "const raw = await readAsText(file);" in app


def test_the_locale_key_only_the_removed_helper_used_is_gone() -> None:
    locale = read("locale.js")
    app = read("app.js")
    assert "image-read-failed" not in app
    assert "image-read-failed" not in locale
    # The photograph wording that other attachment paths still use stays.
    for key in ("image-format-invalid", "image-data-empty", "attachment-photo"):
        assert f'"{key}"' in locale, key


def test_the_ko_and_en_catalogues_keep_exact_key_parity() -> None:
    source = read("locale.js")

    def keys(start: str, end: str) -> set[str]:
        left = source.index(start)
        right = source.index(end, left + len(start))
        return set(re.findall(r'"([^"]+)":', source[left:right]))

    ko = keys("ko: {", "en: {")
    en = keys("en: {", "\n    }")
    assert ko == en
    assert len(ko) >= 294


def test_no_runtime_translation_call_points_at_a_removed_key() -> None:
    locale = read("locale.js")
    app = read("app.js")

    left = locale.index("ko: {")
    right = locale.index("en: {", left + len("ko: {"))
    keys = set(re.findall(r'"([^"]+)":', locale[left:right]))
    runtime_keys = set(re.findall(r'\b(?:uiT|clawT)\("([^"]+)"', app))
    assert runtime_keys
    assert runtime_keys <= keys
