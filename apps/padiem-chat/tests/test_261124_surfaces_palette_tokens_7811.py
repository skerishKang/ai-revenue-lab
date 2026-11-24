"""#7811 C2 surfaces — first-screen/conversation (round 1) and attachment/dialog/scrollbar (round 2).

``padiem-surfaces.css`` paints these 66 declarations with a fixed light palette
in all five themes. The 54 new tokens live only in ``:root`` of
``padiem-tokens.css``; every theme keeps the same computed value. Round two
reuses 14 existing root-only tokens and adds four new ones for values with no
matching usage token. This pins each declared value and the exact token the
sheet must read, so a later theme override or a stray literal cannot silently
repaint these surfaces.
"""

from __future__ import annotations

import re

from _support.calendar_palette import surfaces_rules, surfaces_source, tokens as token_values

ROOT_TOKENS = {
    "--surfaces-eyebrow-glow": "rgba(136, 201, 255, .56)",
    "--surfaces-hero-title-shadow": "rgba(0, 0, 0, .38)",
    "--surfaces-starter-border": "rgba(255, 255, 255, .14)",
    "--surfaces-starter-wash-start": "rgba(255, 255, 255, .075)",
    "--surfaces-starter-wash-end": "rgba(255, 255, 255, .028)",
    "--surfaces-starter-text": "rgba(248, 250, 253, .94)",
    "--surfaces-starter-highlight": "rgba(255, 255, 255, .05)",
    "--surfaces-starter-hover-border": "rgba(255, 255, 255, .28)",
    "--surfaces-starter-hover-wash": "rgba(255, 255, 255, .105)",
    "--surfaces-starter-hover-shadow": "rgba(0, 0, 0, .24)",
    "--surfaces-starter-icon-border": "rgba(255, 255, 255, .11)",
    "--surfaces-starter-icon-bg": "rgba(255, 255, 255, .055)",
    "--surfaces-starter-icon-highlight": "rgba(255, 255, 255, .05)",
    "--surfaces-bubble-border": "rgba(255, 255, 255, .14)",
    "--surfaces-bubble-bg": "rgba(255, 255, 255, .085)",
    "--surfaces-demo-label-border": "rgba(255, 255, 255, .08)",
    "--surfaces-assistant-text": "rgba(247, 249, 252, .90)",
    "--surfaces-answer-link-text": "#b9dcff",
    "--surfaces-card-border": "rgba(255, 255, 255, .12)",
    "--surfaces-card-bg": "rgba(255, 255, 255, .045)",
    "--surfaces-card-text": "rgba(248, 250, 253, .90)",
    "--surfaces-source-index-bg": "rgba(255, 255, 255, .07)",
    "--surfaces-card-muted-text": "rgba(255, 255, 255, .48)",
    "--surfaces-error-border": "rgba(255, 157, 157, .22)",
    "--surfaces-error-bg": "rgba(100, 28, 28, .18)",
    "--surfaces-error-text": "#ffd7d7",
    "--surfaces-retry-border": "rgba(255, 157, 157, .24)",
    "--surfaces-retry-text": "#ffb7b7",
    "--surfaces-composer-border": "rgba(255, 255, 255, .17)",
    "--surfaces-composer-wash-start": "rgba(255, 255, 255, .085)",
    "--surfaces-composer-wash-end": "rgba(255, 255, 255, .038)",
    "--surfaces-composer-highlight": "rgba(255, 255, 255, .07)",
    "--surfaces-composer-shadow": "rgba(0, 0, 0, .44)",
    "--surfaces-composer-focus-border": "rgba(255, 255, 255, .30)",
    "--surfaces-composer-focus-highlight": "rgba(255, 255, 255, .08)",
    "--surfaces-composer-focus-shadow": "rgba(0, 0, 0, .46)",
    "--surfaces-composer-focus-glow": "rgba(136, 201, 255, .055)",
    "--surfaces-composer-text": "#f8fafc",
    "--surfaces-tool-hover-bg": "rgba(255, 255, 255, .065)",
    "--surfaces-tool-pressed-border": "rgba(255, 255, 255, .15)",
    "--surfaces-tool-pressed-bg": "rgba(255, 255, 255, .08)",
    "--surfaces-send-border": "rgba(255, 255, 255, .26)",
    "--surfaces-send-text": "#08090b",
    "--surfaces-send-bg": "rgba(255, 255, 255, .92)",
    "--surfaces-send-shadow": "rgba(0, 0, 0, .22)",
    "--surfaces-send-hover-border": "rgba(255, 255, 255, .5)",
    "--surfaces-send-hover-text": "#06070a",
    "--surfaces-send-hover-bg": "#fff",
    "--surfaces-send-hover-shadow": "rgba(0, 0, 0, .28)",
    "--surfaces-note-text": "rgba(255, 255, 255, .38)",
    # 2차 — values with no existing usage token of their own.
    "--surfaces-attachment-edge": "rgba(255, 255, 255, .12)",
    "--surfaces-project-shadow": "rgba(0, 0, 0, .52)",
    "--surfaces-form-edge": "rgba(255, 255, 255, .13)",
    "--surfaces-scrollbar-thumb": "rgba(255, 255, 255, .18)",
}

