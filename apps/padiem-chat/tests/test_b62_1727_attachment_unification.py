from pathlib import Path

from _android_handoff_storage_guard import assert_session_storage_is_handoff_only

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
        "let pending =",
        "pending = next",
    ]
    for token in forbidden:
        assert token not in BINARY_JS


def test_binary_reader_exports_pure_attachment_api():
    assert "window.PadiemBinaryDocuments = api" in BINARY_JS
    assert "canRead," in BINARY_JS
    assert "read," in BINARY_JS
    assert 'type: "document"' in BINARY_JS
    assert "mediaType," in BINARY_JS
    assert "file," in BINARY_JS
    assert "base64," not in BINARY_JS
    assert "byteSize:" in BINARY_JS


def test_binary_qa_metadata_is_computed_from_file_input_not_stored_state():
    assert "function pendingMeta()" in BINARY_JS
    assert 'document.getElementById("attachmentFileInput")' in BINARY_JS
    assert "input && input.files ? input.files[0] : null" in BINARY_JS
    assert "pendingMeta," in BINARY_JS
    assert "base64" not in BINARY_JS.split("function pendingMeta()", 1)[1].split("const api", 1)[0]
    assert "text" not in BINARY_JS.split("function pendingMeta()", 1)[1].split("const api", 1)[0]


def test_app_owns_binary_attachment_in_selected_attachment_state():
    assert "const binaryDocuments = window.PadiemBinaryDocuments;" in APP_JS
    assert "binaryDocuments.canRead(file)" in APP_JS
    assert "next = await binaryDocuments.read(file);" in APP_JS
    # #261102: the chip list replaced the single attachment slot; the app
    # controller still owns the binary attachment state and re-renders the
    # chips after every intake.
    assert "selectedAttachments.push({ ...next, key: `att-${attachmentKeyCounter}` });" in APP_JS
    assert "renderAttachmentChips();" in APP_JS


def test_binary_attachment_payload_uses_existing_completed_chat_path():
    # #5380 replaced the Base64 attachment body with a binary file intake, so
    # the payload carries the file itself. The completed-chat dispatch path
    # this test protects is unchanged.
    # #261102: the payload is built per chip; a file-carrying chip still
    # carries the file itself through the completed-chat path.
    assert 'media_type: item.mediaType, file: item.file' in APP_JS
    assert "const attachments = attachmentPayload(attachment);" in APP_JS
    assert "if (attachments) payload.attachments = attachments;" in APP_JS
    # #2505: the Chat completed-attachment path is unchanged for Chat; the same
    # guard now also keeps a Claw attachment on its own P01 lane.
    assert "if (attachments && !clawGeneralRequest) {" in APP_JS
    # Success recording for one-click regenerate keeps the same dispatch
    # shape: completed JSON for attachments, streaming otherwise.
    assert "await requestCompletedAnswer(" in APP_JS
    assert "await requestStreamingAnswer(" in APP_JS


def test_binary_reader_loads_before_app_controller():
    assert INDEX_HTML.index('<script src="./document-binary.js"></script>') < INDEX_HTML.index('<script src="./app.js"></script>')


def test_unification_does_not_add_hidden_browser_persistence():
    combined = APP_JS + "\n" + BINARY_JS
    for forbidden in ["localStorage", "indexedDB", "cookieStore"]:
        assert forbidden not in combined
    assert_session_storage_is_handoff_only(combined)
