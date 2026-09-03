from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES_JS = (ROOT / "static/attachment-capabilities.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "static/app.js").read_text(encoding="utf-8")
BINARY_JS = (ROOT / "static/document-binary.js").read_text(encoding="utf-8")
LOCALE_JS = (ROOT / "static/locale.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "static/index.html").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_attachment_capabilities_are_single_browser_truth_source():
    assert "window.PadiemAttachmentCapabilities" in CAPABILITIES_JS
    for label in ["JPEG", "PNG", "WebP", "TXT", "Markdown", "CSV", "JSON", "PDF", "DOCX", "PPTX", "XLSX"]:
        assert f'label: "{label}"' in CAPABILITIES_JS
    assert "imageBytes: 4 * 1024 * 1024" in CAPABILITIES_JS
    assert "textBytes: 96 * 1024" in CAPABILITIES_JS
    assert "textChars: 40000" in CAPABILITIES_JS
    assert "binaryBytes: 2 * 1024 * 1024" in CAPABILITIES_JS
    assert "idleNote:" in CAPABILITIES_JS
    assert "fileButtonTitle:" in CAPABILITIES_JS
    assert "unsupportedFormat:" in CAPABILITIES_JS


def test_capability_projection_loads_before_copy_and_attachment_consumers():
    capability = INDEX_HTML.index('<script src="./attachment-capabilities.js"></script>')
    locale = INDEX_HTML.index('<script src="./locale.js"></script>')
    binary = INDEX_HTML.index('<script src="./document-binary.js"></script>')
    app = INDEX_HTML.index('<script src="./app.js"></script>')
    assert capability < locale < binary < app


def test_composer_does_not_hard_code_format_truth_in_html():
    assert '<input id="attachmentFileInput" type="file" hidden />' in INDEX_HTML
    assert '<small>지원 문서 형식</small>' in INDEX_HTML
    assert 'id="attachmentButton" title="파일 첨부"' in INDEX_HTML
    assert 'id="runtimeNote">파일 첨부 형식을 확인하는 중입니다.' in INDEX_HTML


def test_locale_derives_attachment_copy_without_clobbering_runtime_state():
    assert "const attachmentCapabilities = window.PadiemAttachmentCapabilities;" in LOCALE_JS
    assert "capabilityCopy.documentFormats" in LOCALE_JS
    assert "attachmentInput.accept = attachmentCapabilities.accept" in LOCALE_JS
    assert "attachmentButton.title = capabilityCopy.fileButtonTitle" in LOCALE_JS
    assert '"document-copy"' not in LOCALE_JS
    assert '"note"' not in LOCALE_JS
    assert '"#runtimeNote"' not in LOCALE_JS
    assert "PDF and Office files are not supported yet" not in LOCALE_JS
    assert "PDF·Office 문서는 아직 지원하지 않습니다" not in LOCALE_JS


def test_app_uses_capabilities_for_limits_formats_idle_copy_and_errors():
    assert "const attachmentCapabilities = window.PadiemAttachmentCapabilities;" in APP_JS
    assert "const MAX_IMAGE_BYTES = attachmentCapabilities.limits.imageBytes;" in APP_JS
    assert "const MAX_DOCUMENT_BYTES = attachmentCapabilities.limits.textBytes;" in APP_JS
    assert "const MAX_DOCUMENT_CHARS = attachmentCapabilities.limits.textChars;" in APP_JS
    assert "attachmentCapabilities.images.flatMap" in APP_JS
    assert "attachmentCapabilities.textDocuments.flatMap" in APP_JS
    assert "return activeProject ?" in APP_JS and "attachmentCopy().idleNote" in APP_JS
    assert "throw new Error(attachmentCopy().unsupportedFormat)" in APP_JS
    assert "throw new Error(attachmentCopy().textTooLarge)" in APP_JS
    assert "throw new Error(attachmentCopy().textTooLong)" in APP_JS
    assert "throw new Error(attachmentCopy().imageTooLarge)" in APP_JS
    assert 'window.addEventListener("padiem:localechange"' in APP_JS
    assert "setNote(idleNote());" in APP_JS
    assert "DEFAULT_NOTE" not in APP_JS
    assert "PDF·Office 문서는 아직 지원하지 않습니다" not in APP_JS


def test_binary_reader_derives_formats_and_limit_from_capabilities():
    assert "const attachmentCapabilities = window.PadiemAttachmentCapabilities;" in BINARY_JS
    assert "attachmentCapabilities.limits.binaryBytes" in BINARY_JS
    assert "attachmentCapabilities.binaryDocuments.forEach" in BINARY_JS
    assert "attachmentCapabilities.copy(document.documentElement.lang).binaryTooLarge" in BINARY_JS
    assert "2 * 1024 * 1024" not in BINARY_JS


def test_project_file_persistence_copy_remains_explicitly_distinct():
    assert "프로젝트 파일 저장은 TXT·Markdown·CSV·JSON만 지원합니다." in INDEX_HTML
    assert "PDF·DOCX·PPTX·XLSX는 저장하지 않습니다." in INDEX_HTML
    assert 'id="projectFileInput" type="file" accept="text/plain,text/markdown,text/csv,application/json,.txt,.md,.markdown,.csv,.json"' in INDEX_HTML
    assert "Project files are a distinct persistence capability." in README
    assert "validated UTF-8 text files only" in README


def test_readme_matches_current_ephemeral_composer_contract():
    assert "`static/attachment-capabilities.js`" in README
    assert "JPEG / PNG / WebP" in README
    assert "TXT / Markdown / CSV / JSON" in README
    assert "PDF / DOCX / PPTX / XLSX" in README
    assert "raw binary payload up to 2 MiB" in README
    assert "existing completed `/api/chat` attachment contract" in README
    assert "frontend does not reimplement document extraction" in README
    assert "PDF, DOCX, PPTX and XLSX extraction are **not supported yet**" not in README


def test_no_hidden_browser_persistence_or_interception_added():
    combined = CAPABILITIES_JS + "\n" + APP_JS + "\n" + BINARY_JS + "\n" + LOCALE_JS
    for forbidden in ["localStorage", "sessionStorage", "indexedDB", "cookieStore", "window.fetch =", "MutationObserver"]:
        assert forbidden not in combined
