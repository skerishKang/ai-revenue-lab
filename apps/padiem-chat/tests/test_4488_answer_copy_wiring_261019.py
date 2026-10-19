"""#4488 stage 2: the shared answer-copy module is actually wired.

B62 user-bubble copy and B66 real-answer copy call one canonical clipboard
implementation; legacy branches remain only as fallbacks. B66 product files
stay product-neutral (Shared alias only).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "packages/padiem-conversation-ui/answer-copy.js"
WORKFLOWS = ROOT / ".github/workflows"
SYNC_ANSWER_COPY = "scripts/sync_shared_answer_copy.py --check"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_canonical_exports_copy_contract():
    text = CANONICAL.read_text(encoding="utf-8")
    assert 'VERSION = "shared-answer-copy-v1"' in text
    assert "function copyText(text)" in text
    assert "SharedAnswerCopy" in text
    assert "PadiemAnswerCopy" in text


def test_b62_index_loads_shared_answer_copy():
    html = _read("apps/padiem-chat/static/index.html")
    assert '<script src="./shared-answer-copy.js"></script>' in html
    assert html.index("./shared-answer-copy.js") < html.index("./app.js")


def test_b62_user_copy_calls_shared_first():
    app = _read("apps/padiem-chat/static/app.js")
    assert "window.PadiemAnswerCopy || window.SharedAnswerCopy" in app
    assert app.index("shared.copyText(plain)") < app.index(
        "navigator.clipboard.writeText(plain).then(flash, () => {});"
    )


def test_b66_index_loads_shared_answer_copy_before_easy_mode():
    html = _read("reference/business-66-padiem-quote-v1/index.html")
    assert '<script src="shared-answer-copy.js" defer></script>' in html
    assert html.index("shared-answer-copy.js") < html.index("easy-mode.js")


def test_b66_real_answers_opt_in_and_status_stays_out():
    easy = _read("reference/business-66-padiem-quote-v1/easy-mode.js")
    assert "window.SharedAnswerCopy" in easy
    assert "PadiemAnswerCopy" not in easy
    assert "Padiem" not in easy
    assert "opts.copyAction === true" in easy
    assert "appendCopyAction(body, content)" in easy
    assert easy.count("copyAction: true") == 1
    assert 'const isModelAnswer = result.answer_origin === "registered_model_completion";' in easy
    assert "copyAction: isModelAnswer" in easy


def test_b66_copy_uses_shared_execution_and_truthful_feedback():
    easy = _read("reference/business-66-padiem-quote-v1/easy-mode.js")
    assert "sharedCopy.copyText(text)" in easy
    assert 'App.toast(ok ? "답변을 복사했습니다." : "답변을 복사하지 못했습니다.");' in easy


def test_static_copies_match_canonical_bytes():
    original = CANONICAL.read_bytes()
    for relative in (
        "apps/padiem-chat/static/shared-answer-copy.js",
        "reference/business-66-padiem-quote-v1/shared-answer-copy.js",
    ):
        assert (ROOT / relative).read_bytes() == original


def test_release_paths_check_shared_answer_copy():
    b62 = (WORKFLOWS / "b62-production-code-deploy-gate.yml").read_text(encoding="utf-8")
    b66 = (WORKFLOWS / "b66-neutral-pages-beta.yml").read_text(encoding="utf-8")
    assert b62.count(SYNC_ANSWER_COPY) >= 2
    assert b66.count(SYNC_ANSWER_COPY) >= 1


def test_shared_answer_copy_changes_trigger_release_paths():
    b62 = (WORKFLOWS / "b62-production-code-deploy-gate.yml").read_text(encoding="utf-8")
    b66 = (WORKFLOWS / "b66-neutral-pages-beta.yml").read_text(encoding="utf-8")
    assert '"apps/padiem-chat/static/shared-answer-copy.js"' in b62
    for workflow in (b62, b66):
        assert "scripts/sync_shared_answer_copy.py" in workflow
