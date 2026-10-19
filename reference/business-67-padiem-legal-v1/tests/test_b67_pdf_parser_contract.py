from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / "pdf" / "pdf-page-parser.js"
WORKER = ROOT / "pdf" / "pdf-page-parser-worker.mjs"
VENDOR_IGNORE = ROOT / "pdf" / "vendor" / ".gitignore"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_dependency_is_exactly_pinned_and_local_only() -> None:
    parser = read(PARSER)
    worker = read(WORKER)
    assert 'PINNED_PDFJS_VERSION = "6.3.289"' in parser
    assert 'PINNED_PDFJS_VERSION = "6.3.289"' in worker
    assert 'from "./vendor/pdf.mjs"' in worker
    assert 'from "./vendor/pdf.worker.mjs"' in worker
    assert "http://" not in worker and "https://" not in worker


def test_browser_worker_is_dedicated_module_and_always_terminates() -> None:
    parser = read(PARSER)
    assert 'type: "module"' in parser
    assert 'name: "b67-pdf-page-parser"' in parser
    assert "worker.terminate()" in parser
    assert 'pdf_parser_timeout' in parser
    assert 'pdf_parse_cancelled' in parser
    assert "signal.addEventListener" in parser


def test_parse_contract_is_bounded_and_page_numbered() -> None:
    parser = read(PARSER)
    worker = read(WORKER)
    for marker in (
        "16 * 1024 * 1024",
        "maxPages: 512",
        "maxPageChars: 40000",
        "maxTotalChars: 2000000",
        "parseTimeoutMs: 10000",
    ):
        assert marker in parser
    assert "page_number: pageNumber" in worker
    assert "ocr_candidate_pages" in worker
    assert '"mixed"' in worker and '"none"' in worker and '"all"' in worker
    assert 'pdf_no_native_text' in worker
    assert 'pdf_password_required' in worker


def test_browser_extraction_contract_is_versioned_and_hash_bound() -> None:
    parser = read(PARSER)
    worker = read(WORKER)
    marker = 'b67-browser-pdf-extraction.v1'
    assert marker in parser
    assert marker in worker
    assert "contract_version" in worker
    assert "source_sha256" in worker
    assert "pdf_extraction_contract_version_mismatch" in parser


def test_pdfjs_receives_bytes_not_a_url_and_runtime_fetch_is_disabled() -> None:
    worker = read(WORKER)
    assert "data: new Uint8Array(buffer)" in worker
    assert "disableAutoFetch: true" in worker
    assert "disableRange: true" in worker
    assert "disableStream: true" in worker
    assert "useWorkerFetch: false" in worker
    assert "useWasm: false" in worker
    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon"):
        assert forbidden not in worker


def test_raw_pdf_is_not_persisted_in_browser_storage() -> None:
    source = read(PARSER) + read(WORKER)
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "caches.open",
        "showSaveFilePicker",
    ):
        assert forbidden not in source


def test_vendor_distribution_is_not_committed_by_this_poc() -> None:
    ignore = read(VENDOR_IGNORE)
    assert "pdf.mjs" in ignore
    assert "pdf.worker.mjs" in ignore
