from pathlib import Path

from _android_handoff_storage_guard import assert_session_storage_is_handoff_only

# #7186 R2: 첨부 흡수·페이로드 계약은 모듈 실행 관찰로 검사한다.
from _r5_attachment_module_harness import observations as attachment_module_observations

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "static/app.js").read_text(encoding="utf-8")
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
    """바이너리 원본은 칩 상태로 들어가고 칩 목록을 다시 그린다.

    #7186 R2: 원문 문자열(binaryDocuments.canRead/read·selectedAttachments.push·
    renderAttachmentChips) 대신 chat-conversation-module.js의 addAttachmentFiles를
    실행해 canRead→read 호출, 칩 1개 push(att-N 키), 칩 다시 그리기를 관찰한다.
    app.js가 window.PadiemBinaryDocuments를 deps로 공급하는 줄은 app.js 소유
    와이어링이라 문자열로 남긴다(실행 관찰은 모듈 함수만 돈다).
    """
    # #7216 R5 step 5a: the attachment intake moved into chat-conversation-module.js.
    assert "const binaryDocuments = window.PadiemBinaryDocuments;" in APP_JS
    intake = attachment_module_observations()["conv"]["binaryIntake"]
    assert intake["canRead"] == 1
    assert intake["read"] == 1
    assert intake["chips"] == 1
    assert intake["chipClass"] == "attachment-chip"
    assert intake["key"] == "att-1"
    assert intake["mediaType"] == "application/pdf"
    assert intake["inputCleared"] is True


def test_binary_attachment_payload_uses_existing_completed_chat_path():
    stream_js = STREAM_JS  # #7216 R5 step 5b
    # #5380 replaced the Base64 attachment body with a binary file intake, so
    # the payload carries the file itself. The completed-chat dispatch path
    # this test protects is unchanged.
    # #261102: the payload is built per chip; a file-carrying chip still
    # carries the file itself through the completed-chat path.
    # #7186 R2: the builder is executed instead of string-matched.
    payload = attachment_module_observations()["conv"]["payload"]
    assert payload["fileChip"][0]["media_type"] == "application/pdf"
    assert payload["fileChipSameObject"] is True
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
