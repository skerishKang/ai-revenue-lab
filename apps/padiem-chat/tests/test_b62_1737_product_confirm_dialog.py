# #8060: shipped reads live in _support; assertions stay here.
from _r5_function_source import function_body
from _support.final_share_source import locale_source, shared_read

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def read(name: str) -> str:
    return shared_read(STATIC / name)


def test_native_destructive_confirm_is_removed() -> None:
    app = read("app.js")
    # deleteConversation moved into chat-history-module.js (#7216 R5 step 3)
    # and project destructive actions into chat-project-module.js (R5); the
    # native-confirm ban and confirm-dialog count cover all three sources.
    module = read("chat-history-module.js")
    project = read("chat-project-module.js")
    outputs = read("outputs.js")
    a11y = read("a11y.js")

    assert "window.confirm(" not in app
    assert "window.confirm(" not in module
    assert "window.confirm(" not in project
    assert "window.confirm(" not in outputs
    assert "window.confirm(" not in a11y
    confirm = "PadiemConfirmDialog.confirm({"
    assert app.count(confirm) + module.count(confirm) + project.count(confirm) == 3
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
    # deleteConversation moved into chat-history-module.js (#7216 R5 step 3);
    # its confirm -> guard -> DELETE order is pinned against the module body.
    module = read("chat-history-module.js")
    outputs = read("outputs.js")

    for function_name in ("deleteProjectFile", "deleteProject", "deleteConversation"):
        if function_name == "deleteConversation":
            start = module.index(f"async function {function_name}")
            end = module.find("\n  async function ", start + 1)
            block = module[start:] if end < 0 else module[start:end]
        else:
            block = function_body(function_name, prefix="async function ", end="\n      }")
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
