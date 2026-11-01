from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_project_errors_do_not_render_server_message_or_raw_exception():
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    project = source[source.index("async function loadProjectFiles"):source.index('uiT("project-delete-failed")') + 200]
    assert "data.error.message" not in project
    assert "projectFormError.textContent = error.message" not in project
    assert 'showProjectError(error, uiT("project-file-save-failed"))' in project
    assert 'showProjectError(error, uiT("project-delete-failed"))' in source


def test_claw_error_sinks_use_safe_local_messages_and_keep_history_guidance():
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    for sink in ("setApprovedMemoryStatus", "setClawRunHistoryStatus"):
        assert sink + "(error instanceof Error ? error.message" not in source
    assert 'safeLocalUiMessage(error, clawT("claw-runs-error"))' in source
    assert "clawBoundedRefusalCopy" in source


def test_claw_modules_do_not_display_raw_caught_errors():
    office = (STATIC / "claw-office-chooser.js").read_text(encoding="utf-8")
    xlsx = (STATIC / "claw-web-xlsx-sources.js").read_text(encoding="utf-8")
    assert "setMessage(error.message);" not in office
    assert "report(error.message);" not in xlsx
    for source in (office, xlsx):
        assert "reportError = " in source
        assert 'createElement("small")' in source
        assert '"error-code"' in source
    assert "승인 대기" in office
