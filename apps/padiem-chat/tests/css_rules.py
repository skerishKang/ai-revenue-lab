"""Parse a stylesheet into rule blocks so a UI contract can assert meaning.

#7186: a contract written as ``".a, .b { color: #fff; }" in css`` fails when the
same rule gains a selector, is re-wrapped, gains a comment, or lists its
selectors in another order -- none of which change what the browser paints. The
helpers below answer the questions a contract actually means::

    rules = parse_rules(css_text)
    blocks = find_rules_with_selector(rules, ".claw-generate-button")
    assert rule_selector_list_contains(blocks[0], "#meetingStart")
    assert declaration(blocks[0], "background") == "#355977"

The parser uses the standard library only and understands the shapes this
product ships: comments, quoted strings, attribute selectors, commas nested
inside ``:is()``/``:not()``/``:where()``, multi-line selector lists and
``@media`` nesting. It is not a CSSOM: CSS nesting inside a style rule is
ignored, and at-rules that carry declarations instead of element selectors
(``@font-face``, ``@keyframes``, ``@page``) produce no Rule.

Matching is on the selector list, not on text: a compound selector is never
matched by a suffix, so ``.a`` does not select the rule ``.a:hover``. A rule that
targets a state list carries that list inside ``:is(...)``/``:where(...)``, and
``is_list_items`` expands it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = (
    "Rule",
    "parse_rules",
    "strip_comments",
    "is_list_items",
    "find_rules_with_selector",
    "rule_selector_list_contains",
    "declaration",
)

# At-rules whose block contains style rules rather than declarations.
_NESTING_AT_RULES = frozenset(
    {"@supports", "@layer", "@container", "@scope", "@document", "@starting-style"}
)


@dataclass
class Rule:
    """One style rule: a selector list, its declarations, and its @media scope.

    ``media`` is the @media condition without the ``@media`` keyword (e.g.
    ``"(max-width: 640px)"``), or ``None`` outside any @media. Nested @media
    blocks are joined the way CSS evaluates them: ``"(a) and (b)"``.

    ``declarations`` maps a property name to its value exactly as authored
    (whitespace collapsed). Property names follow CSS: case-insensitive, except
    ``--custom`` ones which keep their case. A property declared twice in one
    block keeps the last value, which is the one the cascade applies.
    """

    selectors: list[str] = field(default_factory=list)
    declarations: dict[str, str] = field(default_factory=dict)
    media: str | None = None


def parse_rules(css_text: str) -> list[Rule]:
    """Return every style rule in ``css_text``, in document order."""
    rules: list[Rule] = []
    _walk(strip_comments(css_text), None, rules)
    return rules


def strip_comments(css_text: str) -> str:
    """Remove ``/* ... */`` comments without touching quoted strings."""
    out: list[str] = []
    i = 0
    n = len(css_text)
    while i < n:
        ch = css_text[i]
        if ch in "\"'":
            end = _skip_string(css_text, i)
            out.append(css_text[i:end])
            i = end
            continue
        if ch == "/" and i + 1 < n and css_text[i + 1] == "*":
            end = css_text.find("*/", i + 2)
            if end == -1:
                break
            i = end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def is_list_items(selector: str) -> list[str]:
    """Return the selectors listed inside ``:is(...)``/``:where(...)``.

    Items are returned in document order, normalized like every other selector
    here. Nesting is not expanded recursively: ``:is(:is(.a))`` yields
    ``":is(.a)"`` as its single immediate item.
    """
    items: list[str] = []
    lowered = selector.lower()
    i = 0
    n = len(selector)
    while i < n:
        ch = selector[i]
        if ch in "\"'":
            i = _skip_string(selector, i)
            continue
        matched = None
        for name in (":is(", ":where("):
            if lowered.startswith(name, i):
                matched = name
                break
        if matched is None:
            i += 1
            continue
        close = _match_pair(selector, i + len(matched) - 1, "(", ")")
        inner = selector[i + len(matched):close]
        for part in _split_top_level(inner, ","):
            part = _normalize_space(part)
            if part:
                items.append(part)
        i = close + 1
    return items


def rule_selector_list_contains(rule: Rule, *selectors: str) -> bool:
    """True when every given selector is part of ``rule``'s selector list.

    Membership is exact: each given selector must appear as a whole selector of
    the rule or as one item of an ``:is(...)``/``:where(...)`` list in it.
    """
    available: set[str] = set()
    for selector in rule.selectors:
        available.add(_normalize_space(selector))
        available.update(is_list_items(selector))
    return all(_normalize_space(selector) in available for selector in selectors)


def find_rules_with_selector(rules: list[Rule], selector: str) -> list[Rule]:
    """Return every rule whose selector list contains ``selector``."""
    return [rule for rule in rules if rule_selector_list_contains(rule, selector)]


def declaration(rule: Rule, prop: str) -> str | None:
    """Return the value of ``prop`` in ``rule``, or None when it is not set."""
    return rule.declarations.get(_property_key(prop))


def _property_key(prop: str) -> str:
    """Property names are case-insensitive, except for ``--custom`` ones."""
    prop = prop.strip()
    return prop if prop.startswith("--") else prop.lower()


def _walk(text: str, media: str | None, rules: list[Rule]) -> None:
    for prelude, body in _iter_blocks(text):
        prelude = _normalize_space(prelude)
        if not prelude or body is None:
            continue
        if prelude.startswith("@"):
            name = prelude.split(None, 1)[0].lower()
            if name == "@media":
                condition = prelude[len(name):].strip()
                _walk(body, condition if media is None else f"{media} and {condition}", rules)
            elif name in _NESTING_AT_RULES:
                _walk(body, media, rules)
            continue
        selectors = [
            part
            for part in (_normalize_space(piece) for piece in _split_top_level(prelude, ","))
            if part
        ]
        if selectors:
            rules.append(Rule(selectors, _parse_declarations(body), media))


def _parse_declarations(body: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for chunk in _split_top_level(_before_first_block(body), ";"):
        if ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        prop = _property_key(prop)
        if prop and not prop.startswith("@"):
            declarations[prop] = _normalize_space(value)
    return declarations


def _before_first_block(body: str) -> str:
    """Drop everything from the first nested block on (CSS nesting)."""
    i = 0
    n = len(body)
    depth = 0
    while i < n:
        ch = body[i]
        if ch in "\"'":
            i = _skip_string(body, i)
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "{" and depth == 0:
            return body[:i]
        i += 1
    return body


def _iter_blocks(text: str) -> list[tuple[str, str | None]]:
    """Split ``text`` into (prelude, block body) items; statements get None."""
    items: list[tuple[str, str | None]] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    depth = 0
    while i < n:
        ch = text[i]
        if ch in "\"'":
            end = _skip_string(text, i)
            buf.append(text[i:end])
            i = end
            continue
        if ch in "([":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch in ")]":
            depth = max(0, depth - 1)
            buf.append(ch)
            i += 1
            continue
        if depth == 0 and ch == ";":
            items.append(("".join(buf), None))
            buf = []
            i += 1
            continue
        if depth == 0 and ch == "{":
            end = _match_pair(text, i, "{", "}")
            items.append(("".join(buf), text[i + 1:end]))
            buf = []
            i = end + 1
            continue
        if depth == 0 and ch == "}":
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        items.append((tail, None))
    return items


def _match_pair(text: str, open_index: int, opener: str, closer: str) -> int:
    depth = 0
    i = open_index
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            i = _skip_string(text, i)
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"unbalanced {opener!r} in CSS")


def _skip_string(text: str, start: int) -> int:
    """Return the index just past the quoted string that starts at ``start``."""
    quote = text[start]
    i = start + 1
    n = len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    return n


def _split_top_level(text: str, separator: str) -> list[str]:
    """Split on ``separator`` outside quotes and ()/[] nesting."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            end = _skip_string(text, i)
            buf.append(text[i:end])
            i = end
            continue
        if ch in "([":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch in ")]":
            depth = max(0, depth - 1)
            buf.append(ch)
            i += 1
            continue
        if ch == separator and depth == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _normalize_space(text: str) -> str:
    """Collapse whitespace runs outside quotes; strip both ends."""
    out: list[str] = []
    pending_space = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            if pending_space and out:
                out.append(" ")
            pending_space = False
            end = _skip_string(text, i)
            out.append(text[i:end])
            i = end
            continue
        if ch.isspace():
            pending_space = True
            i += 1
            continue
        if pending_space and out:
            out.append(" ")
        pending_space = False
        out.append(ch)
        i += 1
    return "".join(out)