#: 2차 재사용 — all already defined in :root and not repainted by any theme.
REUSED_TOKENS = frozenset({
    "--surfaces-card-border", "--surfaces-card-bg", "--surfaces-card-text",
    "--ws-attachment-text", "--surfaces-starter-icon-bg",
    "--surfaces-starter-border", "--ws-form-wash", "--surfaces-starter-text",
    "--ws-dialog-kicker-text", "--foundation-strong-text",
    "--ws-control-hover-edge-strong", "--text-veil-strong",
    "--editorial-summary-text", "--surfaces-retry-text",
})

DECLARATIONS = (
    (".eyebrow::before", "box-shadow",
     "0 0 11px var(--surfaces-eyebrow-glow)", "0 0 11px rgba(136, 201, 255, .56)"),
    (".empty-state h1", "text-shadow",
     "0 18px 42px var(--surfaces-hero-title-shadow)", "0 18px 42px rgba(0, 0, 0, .38)"),
    (".starter", "border-color",
     "var(--surfaces-starter-border)", "rgba(255, 255, 255, .14)"),
    (".starter", "background",
     "linear-gradient(145deg, var(--surfaces-starter-wash-start), var(--surfaces-starter-wash-end)), var(--surface-card-deep)", "linear-gradient(145deg, rgba(255, 255, 255, .075), rgba(255, 255, 255, .028)), var(--surface-card-deep)"),
    (".starter", "color",
     "var(--surfaces-starter-text)", "rgba(248, 250, 253, .94)"),
    (".starter", "box-shadow",
     "inset 0 1px 0 var(--surfaces-starter-highlight)", "inset 0 1px 0 rgba(255, 255, 255, .05)"),
    (".starter:not(:disabled):hover", "border-color",
     "var(--surfaces-starter-hover-border)", "rgba(255, 255, 255, .28)"),
    (".starter:not(:disabled):hover", "background",
     "linear-gradient(145deg, var(--surfaces-starter-hover-wash), var(--surface-veil-panel)), var(--surface-card-solid)", "linear-gradient(145deg, rgba(255, 255, 255, .105), var(--surface-veil-panel)), var(--surface-card-solid)"),
    (".starter:not(:disabled):hover", "box-shadow",
     "0 18px 46px var(--surfaces-starter-hover-shadow)", "0 18px 46px rgba(0, 0, 0, .24)"),
    (".starter-icon", "border",
     "1px solid var(--surfaces-starter-icon-border)", "1px solid rgba(255, 255, 255, .11)"),
    (".starter-icon", "background",
     "var(--surfaces-starter-icon-bg)", "rgba(255, 255, 255, .055)"),
    (".starter-icon", "box-shadow",
     "inset 0 1px 0 var(--surfaces-starter-icon-highlight)", "inset 0 1px 0 rgba(255, 255, 255, .05)"),
    (".message-bubble", "border",
     "1px solid var(--surfaces-bubble-border)", "1px solid rgba(255, 255, 255, .14)"),
    (".message-bubble", "background",
     "var(--surfaces-bubble-bg)", "rgba(255, 255, 255, .085)"),
    (".demo-label", "border",
     "1px solid var(--surfaces-demo-label-border)", "1px solid rgba(255, 255, 255, .08)"),
    (".assistant-content", "color",
     "var(--surfaces-assistant-text)", "rgba(247, 249, 252, .90)"),
    (".assistant-content a", "color",
     "var(--surfaces-answer-link-text)", "#b9dcff"),
    (".source-card", "border-color",
     "var(--surfaces-card-border)", "rgba(255, 255, 255, .12)"),
    (".source-card", "background",
     "var(--surfaces-card-bg) !important", "rgba(255, 255, 255, .045) !important"),
    (".source-card", "color",
     "var(--surfaces-card-text)", "rgba(248, 250, 253, .90)"),
    (".source-index", "background",
     "var(--surfaces-source-index-bg)", "rgba(255, 255, 255, .07)"),
    (".source-card small", "color",
     "var(--surfaces-card-muted-text) !important", "rgba(255, 255, 255, .48) !important"),
    (".error-box", "border-color",
     "var(--surfaces-error-border)", "rgba(255, 157, 157, .22)"),
    (".error-box", "background",
     "var(--surfaces-error-bg)", "rgba(100, 28, 28, .18)"),
    (".error-box", "color",
     "var(--surfaces-error-text)", "#ffd7d7"),
    (".retry-button", "border-color",
     "var(--surfaces-retry-border)", "rgba(255, 157, 157, .24)"),
    (".retry-button", "color",
     "var(--surfaces-retry-text)", "#ffb7b7"),
    (".composer", "border-color",
     "var(--surfaces-composer-border)", "rgba(255, 255, 255, .17)"),
    (".composer", "background",
     "linear-gradient(145deg, var(--surfaces-composer-wash-start), var(--surfaces-composer-wash-end)), var(--surface-panel-veil)", "linear-gradient(145deg, rgba(255, 255, 255, .085), rgba(255, 255, 255, .038)), var(--surface-panel-veil)"),
    (".composer", "box-shadow",
     "inset 0 1px 0 var(--surfaces-composer-highlight), 0 28px 80px var(--surfaces-composer-shadow)", "inset 0 1px 0 rgba(255, 255, 255, .07), 0 28px 80px rgba(0, 0, 0, .44)"),
    (".composer:focus-within", "border-color",
     "var(--surfaces-composer-focus-border)", "rgba(255, 255, 255, .30)"),
    (".composer:focus-within", "box-shadow",
     "inset 0 1px 0 var(--surfaces-composer-focus-highlight), 0 28px 80px var(--surfaces-composer-focus-shadow), 0 0 0 1px var(--surfaces-composer-focus-glow)", "inset 0 1px 0 rgba(255, 255, 255, .08), 0 28px 80px rgba(0, 0, 0, .46), 0 0 0 1px rgba(136, 201, 255, .055)"),
    (".composer textarea", "color",
     "var(--surfaces-composer-text)", "#f8fafc"),
    (".tool-button:hover:not(:disabled)", "background",
     "var(--surfaces-tool-hover-bg)", "rgba(255, 255, 255, .065)"),
    (".tool-button[aria-pressed=\"true\"]", "border",
     "1px solid var(--surfaces-tool-pressed-border)", "1px solid rgba(255, 255, 255, .15)"),
    (".tool-button[aria-pressed=\"true\"]", "background",
     "var(--surfaces-tool-pressed-bg)", "rgba(255, 255, 255, .08)"),
    (".send-button", "border",
     "1px solid var(--surfaces-send-border)", "1px solid rgba(255, 255, 255, .26)"),
    (".send-button", "color",
     "var(--surfaces-send-text)", "#08090b"),
    (".send-button", "background",
     "var(--surfaces-send-bg)", "rgba(255, 255, 255, .92)"),
    (".send-button", "box-shadow",
     "0 8px 26px var(--surfaces-send-shadow)", "0 8px 26px rgba(0, 0, 0, .22)"),
    (".send-button:not(:disabled):hover", "border-color",
     "var(--surfaces-send-hover-border)", "rgba(255, 255, 255, .5)"),
    (".send-button:not(:disabled):hover", "color",
     "var(--surfaces-send-hover-text)", "#06070a"),
    (".send-button:not(:disabled):hover", "background",
     "var(--surfaces-send-hover-bg)", "#fff"),
    (".send-button:not(:disabled):hover", "box-shadow",
     "0 10px 30px var(--surfaces-send-hover-shadow)", "0 10px 30px rgba(0, 0, 0, .28)"),
    (".composer-note", "color",
     "var(--surfaces-note-text) !important", "rgba(255, 255, 255, .38) !important"),
    # 2차 — attachment chips and file icons.
    (".attachment-chip", "border-color",
     "var(--surfaces-attachment-edge) !important", "rgba(255, 255, 255, .12) !important"),
    (".attachment-chip", "background",
     "var(--surfaces-card-bg) !important", "rgba(255, 255, 255, .045) !important"),
    (".attachment-chip", "color",
     "var(--surfaces-card-text) !important", "rgba(248, 250, 253, .90) !important"),
    (".attachment-chip .file-icon", "color",
     "var(--ws-attachment-text) !important", "rgba(255, 255, 255, .74) !important"),
    (".attachment-chip .file-icon", "background",
     "var(--surfaces-starter-icon-bg) !important", "rgba(255, 255, 255, .055) !important"),
    # 2차 — project/saved-output dialogs.
    (".project-form", "border",
     "1px solid var(--surfaces-starter-border)", "1px solid rgba(255, 255, 255, .14)"),
    (".project-form", "background",
     "linear-gradient(145deg, var(--surface-veil-soft), var(--ws-form-wash)), var(--surface-panel-solid) !important",
     "linear-gradient(145deg, var(--surface-veil-soft), rgba(255, 255, 255, .018)), var(--surface-panel-solid) !important"),
    (".project-form", "color",
     "var(--surfaces-starter-text)", "rgba(248, 250, 253, .94)"),
    (".project-form", "box-shadow",
     "0 34px 110px var(--surfaces-project-shadow)", "0 34px 110px rgba(0, 0, 0, .52)"),
    (".project-dialog-header p", "color",
     "var(--ws-dialog-kicker-text) !important", "rgba(255, 255, 255, .62) !important"),
    (".project-form input", "border-color",
     "var(--surfaces-form-edge) !important", "rgba(255, 255, 255, .13) !important"),
    (".project-form input", "background",
     "var(--surfaces-starter-icon-bg) !important", "rgba(255, 255, 255, .055) !important"),
    (".project-form input", "color",
     "var(--foundation-strong-text) !important", "#fff !important"),
    (".project-primary", "border-color",
     "var(--ws-control-hover-edge-strong) !important", "rgba(255, 255, 255, .20) !important"),
    (".project-primary", "color",
     "var(--text-veil-strong) !important", "rgba(255, 255, 255, .92) !important"),
    (".project-secondary", "border-color",
     "var(--surfaces-card-border) !important", "rgba(255, 255, 255, .12) !important"),
    (".project-secondary", "background",
     "var(--surfaces-starter-icon-bg) !important", "rgba(255, 255, 255, .055) !important"),
    (".project-secondary", "color",
     "var(--editorial-summary-text) !important", "rgba(255, 255, 255, .72) !important"),
    (".saved-output-danger", "color",
     "var(--surfaces-retry-text) !important", "#ffb7b7 !important"),
    # 2차 — scrollbars.
    ("*", "scrollbar-color",
     "var(--ws-control-hover-edge-strong) transparent", "rgba(255, 255, 255, .20) transparent"),
    ("*::-webkit-scrollbar-thumb", "background",
     "var(--surfaces-scrollbar-thumb)", "rgba(255, 255, 255, .18)"),
)

COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", re.I)
VAR_RX = re.compile(r"var\((--[a-zA-Z0-9-]+)\)")


def test_root_tokens_hold_the_pre_change_literals():
    found, overridden = token_values()
    for name, expected in ROOT_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    # #7811 C3: 입력칸 글자색 하나는 이제 테마 블록이 값을 준다(light·padiem-home —
    # test_261124_themes_composer_c3_7811.py가 고정). 나머지는 계속 테마 불변이다.
    assert set(ROOT_TOKENS) & overridden == {"--surfaces-composer-text"}, (
        "a theme block repaints a surfaces token")
    assert not (REUSED_TOKENS & overridden), "round two reused a theme-overridden token"
    assert REUSED_TOKENS <= set(found), "round two reused an undefined token"


def test_every_declaration_reads_the_expected_token_value():
    rules = surfaces_rules()
    for selector, prop, after, before in DECLARATIONS:
        values = [r.declarations[prop] for r in rules
                  if selector in r.selectors and prop in r.declarations]
        assert values, (selector, prop)
        assert after in values, (selector, prop, values)
        assert before not in values, (selector, prop, values)


def test_all_declarations_carry_no_color_literals():
    for _selector, _prop, after, _before in DECLARATIONS:
        assert not COLOR_RX.search(after), after


def test_every_new_token_is_read_by_the_sheet():
    painted = {name for rule in surfaces_rules()
               for value in rule.declarations.values()
               for name in VAR_RX.findall(value)}
    assert set(ROOT_TOKENS) <= painted


def test_tokens_are_defined_only_in_the_token_file():
    text = surfaces_source()
    for name in ROOT_TOKENS:
        assert f"{name}:" not in text, name
