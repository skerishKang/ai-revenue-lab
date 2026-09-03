from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "static/app.js").read_text(encoding="utf-8")
BINARY_JS = (ROOT / "static/document-binary.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "static/index.html").read_text(encoding="utf-8")


def test_binary_reader_has_no_transport_or_dom_interception():
    forbidden = [
        "window.fetch =",
        "MutationObserver",
        "stopImmediatePropagation",
        "pendingUserMeta",
        "pendingTruthLabel",
        "toSseResponse",
        "isChatStreamRequest",
        "completedChatUrl",
        "removeButton.click",
    ]
    for token in forbidden:
        assert token not in BINARY_JS


def test_binary_reader_exports_pure_attachment_api():
    assert "window.PadiemBinaryDocuments = api" in BINARY_JS
    assert "canRead," in BINARY_JS
    assert "read," in BINARY_JS
    assert 'type: "document"' in BINARY_JS
    assert "mediaType," in BINARY_JS
    assert "base64," in BINARY_JS
    assert "byteSize:" in BINARY_JS


def test_app_owns_binary_attachment_in_selected_attachment_state():
    assert "const binaryDocuments = window.PadiemBinaryDocuments;" in APP_JS
    assert "binaryDocuments.canRead(file)" in APP_JS
    assert "next = await binaryDocuments.read(file);" in APP_JS
    assert "selectedAttachment = next;" in APP_JS
    assert "renderSelectedAttachment();" in APP_JS


def test_binary_attachment_payload_uses_existing_completed_chat_path():
    assert 'media_type: attachment.mediaType, base64: attachment.base64' in APP_JS
    assert "const attachments = attachmentPayload(attachment);" in APP_JS
    assert "if (attachments) payload.attachments = attachments;" in APP_JS
    assert "if (attachments) {" in APP_JS
    assert "return await requestCompletedAnswer(" in APP_JS
    assert "return await requestStreamingAnswer(" in APP_JS


def test_binary_reader_loads_before_app_controller():
    assert INDEX_HTML.index('<script src="./document-binary.js"></script>') < INDEX_HTML.index('<script src="./app.js"></script>')


def test_unification_does_not_add_hidden_browser_persistence():
    combined = APP_JS + "\n" + BINARY_JS
    for forbidden in ["localStorage", "sessionStorage", "indexedDB", "cookieStore"]:
        assert forbidden not in combined
