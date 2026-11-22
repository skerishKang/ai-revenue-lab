"""Parsed views of the attachment-capability contract sources (#8060 51차).

Every shipped-source read lives here (reusing ``claw_static.sheet`` and
``html_tags``); the contract test receives the capability object evaluated in
Node, parsed HTML attributes/text and named source facts, and asserts on those
instead of pinning raw source substrings.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from _support.claw_static import sheet
from _support.html_tags import tags_for_page

CAPABILITIES = "attachment-capabilities.js"
_APP = Path(__file__).resolve().parents[2]


# ── raw reads (this module only) ────────────────────────────────────────────


def capabilities_js() -> str:
    return sheet(CAPABILITIES)


def app_js() -> str:
    return sheet("app.js")


def binary_js() -> str:
    return sheet("document-binary.js")


def locale_js() -> str:
    return sheet("locale.js")


def index_html() -> str:
    return sheet("index.html")


def readme() -> str:
    return (_APP / "README.md").read_text(encoding="utf-8")


def core_js() -> str:
    return sheet("chat-core-module.js").replace("deps.", "")


def combined_source() -> str:
    return "\n".join((capabilities_js(), app_js(), binary_js(), locale_js()))


# ── capability object, evaluated in Node ────────────────────────────────────


def capabilities_facts() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required"
    script = (
        "const window = {};\n"
        + capabilities_js()
        + "\n(() => {\n"
        + "const c = window.PadiemAttachmentCapabilities;\n"
        + "const labels = (xs) => xs.map((f) => f.label);\n"
        + "const fieldNames = new Set();\n"
        + "for (const obj of [c, ...c.images, ...c.textDocuments, ...c.binaryDocuments]) {\n"
        + "  for (const key of Object.keys(obj)) fieldNames.add(key);\n"
        + "}\n"
        + "const ko = c.copy('ko'), en = c.copy('en');\n"
        + "console.log(JSON.stringify({\n"
        + "  exported: !!c,\n"
        + "  image_labels: labels(c.images),\n"
        + "  text_labels: labels(c.textDocuments),\n"
        + "  binary_labels: labels(c.binaryDocuments),\n"
        + "  accept: c.accept,\n"
        + "  copy_keys: Object.keys(ko),\n"
        + "  size_fields: [...fieldNames].filter((k) => /bytes|chars|gib|kib/i.test(k)),\n"
        + "  size_copy: [ko, en].some((copy) => Object.values(copy).some((v) => /GiB|KiB|bytes/i.test(v))),\n"
        + "}));\n"
        + "})();\n"
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def capabilities_forbidden_tokens() -> list[str]:
    source = capabilities_js()
    return [token for token in ("imageBytes", "textBytes", "textChars", "binaryBytes", "1 GiB") if token in source]


# ── parsed index.html facts ─────────────────────────────────────────────────


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def index_text() -> str:
    parser = _Text()
    parser.feed(index_html())
    parser.close()
    return " ".join(parser.parts)


def index_facts() -> dict:
    tags = tags_for_page("index.html")
    by_id = {attrs["id"]: dict(attrs) for _tag, attrs in tags if attrs.get("id")}
    scripts = [attrs["src"].rsplit("/", 1)[-1] for tag, attrs in tags
               if tag == "script" and attrs.get("src")]
    return {
        "script_sources": scripts,
        "ids": sorted(by_id),
        "attrs": by_id,
        "locale_keys": {attrs["data-locale-key"] for _tag, attrs in tags if attrs.get("data-locale-key")},
    }


def index_forbidden_tokens() -> list[str]:
    source = index_html()
    return [token for token in ("지원 형식은 추후 안내합니다.", 'id="attachmentButton" title=') if token in source]


# ── named source facts ──────────────────────────────────────────────────────


def _has(source: str, token: str) -> bool:
    return token in source


def locale_facts() -> dict:
    source = locale_js()
    return {
        "uses_capability_global": _has(source, "const attachmentCapabilities = window.PadiemAttachmentCapabilities;"),
        "uses_document_formats": _has(source, "capabilityCopy.documentFormats"),
        "zero_width_join": _has(source, 'formats.split("·").join(" · \\u200b")'),
        "input_accept_assignment": _has(source, "attachmentInput.accept = attachmentCapabilities.accept"),
        "tooltip_label": _has(source, "window.PadiemSharedTooltip?.label?.(attachmentButton, capabilityCopy.fileButtonTitle)"),
        "title_assignment": _has(source, "attachmentButton.title = capabilityCopy.fileButtonTitle"),
        "forbidden_tokens": [
            token for token in (
                '"document-copy"', '"note"', '"#runtimeNote"', '"document-formats-soon"',
                "PDF and Office files are not supported yet",
                "PDF·Office 문서는 아직 지원하지 않습니다",
            ) if _has(source, token)
        ],
    }


def app_facts() -> dict:
    source = app_js()
    combined = source + "\n" + core_js()
    return {
        "uses_capability_global": _has(source, "const attachmentCapabilities = window.PadiemAttachmentCapabilities;"),
        "image_flatmap": _has(source, "attachmentCapabilities.images.flatMap"),
        "text_flatmap": _has(source, "attachmentCapabilities.textDocuments.flatMap"),
        "active_project_branch": _has(combined, "return activeProject ?"),
        "idle_note_copy": _has(combined, "attachmentCopy().idleNote"),
        "unsupported_throw": _has(combined, "throw new Error(attachmentCopy().unsupportedFormat)"),
        "localechange_listener": _has(source, 'window.addEventListener("padiem:localechange"'),
        "set_note_idle": _has(source, "coreModule().setNote(coreModule().idleNote());"),
        "forbidden_tokens": [
            token for token in (
                "attachmentCapabilities.limits.imageBytes",
                "attachmentCapabilities.limits",
                "textTooLarge", "textTooLong", "imageTooLarge",
                "DEFAULT_NOTE", "PDF·Office 문서는 아직 지원하지 않습니다",
            ) if _has(combined, token)
        ],
    }


def binary_facts() -> dict:
    source = binary_js()
    return {
        "uses_capability_global": _has(source, "const attachmentCapabilities = window.PadiemAttachmentCapabilities;"),
        "binary_foreach": _has(source, "attachmentCapabilities.binaryDocuments.forEach"),
        "forbidden_tokens": [
            token for token in ("limits.binaryBytes", "binaryTooLarge", "2 * 1024 * 1024")
            if _has(source, token)
        ],
    }


def readme_facts() -> dict:
    source = readme()
    required = (
        "`static/attachment-capabilities.js`",
        "JPEG / PNG / WebP",
        "TXT / Markdown / CSV / JSON",
        "PDF / DOCX / PPTX / XLSX",
        "raw binary payload with no PADIEM byte total",
        "existing completed `/api/chat` attachment contract",
        "frontend does not reimplement document extraction",
    )
    return {
        "missing": [token for token in required if not _has(source, token)],
        "persistence_missing": [
            token for token in (
                "Project files are a distinct persistence capability.",
                "validated UTF-8 text files only",
            ) if not _has(source, token)
        ],
        "forbidden_tokens": [
            token for token in ("PDF, DOCX, PPTX and XLSX extraction are **not supported yet**",)
            if _has(source, token)
        ],
    }


def combined_forbidden_tokens() -> list[str]:
    source = combined_source()
    return [
        token for token in ("localStorage", "indexedDB", "cookieStore", "window.fetch =", "MutationObserver")
        if _has(source, token)
    ]
