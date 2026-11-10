from pathlib import Path

from _android_handoff_storage_guard import assert_session_storage_is_handoff_only

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "static/app.js").read_text(encoding="utf-8")
#7216 R5 step 5a: the conversation area moved into chat-conversation-module.js.
CONV_JS = (ROOT / "static/chat-conversation-module.js").read_text(encoding="utf-8")
#7216 R5 step 5b: the streaming area moved into chat-streaming-module.js.
STREAM_JS = (ROOT / "static/chat-streaming-module.js").read_text(encoding="utf-8")
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
    #7216 R5 step 5a: the attachment intake moved into chat-conversation-module.js.
    conv_js = CONV_JS
    assert "const binaryDocuments = window.PadiemBinaryDocuments;" in APP_JS
    assert "binaryDocuments.canRead(file)" in conv_js
    assert "next = await deps.binaryDocuments.read(file);" in conv_js
    # #261102: the chip list replaced the single attachment slot; the app
    # controller still owns the binary attachment state and re-renders the
    # chips after every intake.
    assert "deps.selectedAttachments.push({ ...next, key: `att-${deps.attachmentKeyCounter}` });" in conv_js
    assert "renderAttachmentChips();" in conv_js


def test_binary_attachment_payload_uses_existing_completed_chat_path():
    conv_js = CONV_JS  # #7216 R5 step 5a
    stream_js = STREAM_JS  # #7216 R5 step 5b
    # #5380 replaced the Base64 attachment body with a binary file intake, so
    # the payload carries the file itself. The completed-chat dispatch path
    # this test protects is unchanged.
    # #261102: the payload is built per chip; a file-carrying chip still
    # carries the file itself through the completed-chat path.
    assert 'media_type: item.mediaType, file: item.file' in conv_js
    assert "const attachments = deps.attachmentPayload(attachment);" in stream_js
    assert "if (attachments) payload.attachments = attachments;" in stream_js
    # #7297: Chat and Claw share the completed-attachment path.
    assert "if (attachments) {" in stream_js
    # Success recording for one-click regenerate keeps the same dispatch
    # shape: completed JSON for attachments, streaming otherwise.
    assert "await deps.requestCompletedAnswer(" in stream_js
    assert "await deps.requestStreamingAnswer(" in stream_js


def test_binary_reader_loads_before_app_controller():
    assert INDEX_HTML.index('<script src="./document-binary.js"></script>') < INDEX_HTML.index('<script src="./app.js"></script>')


def test_unification_does_not_add_hidden_browser_persistence():
    combined = APP_JS + "\n" + BINARY_JS
    for forbidden in ["localStorage", "indexedDB", "cookieStore"]:
        assert forbidden not in combined
    assert_session_storage_is_handoff_only(combined)
