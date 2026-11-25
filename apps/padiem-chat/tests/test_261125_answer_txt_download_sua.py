"""#8697 — answer TXT download label and dark saved-output button contrast.

The download stays inside the answer 'more' menu; only its customer-visible
label and the dark-theme saved-output dialog button ink change. This pins both,
plus the AA contrast of the new ink, without editing shared contract rosters.
"""

from __future__ import annotations

from _support import contrast_repair_source as source
from _support import claw_static

NEW_LABEL_KO = "텍스트 파일로 내려받기"
NEW_LABEL_EN = "Download as text file"
SAVE_LABEL_KO = "저장한 답변으로 저장"


def _locale_css() -> str:
    return claw_static.sheet("locale-chat.js")


def _outputs_js() -> str:
    return claw_static.sheet("outputs.js")


def _outputs_css() -> str:
    return claw_static.sheet("outputs.css")


def test_download_label_names_the_action_and_differs_from_save():
    locale = _locale_css()
    assert f'"answer-txt-download": "{NEW_LABEL_KO}"' in locale
    assert f'"answer-txt-download": "{NEW_LABEL_EN}"' in locale
    assert f'"answer-save": "{SAVE_LABEL_KO}"' in locale
    assert f'localeText("answer-txt-download", "{NEW_LABEL_KO}")' in _outputs_js()
    assert "TXT 다운로드" not in locale
    assert "Download TXT" not in locale


def test_dark_saved_output_button_ink_reuses_an_existing_token():
    css = _outputs_css()
    assert "--ws-secondary-text: var(--outputs-secondary-text);" in css
    assert "html[data-theme=\"dark\"] .saved-output-view" not in css
    assert "!" not in css.split(".saved-output-view {", 1)[1].split("}", 1)[0]


def test_dark_button_ink_clears_aa_on_the_saved_output_panel():
    panel = source.over(
        source.resolve("dark", "var(--surface-panel-solid)"),
        source.resolve("dark", "var(--bg)"),
    )
    ink = source.resolve("dark", "var(--outputs-secondary-text)")
    assert source.contrast(ink, panel) >= 4.5
