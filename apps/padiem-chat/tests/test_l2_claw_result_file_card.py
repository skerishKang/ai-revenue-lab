"""CLAW2 / L2 — result file card: file type + truthful download-only state.

Scope (CLAW2, independent of CLAW1 file reuse and of the CENTRAL CTO
SSE/history server work): the Claw run-history result card is the surface a
user sees after a job completes. Before this change it rendered only the raw
filename and one generic download button, so:

- an XLSX, a PDF and a DOCX looked identical apart from the extension in the
  name, and
- a file with no verified preview said nothing about it, so the single
  download action read as a preview affordance.

Both are fixed from the SERVER-VERIFIED ``media_type`` the owner-scoped
``GET /api/claw/runs`` projection already carries (``app/history.py``
``_run_history_public``). No filename extension is used to invent a type, no
server file is changed, and no second document action is created.

Static string assertions alone do not prove behavior, so this file also runs a
Node harness that executes the REAL ``renderClawRunCard`` source with a minimal
DOM shim. The harness proves actual behavior:

- CARD_KIND_FROM_SERVER_MEDIA_TYPE=PASS
- CARD_KIND_NEVER_INVENTED=PASS
- CARD_DOWNLOAD_ONLY_STATED_WHEN_NO_PREVIEW=PASS
- CARD_PDF_PREVIEW_KEEPS_ITS_OWN_STATE=PASS
- CARD_ONE_DOCUMENT_ACTION=PASS
- CARD_ROW_SHAPE_UNCHANGED=PASS
- CARD_NO_AUTO_DOWNLOAD=PASS
- CARD_FILENAME_STAYS_PLAIN_TEXT=PASS
- CARD_KIND_ACCESSIBLE_NAME=PASS
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
LOCALE_JS = ROOT / "static/locale.js"
WORKSPACE_CSS = ROOT / "static/claw-workspace.css"

KIND_KEY = "claw-runs-kind-aria"
DOWNLOAD_ONLY_KEY = "claw-runs-download-only"

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF = "application/pdf"


def _app() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _card_fn() -> str:
    """The whole real renderer, including the closed kind map it owns."""
    app = _app()
    start = app.index("  function renderClawRunCard(run) {")
    end = app.index("\n  // Unguarded fetch:", start)
    return app[start:end]


def _card_block() -> str:
    """The artifact row only, so the one-button guard still sees one button."""
    app = _app()
    marker = app.index('artifactRow.className = "claw-run-card-artifact";')
    end = app.index("function fetchClawRunHistory", marker)
    return app[marker:end]


# ── static contracts ───────────────────────────────────────────────────────


def test_kind_is_derived_only_from_the_server_verified_media_type() -> None:
    fn = _card_fn()
    block = _card_block()
    # The chip reads artifact.media_type through the closed map, never the name.
    assert "artifactKindOf(artifact.media_type)" in block
    assert "artifactKindMap" in fn
    # A filename is never used to classify the file.
    assert not re.search(r"artifactKindOf\(\s*artifact\.filename", fn)
    assert not re.search(r"\.endsWith\(\s*[\"']\.", fn)
    # An unrecognised or absent media type yields no chip, never a guess.
    assert 'artifactKindMap[mediaType.trim().toLowerCase()] || ""' in fn
    assert 'typeof mediaType === "string"' in fn


def test_kind_map_is_closed_and_covers_the_shipped_formats() -> None:
    fn = _card_fn()
    for media_type, label in (
        (XLSX, "XLSX"),
        (DOCX, "DOCX"),
        (PDF, "PDF"),
        ("text/csv", "CSV"),
    ):
        assert f'"{media_type}": "{label}"' in fn, media_type



def test_card_still_has_exactly_one_document_action() -> None:
    block = _card_block()
    # Reused B54 guard: the card never grows a second button or a second owner.
    assert block.count('createElement("button")') == 1
    assert "claw-run-card-download" in block
    assert block.count("downloadClawArtifact(artifact.document_id") == 1
    assert "validHistoricalArtifact?.(artifact)" in block
    assert "viewer?.setHistorical?.(artifact)" in block
    for forbidden in ("fetch(", "/api/", "window.open(", "innerHTML", "POST", "retry("):
        assert forbidden not in block, forbidden
    app = _app()
    assert app.count("/api/claw/manual-intake/artifact/") == 1
    assert app.count("function downloadClawArtifact(") == 1


def test_download_only_note_is_stated_only_when_no_verified_preview_exists() -> None:
    block = _card_block()
    assert "const previewable = Boolean(window.PadiemClawPdfPreview?.validHistoricalArtifact?.(artifact));" in block
    assert "if (!previewable) {" in block
    assert "claw-run-card-download-only" in block
    assert 'clawT("claw-runs-download-only")' in block
    # The note is a non-interactive note, not a control.
    note_block = block.split("if (!previewable) {", 1)[1].split("}", 1)[0]
    assert 'setAttribute("role", "note")' in note_block
    assert "createElement(\"button\")" not in note_block


def test_new_runtime_copy_is_locale_owned_in_both_languages() -> None:
    app = _app()
    locale = LOCALE_JS.read_text(encoding="utf-8")
    assert f'clawT("{KIND_KEY}", {{ kind: artifactKind }})' in app
    assert f'clawT("{DOWNLOAD_ONLY_KEY}")' in app
    ko, en = locale.split("en: {", 1)
    for key in (KIND_KEY, DOWNLOAD_ONLY_KEY):
        assert f'"{key}"' in ko, key
        assert f'"{key}"' in en, key
    # English fallback copy exists for the non-locale path.
    assert f'"{KIND_KEY}": "File type {{kind}}"' in app
    assert f'"{DOWNLOAD_ONLY_KEY}":' in app


def test_app_runtime_copy_stays_free_of_hardcoded_korean() -> None:
    block = _card_block()
    for line_no, line in enumerate(block.splitlines(), start=1):
        assert not any("\uac00" <= ch <= "\ud7a3" for ch in line), f"hardcoded Korean: {line.strip()}"


def test_card_styles_reuse_shared_theme_tokens() -> None:
    css = WORKSPACE_CSS.read_text(encoding="utf-8")
    for selector in (".claw-run-card-file", ".claw-run-card-kind", ".claw-run-card-download-only"):
        assert selector in css, selector
    block = css.split("#2317 recent-run presentation", 1)[1]
    for token in ("var(--text)", "var(--muted)", "var(--line)", "var(--accent-soft)"):
        assert token in block
    assert "--claw-" not in block
    # A long filename must be able to shrink instead of pushing the action out.
    assert "min-width: 0;" in css.split(".claw-run-card-file {", 1)[1].split("}", 1)[0]


# ── behavioral proof via Node executing the real renderer ──────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const app = fs.readFileSync(process.argv[2], "utf8");

const start = app.indexOf("  function renderClawRunCard(run) {");
const end = app.indexOf("\n  // Unguarded fetch:", start);
if (start < 0 || end <= start) throw new Error("real run-card source must be located");

function el(tag) {
  return {
    tag, className: "", textContent: "", dataset: {}, children: [], listeners: {},
    setAttribute(name, value) { this[name] = value; },
    append(...items) { this.children.push(...items); },
    appendChild(child) { this.children.push(child); return child; },
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    click() { (this.listeners.click || []).forEach((fn) => fn()); },
  };
}

const COPY = {
  "claw-runs-download": "문서 다시 받기",
  "claw-runs-artifact-unverified": "실행이 완료 상태가 아닙니다.",
  "claw-runs-kind-aria": "파일 형식 {kind}",
  "claw-runs-download-only": "이 형식은 다운로드 전용입니다. 파일을 내려받아 확인하세요.",
};
function clawT(key, variables) {
  let value = COPY[key] || key;
  if (variables && typeof variables === "object") {
    Object.entries(variables).forEach(([name, replacement]) => {
      value = value.split("{" + name + "}").join(String(replacement));
    });
  }
  return value;
}

const downloads = [];
const pdfControllers = new Set();
const previewStub = {
  validHistoricalArtifact: (artifact) =>
    Boolean(artifact) && artifact.media_type === "application/pdf"
      && typeof artifact.filename === "string" && /\.pdf$/i.test(artifact.filename),
  create({ mount }) {
    const button = el("button");
    button.className = "claw-pdf-preview-action";
    button.textContent = "PDF 미리보기 확인";
    let attached = false;
    return {
      setHistorical() { if (!attached) { mount.appendChild(button); attached = true; } return true; },
      destroy() {},
    };
  },
};

function build(mediaType, filename) {
  return vm.runInNewContext("(" + app.slice(start, end).trim() + ")", {
    document: { createElement: el },
    window: { PadiemClawPdfPreview: previewStub },
    clawT,
    clawRunStatusLabel: (status) => status,
    clawRunHistoryPdfControllers: pdfControllers,
    setClawRunHistoryStatus: () => {},
    downloadClawArtifact: (id, name) => downloads.push([id, name]),
    openSavedConversation: () => { throw new Error("unexpected session open"); },
    renderClawApprovalControls: () => {},
  });
}

const DOC_ID = "doc_" + "a".repeat(32);
function render(mediaType, filename, status) {
  const artifact = { document_id: DOC_ID, filename, media_type: mediaType };
  return build(mediaType, filename)({
    run_id: "run.one", title: "Task", status: status || "completed",
    channel: "web", action: "document", created_at: "2026-10-12T00:00:00Z",
    result_summary: "bounded summary", artifact, session: null,
  });
}
function walk(root, out) {
  out = out || [];
  (root.children || []).forEach((child) => { out.push(child); walk(child, out); });
  return out;
}
function byClass(card, name) { return walk(card).filter((n) => n.className === name); }
function rowOf(card) { return byClass(card, "claw-run-card-artifact")[0]; }
function textOf(root) { return walk(root).map((n) => String(n.textContent || "")).join(" "); }

const checks = {};
const ok = (name, condition, detail) => {
  checks[name] = condition;
  if (!condition) { console.log(JSON.stringify({ ok: false, error: name, detail, checks })); process.exit(0); }
};

// 1) XLSX: the kind comes from the server media type, and no preview exists.
const xlsx = render("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "견적서_광주대학교.xlsx");
const xlsxRow = rowOf(xlsx);
const xlsxFile = byClass(xlsx, "claw-run-card-file")[0];
ok("CARD_KIND_FROM_SERVER_MEDIA_TYPE", byClass(xlsx, "claw-run-card-kind")[0].textContent === "XLSX");
ok("CARD_KIND_ACCESSIBLE_NAME", byClass(xlsx, "claw-run-card-kind")[0]["aria-label"] === "파일 형식 XLSX");
ok("CARD_DOWNLOAD_ONLY_STATED_WHEN_NO_PREVIEW",
   byClass(xlsx, "claw-run-card-download-only").length === 1
   && textOf(xlsx).indexOf("다운로드 전용") >= 0);
ok("CARD_ROW_SHAPE_UNCHANGED", xlsxRow.children.length === 2 && xlsxRow.children[0] === xlsxFile);
ok("CARD_ONE_DOCUMENT_ACTION",
   byClass(xlsx, "claw-run-card-download").length === 1
   && walk(xlsx).filter((n) => n.tag === "button").length === 1);

// 2) DOCX: same truthfulness, still one action and no preview controller.
const docx = render("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "reply.docx");
ok("CARD_KIND_FROM_SERVER_MEDIA_TYPE", byClass(docx, "claw-run-card-kind")[0].textContent === "DOCX");
ok("CARD_DOWNLOAD_ONLY_STATED_WHEN_NO_PREVIEW", byClass(docx, "claw-run-card-download-only").length === 1);
ok("CARD_ONE_DOCUMENT_ACTION", walk(docx).filter((n) => n.tag === "button").length === 1);

// 3) PDF: keeps its own verified preview state and drops the download-only note.
const pdf = render("application/pdf", "quote.pdf");
ok("CARD_KIND_FROM_SERVER_MEDIA_TYPE", byClass(pdf, "claw-run-card-kind")[0].textContent === "PDF");
ok("CARD_PDF_PREVIEW_KEEPS_ITS_OWN_STATE",
   byClass(pdf, "claw-run-card-download-only").length === 0
   && byClass(pdf, "claw-pdf-preview-action").length === 1
   && pdfControllers.size === 1);
ok("CARD_ROW_SHAPE_UNCHANGED", rowOf(pdf).children.length === 3);

// 4) The kind is never invented from a filename or a hostile media type.
for (const [media, name] of [
  ["", "mystery.xlsx"],
  [null, "mystery.xlsx"],
  ["application/octet-stream", "mystery.xlsx"],
  ["text/html; <script>alert(1)</script>", "mystery.xlsx"],
  ["APPLICATION/PDF<script>", "mystery.pdf"],
]) {
  const card = render(media, name);
  ok("CARD_KIND_NEVER_INVENTED", byClass(card, "claw-run-card-kind").length === 0, String(media));
}

// 5) Case/whitespace tolerance uses the same closed map, never a new type.
ok("CARD_KIND_FROM_SERVER_MEDIA_TYPE", byClass(render("  " + "application/pdf".toUpperCase() + " ", "a.pdf"), "claw-run-card-kind")[0].textContent === "PDF");

// 6) A hostile filename stays plain text and does not change the chip.
const hostile = render("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "<img src=x onerror=alert(1)>");
ok("CARD_FILENAME_STAYS_PLAIN_TEXT",
   byClass(hostile, "claw-run-card-filename")[0].textContent === "<img src=x onerror=alert(1)>"
   && byClass(hostile, "claw-run-card-kind")[0].textContent === "XLSX");

// 7) A partial run keeps its own truthful note alongside the download-only note.
const failed = render("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "broken.xlsx", "failed");
ok("CARD_DOWNLOAD_ONLY_STATED_WHEN_NO_PREVIEW",
   byClass(failed, "claw-run-card-partial-note").length === 1
   && byClass(failed, "claw-run-card-download-only").length === 1);

// 8) Rendering never downloads; only an explicit click does, exactly once.
const before = downloads.length;
byClass(xlsx, "claw-run-card-download")[0].click();
ok("CARD_NO_AUTO_DOWNLOAD", downloads.length === before + 1 && downloads.at(-1)[0] === DOC_ID);

console.log(JSON.stringify({ ok: true, checks }));
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_l2_claw_result_file_card_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS)],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    return json.loads(line)


def test_behavioral_result_file_card() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    for name in (
        "CARD_KIND_FROM_SERVER_MEDIA_TYPE",
        "CARD_KIND_NEVER_INVENTED",
        "CARD_DOWNLOAD_ONLY_STATED_WHEN_NO_PREVIEW",
        "CARD_PDF_PREVIEW_KEEPS_ITS_OWN_STATE",
        "CARD_ONE_DOCUMENT_ACTION",
        "CARD_ROW_SHAPE_UNCHANGED",
        "CARD_NO_AUTO_DOWNLOAD",
        "CARD_FILENAME_STAYS_PLAIN_TEXT",
        "CARD_KIND_ACCESSIBLE_NAME",
    ):
        assert payload["checks"].get(name) is True, name


if __name__ == "__main__":
    test_kind_is_derived_only_from_the_server_verified_media_type()
    test_kind_map_is_closed_and_covers_the_shipped_formats()
    test_card_still_has_exactly_one_document_action()
    test_download_only_note_is_stated_only_when_no_verified_preview_exists()
    test_new_runtime_copy_is_locale_owned_in_both_languages()
    test_app_runtime_copy_stays_free_of_hardcoded_korean()
    test_card_styles_reuse_shared_theme_tokens()
    test_behavioral_result_file_card()
    print("L2_CLAW_RESULT_FILE_CARD_TESTS=PASS")
