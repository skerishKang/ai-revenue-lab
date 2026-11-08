"""#7186: the CSS rule parser must read behavior, not bytes.

These tests exercise ``css_rules`` against the stylesheet that carries the shared
primary button rule. If a contract here fails, either the parser stopped reading
a shape this product ships or the shipped rule really changed -- reading the
failure tells which.
"""

from __future__ import annotations

from pathlib import Path

from css_rules import (
    Rule,
    declaration,
    find_rules_with_selector,
    is_list_items,
    parse_rules,
    rule_selector_list_contains,
    strip_comments,
)

POLISH_CSS = Path(__file__).resolve().parents[1] / "static" / "padiem-chat-ui-polish.css"
MOBILE_MEDIA = "(max-width: 640px)"


def _rules() -> list[Rule]:
    return parse_rules(POLISH_CSS.read_text(encoding="utf-8"))


def _primary_blocks(rules: list[Rule]) -> list[Rule]:
    return find_rules_with_selector(rules, ".claw-generate-button")


def _base_block(blocks: list[Rule]) -> Rule:
    base = [
        rule
        for rule in blocks
        if not any(
            selector.endswith(":hover") or selector.endswith(":focus-visible")
            for selector in rule.selectors
        )
    ]
    assert len(base) == 1, "expected exactly one unconditional primary button block"
    return base[0]


def test_shared_primary_rule_has_base_hover_and_focus_blocks() -> None:
    blocks = _primary_blocks(_rules())

    assert len(blocks) == 3, "the shared primary rule is one decision in three states"
    hover = [r for r in blocks if any(s.endswith(":hover") for s in r.selectors)]
    focus = [r for r in blocks if any(s.endswith(":focus-visible") for s in r.selectors)]
    assert len(hover) == 1
    assert len(focus) == 1
    assert rule_selector_list_contains(_base_block(blocks), ".claw-generate-button")


def test_primary_base_selector_list_includes_send_button_and_meeting_start() -> None:
    base = _base_block(_primary_blocks(_rules()))

    assert rule_selector_list_contains(base, ".claw-generate-button", "#meetingStart")
    assert "#meetingStart" in is_list_items(base.selectors[0])


def test_primary_base_background_is_the_composer_send_navy() -> None:
    base = _base_block(_primary_blocks(_rules()))

    assert declaration(base, "background") == "#355977"
    assert declaration(base, "color") == "#fff"


def test_primary_state_blocks_keep_their_own_declarations() -> None:
    blocks = _primary_blocks(_rules())
    hover = next(r for r in blocks if any(s.endswith(":hover") for s in r.selectors))
    focus = next(r for r in blocks if any(s.endswith(":focus-visible") for s in r.selectors))

    assert declaration(hover, "background") == "#2e4d67"
    assert declaration(focus, "outline") == "3px solid #6a9abc"
    assert rule_selector_list_contains(hover, ".claw-generate-button", "#meetingStart")
    assert rule_selector_list_contains(focus, ".claw-generate-button", "#meetingStart")


def test_settings_done_mobile_rule_lives_in_the_640px_media_query() -> None:
    rules = find_rules_with_selector(_rules(), ".settings-done")

    assert len(rules) == 2, "one unconditional rule and one phone override"
    mobile = [rule for rule in rules if rule.media == MOBILE_MEDIA]
    assert len(mobile) == 1
    assert declaration(mobile[0], "width") == "100%"
    assert [rule.media for rule in rules if rule is not mobile[0]] == [None]


def test_reordered_and_reformatted_css_yields_the_same_facts() -> None:
    base = _base_block(_primary_blocks(_rules()))
    items = is_list_items(base.selectors[0])
    assert items, "the shared primary rule lists its targets inside :is(...)"

    reordered = list(reversed(items))
    wrapped = ",\n    ".join(reordered)
    synthetic = (
        "/* a comment the real sheet does not currently carry */\n"
        f"html body :is(\n    {wrapped}\n) {{\n"
        "  background:   #355977 ;\n"
        "  border-color:#294b64;\n"
        "  color: #fff;\n"
        "}\n"
        "html body :is(\n"
        f"    {wrapped}\n"
        "):not(:disabled):hover { background:#2e4d67; border-color:#23445d; }\n"
        "html body :is(\n"
        f"    {wrapped}\n"
        "):focus-visible { outline:3px solid #6a9abc; outline-offset:3px; }\n"
    )

    blocks = _primary_blocks(parse_rules(synthetic))

    assert len(blocks) == 3
    synthetic_base = _base_block(blocks)
    assert is_list_items(synthetic_base.selectors[0]) == reordered
    assert set(is_list_items(synthetic_base.selectors[0])) == set(items)
    assert rule_selector_list_contains(synthetic_base, ".claw-generate-button", "#meetingStart")
    assert declaration(synthetic_base, "background") == "#355977"


def test_commas_inside_is_and_not_do_not_split_the_selector_list() -> None:
    rules = parse_rules(
        ":is(.a, .b), .c:not(.d, .e) { color: #111; }\n"
        "html body :is(.a,\n    .b):hover { color: #222; }\n"
    )

    assert rules[0].selectors == [":is(.a, .b)", ".c:not(.d, .e)"]
    assert rules[1].selectors == ["html body :is(.a, .b):hover"]
    assert is_list_items(rules[0].selectors[0]) == [".a", ".b"]


def test_comments_are_removed_even_when_they_contain_css_punctuation() -> None:
    css = (
        "/* .ghost, .phantom { color: red; } */\n"
        ".real /* inline , ; { } */ { color: #123; }\n"
    )

    rules = parse_rules(css)

    assert [rule.selectors for rule in rules] == [[".real"]]
    assert declaration(rules[0], "color") == "#123"
    assert ".ghost" not in strip_comments(css)


def test_quoted_strings_keep_commas_braces_and_semicolons() -> None:
    rules = parse_rules(
        '[data-label="a, b {c}"] { content: "x;y, z"; background: url(data:image/svg+xml;base64,AAA); }\n'
    )

    assert rules[0].selectors == ['[data-label="a, b {c}"]']
    assert declaration(rules[0], "content") == '"x;y, z"'
    assert declaration(rules[0], "background") == "url(data:image/svg+xml;base64,AAA)"


def test_nested_media_queries_join_the_way_css_evaluates_them() -> None:
    rules = parse_rules(
        "@media (max-width: 640px) {\n"
        "  @media (min-width: 400px) {\n"
        "    .both { display: flex; }\n"
        "  }\n"
        "}\n"
    )

    assert len(rules) == 1
    assert rules[0].media == "(max-width: 640px) and (min-width: 400px)"
    assert declaration(rules[0], "display") == "flex"


def test_a_property_declared_twice_keeps_the_cascaded_last_value() -> None:
    rules = parse_rules(".dup { color: #111; color: #222; }")

    assert declaration(rules[0], "color") == "#222"


def test_property_names_are_case_insensitive_except_custom_properties() -> None:
    rules = parse_rules(".case { BACKGROUND: #111; --Brand-Tone: #222; }")

    assert declaration(rules[0], "background") == "#111"
    assert declaration(rules[0], "--Brand-Tone") == "#222"
    assert declaration(rules[0], "--brand-tone") is None


def test_font_face_and_keyframes_produce_no_element_rule() -> None:
    rules = parse_rules(
        "@font-face { font-family: Demo; src: url(demo.woff2); }\n"
        "@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }\n"
        ".kept { animation: spin 1s; }\n"
    )

    assert [rule.selectors for rule in rules] == [[".kept"]]
