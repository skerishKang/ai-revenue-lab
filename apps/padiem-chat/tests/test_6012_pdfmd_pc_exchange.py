"""#6012: the PDF·MD menu opens the shared "내 PC에서 가져오기·저장하기" part.

The conversion itself is untouched: a file picked on the PC comes back as the
file lane's id, its bytes are read once through ``/api/pc/file``, and the SAME
``uploadFile`` the browser path uses carries them into the existing conversion.
The result is offered back through the same part, starting in the folder the
original came from and named after it with the new extension.

#5710's pause is deliberately still in place here: this file pins that both
flags are still closed, that the pick button therefore says 준비 중 rather than
pretending to work, and that the two halves that do not depend on the pause —
saving an existing result and telling an unlinked owner how to link — are live.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDFMD_JS = ROOT / "static/util-pdfmd.js"
EXCHANGE_JS = ROOT / "static/pc-file-exchange.js"
CONVERT_ROUTES = ROOT / "app/document_convert_routes.py"


def _js() -> str:
    return PDFMD_JS.read_text(encoding="utf-8")


def test_a_picked_pc_file_is_carried_into_the_conversion_request() -> None:
    js = _js()
    # The pick is the shared part, opened in its import half, loaded on first use.
    assert 'loadPcExchange()' in js
    assert 'script.src = "./pc-file-exchange.js"' in js
    assert 'mode: "import"' in js
    assert "onSelect" in js
    # The file lane's id is what names the bytes, and it is read once.
    assert '"/api/pc/file?dispatch_id=" + encodeURIComponent(picked.fileId)' in js
    # The bytes then travel the existing upload, so one conversion and one ledger
    # serve both entry points.
    assert "if (await uploadFile(file)) pcOrigin.set(name, picked.folder || \".\");" in js
    assert '"/api/document-conversions/" + currentJobId + "/files"' in js
    assert '"X-Padiem-Filename": encodeURIComponent(file.name)' in js
    # Nothing here invents a second upload endpoint or a size/count ceiling.
    assert "/api/document-conversions/" in js
    assert "max_bytes" not in js and "max_files" not in js
    # 5710's pause is not lifted by this change: the button says so instead.
    assert "const PDFMD_NEW_WORK_DISABLED = true;" in js
    assert "PDFMD_NEW_WORK_DISABLED = True" in CONVERT_ROUTES.read_text(encoding="utf-8")


def test_saving_a_result_asks_for_the_original_folder_and_a_new_extension() -> None:
    js = _js()
    exchange = EXCHANGE_JS.read_text(encoding="utf-8")
    # The result goes back through the same part, in its save half.
    assert 'mode: "save"' in js
    assert '"/api/document-conversions/items/" + item.id + "/markdown?display=inline"' in js
    # The default name is the original's name with the new extension.
    assert 'function resultName(name) {' in js
    assert '(name.replace(/\\.[^.]+$/, "") || "document") + ".md"' in js
    assert "fileName: resultName(item.name)" in js
    # The default folder is the one the original was found in.
    assert "startFolder: pcOrigin.get(item.name) || \".\"" in js
    # The part honours that folder and reports the folder it picked from.
    assert "settings.startFolder" in exchange
    assert "void start(BROWSE, { path: state.path }, listed);" in exchange
    assert "folder: state.path," in exchange
    # The backup is the part's own write lane (#5573), not something this menu re-does.
    assert "SAVE = \"/api/pc/save\"" in exchange


def test_a_missing_pc_is_explained_with_a_connect_link() -> None:
    js = _js()
    assert '"PC를 연결하면 내 PC 문서를 바로 변환할 수 있습니다."' in js
    assert '"이 PC 연결"' in js
    assert 'pcNote.id = "pdfmdPcNote";' in js
    assert "pcNote.hidden = true;" in js
    # Only a definite "no PC" shows it; a failed check stays quiet rather than
    # telling an owner with a PC that they have none.
    assert "void pcLinked().then((linked) => {" in js
    assert "if (linked === false) pcNote.hidden = false;" in js
    # The link opens the existing Connectors card instead of a second pairing screen.
    assert 'document.getElementById("connectorsNavButton")' in js
    assert 'document.getElementById("connectorComputerCard")' in js
    # The existing browser upload is untouched and stays available.
    assert 'fileInput.accept = ".pdf,.zip,application/pdf,application/zip"' in js
    assert "const drop = el(\"div\", \"pdfmd-drop\");" in js
