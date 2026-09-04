from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_native_destructive_confirm_is_removed() -> None:
    app = read("app.js")
    outputs = read("outputs.js")
    a11y = read("a11y.js")

    assert "window.confirm(" not in app
    assert "window.confirm(" not in outputs
    assert "window.confirm(" not in a11y
    assert app.count("PadiemConfirmDialog.confirm({") == 3
    assert outputs.count("PadiemConfirmDialog.confirm({") == 1


def test_shared_first_party_dialog_has_accessible_contract() -> None:
    source = read("a11y.js")

    for token in (
        'dialog.id = "confirmDialog"',
        'dialog.setAttribute("aria-labelledby", "confirmDialogTitle")',
        'dialog.setAttribute("aria-describedby", "confirmDialogMessage")',
        'cancelButton.id = "confirmDialogCancel"',
        'confirmButton.id = "confirmDialogConfirm"',
        'dialog.addEventListener("cancel"',
        'event.key !== "Tab"',
        "current.returnFocus.focus()",
        "dialog.showModal()",
        "cancelButton.focus()",
        "if (active || dialog.open) return Promise.resolve(false)",
    ):
        assert token in source


def test_delete_calls_remain_after_explicit_confirmation() -> None:
    app = read("app.js")
    outputs = read("outputs.js")

    for function_name in ("deleteProjectFile", "deleteProject", "deleteConversation"):
        start = app.index(f"async function {function_name}")
        end = app.find("\n  async function ", start + 1)
        block = app[start:] if end < 0 else app[start:end]
        confirm_at = block.index("await window.PadiemConfirmDialog.confirm")
        guard_at = block.index("if (!confirmed) return")
        delete_at = block.index('method: "DELETE"')
        assert confirm_at < guard_at < delete_at

    start = outputs.index("async function deleteOutput")
    end = outputs.find("\n  outputsNavButton", start)
    block = outputs[start:end]
    confirm_at = block.index("await window.PadiemConfirmDialog.confirm")
    guard_at = block.index("if (!confirmed) return")
    delete_at = block.index('method: "DELETE"')
    assert confirm_at < guard_at < delete_at


def test_dialog_is_themed_for_every_product_theme() -> None:
    css = read("accessibility-polish.css")

    for selector in (
        ".confirm-dialog",
        ".confirm-dialog-panel",
        ".confirm-dialog-actions",
        ".confirm-dialog-cancel",
        ".confirm-dialog-confirm",
        'html[data-theme="dark"] .confirm-dialog-panel',
        'html[data-theme="cinematic"] .confirm-dialog-panel',
        'html[data-theme="padiem-home"] .confirm-dialog-panel',
        'html[data-theme="padiem-glass"] .confirm-dialog-panel',
    ):
        assert selector in css

    assert "min-height: 44px" in css
    assert "min-height: 48px" in css
