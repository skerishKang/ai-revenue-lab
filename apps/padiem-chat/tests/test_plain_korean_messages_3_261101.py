from _support import plain_message_launcher_source as sheets


def test_project_errors_do_not_render_server_message_or_raw_exception():
    project = sheets.sheet("chat-project-module.js")
    assert "data.error.message" not in project
    assert "projectFormError.textContent = error.message" not in project
    assert 'showProjectError(error, deps.uiT("project-file-save-failed"))' in project
    assert 'showProjectError(error, deps.uiT("project-delete-failed"))' in project


def test_claw_error_sinks_use_safe_local_messages_and_keep_history_guidance():
    source = sheets.sheet("app.js")
    # setClawRunHistoryStatus moved into chat-run-history-module.js (#7216 R5 B3)
    # and setApprovedMemoryStatus moved into chat-memory-module.js (#7216 R5 A2);
    # all shipped sources are checked so the raw-error ban keeps its strength.
    module = sheets.sheet("chat-run-history-module.js")
    memory_mod = sheets.sheet("chat-memory-module.js")
    for sink in ("setApprovedMemoryStatus", "setClawRunHistoryStatus"):
        assert sink + "(error instanceof Error ? error.message" not in source
        assert sink + "(error instanceof Error ? error.message" not in module
        assert sink + "(error instanceof Error ? error.message" not in memory_mod
    assert 'safeLocalUiMessage(error, clawT("claw-runs-error"))' not in source
    assert 'safeLocalUiMessage(error, deps.clawT("claw-runs-error"))' in module
    assert 'deps.safeLocalUiMessage(error, deps.clawT("claw-memory-error-generic"))' in memory_mod
    assert "clawBoundedRefusalCopy" in source


def test_claw_modules_do_not_display_raw_caught_errors():
    office = sheets.sheet("claw-office-chooser.js")
    xlsx = sheets.sheet("claw-web-xlsx-sources.js")
    assert "setMessage(error.message);" not in office
    assert "report(error.message);" not in xlsx
    for source in (office, xlsx):
        assert "reportError = " in source
        assert 'createElement("small")' in source
        assert '"error-code"' in source
    assert "승인 대기" in office
