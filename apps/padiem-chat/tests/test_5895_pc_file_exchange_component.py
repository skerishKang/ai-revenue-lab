"""#5895: the shared PC file part, driven as the shipped script.

The Node harness loads `static/pc-file-exchange.js` itself against a minimal DOM and a
scripted fetch, so what is proved is the byte the browser will run: the dialog opens on
the owner's own folder, a folder click and a name search go back to the server, the
chosen file arrives as text or as a file the menu can keep, several PCs are asked about
instead of guessed, and a PC that takes thirty rounds of polling is still simply
working. This file keeps that contract inside the normal pytest run and pins the wiring
the harness cannot see.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
NODE_TEST = ROOT / "tests" / "pc_file_exchange_harness.js"


def test_the_shipped_component_flow_passes_under_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    completed = subprocess.run(
        [node, str(NODE_TEST), str(STATIC / "pc-file-exchange.js"), str(STATIC / "locale.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PC_FILE_EXCHANGE=PASS" in completed.stdout
    assert "FAIL" not in completed.stdout


def test_the_component_is_loaded_once_and_calls_only_the_new_routes():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "pc-file-exchange.js").read_text(encoding="utf-8")

    assert html.count('<script src="./pc-file-exchange.js" defer></script>') == 1
    assert html.count('<link rel="stylesheet" href="./pc-file-exchange.css" />') == 1
    # The part speaks only to the four new owner routes: nothing older, nothing the
    # composer owns, and no second pairing or dispatch surface.
    assert sorted({found for found in script.split('"') if found.startswith("/api/")}) == [
        "/api/pc/browse", "/api/pc/fetch", "/api/pc/find", "/api/pc/result",
    ]
    assert "EventSource" not in script and "WebSocket" not in script
    # One entry point, for any menu.
    assert "root.PadiemPcFileExchange = Object.freeze" in script
    assert script.count("function open(") == 1


def test_the_component_adds_no_deadline_no_give_up_and_no_confirmation():
    script = (STATIC / "pc-file-exchange.js").read_text(encoding="utf-8")
    for forbidden in ("confirm(", "alert(", "maxAttempts", "max_attempts", "deadline",
                      "AbortSignal.timeout", "setTimeout(fetch"):
        assert forbidden not in script, forbidden
    # The wait is the server's record: the loop ends only when the answer is ready or
    # the operation is over, and `더 보기` splits the answer without shortening it.
    assert "for (;;)" in script
    assert "state.items.slice(0, state.shown)" in script
    assert "poll_seconds" in script
    assert "pc-exchange-working" in script
    assert script.count("PAGE = 60") == 1
    # A second PC and a second folder are both choices the owner makes; neither is
    # ever guessed, and the strip that asks is styled for touch like the rest.
    css = (STATIC / "pc-file-exchange.css").read_text(encoding="utf-8")
    assert 'aria-label", copy(groupLabelKey)' in script
    for token in ("pc_link_selection_required", "pc_folder_selection_required"):
        assert token in script, token
    assert ".pc-exchange-choice" in css and "min-height: 44px" in css


def test_the_waiting_copy_exists_in_both_languages_and_names_no_technical_term():
    import re

    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    korean, english = locale.split("\n    en: {", 1)[0], locale.split("\n    en: {", 1)[1]
    pattern = re.compile(r'"(pc-exchange-[a-z-]+)": "([^"]*)"')

    def copy_of(block: str) -> dict[str, str]:
        return dict(pattern.findall(block))

    ko, en = copy_of(korean), copy_of(english)
    assert set(ko) == set(en) >= {
        "pc-exchange-import-title", "pc-exchange-choose-pc", "pc-exchange-choose-folder",
        "pc-exchange-up", "pc-exchange-search", "pc-exchange-more", "pc-exchange-close",
        "pc-exchange-open-file", "pc-exchange-working", "pc-exchange-no-pc",
        "pc-exchange-no-answer",
    }, sorted(ko)
    # An owner reading this should never meet a server word.
    for value in list(ko.values()) + list(en.values()):
        for jargon in ("dispatch", "route", "endpoint", "http", "json",
                       "디스패치", "라우트", "경로", "엔드포인트"):
            assert jargon not in value.lower(), value
    assert "{elapsed}" in ko["pc-exchange-working"] and "PC에서 작업 중" in ko["pc-exchange-working"]
    assert "{elapsed}" in en["pc-exchange-working"] and "elapsed" in en["pc-exchange-working"]
    # The waiting line is the same one #5895 puts on the composer, so a picker and a
    # chat turn never describe the same wait in two different ways.
    assert "경과" in ko["pc-exchange-working"]
